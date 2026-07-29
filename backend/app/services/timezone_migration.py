from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.timezones import shanghai_now


MIGRATION_KEY = "2026_07_29_system_timestamps_to_asia_shanghai"
TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{1,6})?$")

# EXIF fields such as gallery_photos.taken_at and sample_photos.taken_at are
# intentionally absent: they are source wall-clock values, not system times.
SYSTEM_TIMESTAMP_COLUMNS: dict[str, tuple[str, ...]] = {
    "acquisition_assets": ("created_at", "updated_at"),
    "acquisition_categories": ("created_at", "updated_at"),
    "acquisition_export_jobs": ("expires_at", "created_at", "completed_at", "downloaded_at"),
    "acquisition_import_batch_items": ("created_at", "updated_at"),
    "acquisition_import_batches": ("started_at", "completed_at", "created_at", "updated_at"),
    "acquisition_imported_photos": ("created_at",),
    "acquisition_run_items": ("created_at", "updated_at"),
    "acquisition_runs": ("started_at", "completed_at", "created_at", "updated_at"),
    "acquisition_scripts": ("created_at", "updated_at"),
    "acquisition_similarity_candidates": ("created_at",),
    "acquisition_source_items": ("last_seen_at", "failed_at", "created_at", "updated_at"),
    "acquisition_source_scripts": ("created_at", "updated_at"),
    "acquisition_sources": ("created_at", "updated_at"),
    "face_recognition_corrections": ("created_at",),
    "face_records": ("created_at",),
    "gallery_photo_person_tags": ("created_at",),
    "gallery_photo_tags": ("created_at",),
    "gallery_photos": ("created_at", "updated_at"),
    "gallery_similarity_features": ("created_at", "updated_at"),
    "gallery_similarity_groups": ("created_at",),
    "gallery_similarity_scans": ("created_at", "completed_at"),
    "person_tags": ("created_at",),
    "persons": ("created_at", "updated_at"),
    "sample_photos": ("created_at",),
    "tags": ("created_at",),
    "tasks": ("created_at", "updated_at"),
    "upload_history": ("created_at",),
    "users": ("created_at", "updated_at"),
    "video_category_tags": ("created_at",),
    "video_item_category_tags": ("created_at",),
    "video_item_people": ("created_at",),
    "video_items": ("created_at", "updated_at", "processed_at", "seek_optimized_at"),
    "video_people": ("created_at", "updated_at"),
    "video_subtitle_tracks": ("generated_at", "created_at", "updated_at"),
    "video_upload_parts": ("created_at",),
    "video_upload_sessions": ("created_at", "updated_at"),
    "workspace_invitations": ("created_at", "updated_at"),
    "workspace_members": ("created_at",),
    "workspaces": ("created_at", "updated_at"),
}


def _ensure_marker_table(connection) -> None:
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS app_schema_migrations ("
            "migration_key VARCHAR(128) PRIMARY KEY, applied_at DATETIME NOT NULL)"
        )
    )


def is_timezone_migration_applied(engine: Engine) -> bool:
    if "app_schema_migrations" not in inspect(engine).get_table_names():
        return False
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT 1 FROM app_schema_migrations WHERE migration_key=:key"),
            {"key": MIGRATION_KEY},
        ).first() is not None


def mark_timezone_baseline(engine: Engine) -> None:
    with engine.begin() as connection:
        _ensure_marker_table(connection)
        connection.execute(
            text(
                "INSERT OR IGNORE INTO app_schema_migrations (migration_key, applied_at) "
                "VALUES (:key, :applied_at)"
            ),
            {"key": MIGRATION_KEY, "applied_at": shanghai_now()},
        )


def require_timezone_migration(engine: Engine) -> None:
    if not is_timezone_migration_applied(engine):
        raise RuntimeError(
            "数据库时间尚未迁移到 Asia/Shanghai，请先执行 "
            "python -m app.tools.migrate_timezone_to_shanghai"
        )


def sqlite_database_path(engine: Engine) -> Path:
    url = make_url(str(engine.url))
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise ValueError("时间迁移工具仅支持文件型 SQLite 数据库")
    return Path(url.database).resolve()


def backup_sqlite_database(engine: Engine) -> Path:
    source_path = sqlite_database_path(engine)
    timestamp = shanghai_now().strftime("%Y%m%d_%H%M%S")
    backup_path = source_path.with_name(f"{source_path.name}.before-shanghai-time-{timestamp}.bak")
    with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)
    return backup_path


def migrate_system_timestamps(engine: Engine) -> tuple[Path | None, int]:
    if is_timezone_migration_applied(engine):
        return None, 0

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    available: dict[str, tuple[str, ...]] = {}
    for table_name, configured_columns in SYSTEM_TIMESTAMP_COLUMNS.items():
        if table_name not in tables:
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        available[table_name] = tuple(column for column in configured_columns if column in columns)

    with engine.connect() as connection:
        for table_name, columns in available.items():
            for column_name in columns:
                rows = connection.execution_options(stream_results=True).execute(
                    text(f'SELECT "{column_name}" FROM "{table_name}" WHERE "{column_name}" IS NOT NULL')
                )
                for (value,) in rows:
                    rendered = value.isoformat(sep=" ") if isinstance(value, datetime) else str(value)
                    if not TIMESTAMP_PATTERN.fullmatch(rendered):
                        raise ValueError(f"{table_name}.{column_name} 包含无法迁移的时间值: {rendered!r}")

    backup_path = backup_sqlite_database(engine)
    updated_rows = 0
    with engine.begin() as connection:
        _ensure_marker_table(connection)
        for table_name, columns in available.items():
            for column_name in columns:
                result = connection.execute(
                    text(
                        f'UPDATE "{table_name}" SET "{column_name}" = '
                        f'datetime(substr("{column_name}", 1, 19), \'+8 hours\') || substr("{column_name}", 20) '
                        f'WHERE "{column_name}" IS NOT NULL'
                    )
                )
                updated_rows += result.rowcount or 0
        connection.execute(
            text(
                "INSERT INTO app_schema_migrations (migration_key, applied_at) "
                "VALUES (:key, :applied_at)"
            ),
            {"key": MIGRATION_KEY, "applied_at": shanghai_now()},
        )
    return backup_path, updated_rows
