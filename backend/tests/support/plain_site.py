"""测试进程内的普通站点脚本。不写入产品注册表源码。"""

from __future__ import annotations

from collections.abc import Iterable

from app.services.acquisition_adapters.contracts import RemotePage, ScriptDefinition, ScriptParameter, SourceAdapter
from app.services.acquisition_adapters.registry import SCRIPT_REGISTRY

PLAIN_SITE_KEY = "plain-site"
OTHER_SITE_KEY = "other-site"


class IdleAdapter(SourceAdapter):
    def enumerate_pages(
        self,
        crawl_url: str,
        parameters: dict[str, object],
        known_external_keys: set[str],
        incremental: bool,
    ) -> Iterable[RemotePage]:
        return iter(())


def install_plain_site_scripts() -> None:
    if PLAIN_SITE_KEY in SCRIPT_REGISTRY:
        return
    SCRIPT_REGISTRY[PLAIN_SITE_KEY] = ScriptDefinition(
        key=PLAIN_SITE_KEY,
        name="普通站点",
        version="1.0.0",
        page_format_key="plain-site-v1",
        description="测试用普通站点脚本",
        adapter=IdleAdapter(),
        parameters=(
            ScriptParameter(
                "max_pages",
                "最大扫描页数",
                "integer",
                default=None,
                minimum=1,
                maximum=1000,
            ),
        ),
    )
    SCRIPT_REGISTRY[OTHER_SITE_KEY] = ScriptDefinition(
        key=OTHER_SITE_KEY,
        name="另一站点",
        version="1.0.0",
        page_format_key="other-site-v1",
        description="测试用另一网页格式",
        adapter=IdleAdapter(),
        parameters=(
            ScriptParameter("start_page", "起始页", "integer", default=1, minimum=1, maximum=1001),
            ScriptParameter("end_page", "结束页", "integer", default=None, minimum=1, maximum=1001),
        ),
    )


def remove_plain_site_scripts() -> None:
    SCRIPT_REGISTRY.pop(PLAIN_SITE_KEY, None)
    SCRIPT_REGISTRY.pop(OTHER_SITE_KEY, None)
