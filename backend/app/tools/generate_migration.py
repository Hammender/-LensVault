"""Alembic 迁移脚本生成工具。

基于临时空库先升级到最新迁移版本，再执行 autogenerate，
只包含本次 ORM 模型改动，避免存量数据库因历史手工迁移遗留的
结构命名差异（缺失 server default、外键/唯一约束命名不一致等）
污染生成的脚本。

用法：
    $env:PYTHONPATH='backend'
    python -m app.tools.generate_migration "新增视频封面对象键"

生成的脚本只是草稿，必须先人工/AI 逐行审核（见 AGENTS.md
「数据库迁移工作流程」），确认无误后再执行 alembic upgrade head。
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_CONFIG_PATH = PROJECT_ROOT / "alembic.ini"


def _build_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logger"] = False
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="基于临时空库生成 Alembic 迁移脚本")
    parser.add_argument("message", help="迁移说明（中文，描述本次表结构变化）")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="alembic-autogen-") as temp_dir:
        scratch_db = (Path(temp_dir) / "scratch.db").as_posix()
        config = _build_config(f"sqlite:///{scratch_db}")
        # 临时库先升级到最新版本，作为 autogenerate 的对照基线
        command.upgrade(config, "head")
        command.revision(config, message=args.message, autogenerate=True)

    script_dir = PROJECT_ROOT / "backend" / "alembic" / "versions"
    logging.getLogger(__name__).info("迁移脚本草稿已生成：%s", script_dir)
    print(f"迁移脚本草稿已生成到 {script_dir}，请先审核脚本内容，确认无误后再执行：")
    print("  python -m alembic upgrade head")
    return 0


if __name__ == "__main__":
    sys.exit(main())
