from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.application import create_app
from app.core.config import Settings
from app.db import Base
from app.lifecycle import ensure_gallery_ingest_source_column, initialize_database


class FakeStorage:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def ensure_bucket(self) -> None:
        self.calls.append("storage")


class FakeVectorStore:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def ensure_collections(self) -> None:
        self.calls.append("vector_store")


class FakeFaceService:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def warmup(self) -> None:
        self.calls.append("face")


class FakeOcrService:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def engine_status(self) -> dict[str, bool | str | None]:
        self.calls.append("ocr")
        return {
            "rapidocr_ready": True,
            "tesseract_ready": False,
            "rapidocr_error": None,
            "tesseract_error": "未配置",
        }


class FakePictureService:
    def ensure_system_tags(self, _db: object, _workspace_id: int) -> None:
        raise AssertionError("空数据库不应初始化工作空间标签")


def test_create_app_uses_injected_lifecycle_dependencies(tmp_path, monkeypatch) -> None:
    calls: list[str] = []
    engine = create_engine(f"sqlite:///{(tmp_path / 'factory.db').as_posix()}")
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    settings = Settings(database_url=str(engine.url), data_dir=tmp_path)
    services = SimpleNamespace(
        storage=FakeStorage(calls),
        vector_store=FakeVectorStore(calls),
        face=FakeFaceService(calls),
        ocr=FakeOcrService(calls),
        pictures=FakePictureService(),
    )

    recovered_types: list[str] = []

    def fake_fail_incomplete_tasks(_db: object, task_type: str) -> int:
        recovered_types.append(task_type)
        return 0

    monkeypatch.setattr("app.lifecycle.fail_incomplete_tasks", fake_fail_incomplete_tasks)
    app = create_app(
        settings=settings,
        services=services,
        engine=engine,
        session_factory=session_factory,
        logger=logging.getLogger("test.application"),
    )

    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            assert app.state.services is services
            assert app.state.engine is engine

    asyncio.run(run_lifespan())

    assert inspect(engine).has_table("video_items")
    assert calls == ["storage", "vector_store", "face", "ocr"]
    assert recovered_types == [
        "gallery_import",
        "gallery_rich_import",
        "gallery_zip_import",
        "person_import",
        "video_subtitle_generation",
        "gallery_similarity_scan",
        "acquisition_similarity_scan",
    ]
    engine.dispose()


def test_initialize_database_adds_similarity_group_review_status_to_legacy_database(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE gallery_similarity_groups ("
                "id INTEGER PRIMARY KEY, "
                "scan_id VARCHAR(36) NOT NULL, "
                "ordinal INTEGER NOT NULL, "
                "tier VARCHAR(32) NOT NULL, "
                "min_score FLOAT NOT NULL, "
                "average_score FLOAT NOT NULL, "
                "created_at DATETIME NOT NULL"
                ")"
            )
        )
        connection.execute(
            text(
                "INSERT INTO gallery_similarity_groups "
                "(id, scan_id, ordinal, tier, min_score, average_score, created_at) "
                "VALUES (1, 'legacy-scan', 1, 'near_duplicate', 0.95, 0.97, CURRENT_TIMESTAMP)"
            )
        )

    initialize_database(engine)

    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("gallery_similarity_groups")}
    indexes = {index["name"] for index in inspector.get_indexes("gallery_similarity_groups")}
    with engine.connect() as connection:
        review_status = connection.scalar(
            text("SELECT review_status FROM gallery_similarity_groups WHERE id = 1")
        )

    assert "review_status" in columns
    assert "ix_gallery_similarity_groups_review_status" in indexes
    assert review_status == "pending"
    engine.dispose()


def test_gallery_ingest_source_migration_marks_legacy_acquisition_photos(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy-gallery-source.db').as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE gallery_photos (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE acquisition_imported_photos (gallery_photo_id INTEGER)"))
        connection.execute(text("INSERT INTO gallery_photos (id) VALUES (1), (2)"))
        connection.execute(text("INSERT INTO acquisition_imported_photos (gallery_photo_id) VALUES (1)"))

    ensure_gallery_ingest_source_column(engine)

    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("gallery_photos")}
    indexes = {index["name"] for index in inspector.get_indexes("gallery_photos")}
    with engine.connect() as connection:
        values = connection.execute(
            text("SELECT id, ingest_source FROM gallery_photos ORDER BY id")
        ).all()

    assert "ingest_source" in columns
    assert "ix_gallery_photos_ingest_source" in indexes
    assert values == [(1, "acquisition"), (2, "legacy_unclassified")]
    engine.dispose()


