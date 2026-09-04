from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.db import Base
from app.lifecycle import initialize_database, run_database_migrations

ALEMBIC_CONFIG = Path(__file__).resolve().parents[2] / "alembic.ini"


def _table_names(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def _alembic_version(connection) -> str | None:
    return connection.scalar(text("SELECT version_num FROM alembic_version"))


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_CONFIG))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logger"] = False
    return config


def test_initialize_database_builds_fresh_schema_via_alembic(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")

    initialize_database(engine)

    tables = _table_names(engine)
    assert "alembic_version" in tables
    assert "gallery_photos" in tables
    assert "video_items" in tables
    assert "acquisition_scripts" in tables
    assert "app_schema_migrations" in tables

    with engine.connect() as connection:
        assert _alembic_version(connection) == "0003"

    # 重复启动幂等
    initialize_database(engine)
    with engine.connect() as connection:
        assert _alembic_version(connection) == "0003"
    engine.dispose()


def test_initialize_database_stamps_legacy_database_without_schema_fixup(tmp_path) -> None:
    """无 alembic_version 的存量库：仅 stamp head，不再执行旧版 ensure_*。"""
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE legacy_marker (id INTEGER PRIMARY KEY)"))

    outcome = run_database_migrations(engine)
    assert outcome == "legacy-stamped"

    tables = _table_names(engine)
    assert "alembic_version" in tables
    # stamp-only：不自动建业务表
    assert "gallery_photos" not in tables
    assert "legacy_marker" in tables

    with engine.connect() as connection:
        assert _alembic_version(connection) == "0003"

    # 再次启动：已有 alembic_version，走常规升级（no-op）
    outcome2 = run_database_migrations(engine)
    assert outcome2 == "up-to-date"
    engine.dispose()


def test_initialize_database_seeds_acquisition_scripts_on_fresh_database(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'seed.db').as_posix()}")

    initialize_database(engine)

    with engine.connect() as connection:
        script_count = connection.scalar(text("SELECT COUNT(*) FROM acquisition_scripts"))
    assert script_count > 0
    engine.dispose()


def test_fresh_alembic_schema_matches_orm_metadata(tmp_path) -> None:
    """空库经 initialize_database 建表后，与 create_all 的建表结果一致。"""
    alembic_engine = create_engine(f"sqlite:///{(tmp_path / 'alembic.db').as_posix()}")
    create_all_engine = create_engine(f"sqlite:///{(tmp_path / 'create_all.db').as_posix()}")

    initialize_database(alembic_engine)
    Base.metadata.create_all(bind=create_all_engine)

    alembic_tables = _table_names(alembic_engine) - {"alembic_version", "app_schema_migrations"}
    create_all_tables = _table_names(create_all_engine)
    assert alembic_tables == create_all_tables

    for table_name in sorted(create_all_tables):
        alembic_columns = {column["name"] for column in inspect(alembic_engine).get_columns(table_name)}
        create_all_columns = {column["name"] for column in inspect(create_all_engine).get_columns(table_name)}
        assert alembic_columns == create_all_columns, f"表 {table_name} 列不一致"

    alembic_engine.dispose()
    create_all_engine.dispose()


def test_fresh_database_upgrade_head_has_no_alembic_drift(tmp_path) -> None:
    """全新库 upgrade head 后 alembic check 无漂移。"""
    db_path = tmp_path / "check.db"
    url = f"sqlite:///{db_path.as_posix()}"
    config = _alembic_config(url)
    command.upgrade(config, "head")
    # check 在无漂移时正常返回；有漂移会抛 CommandError
    command.check(config)
