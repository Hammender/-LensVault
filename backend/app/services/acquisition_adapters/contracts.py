from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from app.core.timezones import as_shanghai_naive, shanghai_isoformat
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


_PARAMETER_FIELDS = {
    "key", "label", "type", "required", "default", "description", "minimum", "maximum", "options",
}
_PARAMETER_TYPES = {
    "string", "integer", "number", "boolean", "select", "datetime", "string_list",
}


def script_parameter_from_manifest(item: object) -> ScriptParameter:
    if not isinstance(item, dict):
        raise ValueError("插件参数必须是对象")
    unknown = sorted(str(key) for key in item if key not in _PARAMETER_FIELDS)
    if unknown:
        raise ValueError(f"插件参数包含未知字段：{', '.join(unknown)}")
    key, label, kind = item.get("key"), item.get("label"), item.get("type")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("插件参数缺少标识")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("插件参数缺少名称")
    if kind not in _PARAMETER_TYPES:
        raise ValueError(f"插件参数“{label}”类型无效")
    description = item.get("description")
    if description is not None and not isinstance(description, str):
        raise ValueError(f"插件参数“{label}”的说明必须是文本")
    return ScriptParameter(
        key=key,
        label=label,
        type=kind,
        required=bool(item.get("required", False)),
        default=item.get("default"),
        description=description,
        minimum=_optional_number(item.get("minimum"), f"插件参数“{label}”的最小值"),
        maximum=_optional_number(item.get("maximum"), f"插件参数“{label}”的最大值"),
        options=_normalize_parameter_options(item.get("options", ()), label),
    )


def parse_max_download_workers(raw: object) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ValueError("max_download_workers 必须是正整数")
    return raw


def remote_item_from_plugin(raw: object) -> RemoteItem:
    if not isinstance(raw, dict):
        raise ValueError("插件条目必须是对象")
    external_key = raw.get("external_key")
    source_url = raw.get("source_url")
    if not isinstance(external_key, str) or not external_key.strip():
        raise ValueError("插件条目缺少稳定来源键")
    if not isinstance(source_url, str) or not source_url.strip():
        raise ValueError("插件条目缺少原始地址")
    media_type = raw.get("media_type", "image")
    if media_type not in {"image", "video"}:
        raise ValueError("插件条目媒体类型必须是 image 或 video")
    plugin_data = raw.get("plugin_data")
    if plugin_data is not None and not isinstance(plugin_data, dict):
        raise ValueError("插件条目 plugin_data 必须是对象")
    abort = raw.get("abort_on_access_block", False)
    if not isinstance(abort, bool):
        raise ValueError("插件条目 abort_on_access_block 必须是布尔值")
    return RemoteItem(
        external_key=external_key,
        source_url=source_url,
        preview_url=_optional_text(raw.get("preview_url"), "preview_url"),
        title=_optional_text(raw.get("title"), "title"),
        candidate_urls=_string_tuple(raw.get("candidate_urls"), "candidate_urls"),
        ignored_reason=_optional_text(raw.get("ignored_reason"), "ignored_reason"),
        referer_url=_optional_text(raw.get("referer_url"), "referer_url"),
        abort_on_access_block=abort,
        media_type=media_type,
        plugin_data=plugin_data,
        caption=_optional_text(raw.get("caption"), "caption"),
        hashtags=_string_tuple(raw.get("hashtags"), "hashtags"),
        published_at=normalize_plugin_published_at(raw.get("published_at"), external_key),
        channel_title=_optional_text(raw.get("channel_title"), "channel_title"),
    )


def normalize_plugin_published_at(value: object, source_key: str | int) -> str | None:
    if value is None or value == "":
        return None
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
        if parsed is not None:
            return shanghai_isoformat(as_shanghai_naive(parsed))
    except ValueError:
        pass
    logging.getLogger(__name__).warning("插件发布时间无效，已忽略 source_key=%s", source_key)
    return None


def _optional_number(value: object, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}必须是数字")
    return float(value)


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"插件条目 {field} 必须是文本")
    return value


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or not all(isinstance(part, str) for part in value):
        raise ValueError(f"插件条目 {field} 必须是文本列表")
    return tuple(value)


def _normalize_parameter_options(raw: object, label: str) -> tuple[tuple[str, str], ...]:
    if raw in (None, (), []):
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"插件参数“{label}”的选项无效")
    options: list[tuple[str, str]] = []
    for option in raw:
        if isinstance(option, dict):
            value, option_label = option.get("value"), option.get("label")
            if not isinstance(value, str) or not isinstance(option_label, str):
                raise ValueError(f"插件参数“{label}”的选项无效")
            options.append((value, option_label))
        elif (
            isinstance(option, (list, tuple))
            and len(option) == 2
            and all(isinstance(part, str) for part in option)
        ):
            options.append((option[0], option[1]))
        else:
            raise ValueError(f"插件参数“{label}”的选项无效")
    return tuple(options)


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
    media_type: Literal["image", "video"] = "image"
    plugin_data: dict[str, object] | None = None
    caption: str | None = None
    hashtags: tuple[str, ...] = ()
    published_at: str | None = None
    channel_title: str | None = None


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
                if parameter.key == "media_types":
                    invalid = sorted(set(value) - {"image", "video"})
                    if invalid:
                        raise ValueError(f"参数“{parameter.label}”包含无效媒体类型：{', '.join(invalid)}")
                    if not value:
                        raise ValueError(f"参数“{parameter.label}”至少选择图片或视频")
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
        if any(parameter.key == "start_page" for parameter in self.parameters):
            start_page = int(result.get("start_page", 1))
            end_page = result.get("end_page")
            if end_page is not None and int(end_page) < start_page:
                raise ValueError("结束页不能小于起始页")
        if self.key == "telegram-channel-mtproto" and not result.get("media_types"):
            raise ValueError("至少选择一种采集媒体：图片或视频")
        if self.key == "telegram-channel-mtproto" and result.get("comments_only"):
            result["collect_comments"] = True
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


