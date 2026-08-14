from __future__ import annotations

import hashlib
import json
import random
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable, Literal
from urllib.error import HTTPError
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)
PAGE_RE = re.compile(r"(?:^|&)page=(-?\d+)(?:&|$)")
PERPAGE_RE = re.compile(r"(?:^|&)perpage=(\d+)(?:&|$)")
BOOKMARKS_RE = re.compile(r"([\d,]+)\s+bookmarks?", re.IGNORECASE)
VIDEO_EXTENSIONS = {".3gp", ".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ogv", ".ts", ".webm", ".wmv"}
IDOLXXX_COLLECTION_RE = re.compile(r"^/idols/([^/]+)(?:/page/(\d+))?/?$", re.IGNORECASE)
IDOLXXX_POST_RE = re.compile(r"^/post/\d+/?$", re.IGNORECASE)
VOID_HTML_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class AccessBlockedError(RuntimeError):
    def __init__(self, url: str, status_code: int) -> None:
        host = urlparse(url).hostname or "远端站点"
        self.status_code = status_code
        super().__init__(f"站点 {host} 返回 HTTP {status_code}，已停止本次采集以避免继续触发访问限制")


@dataclass(frozen=True)
class ScriptParameter:
    key: str
    label: str
    type: Literal["string", "integer", "number", "boolean", "select"]
    required: bool = False
    default: object | None = None
    description: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    options: tuple[tuple[str, str], ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "default": self.default,
            "description": self.description,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "options": [{"value": value, "label": label} for value, label in self.options],
        }


@dataclass(frozen=True)
class RemoteItem:
    external_key: str
    source_url: str
    preview_url: str | None = None
    title: str | None = None
    candidate_urls: tuple[str, ...] = ()
    ignored_reason: str | None = None
    referer_url: str | None = None
    abort_on_access_block: bool = False


@dataclass(frozen=True)
class RemotePage:
    page_number: int
    items: tuple[RemoteItem, ...]
    stop_reason: Literal["collection_end", "requested_end", "known_page"] | None = None

    @property
    def reached_collection_end(self) -> bool:
        return self.stop_reason == "collection_end"


@dataclass(frozen=True)
class ScriptDefinition:
    key: str
    name: str
    version: str
    page_format_key: str
    description: str
    adapter: "SourceAdapter"
    parameters: tuple[ScriptParameter, ...] = field(default_factory=tuple)
    legacy_parameters: tuple[ScriptParameter, ...] = field(default_factory=tuple)
    max_download_workers: int | None = None
    download_start_interval_seconds: float = 0.0

    def metadata(self) -> dict[str, object]:
        return {
            "key": self.key,
            "name": self.name,
            "version": self.version,
            "page_format_key": self.page_format_key,
            "description": self.description,
            "parameters": [parameter.as_dict() for parameter in self.parameters],
        }

    def validate_parameters(self, raw: dict[str, object] | None) -> dict[str, object]:
        raw = raw or {}
        all_parameters = (*self.parameters, *self.legacy_parameters)
        known = {parameter.key for parameter in all_parameters}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ValueError(f"脚本包含未知参数：{', '.join(unknown)}")
        result: dict[str, object] = {}
        for parameter in all_parameters:
            value = raw.get(parameter.key, parameter.default)
            if value in (None, ""):
                if parameter.required:
                    raise ValueError(f"参数“{parameter.label}”不能为空")
                continue
            if parameter.type == "integer":
                try:
                    value = int(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"参数“{parameter.label}”必须是整数") from exc
            elif parameter.type == "number":
                try:
                    value = float(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"参数“{parameter.label}”必须是数字") from exc
            elif parameter.type == "boolean":
                if not isinstance(value, bool):
                    raise ValueError(f"参数“{parameter.label}”必须是布尔值")
            else:
                value = str(value)
            if isinstance(value, (int, float)):
                if parameter.minimum is not None and value < parameter.minimum:
                    raise ValueError(f"参数“{parameter.label}”不能小于 {parameter.minimum:g}")
                if parameter.maximum is not None and value > parameter.maximum:
                    raise ValueError(f"参数“{parameter.label}”不能大于 {parameter.maximum:g}")
            if parameter.type == "select" and str(value) not in {option[0] for option in parameter.options}:
                raise ValueError(f"参数“{parameter.label}”的选项无效")
            result[parameter.key] = value
        if self.key == "shfwzwz-raindrop-page":
            if "max_pages" in result:
                if any(key in raw for key in ("start_page", "end_page")):
                    raise ValueError("旧参数 max_pages 不能与起止页同时使用")
                result = {"start_page": 1, "end_page": int(result["max_pages"])}
        if any(parameter.key == "start_page" for parameter in self.parameters):
            start_page = int(result.get("start_page", 1))
            end_page = result.get("end_page")
            if end_page is not None and int(end_page) < start_page:
                raise ValueError("结束页不能小于起始页")
        return result


