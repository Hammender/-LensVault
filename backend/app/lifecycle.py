from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import Base
from app.models import Workspace
from app.services.container import ServiceContainer
from app.services.tasks import fail_incomplete_tasks


INCOMPLETE_TASK_TYPES = (
    "gallery_import",
    "gallery_rich_import",
    "gallery_zip_import",
    "person_import",
    "video_subtitle_generation",
    "gallery_similarity_scan",
)


def ensure_video_seek_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("video_items")}
    statements: list[str] = []
    if "seek_optimized" not in columns:
        statements.append("ALTER TABLE video_items ADD COLUMN seek_optimized BOOLEAN NOT NULL DEFAULT 0")
    if "seek_optimized_at" not in columns:
        statements.append("ALTER TABLE video_items ADD COLUMN seek_optimized_at DATETIME")
    if "seek_keyframe_interval_seconds" not in columns:
        statements.append("ALTER TABLE video_items ADD COLUMN seek_keyframe_interval_seconds FLOAT")
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def ensure_face_recognition_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    additions = {
        "sample_photos": {
            "quality_status": "ALTER TABLE sample_photos ADD COLUMN quality_status VARCHAR(32)",
            "quality_warnings": "ALTER TABLE sample_photos ADD COLUMN quality_warnings TEXT",
            "source_type": "ALTER TABLE sample_photos ADD COLUMN source_type VARCHAR(32) NOT NULL DEFAULT 'upload'",
            "source_gallery_photo_id": "ALTER TABLE sample_photos ADD COLUMN source_gallery_photo_id INTEGER",
        },
        "face_records": {
            "second_person_id": "ALTER TABLE face_records ADD COLUMN second_person_id INTEGER",
            "second_match_score": "ALTER TABLE face_records ADD COLUMN second_match_score FLOAT",
            "match_margin": "ALTER TABLE face_records ADD COLUMN match_margin FLOAT",
            "embedding_version": "ALTER TABLE face_records ADD COLUMN embedding_version VARCHAR(64)",
            "face_size": "ALTER TABLE face_records ADD COLUMN face_size FLOAT",
            "blur_score": "ALTER TABLE face_records ADD COLUMN blur_score FLOAT",
            "pose_yaw": "ALTER TABLE face_records ADD COLUMN pose_yaw FLOAT",
        },
    }
    statements: list[str] = []
    for table, columns in additions.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        statements.extend(statement for name, statement in columns.items() if name not in existing)
    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_sample_person_source_gallery "
                "ON sample_photos (person_id, source_gallery_photo_id)"
            )
        )


def ensure_gallery_similarity_group_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    if "gallery_similarity_groups" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("gallery_similarity_groups")}
    with engine.begin() as connection:
        if "review_status" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE gallery_similarity_groups "
                    "ADD COLUMN review_status VARCHAR(32) NOT NULL DEFAULT 'pending'"
                )
            )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_gallery_similarity_groups_review_status "
                "ON gallery_similarity_groups (review_status)"
            )
        )


def _sqlite_index_columns(connection, index_name: str) -> list[str]:
    safe_index_name = index_name.replace("'", "''")
    rows = connection.execute(text(f"PRAGMA index_info('{safe_index_name}')")).mappings().all()
    return [str(row["name"]) for row in rows]


def _sqlite_unique_index_columns(connection, table_name: str) -> list[list[str]]:
    safe_table_name = table_name.replace("'", "''")
    rows = connection.execute(text(f"PRAGMA index_list('{safe_table_name}')")).mappings().all()
    return [
        _sqlite_index_columns(connection, str(row["name"]))
        for row in rows
        if int(row["unique"]) == 1
    ]


def _sqlite_gallery_unique_indexes(connection) -> list[list[str]]:
    return _sqlite_unique_index_columns(connection, "gallery_photos")


def _ensure_no_workspace_name_duplicates(connection, table_name: str) -> None:
    duplicate = connection.execute(
        text(
            f"SELECT workspace_id, name, COUNT(*) AS duplicate_count "
            f"FROM {table_name} "
            "GROUP BY workspace_id, name "
            "HAVING COUNT(*) > 1 "
            "LIMIT 1"
        )
    ).mappings().first()
    if duplicate is None:
        return
    raise RuntimeError(
        "数据库迁移失败："
        f"{table_name} 中工作区 {duplicate['workspace_id']} 存在重复名称 "
        f"{duplicate['name']!r}（{duplicate['duplicate_count']} 条），请先人工处理"
    )


