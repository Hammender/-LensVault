from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from .contracts import RemoteItem, RemotePage, ScriptParameter, SourceAdapter, stable_key
from . import _RequestStartLimiter


def _request_bytes(*args: object, **kwargs: object):
    from . import _request_bytes as request
    return request(*args, **kwargs)


IDOLXXX_COLLECTION_RE = re.compile(r"^/idols/([^/]+)(?:/page/(\d+))?/?$", re.IGNORECASE)
IDOLXXX_POST_RE = re.compile(r"^/post/\d+/?$", re.IGNORECASE)
VOID_HTML_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
VIDEO_EXTENSIONS = {".3gp", ".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ogv", ".ts", ".webm", ".wmv"}


def _class_tokens(attributes: dict[str, str | None]) -> set[str]:
    return set((attributes.get("class") or "").split())


@dataclass(frozen=True)
class IdolxxxListingData:
    cards: tuple[tuple[str, str | None], ...]
    page_numbers: tuple[int, ...]


class IdolxxxListingParser(HTMLParser):
    def __init__(self, page_url: str, collection_slug: str) -> None:
        super().__init__(convert_charrefs=True)
        parsed = urlparse(page_url)
        self.page_url = page_url
        self.site_netloc = parsed.netloc.lower()
        self.collection_slug = collection_slug.lower()
        self.article_depth = 0
        self.current_premium = False
        self.current_detail_url: str | None = None
        self.current_title: str | None = None
        self.cards: list[tuple[str, str | None]] = []
        self.page_numbers: set[int] = {1}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "article":
            if self.article_depth == 0:
                self.current_premium = "post-premium" in _class_tokens(attributes)
                self.current_detail_url = None
                self.current_title = None
            self.article_depth += 1
            return
        if tag == "a":
            href = (attributes.get("href") or "").strip()
            absolute = urljoin(self.page_url, href)
            parsed = urlparse(absolute)
            collection_match = IDOLXXX_COLLECTION_RE.fullmatch(parsed.path)
            if parsed.netloc.lower() == self.site_netloc and collection_match:
                slug, page = collection_match.groups()
                if slug.lower() == self.collection_slug:
                    self.page_numbers.add(int(page or 1))
            if (
                self.article_depth
                and parsed.netloc.lower() == self.site_netloc
                and IDOLXXX_POST_RE.fullmatch(parsed.path)
            ):
                self.current_detail_url = urlunparse(
                    (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", "", "")
                )
                title = (attributes.get("title") or "").strip()
                if title:
                    self.current_title = title
        elif tag == "img" and self.article_depth:
            title = (attributes.get("alt") or "").strip()
            if title:
                self.current_title = title

    def handle_endtag(self, tag: str) -> None:
        if tag != "article" or not self.article_depth:
            return
        self.article_depth -= 1
        if self.article_depth == 0:
            if not self.current_premium and self.current_detail_url:
                self.cards.append((self.current_detail_url, self.current_title))
            self.current_detail_url = None
            self.current_title = None

    def result(self) -> IdolxxxListingData:
        return IdolxxxListingData(tuple(self.cards), tuple(sorted(self.page_numbers)))


class IdolxxxDetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.media_depth: int | None = None
        self.item_depth: int | None = None
        self.item_tag: str | None = None
        self.item_has_image = False
        self.item_has_video = False
        self.item_candidates: dict[str, list[str]] = {"data-src": [], "href": [], "src": []}
        self.media_candidates: list[tuple[tuple[str, ...], str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        current_depth = self.depth + (0 if tag in VOID_HTML_TAGS else 1)
        classes = _class_tokens(attributes)
        if self.media_depth is None and "post-media" in classes:
            self.media_depth = current_depth
        if self.media_depth is not None and self.item_depth is None and "post-media-item" in classes:
            self.item_depth = current_depth
            self.item_tag = tag
            self.item_has_image = False
            self.item_has_video = False
            self.item_candidates = {"data-src": [], "href": [], "src": []}
        if self.item_depth is not None:
            if tag == "img":
                self.item_has_image = True
            if tag == "video" or (tag == "source" and (attributes.get("type") or "").lower().startswith("video/")):
                self.item_has_video = True
            for attribute in ("data-src", "href", "src"):
                value = (attributes.get(attribute) or "").strip()
                if value and value not in self.item_candidates[attribute]:
                    self.item_candidates[attribute].append(value)
        if tag not in VOID_HTML_TAGS:
            self.depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if self.item_depth == self.depth and tag == self.item_tag:
            if self.item_has_image or self.item_has_video:
                candidates = tuple(
                    value
                    for attribute in ("data-src", "href", "src")
                    for value in self.item_candidates[attribute]
                )
                self.media_candidates.append((candidates, "video" if self.item_has_video else "image"))
            self.item_depth = None
            self.item_tag = None
        if self.media_depth == self.depth and self.item_depth is None:
            self.media_depth = None
        if self.depth:
            self.depth -= 1


class IdolxxxGalleryAdapter(SourceAdapter):
    DETAIL_BATCH_SIZE = 4
    DETAIL_WORKERS = 2
    HTML_START_INTERVAL_SECONDS = 1.0

    @staticmethod
    def _normalize_collection(raw_url: str) -> tuple[str, str, str]:
        parsed = urlparse(raw_url.strip())
        match = IDOLXXX_COLLECTION_RE.fullmatch(parsed.path)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or not match:
            raise ValueError("该脚本只支持 /idols/{slug}/ 或 /idols/{slug}/page/{n}/ 分类网页")
        slug = match.group(1)
        site_url = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        return site_url, slug, f"{site_url}/idols/{slug}/"

    @staticmethod
    def _page_url(collection_url: str, page_number: int) -> str:
        if page_number == 1:
            return collection_url
        return urljoin(collection_url, f"page/{page_number}/")

    @staticmethod
    def _normalize_original(candidate: str, detail_url: str, site_host: str) -> str | None:
        parsed = urlparse(urljoin(detail_url, candidate))
        hostname = (parsed.hostname or "").lower()
        site_domain = site_host.removeprefix("www.")
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not hostname
            or (hostname != site_domain and not hostname.endswith(f".{site_domain}"))
            or "/files/src/" not in parsed.path.lower()
        ):
            return None
        return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", parsed.query, ""))

    @staticmethod
    def _parse_listing(raw: bytes, page_url: str, slug: str) -> IdolxxxListingData:
        parser = IdolxxxListingParser(page_url, slug)
        parser.feed(raw.decode("utf-8", errors="replace"))
        return parser.result()

    @staticmethod
    def _parse_detail(raw: bytes) -> tuple[tuple[tuple[str, ...], str], ...]:
        parser = IdolxxxDetailParser()
        parser.feed(raw.decode("utf-8", errors="replace"))
        return tuple(parser.media_candidates)

    def enumerate_pages(
        self,
        crawl_url: str,
        parameters: dict[str, object],
        known_external_keys: set[str],
        incremental: bool,
    ) -> Iterable[RemotePage]:
        site_url, slug, collection_url = self._normalize_collection(crawl_url)
        site_host = (urlparse(site_url).hostname or "").lower()
        start_page = int(parameters.get("start_page") or 1)
        end_page = int(parameters["end_page"]) if parameters.get("end_page") not in (None, "") else None
        media_types = {str(item) for item in parameters.get("media_types", ["image"])}
        request_limiter = _RequestStartLimiter(self.HTML_START_INTERVAL_SECONDS)

        def fetch(url: str, referer: str) -> bytes:
            raw, content_type = _request_bytes(
                url,
                "text/html,*/*;q=0.8",
                referer,
                abort_on_access_block=True,
                retries=3,
                before_attempt=request_limiter.wait,
            )
            if "text/html" not in content_type.lower():
                raise ValueError(f"目标站点未返回 HTML 页面：{content_type or '未知类型'}")
            return raw

        first_raw = fetch(collection_url, collection_url)
        first_page = self._parse_listing(first_raw, collection_url, slug)
        last_page = max(first_page.page_numbers, default=1)
        if start_page > last_page:
            raise ValueError(f"起始页 {start_page} 超过网站最后一页 {last_page}")
        requested_last_page = min(last_page, end_page) if end_page is not None else last_page
        seen_originals: set[str] = set()
        with ThreadPoolExecutor(max_workers=self.DETAIL_WORKERS, thread_name_prefix="idolxxx-detail") as executor:
            for page_number in range(start_page, requested_last_page + 1):
                page_url = self._page_url(collection_url, page_number)
                listing = first_page if page_number == 1 else self._parse_listing(fetch(page_url, collection_url), page_url, slug)
                page_keys: list[str] = []
                card_batches = [
                    listing.cards[index : index + self.DETAIL_BATCH_SIZE]
                    for index in range(0, len(listing.cards), self.DETAIL_BATCH_SIZE)
                ] or [()]
                for batch_index, cards in enumerate(card_batches):
                    detail_payloads: list[bytes | None] = [None] * len(cards)
                    for group_start in range(0, len(cards), self.DETAIL_WORKERS):
                        request_group = cards[group_start : group_start + self.DETAIL_WORKERS]
                        futures = {
                            executor.submit(fetch, detail_url, page_url): group_start + index
                            for index, (detail_url, _card_title) in enumerate(request_group)
                        }
                        try:
                            for future in as_completed(futures):
                                detail_payloads[futures[future]] = future.result()
                        except Exception:
                            for future in futures:
                                future.cancel()
                            raise

                    batch_items: list[RemoteItem] = []
                    for (detail_url, card_title), detail_raw in zip(cards, detail_payloads, strict=True):
                        if detail_raw is None:
                            continue
                        parsed_media = self._parse_detail(detail_raw)
                        originals: list[tuple[str, str]] = []
                        for candidates, media_type in parsed_media:
                            if media_type not in media_types:
                                continue
                            original = next(
                                (
                                    normalized
                                    for candidate in candidates
                                    if (normalized := self._normalize_original(candidate, detail_url, site_host)) is not None
                                ),
                                None,
                            )
                            if original and original not in seen_originals:
                                seen_originals.add(original)
                                originals.append((original, media_type))
                        for index, (original, media_type) in enumerate(originals, start=1):
                            external_key = stable_key(original)
                            page_keys.append(external_key)
                            title = card_title
                            if title and len(originals) > 1:
                                title = f"{title} ({index}/{len(originals)})"
                            batch_items.append(
                                RemoteItem(
                                    external_key=external_key,
                                    source_url=detail_url,
                                    title=title,
                                    candidate_urls=(original,),
                                    media_type=media_type,
                                    referer_url=detail_url,
                                    abort_on_access_block=True,
                                )
                            )

                    is_last_batch = batch_index + 1 >= len(card_batches)
                    stop_reason = None
                    if is_last_batch:
                        natural_end = page_number >= last_page
                        requested_end = page_number >= requested_last_page
                        known_end = incremental and page_keys and all(key in known_external_keys for key in page_keys)
                        stop_reason = (
                            "collection_end"
                            if natural_end
                            else "known_page"
                            if known_end
                            else "requested_end"
                            if requested_end
                            else None
                        )
                    yield RemotePage(page_number=page_number, items=tuple(batch_items), stop_reason=stop_reason)
                    if stop_reason is not None:
                        return