class SourceAdapter:
    def enumerate_pages(
        self,
        crawl_url: str,
        parameters: dict[str, object],
        known_external_keys: set[str],
        incremental: bool,
    ) -> Iterable[RemotePage]:
        raise NotImplementedError

    def enumerate(
        self,
        crawl_url: str,
        parameters: dict[str, object],
        known_external_keys: set[str],
        incremental: bool,
    ) -> Iterable[RemoteItem]:
        for page in self.enumerate_pages(crawl_url, parameters, known_external_keys, incremental):
            yield from page.items


def max_pages_from(parameters: dict[str, object]) -> int | None:
    raw = parameters.get("max_pages")
    if raw in (None, "", 0, "0"):
        return None
    value = int(raw)
    if value < 1:
        raise ValueError("最大扫描页数必须大于等于 1，留空表示扫描全部页面")
    return value


def stable_key(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def is_tls_transport_error(exc: Exception) -> bool:
    message = str(exc).upper()
    markers = (
        "ASN1",
        "CERTIFICATE_VERIFY_FAILED",
        "EOF",
        "NOT_ENOUGH_DATA",
        "SSL",
        "TLS",
        "UNEXPECTED_EOF_WHILE_READING",
        "WRONG_VERSION_NUMBER",
    )
    return any(marker in message for marker in markers)


def curl_request_bytes(
    url: str,
    accept: str,
    referer: str,
    timeout: float = 45,
    max_bytes: int | None = None,
    retries: int = 3,
    abort_on_access_block: bool = False,
    before_attempt: Callable[[], None] | None = None,
) -> tuple[bytes, str]:
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise RuntimeError("系统未安装 curl，无法回退处理网站 TLS 异常")
    parsed = urlparse(url)
    if not parsed.hostname:
        raise ValueError("下载地址缺少主机名")
    attempts = max(1, int(retries))
    request_timeout = max(1, int(timeout))
    retry_delay = 1
    temporary = tempfile.NamedTemporaryFile(prefix="pictureshow-curl-", suffix=".tmp", delete=False)
    temporary_path = Path(temporary.name)
    temporary.close()
    command = [
        curl,
        "--ipv4",
        "--location",
        "--fail",
        "--silent",
        "--show-error",
        "--retry",
        str(0 if abort_on_access_block else attempts - 1),
        "--retry-delay",
        str(retry_delay),
        "--retry-all-errors",
        "--connect-timeout",
        str(min(30, request_timeout)),
        "--max-time",
        str(request_timeout),
        "--user-agent",
        USER_AGENT,
        "--header",
        f"Accept: {accept}",
        "--referer",
        referer,
        "--output",
        str(temporary_path),
        "--write-out",
        "%{http_code}\n%{content_type}" if abort_on_access_block else "%{content_type}",
    ]
    try:
        command.append(url)
        process_timeout = (
            request_timeout + 10
            if abort_on_access_block
            else attempts * request_timeout + (attempts - 1) * retry_delay + 10
        )
        last_error: RuntimeError | None = None
        process_attempts = attempts if abort_on_access_block else 1
        for attempt in range(process_attempts):
            if before_attempt is not None:
                before_attempt()
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=process_timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                last_error = RuntimeError(
                    f"请求 {parsed.hostname} 超时：最多尝试 {attempts} 次，每次 {request_timeout} 秒"
                )
                if attempt + 1 >= process_attempts:
                    raise last_error from exc
                if before_attempt is None:
                    time.sleep(retry_delay)
                continue
            output = result.stdout.strip()
            status_text, _, content_type = output.partition("\n") if abort_on_access_block else ("", "", output)
            status_code = int(status_text) if status_text.isdigit() else 0
            if status_code in {403, 429}:
                raise AccessBlockedError(url, status_code)
            if result.returncode != 0:
                last_error = RuntimeError(result.stderr.strip() or f"curl 下载失败（退出码 {result.returncode}）")
                if attempt + 1 < process_attempts:
                    if before_attempt is None:
                        time.sleep(retry_delay)
                    continue
                raise last_error
            size = temporary_path.stat().st_size
            if max_bytes is not None and size > max_bytes:
                raise ValueError("文件超过下载大小上限")
            return temporary_path.read_bytes(), content_type
        raise last_error or RuntimeError("curl 下载失败")
    finally:
        temporary_path.unlink(missing_ok=True)


def _request_bytes(
    url: str,
    accept: str,
    referer: str,
    timeout: float = 45,
    abort_on_access_block: bool = False,
    retries: int = 1,
) -> tuple[bytes, str]:
    request = Request(url, headers={"Accept": accept, "Referer": referer, "User-Agent": USER_AGENT})
    attempts = max(1, int(retries))
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read(), response.headers.get("Content-Type", "")
        except HTTPError as exc:
            if abort_on_access_block and exc.code in {403, 429}:
                raise AccessBlockedError(url, exc.code) from exc
            if attempt + 1 >= attempts:
                raise
        except Exception as exc:
            if is_tls_transport_error(exc):
                return curl_request_bytes(
                    url,
                    accept,
                    referer,
                    timeout,
                    retries=attempts,
                    abort_on_access_block=abort_on_access_block,
                )
            if attempt + 1 >= attempts:
                raise
        time.sleep(1)
    raise RuntimeError("请求失败")


class RaindropWorkersAdapter(SourceAdapter):
    def _normalize(self, raw_url: str) -> tuple[str, str]:
        parsed = urlparse(raw_url.strip())
        if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() != "raindrop.ftxsri.workers.dev":
            raise ValueError("该脚本只支持 raindrop.ftxsri.workers.dev 的分类网页")
        if not [part for part in parsed.path.split("/") if part]:
            raise ValueError("分类 URL 中缺少集合标识")
        query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() not in {"ajax", "page", "sort"}]
        page_url = urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", urlencode(query), ""))
        return f"{parsed.scheme}://{parsed.netloc.lower()}", page_url

    def enumerate_pages(self, crawl_url: str, parameters: dict[str, object], known_external_keys: set[str], incremental: bool) -> Iterable[RemotePage]:
        base_url, page_url = self._normalize(crawl_url)
        max_pages = max_pages_from(parameters)
        page = 0
        seen: set[str] = set()
        while page <= 1000 and (max_pages is None or page < max_pages):
            parsed = urlparse(page_url)
            query = parse_qsl(parsed.query, keep_blank_values=True) + [("ajax", "1"), ("page", str(page)), ("sort", "-created")]
            request_url = urlunparse(parsed._replace(query=urlencode(query)))
            raw, _ = _request_bytes(request_url, "application/json,*/*;q=0.8", page_url)
            payload = json.loads(raw.decode("utf-8"))
            batch = (payload.get("items") or []) if isinstance(payload, dict) else []
            if not isinstance(batch, list):
                raise ValueError("Workers 采集接口未返回图片列表")
            if not batch:
                yield RemotePage(page_number=page + 1, items=(), stop_reason="collection_end")
                break
            page_keys: list[str] = []
            page_items: list[RemoteItem] = []
            for record in batch:
                if not isinstance(record, dict) or record.get("type") != "image":
                    continue
                link = str(record.get("link") or "").strip()
                cover = str(record.get("cover") or "").strip()
                if not link and not cover:
                    continue
                item_id = str(record.get("_id") or stable_key(link or cover))
                if item_id in seen:
                    continue
                seen.add(item_id)
                page_keys.append(item_id)
                candidates: list[str] = []
                for candidate in (
                    link,
                    f"{base_url}/get_cache_url?id={quote(item_id)}",
                    f"{base_url}/proxy?url={quote(link, safe='')}" if link else "",
                    cover,
                    f"{base_url}/proxy?url={quote(cover, safe='')}" if cover else "",
                ):
                    if candidate and candidate not in candidates:
                        candidates.append(candidate)
                page_items.append(RemoteItem(item_id, link or cover, cover or None, str(record.get("title") or "") or None, tuple(candidates)))
            natural_end = len(batch) < 30
            requested_end = max_pages is not None and page + 1 >= max_pages
            known_end = incremental and page_keys and all(key in known_external_keys for key in page_keys)
            stop_reason = "collection_end" if natural_end else "known_page" if known_end else "requested_end" if requested_end else None
            yield RemotePage(page_number=page + 1, items=tuple(page_items), stop_reason=stop_reason)
            if stop_reason is not None:
                break
            page += 1


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
        self.image_candidates: list[tuple[str, ...]] = []

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
            if self.item_has_image and not self.item_has_video:
                candidates = tuple(
                    value
                    for attribute in ("data-src", "href", "src")
                    for value in self.item_candidates[attribute]
                )
                self.image_candidates.append(candidates)
            self.item_depth = None
            self.item_tag = None
        if self.media_depth == self.depth and self.item_depth is None:
            self.media_depth = None
        if self.depth:
            self.depth -= 1


