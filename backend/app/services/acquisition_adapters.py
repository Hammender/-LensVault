from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Literal
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


@dataclass(frozen=True)
class ScriptDefinition:
    key: str
    name: str
    version: str
    page_format_key: str
    description: str
    adapter: "SourceAdapter"
    parameters: tuple[ScriptParameter, ...] = field(default_factory=tuple)

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
        known = {parameter.key for parameter in self.parameters}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ValueError(f"脚本包含未知参数：{', '.join(unknown)}")
        result: dict[str, object] = {}
        for parameter in self.parameters:
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
        return result


class SourceAdapter:
    def enumerate(
        self,
        crawl_url: str,
        parameters: dict[str, object],
        known_external_keys: set[str],
        incremental: bool,
    ) -> Iterable[RemoteItem]:
        raise NotImplementedError


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
        str(attempts - 1),
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
        "%{content_type}",
    ]
    try:
        command.append(url)
        process_timeout = attempts * request_timeout + (attempts - 1) * retry_delay + 10
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=process_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"请求 {parsed.hostname} 超时：最多尝试 {attempts} 次，每次 {request_timeout} 秒"
            ) from exc
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"curl 下载失败（退出码 {result.returncode}）")
        size = temporary_path.stat().st_size
        if max_bytes is not None and size > max_bytes:
            raise ValueError("文件超过下载大小上限")
        return temporary_path.read_bytes(), result.stdout.strip()
    finally:
        temporary_path.unlink(missing_ok=True)


def _request_bytes(url: str, accept: str, referer: str, timeout: float = 45) -> tuple[bytes, str]:
    request = Request(url, headers={"Accept": accept, "Referer": referer, "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read(), response.headers.get("Content-Type", "")
    except Exception as exc:
        if not is_tls_transport_error(exc):
            raise
        return curl_request_bytes(url, accept, referer, timeout)


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

    def enumerate(self, crawl_url: str, parameters: dict[str, object], known_external_keys: set[str], incremental: bool) -> Iterable[RemoteItem]:
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
                break
            page_keys: list[str] = []
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
                yield RemoteItem(item_id, link or cover, cover or None, str(record.get("title") or "") or None, tuple(candidates))
            if incremental and page_keys and all(key in known_external_keys for key in page_keys):
                break
            page += 1
            if len(batch) < 30:
                break


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

    def enumerate(self, crawl_url: str, parameters: dict[str, object], known_external_keys: set[str], incremental: bool) -> Iterable[RemoteItem]:
        requested_url = self._validate(crawl_url)
        max_pages = max_pages_from(parameters)
        first_url = self._url_with_page(requested_url, 0) if incremental else requested_url
        first_page = self._fetch(first_url)
        parts = [part for part in urlparse(first_url).path.split("/") if part]
        start_match = PAGE_RE.search(parts[1]) if len(parts) > 1 else None
        start_page = int(start_match.group(1)) if start_match else 0
        last_page = max([start_page, *first_page.page_urls.keys()])
        if first_page.bookmark_count is not None:
            per_page = 30
            for candidate in [first_url, *first_page.page_urls.values()]:
                candidate_parts = [part for part in urlparse(candidate).path.split("/") if part]
                match = PERPAGE_RE.search(candidate_parts[1]) if len(candidate_parts) > 1 else None
                if match:
                    per_page = max(1, int(match.group(1)))
                    break
            last_page = max(last_page, max(0, (first_page.bookmark_count - 1) // per_page))
        if max_pages is not None:
            last_page = min(last_page, start_page + max_pages - 1)
        discovered = dict(first_page.page_urls)
        seen: set[str] = set()
        for page_number in range(start_page, last_page + 1):
            current_url = discovered.get(page_number) or self._url_with_page(first_url, page_number)
            page = first_page if page_number == start_page else self._fetch(current_url)
            discovered.update(page.page_urls)
            page_keys: list[str] = []
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
                yield RemoteItem(
                    external_key=external_key,
                    source_url=source_url,
                    preview_url=str(item.get("preview_url") or "") or None,
                    title=str(item.get("title") or "") or None,
                    candidate_urls=tuple(dict.fromkeys(filter(None, (source_url, str(item.get("preview_url") or ""))))),
                    ignored_reason=ignored,
                )
            if incremental and page_keys and all(key in known_external_keys for key in page_keys):
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

SCRIPT_REGISTRY: dict[str, ScriptDefinition] = {
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
        version="1.0.2",
        page_format_key="raindrop-public-page-v1",
        description="解析 *.raindrop.page 公共集合 HTML，并支持最新优先增量停止。",
        adapter=RaindropPageAdapter(),
        parameters=(MAX_PAGES,),
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
