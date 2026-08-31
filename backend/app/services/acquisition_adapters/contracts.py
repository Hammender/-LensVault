from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from collections.abc import Iterable
from typing import Literal
from urllib.parse import urlparse


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)
class AccessBlockedError(RuntimeError):
    def __init__(self, url: str, status_code: int) -> None:
        host = urlparse(url).hostname or "远端站点"
        self.status_code = status_code
        super().__init__(f"站点 {host} 返回 HTTP {status_code}，已停止本次采集以避免继续触发访问限制")


@dataclass(frozen=True)
class ScriptParameter:
    key: str
    label: str
    type: Literal["string", "integer", "number", "boolean", "select", "datetime", "string_list"]
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
            elif parameter.type == "string_list":
                if isinstance(value, str):
                    value = [part.strip() for part in value.split(",") if part.strip()]
                elif isinstance(value, list) and all(isinstance(part, str) for part in value):
                    value = [part.strip() for part in value if part.strip()]
                else:
                    raise ValueError(f"参数“{parameter.label}”必须是文本列表")
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