def _rebuild_persons_table(connection) -> None:
    connection.execute(text("DROP TABLE IF EXISTS persons_new"))
    connection.execute(
        text(
            """
            CREATE TABLE persons_new (
                id INTEGER NOT NULL,
                workspace_id INTEGER,
                name VARCHAR(256) NOT NULL,
                display_name VARCHAR(256) NOT NULL,
                note TEXT,
                is_unknown BOOLEAN NOT NULL,
                unknown_serial INTEGER,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
                CONSTRAINT uq_persons_workspace_name UNIQUE (workspace_id, name),
                CONSTRAINT uq_persons_workspace_unknown_serial UNIQUE (workspace_id, unknown_serial)
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO persons_new (
                id, workspace_id, name, display_name, note, is_unknown,
                unknown_serial, created_at, updated_at
            )
            SELECT
                id, workspace_id, name, display_name, note, is_unknown,
                unknown_serial, created_at, updated_at
            FROM persons
            """
        )
    )
    connection.execute(text("DROP TABLE persons"))
    connection.execute(text("ALTER TABLE persons_new RENAME TO persons"))
    connection.execute(text("CREATE INDEX ix_persons_workspace_id ON persons (workspace_id)"))
    connection.execute(text("CREATE INDEX ix_persons_name ON persons (name)"))
    connection.execute(text("CREATE INDEX ix_persons_display_name ON persons (display_name)"))
    connection.execute(text("CREATE INDEX ix_persons_is_unknown ON persons (is_unknown)"))


def _rebuild_video_category_tags_table(connection) -> None:
    connection.execute(text("DROP TABLE IF EXISTS video_category_tags_new"))
    connection.execute(
        text(
            """
            CREATE TABLE video_category_tags_new (
                id INTEGER NOT NULL,
                workspace_id INTEGER,
                name VARCHAR(128) NOT NULL,
                created_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
                CONSTRAINT uq_video_category_tags_workspace_name UNIQUE (workspace_id, name)
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO video_category_tags_new (id, workspace_id, name, created_at)
            SELECT id, workspace_id, name, created_at
            FROM video_category_tags
            """
        )
    )
    connection.execute(text("DROP TABLE video_category_tags"))
    connection.execute(text("ALTER TABLE video_category_tags_new RENAME TO video_category_tags"))
    connection.execute(text("CREATE INDEX ix_video_category_tags_workspace_id ON video_category_tags (workspace_id)"))
    connection.execute(text("CREATE INDEX ix_video_category_tags_name ON video_category_tags (name)"))


def _rebuild_video_people_table(connection) -> None:
    connection.execute(text("DROP TABLE IF EXISTS video_people_new"))
    connection.execute(
        text(
            """
            CREATE TABLE video_people_new (
                id INTEGER NOT NULL,
                workspace_id INTEGER,
                name VARCHAR(256) NOT NULL,
                note TEXT,
                avatar_object_key VARCHAR(512),
                avatar_content_type VARCHAR(128),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
                CONSTRAINT uq_video_people_workspace_name UNIQUE (workspace_id, name),
                UNIQUE (avatar_object_key)
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO video_people_new (
                id, workspace_id, name, note, avatar_object_key,
                avatar_content_type, created_at, updated_at
            )
            SELECT
                id, workspace_id, name, note, avatar_object_key,
                avatar_content_type, created_at, updated_at
            FROM video_people
            """
        )
    )
    connection.execute(text("DROP TABLE video_people"))
    connection.execute(text("ALTER TABLE video_people_new RENAME TO video_people"))
    connection.execute(text("CREATE INDEX ix_video_people_workspace_id ON video_people (workspace_id)"))
    connection.execute(text("CREATE INDEX ix_video_people_name ON video_people (name)"))


def ensure_workspace_scoped_name_constraints(engine: Engine) -> None:
    expected_unique_indexes = {
        "persons": (["workspace_id", "name"], ["workspace_id", "unknown_serial"]),
        "video_category_tags": (["workspace_id", "name"],),
        "video_people": (["workspace_id", "name"],),
    }
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        tables_to_rebuild = []
        for table_name, expected_indexes in expected_unique_indexes.items():
            if table_name not in existing_tables:
                continue
            unique_indexes = _sqlite_unique_index_columns(connection, table_name)
            has_missing_workspace_unique = any(
                list(expected_columns) not in unique_indexes
                for expected_columns in expected_indexes
            )
            has_legacy_global_unique = ["name"] in unique_indexes or (
                table_name == "persons" and ["unknown_serial"] in unique_indexes
            )
            if has_missing_workspace_unique or has_legacy_global_unique:
                tables_to_rebuild.append(table_name)
        if not tables_to_rebuild:
            return

        for table_name in tables_to_rebuild:
            _ensure_no_workspace_name_duplicates(connection, table_name)

        connection.execute(text("PRAGMA foreign_keys=OFF"))
        connection.execute(text("BEGIN IMMEDIATE"))
        try:
            if "persons" in tables_to_rebuild:
                _rebuild_persons_table(connection)
            if "video_category_tags" in tables_to_rebuild:
                _rebuild_video_category_tags_table(connection)
            if "video_people" in tables_to_rebuild:
                _rebuild_video_people_table(connection)
            connection.execute(text("COMMIT"))
        except Exception:
            connection.execute(text("ROLLBACK"))
            raise
        finally:
            connection.execute(text("PRAGMA foreign_keys=ON"))

        foreign_key_error = connection.execute(text("PRAGMA foreign_key_check")).mappings().first()
        if foreign_key_error is not None:
            raise RuntimeError(f"数据库迁移后外键检查失败：{dict(foreign_key_error)}")


