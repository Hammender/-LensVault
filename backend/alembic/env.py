"""Alembic 迁移环境。

数据库连接串的来源优先级：

1. 调用方通过 ``Config.attributes["database_url"]`` 注入（应用启动
   ``app.lifecycle`` 与 ``app.tools.generate_migration`` 都走这条路径）；
2. 命令行 ``alembic -x database_url=...``；
3. 项目根目录 ``.env`` 中的 ``DATABASE_URL``。

SQLite 下开启 ``render_as_batch``，让修改列/约束走表重建流程。
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.models  # noqa: F401,E402  在读取元数据前注册全部 ORM 表及其注释
from app.db import Base  # noqa: E402

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _dotenv_database_url() -> str:
    """从项目根目录 .env 读取 DATABASE_URL（与运行时配置保持同一来源）。"""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        raise RuntimeError(f"未找到运行时配置文件：{env_path}")
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "DATABASE_URL":
            return value.strip()
    raise RuntimeError(f"{env_path} 中缺少 DATABASE_URL")


def _database_url() -> str:
    injected = config.attributes.get("database_url")
    if injected:
        return str(injected)
    from_cli = context.get_x_argument(as_dictionary=True).get("database_url")
    if from_cli:
        return from_cli
    return _dotenv_database_url()


def _configure(connection=None) -> None:
    url = _database_url()
    context.configure(
        connection=connection,
        url=None if connection is not None else url,
        target_metadata=target_metadata,
        render_as_batch=url.startswith("sqlite"),
        compare_type=True,
        include_schemas=False,
    )


def run_migrations_offline() -> None:
    _configure()
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