class IdolxxxGalleryAdapter(SourceAdapter):
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
    def _parse_detail(raw: bytes) -> tuple[tuple[str, ...], ...]:
        parser = IdolxxxDetailParser()
        parser.feed(raw.decode("utf-8", errors="replace"))
        return tuple(parser.image_candidates)

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
        has_requested = False

        def fetch(url: str, referer: str) -> bytes:
            nonlocal has_requested
            if has_requested:
                time.sleep(random.uniform(2.0, 4.0))
            has_requested = True
            raw, content_type = _request_bytes(
                url,
                "text/html,*/*;q=0.8",
                referer,
                abort_on_access_block=True,
                retries=3,
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
        for page_number in range(start_page, requested_last_page + 1):
            page_url = self._page_url(collection_url, page_number)
            listing = first_page if page_number == 1 else self._parse_listing(fetch(page_url, collection_url), page_url, slug)
            page_keys: list[str] = []
            page_items: list[RemoteItem] = []
            for detail_url, card_title in listing.cards:
                detail_raw = fetch(detail_url, page_url)
                parsed_media = self._parse_detail(detail_raw)
                originals: list[str] = []
                for candidates in parsed_media:
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
                        originals.append(original)
                for index, original in enumerate(originals, start=1):
                    external_key = stable_key(original)
                    page_keys.append(external_key)
                    title = card_title
                    if title and len(originals) > 1:
                        title = f"{title} ({index}/{len(originals)})"
                    page_items.append(
                        RemoteItem(
                            external_key=external_key,
                            source_url=detail_url,
                            title=title,
                            candidate_urls=(original,),
                            referer_url=detail_url,
                            abort_on_access_block=True,
                        )
                    )
            natural_end = page_number >= last_page
            requested_end = page_number >= requested_last_page
            known_end = incremental and page_keys and all(key in known_external_keys for key in page_keys)
            stop_reason = "collection_end" if natural_end else "known_page" if known_end else "requested_end" if requested_end else None
            yield RemotePage(page_number=page_number, items=tuple(page_items), stop_reason=stop_reason)
            if stop_reason is not None:
                break


MAX_PAGES = ScriptParameter(
    key="max_pages",
    label="最大扫描页数（留空为全部）",
    type="integer",
    default=None,
    minimum=1,
    maximum=1000,
    description="留空时按网站返回的总页数扫描。",
)

START_PAGE = ScriptParameter(
    key="start_page",
    label="起始页",
    type="integer",
    default=1,
    minimum=1,
    maximum=1001,
    description="从第几页开始扫描，第一页填写 1。",
)

END_PAGE = ScriptParameter(
    key="end_page",
    label="结束页（包含，留空为末页）",
    type="integer",
    default=None,
    minimum=1,
    maximum=1001,
    description="扫描到该页后结束；留空时扫描到网站最后一页。",
)

SCRIPT_REGISTRY: dict[str, ScriptDefinition] = {
    "idolxxx-gallery": ScriptDefinition(
        key="idolxxx-gallery",
        name="idolxxx-gallery",
        version="1.0.0",
        page_format_key="idolxxx-gallery-v1",
        description="解析目标站点偶像分类页及卡片详情页，仅采集 /files/src/ 原图。",
        adapter=IdolxxxGalleryAdapter(),
        parameters=(START_PAGE, END_PAGE),
        max_download_workers=3,
        download_start_interval_seconds=1.0,
    ),
    "raindrop-ftxsri-workers-dev": ScriptDefinition(
        key="raindrop-ftxsri-workers-dev",
        name="raindrop-ftxsri-workers-dev",
        version="1.0.2",
        page_format_key="raindrop-workers-json-v1",
        description="读取 raindrop.ftxsri.workers.dev 集合的分页 JSON 接口。",
        adapter=RaindropWorkersAdapter(),
        parameters=(MAX_PAGES,),
    ),
    "shfwzwz-raindrop-page": ScriptDefinition(
        key="shfwzwz-raindrop-page",
        name="shfwzwz-raindrop-page",
        version="1.2.0",
        page_format_key="raindrop-public-page-v1",
        description="解析 *.raindrop.page 公共集合 HTML，支持指定页码范围。",
        adapter=RaindropPageAdapter(),
        parameters=(START_PAGE, END_PAGE),
        legacy_parameters=(MAX_PAGES,),
    ),
}


LEGACY_SCRIPT_KEYS = {
    "raindrop-workers": "raindrop-ftxsri-workers-dev",
    "raindrop-page": "shfwzwz-raindrop-page",
}


def get_script(key: str) -> ScriptDefinition | None:
    return SCRIPT_REGISTRY.get(LEGACY_SCRIPT_KEYS.get(key, key))


def script_catalog() -> list[dict[str, object]]:
    return [SCRIPT_REGISTRY[key].metadata() for key in sorted(SCRIPT_REGISTRY)]
