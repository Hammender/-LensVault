from __future__ import annotations

from .contracts import ScriptDefinition, ScriptParameter
from .idolxxx import IdolxxxGalleryAdapter
from .raindrop_workers import RaindropWorkersAdapter
from .shfwzwz_raindrop import RaindropPageAdapter


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
IDOLXXX_MEDIA_TYPES = ScriptParameter(
    "media_types", "采集媒体", "string_list", default=["image"], description="选择图片、视频或两者。"
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
        adapter=RaindropWorkersAdapter(),
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
    "idolxxx-gallery": ScriptDefinition(
        key="idolxxx-gallery",
        name="idolxxx-gallery",
        version="1.1.0",
        page_format_key="idolxxx-gallery-v1",
        description="解析目标站点偶像分类页及卡片详情页，支持采集 /files/src/ 图片和视频原文件。",
        adapter=IdolxxxGalleryAdapter(),
        parameters=(START_PAGE, END_PAGE, IDOLXXX_MEDIA_TYPES),
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
    return [SCRIPT_REGISTRY[key].metadata() for key in sorted(SCRIPT_REGISTRY) if key != "telegram-channel-mtproto"] + [
        SCRIPT_REGISTRY["telegram-channel-mtproto"].metadata()
    ]
