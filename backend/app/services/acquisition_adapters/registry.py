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

SCRIPT_REGISTRY: dict[str, ScriptDefinition] = {
    "idolxxx-gallery": ScriptDefinition(
        key="idolxxx-gallery",
        name="idolxxx-gallery",
        version="1.0.1",
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