def ensure_gallery_photo_type_unique_constraint(engine: Engine) -> None:
    inspector = inspect(engine)
    if "gallery_photos" not in inspector.get_table_names():
        return
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        unique_indexes = _sqlite_gallery_unique_indexes(connection)
        has_new_unique = ["workspace_id", "sha256", "is_rich_text"] in unique_indexes
        has_legacy_sha_unique = any(
            columns in (["sha256"], ["workspace_id", "sha256"])
            for columns in unique_indexes
        )
        if has_new_unique and not has_legacy_sha_unique:
            return
        if not has_legacy_sha_unique:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_gallery_photos_workspace_sha256_rich_text "
                    "ON gallery_photos (workspace_id, sha256, is_rich_text)"
                )
            )
            return

        try:
            connection.execute(text("PRAGMA foreign_keys=OFF"))
            connection.execute(text("DROP TABLE IF EXISTS gallery_photos_new"))
            connection.execute(
                text(
                    """
                    CREATE TABLE gallery_photos_new (
                        id INTEGER NOT NULL,
                        workspace_id INTEGER,
                        filename VARCHAR(512) NOT NULL,
                        content_type VARCHAR(128),
                        sha256 VARCHAR(64) NOT NULL,
                        object_key VARCHAR(512) NOT NULL,
                        width INTEGER,
                        height INTEGER,
                        taken_at DATETIME,
                        is_rich_text BOOLEAN NOT NULL,
                        rich_text TEXT,
                        ocr_status VARCHAR(32),
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL,
                        PRIMARY KEY (id),
                        FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
                        CONSTRAINT uq_gallery_photos_workspace_sha256_rich_text
                            UNIQUE (workspace_id, sha256, is_rich_text),
                        UNIQUE (object_key)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO gallery_photos_new (
                        id, workspace_id, filename, content_type, sha256, object_key,
                        width, height, taken_at, is_rich_text, rich_text, ocr_status,
                        created_at, updated_at
                    )
                    SELECT
                        id, workspace_id, filename, content_type, sha256, object_key,
                        width, height, taken_at, is_rich_text, rich_text, ocr_status,
                        created_at, updated_at
                    FROM gallery_photos
                    """
                )
            )
            connection.execute(text("DROP TABLE gallery_photos"))
            connection.execute(text("ALTER TABLE gallery_photos_new RENAME TO gallery_photos"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_gallery_photos_workspace_id ON gallery_photos (workspace_id)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_gallery_photos_sha256 ON gallery_photos (sha256)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_gallery_photos_is_rich_text ON gallery_photos (is_rich_text)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_gallery_photos_ocr_status ON gallery_photos (ocr_status)"))
        finally:
            connection.execute(text("PRAGMA foreign_keys=ON"))


def initialize_database(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)
    ensure_workspace_scoped_name_constraints(engine)
    ensure_gallery_photo_type_unique_constraint(engine)
    ensure_video_seek_columns(engine)
    ensure_face_recognition_columns(engine)
    ensure_gallery_similarity_group_columns(engine)


def initialize_runtime(
    settings: Settings,
    services: ServiceContainer,
    session_factory: Callable[[], Session],
    logger: logging.Logger,
) -> None:
    logger.info("应用启动：开始检查存储、向量库、人脸识别和 OCR 依赖")
    services.storage.ensure_bucket()
    services.vector_store.ensure_collections()
    services.face.warmup()
    ocr_status = services.ocr.engine_status()
    logger.info(
        "OCR 引擎状态：rapidocr_ready=%s tesseract_ready=%s rapidocr_error=%s tesseract_error=%s",
        ocr_status["rapidocr_ready"],
        ocr_status["tesseract_ready"],
        ocr_status["rapidocr_error"] or "-",
        ocr_status["tesseract_error"] or "-",
    )

    db = session_factory()
    try:
        for workspace in db.scalars(select(Workspace)).all():
            services.pictures.ensure_system_tags(db, workspace.id)
        recovered = sum(fail_incomplete_tasks(db, task_type) for task_type in INCOMPLETE_TASK_TYPES)
        if recovered > 0:
            logger.warning("应用启动：已恢复未完成任务 count=%d", recovered)
    finally:
        db.close()

    logger.info(
        "应用启动完成：minio_bucket=%s qdrant_sample_collection=%s",
        settings.minio_bucket,
        settings.qdrant_known_collection,
    )