def test_initialize_database_migrates_legacy_global_name_constraints(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy-workspaces.db').as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE workspaces ("
                "id INTEGER PRIMARY KEY, "
                "name VARCHAR(128) NOT NULL, "
                "kind VARCHAR(32) NOT NULL, "
                "owner_user_id INTEGER, "
                "created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL"
                ")"
            )
        )
        connection.execute(
            text(
                "INSERT INTO workspaces (id, name, kind, owner_user_id, created_at, updated_at) VALUES "
                "(1, '工作区一', 'private', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(2, '工作区二', 'private', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE persons ("
                "id INTEGER PRIMARY KEY, "
                "name VARCHAR(256) NOT NULL, "
                "display_name VARCHAR(256) NOT NULL, "
                "note TEXT, "
                "is_unknown BOOLEAN NOT NULL, "
                "unknown_serial INTEGER UNIQUE, "
                "created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL, "
                "workspace_id INTEGER"
                ")"
            )
        )
        connection.execute(text("CREATE UNIQUE INDEX ix_persons_name ON persons (name)"))
        connection.execute(
            text(
                "INSERT INTO persons "
                "(id, workspace_id, name, display_name, note, is_unknown, unknown_serial, created_at, updated_at) "
                "VALUES (10, 1, '同名人物', '同名人物', NULL, 0, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE video_category_tags ("
                "id INTEGER PRIMARY KEY, workspace_id INTEGER, name VARCHAR(128) NOT NULL, created_at DATETIME NOT NULL"
                ")"
            )
        )
        connection.execute(text("CREATE UNIQUE INDEX ix_video_category_tags_name ON video_category_tags (name)"))
        connection.execute(
            text(
                "INSERT INTO video_category_tags (id, workspace_id, name, created_at) "
                "VALUES (20, 1, '同名分类', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE video_people ("
                "id INTEGER PRIMARY KEY, workspace_id INTEGER, name VARCHAR(256) NOT NULL, note TEXT, "
                "avatar_object_key VARCHAR(512) UNIQUE, avatar_content_type VARCHAR(128), "
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL"
                ")"
            )
        )
        connection.execute(text("CREATE UNIQUE INDEX ix_video_people_name ON video_people (name)"))
        connection.execute(
            text(
                "INSERT INTO video_people "
                "(id, workspace_id, name, note, avatar_object_key, avatar_content_type, created_at, updated_at) "
                "VALUES (30, 1, '同名视频人物', NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tags (id, workspace_id, name, is_system, created_at) "
                "VALUES (40, 1, '关联标签', 0, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO person_tags (id, person_id, tag_id, created_at) "
                "VALUES (50, 10, 40, CURRENT_TIMESTAMP)"
            )
        )

    initialize_database(engine)
    initialize_database(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO persons "
                "(workspace_id, name, display_name, note, is_unknown, unknown_serial, created_at, updated_at) "
                "VALUES (2, '同名人物', '同名人物', NULL, 0, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO video_category_tags (workspace_id, name, created_at) "
                "VALUES (2, '同名分类', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO video_people "
                "(workspace_id, name, note, avatar_object_key, avatar_content_type, created_at, updated_at) "
                "VALUES (2, '同名视频人物', NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT person_id FROM person_tags WHERE id = 50")) == 10
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        assert connection.scalar(text("SELECT COUNT(*) FROM persons WHERE name = '同名人物'")) == 2
        assert connection.scalar(text("SELECT COUNT(*) FROM video_category_tags WHERE name = '同名分类'")) == 2
        assert connection.scalar(text("SELECT COUNT(*) FROM video_people WHERE name = '同名视频人物'")) == 2
        for table_name in ("persons", "video_category_tags", "video_people"):
            unique_indexes = connection.execute(text(f"PRAGMA index_list('{table_name}')")).mappings().all()
            unique_columns = []
            for index in unique_indexes:
                if not index["unique"]:
                    continue
                columns = connection.execute(
                    text(f"PRAGMA index_info('{index['name']}')")
                ).mappings().all()
                unique_columns.append([column["name"] for column in columns])
            assert ["name"] not in unique_columns
            if table_name == "persons":
                assert ["unknown_serial"] not in unique_columns

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO persons "
                    "(workspace_id, name, display_name, note, is_unknown, unknown_serial, created_at, updated_at) "
                    "VALUES (1, '同名人物', '同名人物', NULL, 0, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )

    inspector = inspect(engine)
    assert {tuple(item["column_names"]) for item in inspector.get_unique_constraints("persons")} == {
        ("workspace_id", "name"),
        ("workspace_id", "unknown_serial"),
    }
    assert {tuple(item["column_names"]) for item in inspector.get_unique_constraints("video_category_tags")} == {
        ("workspace_id", "name"),
    }
    assert ("workspace_id", "name") in {
        tuple(item["column_names"]) for item in inspector.get_unique_constraints("video_people")
    }
    engine.dispose()
