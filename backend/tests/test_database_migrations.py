from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.db import Base
from app.lifecycle import initialize_database, run_database_migrations

ALEMBIC_CONFIG = Path(__file__).resolve().parents[2] / "alembic.ini"
ALEMBIC_HEAD = ScriptDirectory.from_config(Config(str(ALEMBIC_CONFIG))).get_current_head()


def test_provenance_migration_preserves_existing_media_and_constraints(tmp_path):
    """新增外键需要SQLite重建表，验证已有素材及原索引不丢失。"""
    from datetime import datetime
    from sqlalchemy import MetaData, Table
    url = f"sqlite:///{(tmp_path / 'provenance-upgrade.db').as_posix()}"
    config = _alembic_config(url)
    command.upgrade(config, "0014b0f63f70")
    engine = create_engine(url)
    metadata = MetaData()
    table = Table("gallery_photos", metadata, autoload_with=engine)
    now = datetime(2026, 1, 1)
    with engine.begin() as connection:
        connection.execute(table.insert().values(id=41, filename="keep.jpg", sha256="keep", object_key="keep",
            is_rich_text=False, ingest_source="manual_upload", display_batch_at=now, display_index=3,
            created_at=now, updated_at=now))
    before_indexes = {row["name"] for row in inspect(engine).get_indexes("gallery_photos")}
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT filename, display_index, created_by FROM gallery_photos WHERE id=41")).one() == ("keep.jpg", 3, None)
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    assert before_indexes <= {row["name"] for row in inspect(engine).get_indexes("gallery_photos")}
    assert any(fk["name"] == "fk_gallery_photos_created_by" for fk in inspect(engine).get_foreign_keys("gallery_photos"))
    engine.dispose()


def test_asset_source_snapshot_migration_preserves_constraints(tmp_path):
    """新增素材来源快照列需要重建 acquisition_assets，验证索引、约束和已有行都不丢。"""
    from datetime import datetime
    from sqlalchemy import MetaData, Table
    url = f"sqlite:///{(tmp_path / 'asset-source.db').as_posix()}"
    config = _alembic_config(url)
    command.upgrade(config, "6c4d9140f96b")
    engine = create_engine(url)
    table = Table("acquisition_assets", MetaData(), autoload_with=engine)
    now = datetime(2026, 1, 1)
    with engine.begin() as connection:
        connection.execute(table.insert().values(id="a", sha256="keep", filename="keep.jpg", media_type="image",
            size_bytes=3, status="pending_review", created_at=now, updated_at=now))
    before_indexes = {row["name"] for row in inspect(engine).get_indexes("acquisition_assets")}
    before_unique = {row["name"] for row in inspect(engine).get_unique_constraints("acquisition_assets")}
    before_foreign = {row["name"] for row in inspect(engine).get_foreign_keys("acquisition_assets")}
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id, source_snapshot_json FROM acquisition_assets")).all() == [("a", None)]
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    assert "source_snapshot_json" in {column["name"] for column in inspect(engine).get_columns("acquisition_assets")}
    assert before_indexes <= {row["name"] for row in inspect(engine).get_indexes("acquisition_assets")}
    assert before_unique <= {row["name"] for row in inspect(engine).get_unique_constraints("acquisition_assets")}
    assert before_foreign <= {row["name"] for row in inspect(engine).get_foreign_keys("acquisition_assets")}
    engine.dispose()


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
    assert "app_schema_migrations" not in tables

    with engine.connect() as connection:
        assert _alembic_version(connection) == ALEMBIC_HEAD

    # 重复启动幂等
    initialize_database(engine)
    with engine.connect() as connection:
        assert _alembic_version(connection) == ALEMBIC_HEAD
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
        assert _alembic_version(connection) == ALEMBIC_HEAD

    # 再次启动：已有 alembic_version，走常规升级（no-op）
    outcome2 = run_database_migrations(engine)
    assert outcome2 == "up-to-date"
    engine.dispose()


def test_fresh_database_seeds_only_builtin_telegram(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'seed.db').as_posix()}")

    initialize_database(engine)

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT key, name FROM acquisition_scripts ORDER BY key")).all()
    assert rows == [("telegram-channel-mtproto", "Telegram 频道")]
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


def test_upgrade_preserves_legacy_migration_history_without_drift(tmp_path) -> None:
    """旧迁移记录表保留审计数据，不应被 autogenerate 误判为待删除表。"""
    url = f"sqlite:///{(tmp_path / 'legacy-history.db').as_posix()}"
    config = _alembic_config(url)
    command.upgrade(config, "19a44fe179ff")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE app_schema_migrations "
            "(migration_key VARCHAR(128) PRIMARY KEY, applied_at DATETIME NOT NULL)"
        ))
        connection.execute(text(
            "INSERT INTO app_schema_migrations VALUES ('legacy-marker', '2026-09-30 12:00:00')"
        ))
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT migration_key, applied_at FROM app_schema_migrations"
        )).one() == ("legacy-marker", "2026-09-30 12:00:00")
        assert _alembic_version(connection) == ALEMBIC_HEAD
    engine.dispose()
