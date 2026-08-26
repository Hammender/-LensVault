from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from collections.abc import Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
import re

from .contracts import RemoteItem, RemotePage, SourceAdapter, max_pages_from, stable_key


def _request_bytes(*args: object, **kwargs: object):
    from . import _request_bytes as request
    return request(*args, **kwargs)

PAGE_RE = re.compile(r"(?:^|&)page=(-?\d+)(?:&|$)")
PERPAGE_RE = re.compile(r"(?:^|&)perpage=(\d+)(?:&|$)")
BOOKMARKS_RE = re.compile(r"([\d,]+)\s+bookmarks?", re.IGNORECASE)
VIDEO_EXTENSIONS = {".3gp", ".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ogv", ".ts", ".webm", ".wmv"}


@dataclass
class PageData:
    items: list[dict[str, object]]
    page_urls: dict[int, str]
    bookmark_count: int | None


class CollectionPageParser(HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.article_depth = 0
        self.current: dict[str, object] | None = None
        self.items: list[dict[str, object]] = []
        self.page_urls: dict[int, str] = {}
        self.bookmark_count: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a":
            href = attributes.get("href") or ""
            match = PAGE_RE.search(href)
            if match and int(match.group(1)) >= 0:
                self.page_urls[int(match.group(1))] = urljoin(self.page_url, href)
        if tag == "article":
            if self.article_depth == 0:
                self.current = {"title": "", "original_url": "", "preview_url": "", "has_video": False}
            self.article_depth += 1
            return
        if not self.article_depth or self.current is None:
            return
        if tag == "video" or (tag == "source" and (attributes.get("type") or "").lower().startswith("video/")):
            self.current["has_video"] = True
        elif tag in {"img", "source"}:
            if tag == "img":
                self.current["title"] = attributes.get("alt") or self.current["title"]
            source = attributes.get("src") or attributes.get("data-src") or ""
            if not source and attributes.get("srcset"):
                source = attributes["srcset"].split(",")[-1].strip().split()[0]
            media_type = (attributes.get("type") or "").lower()
            if source and (tag == "img" or not media_type or media_type.startswith("image/")):
                self.current["preview_url"] = urljoin(self.page_url, source)
        elif tag == "a":
            href = attributes.get("href") or ""
            absolute = urljoin(self.page_url, href)
            host = (urlparse(absolute).hostname or "").lower()
            if href and host and not host.endswith("raindrop.page") and host != "app.raindrop.io":
                self.current["original_url"] = absolute

    def handle_data(self, data: str) -> None:
        match = BOOKMARKS_RE.search(data)
        if match:
            self.bookmark_count = int(match.group(1).replace(",", ""))

    def handle_endtag(self, tag: str) -> None:
        if tag == "article" and self.article_depth:
            self.article_depth -= 1
            if self.article_depth == 0 and self.current is not None:
                if self.current["original_url"] or self.current["preview_url"]:
                    self.items.append(self.current)
                self.current = None


class RaindropPageAdapter(SourceAdapter):
    def _validate(self, raw_url: str) -> str:
        parsed = urlparse(raw_url.strip())
        if parsed.scheme not in {"http", "https"} or not (parsed.hostname or "").lower().endswith(".raindrop.page"):
            raise ValueError("该脚本只支持 *.raindrop.page 的分类网页")
        if not [part for part in parsed.path.split("/") if part]:
            raise ValueError("分类 URL 中缺少集合路径")
        return raw_url.strip()

    @staticmethod
    def _url_with_page(page_url: str, page: int) -> str:
        parsed = urlparse(page_url)
        parts = [part for part in parsed.path.split("/") if part]
        options = parse_qsl(parts[1], keep_blank_values=True) if len(parts) > 1 and "=" in parts[1] else [("sort", "-created"), ("perpage", "30")]
        options = [(key, value) for key, value in options if key not in {"sort", "page"}]
        options.insert(0, ("sort", "-created"))
        if not any(key == "perpage" for key, _ in options):
            options.append(("perpage", "30"))
        options.append(("page", str(page)))
        return urlunparse((parsed.scheme, parsed.netloc, f"/{parts[0]}/{urlencode(options)}", "", "", ""))

    @staticmethod
    def _fetch(page_url: str) -> PageData:
        raw, content_type = _request_bytes(page_url, "text/html,*/*;q=0.8", page_url)
        if "text/html" not in content_type.lower():
            raise ValueError(f"分类 URL 未返回 HTML 页面：{content_type or '未知类型'}")
        parser = CollectionPageParser(page_url)
        parser.feed(raw.decode("utf-8", errors="replace"))
        if not parser.items:
            raise ValueError("页面中没有找到媒体条目")
        return PageData(parser.items, parser.page_urls, parser.bookmark_count)

    def enumerate_pages(self, crawl_url: str, parameters: dict[str, object], known_external_keys: set[str], incremental: bool) -> Iterable[RemotePage]:
        requested_url = self._validate(crawl_url)
        start_page = int(parameters.get("start_page") or 1) - 1
        end_page = int(parameters["end_page"]) - 1 if parameters.get("end_page") not in (None, "") else None
        if "max_pages" in parameters:
            start_page = 0
            legacy_max_pages = max_pages_from(parameters)
            end_page = legacy_max_pages - 1 if legacy_max_pages is not None else None
        first_url = self._url_with_page(requested_url, 0)
        first_page = self._fetch(first_url)
        last_page = max([0, *first_page.page_urls.keys()])
        if first_page.bookmark_count is not None:
            per_page = 30
            for candidate in [first_url, *first_page.page_urls.values()]:
                candidate_parts = [part for part in urlparse(candidate).path.split("/") if part]
                match = PERPAGE_RE.search(candidate_parts[1]) if len(candidate_parts) > 1 else None
                if match:
                    per_page = max(1, int(match.group(1)))
                    break
            last_page = max(last_page, max(0, (first_page.bookmark_count - 1) // per_page))
        if start_page > last_page:
            raise ValueError(f"起始页 {start_page + 1} 超过网站最后一页 {last_page + 1}")
        requested_last_page = min(last_page, end_page) if end_page is not None else last_page
        discovered = dict(first_page.page_urls)
        seen: set[str] = set()
        for page_number in range(start_page, requested_last_page + 1):
            current_url = discovered.get(page_number) or self._url_with_page(first_url, page_number)
            page = first_page if page_number == 0 else self._fetch(current_url)
            discovered.update(page.page_urls)
            page_keys: list[str] = []
            page_items: list[RemoteItem] = []
            for item in page.items:
                source_url = str(item.get("original_url") or item.get("preview_url") or "")
                parsed = urlparse(source_url)
                normalized = urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.params, parsed.query, ""))
                external_key = stable_key(normalized)
                page_keys.append(external_key)
                if external_key in seen:
                    continue
                seen.add(external_key)
                suffix = parsed.path.lower().rsplit(".", 1)[-1] if "." in parsed.path else ""
                ignored = "页面条目是视频" if item.get("has_video") or f".{suffix}" in VIDEO_EXTENSIONS else None
                page_items.append(RemoteItem(
                    external_key=external_key,
                    source_url=source_url,
                    preview_url=str(item.get("preview_url") or "") or None,
                    title=str(item.get("title") or "") or None,
                    candidate_urls=tuple(dict.fromkeys(filter(None, (source_url, str(item.get("preview_url") or ""))))),
                    ignored_reason=ignored,
                ))
            natural_end = page_number >= last_page
            requested_end = page_number >= requested_last_page
            known_end = incremental and page_keys and all(key in known_external_keys for key in page_keys)
            stop_reason = "collection_end" if natural_end else "known_page" if known_end else "requested_end" if requested_end else None
            yield RemotePage(page_number=page_number + 1, items=tuple(page_items), stop_reason=stop_reason)
            if stop_reason is not None:
                break


