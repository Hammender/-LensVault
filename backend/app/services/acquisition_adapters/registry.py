from __future__ import annotations

from collections.abc import Iterable

from .contracts import RemotePage, ScriptDefinition, ScriptParameter, SourceAdapter


class BuiltinTelegramAdapter(SourceAdapter):
    """占位适配器。Telegram 采集由 AcquisitionService 的内置流程处理。"""

    def enumerate_pages(
        self,
        crawl_url: str,
        parameters: dict[str, object],
        known_external_keys: set[str],
        incremental: bool,
    ) -> Iterable[RemotePage]:
        raise RuntimeError("Telegram 频道由内置采集流程处理")


TELEGRAM_DATE_FROM = ScriptParameter(
    "date_from",
    "起始时间（上海时间）",
    "datetime",
    description="只采集该时间及之后发布的消息。时间按上海时区理解。",
)
TELEGRAM_DATE_TO = ScriptParameter(
    "date_to",
    "结束时间（上海时间）",
    "datetime",
    description="只采集该时间及之前发布的消息。时间按上海时区理解。",
)
TELEGRAM_MEDIA_TYPES = ScriptParameter(
    "media_types", "采集媒体", "string_list", default=["image", "video"], description="选择图片、视频或两者。"
)
TELEGRAM_COLLECT_COMMENTS = ScriptParameter(
    "collect_comments", "采集评论区媒体", "boolean", default=False, description="仅频道有效；从频道帖子的评论区采集图片和视频。"
)
TELEGRAM_HASHTAGS = ScriptParameter("hashtags", "包含标签", "string_list", description="所有标签均需出现在消息文案中。")
TELEGRAM_KEYWORDS = ScriptParameter("caption_keywords", "文案关键词", "string_list", description="所有关键词均需出现在消息文案中。")
TELEGRAM_MAX_MESSAGES = ScriptParameter(
    "max_messages",
    "最大扫描消息数",
    "integer",
    default=1000,
    minimum=1,
    maximum=10000,
    description="按频道里看到的消息条数计数，相册算 1 条；达到上限后整组收录，不会只下相册里的一部分图。",
)
TELEGRAM_SCAN_ORDER = ScriptParameter(
    "scan_order",
    "扫描顺序",
    "select",
    default="newest",
    description="限额从所选方向的一端开始计数。从旧到新且未填起始时间时，会从频道最早的消息往后走。",
    options=(("newest", "从新到旧"), ("oldest", "从旧到新")),
)

SCRIPT_REGISTRY: dict[str, ScriptDefinition] = {
    "telegram-channel-mtproto": ScriptDefinition(
        key="telegram-channel-mtproto",
        name="Telegram 频道",
        version="1.1.0",
        page_format_key="telegram-channel-v1",
        description="使用当前工作区 Telegram 账号读取频道图片和视频。",
        adapter=BuiltinTelegramAdapter(),
        parameters=(
            TELEGRAM_DATE_FROM,
            TELEGRAM_DATE_TO,
            TELEGRAM_SCAN_ORDER,
            TELEGRAM_MEDIA_TYPES,
            TELEGRAM_HASHTAGS,
            TELEGRAM_KEYWORDS,
            TELEGRAM_MAX_MESSAGES,
            TELEGRAM_COLLECT_COMMENTS,
        ),
        max_download_workers=1,
    ),
}


def get_script(key: str) -> ScriptDefinition | None:
    return SCRIPT_REGISTRY.get(key)


def script_catalog() -> list[dict[str, object]]:
    return [SCRIPT_REGISTRY[key].metadata() for key in sorted(SCRIPT_REGISTRY)]
