from __future__ import annotations

import logging
from collections.abc import Callable

import json

from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.timezones import shanghai_now
from app.db import Base
from app.models import VideoItem, Workspace
from app.services.container import ServiceContainer
from app.services.tasks import fail_incomplete_tasks
from app.services.timezone_migration import mark_timezone_baseline, migrate_system_timestamps
from app.services.acquisition_adapters import LEGACY_SCRIPT_KEYS, SCRIPT_REGISTRY


INCOMPLETE_TASK_TYPES = (
    "gallery_import",
    "gallery_rich_import",
    "gallery_zip_import",
    "person_import",
    "video_subtitle_generation",
    "gallery_similarity_scan",
    "acquisition_similarity_scan",
    "acquisition_similarity_scan_mirror_pending",
    "acquisition_similarity_scan_normal_gallery",
    "acquisition_similarity_scan_mirror_gallery",
)

IGNORED_GALLERY_FACE_CLEANUP_KEY = "2026_08_08_delete_ignored_gallery_face_records"


def cleanup_ignored_gallery_face_records(engine: Engine) -> int:
    """删除旧版取消未知标签后遗留的无归属图库人脸记录。"""
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS app_schema_migrations ("
                "migration_key VARCHAR(128) PRIMARY KEY, applied_at DATETIME NOT NULL)"
            )
        )
        applied = connection.execute(
            text("SELECT 1 FROM app_schema_migrations WHERE migration_key=:key"),
            {"key": IGNORED_GALLERY_FACE_CLEANUP_KEY},
        ).first()
        if applied is not None:
            return 0

        result = connection.execute(
            text(
                "DELETE FROM face_records "
                "WHERE gallery_photo_id IS NOT NULL "
                "AND sample_photo_id IS NULL "
                "AND matched_person_id IS NULL "
                "AND needs_review = 0 "
                "AND vector_collection IS NULL "
                "AND NOT EXISTS ("
                "SELECT 1 FROM gallery_photo_person_tags AS photo_person "
                "JOIN persons AS person ON person.id = photo_person.person_id "
                "WHERE photo_person.gallery_photo_id = face_records.gallery_photo_id "
                "AND person.is_unknown = 1"
                ")"
            )
        )
        connection.execute(
            text(
                "INSERT INTO app_schema_migrations (migration_key, applied_at) "
                "VALUES (:key, :applied_at)"
            ),
            {"key": IGNORED_GALLERY_FACE_CLEANUP_KEY, "applied_at": shanghai_now()},
        )
        return max(result.rowcount or 0, 0)


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


def ensure_video_type_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    if "video_items" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("video_items")}
    with engine.begin() as connection:
        if "video_type" not in columns:
            connection.execute(text("ALTER TABLE video_items ADD COLUMN video_type VARCHAR(16) NOT NULL DEFAULT 'short'"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_video_items_video_type ON video_items (video_type)"))
            # 存量数据基于时长初始化；duration_seconds 为 NULL 的记录保留 ALTER TABLE 的默认值 'short'
            connection.execute(text("UPDATE video_items SET video_type = 'long' WHERE duration_seconds > 300"))
            connection.execute(text("UPDATE video_items SET video_type = 'short' WHERE duration_seconds <= 300 AND duration_seconds IS NOT NULL"))
            # 存量数据如果关联了旧的“长视频”或“短视频”标签，优先以此覆盖
            if "video_category_tags" in inspector.get_table_names() and "video_item_category_tags" in inspector.get_table_names():
                connection.execute(text("""
                    UPDATE video_items SET video_type = 'long' 
                    WHERE id IN (
                        SELECT vict.video_id FROM video_item_category_tags vict
                        JOIN video_category_tags vct ON vict.tag_id = vct.id
                        WHERE vct.name = '长视频'
                    )
                """))
                connection.execute(text("""
                    UPDATE video_items SET video_type = 'short' 
                    WHERE id IN (
                        SELECT vict.video_id FROM video_item_category_tags vict
                        JOIN video_category_tags vct ON vict.tag_id = vct.id
                        WHERE vct.name = '短视频'
                    )
                """))


def ensure_face_recognition_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    additions = {
        "sample_photos": {
            "quality_status": "ALTER TABLE sample_photos ADD COLUMN quality_status VARCHAR(32)",
            "quality_warnings": "ALTER TABLE sample_photos ADD COLUMN quality_warnings TEXT",
            "source_type": "ALTER TABLE sample_photos ADD COLUMN source_type VARCHAR(32) NOT NULL DEFAULT 'upload'",
            "source_gallery_photo_id": "ALTER TABLE sample_photos ADD COLUMN source_gallery_photo_id INTEGER",
            "source_gallery_face_id": "ALTER TABLE sample_photos ADD COLUMN source_gallery_face_id INTEGER",
        },
        "face_records": {
            "predicted_person_id": "ALTER TABLE face_records ADD COLUMN predicted_person_id INTEGER",
            "predicted_match_source": "ALTER TABLE face_records ADD COLUMN predicted_match_source VARCHAR(16)",
            "predicted_sample_photo_id": "ALTER TABLE face_records ADD COLUMN predicted_sample_photo_id INTEGER",
            "second_person_id": "ALTER TABLE face_records ADD COLUMN second_person_id INTEGER",
            "second_match_score": "ALTER TABLE face_records ADD COLUMN second_match_score FLOAT",
            "second_match_source": "ALTER TABLE face_records ADD COLUMN second_match_source VARCHAR(16)",
            "second_sample_photo_id": "ALTER TABLE face_records ADD COLUMN second_sample_photo_id INTEGER",
            "match_margin": "ALTER TABLE face_records ADD COLUMN match_margin FLOAT",
            "rejection_reason": "ALTER TABLE face_records ADD COLUMN rejection_reason VARCHAR(32)",
            "recognition_adapter_id": "ALTER TABLE face_records ADD COLUMN recognition_adapter_id VARCHAR(64)",
            "decision_threshold": "ALTER TABLE face_records ADD COLUMN decision_threshold FLOAT",
            "decision_min_margin": "ALTER TABLE face_records ADD COLUMN decision_min_margin FLOAT",
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
            text("CREATE INDEX IF NOT EXISTS ix_face_records_predicted_person_id ON face_records (predicted_person_id)")
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_sample_person_source_gallery "
                "ON sample_photos (person_id, source_gallery_photo_id)"
            )
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_sample_photos_source_gallery_face_id ON sample_photos (source_gallery_face_id)")
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


def ensure_similarity_scan_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    additions = {
        "gallery_similarity_features": {
            "mirror_phash": "ALTER TABLE gallery_similarity_features ADD COLUMN mirror_phash VARCHAR(64)",
            "mirror_dhash": "ALTER TABLE gallery_similarity_features ADD COLUMN mirror_dhash VARCHAR(64)",
            "quality_version": "ALTER TABLE gallery_similarity_features ADD COLUMN quality_version VARCHAR(64)",
            "resolution_score": "ALTER TABLE gallery_similarity_features ADD COLUMN resolution_score FLOAT",
            "sharpness_score": "ALTER TABLE gallery_similarity_features ADD COLUMN sharpness_score FLOAT",
            "artifact_score": "ALTER TABLE gallery_similarity_features ADD COLUMN artifact_score FLOAT",
            "exposure_score": "ALTER TABLE gallery_similarity_features ADD COLUMN exposure_score FLOAT",
            "primary_face_quality_score": "ALTER TABLE gallery_similarity_features ADD COLUMN primary_face_quality_score FLOAT",
            "primary_face_embedding": "ALTER TABLE gallery_similarity_features ADD COLUMN primary_face_embedding BLOB",
            "primary_face_dominant": "ALTER TABLE gallery_similarity_features ADD COLUMN primary_face_dominant BOOLEAN NOT NULL DEFAULT 0",
        },
        "gallery_similarity_groups": {
            "face_quality_enabled": "ALTER TABLE gallery_similarity_groups ADD COLUMN face_quality_enabled BOOLEAN NOT NULL DEFAULT 0",
            "recommendation_status": "ALTER TABLE gallery_similarity_groups ADD COLUMN recommendation_status VARCHAR(32) NOT NULL DEFAULT 'unavailable'",
        },
        "gallery_similarity_group_members": {
            "overall_quality_score": "ALTER TABLE gallery_similarity_group_members ADD COLUMN overall_quality_score FLOAT NOT NULL DEFAULT 0",
            "face_quality_score": "ALTER TABLE gallery_similarity_group_members ADD COLUMN face_quality_score FLOAT",
        },
        "gallery_similarity_scans": {
            "scan_type": "ALTER TABLE gallery_similarity_scans ADD COLUMN scan_type VARCHAR(32) NOT NULL DEFAULT 'normal'",
            "auto_delete_exact_mirror": "ALTER TABLE gallery_similarity_scans ADD COLUMN auto_delete_exact_mirror BOOLEAN NOT NULL DEFAULT 0",
            "auto_deleted_count": "ALTER TABLE gallery_similarity_scans ADD COLUMN auto_deleted_count INTEGER NOT NULL DEFAULT 0",
        },
        "acquisition_similarity_candidates": {
            "scan_type": "ALTER TABLE acquisition_similarity_candidates ADD COLUMN scan_type VARCHAR(32) NOT NULL DEFAULT 'normal'",
            "scan_scope": "ALTER TABLE acquisition_similarity_candidates ADD COLUMN scan_scope VARCHAR(32) NOT NULL DEFAULT 'pending_only'",
            "relation_type": "ALTER TABLE acquisition_similarity_candidates ADD COLUMN relation_type VARCHAR(32) NOT NULL DEFAULT 'near_duplicate'",
        },
    }
    with engine.begin() as connection:
        added_member_overall_score = False
        added_group_recommendation_status = False
        for table_name, columns in additions.items():
            if table_name not in tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, statement in columns.items():
                if column_name not in existing:
                    connection.execute(text(statement))
                    if table_name == "gallery_similarity_group_members" and column_name == "overall_quality_score":
                        added_member_overall_score = True
                    if table_name == "gallery_similarity_groups" and column_name == "recommendation_status":
                        added_group_recommendation_status = True
        if added_member_overall_score:
            connection.execute(
                text(
                    "UPDATE gallery_similarity_group_members "
                    "SET overall_quality_score = quality_score"
                )
            )
        if added_group_recommendation_status:
            connection.execute(
                text(
                    "UPDATE gallery_similarity_groups SET recommendation_status = 'recommended' "
                    "WHERE EXISTS ("
                    "SELECT 1 FROM gallery_similarity_group_members "
                    "WHERE gallery_similarity_group_members.group_id = gallery_similarity_groups.id "
                    "AND gallery_similarity_group_members.recommended_keep = 1"
                    ")"
                )
            )
        if "gallery_similarity_scans" in tables:
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_gallery_similarity_scans_scan_type ON gallery_similarity_scans (scan_type)"))
        if "gallery_similarity_features" in tables:
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_gallery_similarity_features_quality_version ON gallery_similarity_features (quality_version)"))
        if "acquisition_similarity_candidates" in tables:
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_acquisition_similarity_candidates_scan_type ON acquisition_similarity_candidates (scan_type)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_acquisition_similarity_candidates_scan_scope ON acquisition_similarity_candidates (scan_scope)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_acquisition_similarity_candidates_relation_type ON acquisition_similarity_candidates (relation_type)"))


def ensure_gallery_display_order_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    if "gallery_photos" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("gallery_photos")}
    with engine.begin() as connection:
        if "display_batch_at" not in columns:
            connection.execute(text("ALTER TABLE gallery_photos ADD COLUMN display_batch_at DATETIME"))
        if "display_index" not in columns:
            connection.execute(text("ALTER TABLE gallery_photos ADD COLUMN display_index INTEGER NOT NULL DEFAULT 0"))
        connection.execute(
            text(
                "UPDATE gallery_photos SET display_batch_at = created_at "
                "WHERE display_batch_at IS NULL"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_gallery_photos_display_order "
                "ON gallery_photos (workspace_id, display_batch_at, display_index)"
            )
        )


def ensure_gallery_ingest_source_column(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "gallery_photos" not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns("gallery_photos")}
    with engine.begin() as connection:
        if "ingest_source" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE gallery_photos "
                    "ADD COLUMN ingest_source VARCHAR(32) NOT NULL DEFAULT 'legacy_unclassified'"
                )
            )
        if "acquisition_imported_photos" in tables:
            connection.execute(
                text(
                    "UPDATE gallery_photos SET ingest_source = 'acquisition' "
                    "WHERE ingest_source = 'legacy_unclassified' "
                    "AND id IN ("
                    "SELECT gallery_photo_id FROM acquisition_imported_photos "
                    "WHERE gallery_photo_id IS NOT NULL"
                    ")"
                )
            )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_gallery_photos_ingest_source "
                "ON gallery_photos (ingest_source)"
            )
        )


def ensure_gallery_photo_size_column(engine: Engine) -> None:
    inspector = inspect(engine)
    if "gallery_photos" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("gallery_photos")}
    if "size_bytes" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE gallery_photos ADD COLUMN size_bytes BIGINT"))


def ensure_acquisition_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    additions = {
        "acquisition_sources": {
            "notes": "ALTER TABLE acquisition_sources ADD COLUMN notes TEXT",
            "page_format_key": "ALTER TABLE acquisition_sources ADD COLUMN page_format_key VARCHAR(128)",
        },
        "acquisition_categories": {
            "notes": "ALTER TABLE acquisition_categories ADD COLUMN notes TEXT",
        },
        "acquisition_runs": {
            "script_key": "ALTER TABLE acquisition_runs ADD COLUMN script_key VARCHAR(128)",
            "script_name_snapshot": "ALTER TABLE acquisition_runs ADD COLUMN script_name_snapshot VARCHAR(128) NOT NULL DEFAULT ''",
            "script_version_snapshot": "ALTER TABLE acquisition_runs ADD COLUMN script_version_snapshot VARCHAR(64) NOT NULL DEFAULT ''",
            "source_name_snapshot": "ALTER TABLE acquisition_runs ADD COLUMN source_name_snapshot VARCHAR(128) NOT NULL DEFAULT ''",
            "category_name_snapshot": "ALTER TABLE acquisition_runs ADD COLUMN category_name_snapshot VARCHAR(256) NOT NULL DEFAULT ''",
            "category_url_snapshot": "ALTER TABLE acquisition_runs ADD COLUMN category_url_snapshot VARCHAR(2048) NOT NULL DEFAULT ''",
            "parameters_json": "ALTER TABLE acquisition_runs ADD COLUMN parameters_json TEXT NOT NULL DEFAULT '{}'",
            "download_success_count": "ALTER TABLE acquisition_runs ADD COLUMN download_success_count INTEGER NOT NULL DEFAULT 0",
            "candidate_count": "ALTER TABLE acquisition_runs ADD COLUMN candidate_count INTEGER NOT NULL DEFAULT 0",
            "content_duplicate_count": "ALTER TABLE acquisition_runs ADD COLUMN content_duplicate_count INTEGER NOT NULL DEFAULT 0",
            "gallery_duplicate_count": "ALTER TABLE acquisition_runs ADD COLUMN gallery_duplicate_count INTEGER NOT NULL DEFAULT 0",
            "resolution_duplicate_count": "ALTER TABLE acquisition_runs ADD COLUMN resolution_duplicate_count INTEGER NOT NULL DEFAULT 0",
            "resolution_upgrade_count": "ALTER TABLE acquisition_runs ADD COLUMN resolution_upgrade_count INTEGER NOT NULL DEFAULT 0",
            "ignored_count": "ALTER TABLE acquisition_runs ADD COLUMN ignored_count INTEGER NOT NULL DEFAULT 0",
            "scan_start_page": "ALTER TABLE acquisition_runs ADD COLUMN scan_start_page INTEGER",
            "scan_end_page": "ALTER TABLE acquisition_runs ADD COLUMN scan_end_page INTEGER",
            "reached_collection_end": "ALTER TABLE acquisition_runs ADD COLUMN reached_collection_end BOOLEAN NOT NULL DEFAULT 0",
            "stop_reason": "ALTER TABLE acquisition_runs ADD COLUMN stop_reason VARCHAR(32)",
        },
        "acquisition_assets": {
            "perceptual_phash": "ALTER TABLE acquisition_assets ADD COLUMN perceptual_phash VARCHAR(32)",
            "perceptual_dhash": "ALTER TABLE acquisition_assets ADD COLUMN perceptual_dhash VARCHAR(32)",
            "quality_score": "ALTER TABLE acquisition_assets ADD COLUMN quality_score FLOAT",
            "quality_version": "ALTER TABLE acquisition_assets ADD COLUMN quality_version VARCHAR(64)",
            "resolution_score": "ALTER TABLE acquisition_assets ADD COLUMN resolution_score FLOAT",
            "sharpness_score": "ALTER TABLE acquisition_assets ADD COLUMN sharpness_score FLOAT",
            "artifact_score": "ALTER TABLE acquisition_assets ADD COLUMN artifact_score FLOAT",
            "exposure_score": "ALTER TABLE acquisition_assets ADD COLUMN exposure_score FLOAT",
            "primary_face_quality_score": "ALTER TABLE acquisition_assets ADD COLUMN primary_face_quality_score FLOAT",
            "primary_face_embedding": "ALTER TABLE acquisition_assets ADD COLUMN primary_face_embedding BLOB",
            "primary_face_dominant": "ALTER TABLE acquisition_assets ADD COLUMN primary_face_dominant BOOLEAN NOT NULL DEFAULT 0",
        },
        "acquisition_import_batches": {
            "is_rich_text": "ALTER TABLE acquisition_import_batches ADD COLUMN is_rich_text BOOLEAN NOT NULL DEFAULT 0",
        },
        "acquisition_source_items": {
            "script_key": "ALTER TABLE acquisition_source_items ADD COLUMN script_key VARCHAR(128)",
            "remote_external_key": "ALTER TABLE acquisition_source_items ADD COLUMN remote_external_key VARCHAR(256)",
        },
        "acquisition_run_items": {
            "collection_outcome": "ALTER TABLE acquisition_run_items ADD COLUMN collection_outcome VARCHAR(32) NOT NULL DEFAULT 'pending'",
            "resolved_url": "ALTER TABLE acquisition_run_items ADD COLUMN resolved_url VARCHAR(2048)",
            "resolved_candidate": "ALTER TABLE acquisition_run_items ADD COLUMN resolved_candidate VARCHAR(32)",
        },
        "acquisition_similarity_candidates": {
            "scan_task_id": "ALTER TABLE acquisition_similarity_candidates ADD COLUMN scan_task_id VARCHAR(64)",
        },
    }
    with engine.begin() as connection:
        for table_name, columns in additions.items():
            if table_name not in tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, statement in columns.items():
                if column_name not in existing:
                    connection.execute(text(statement))

        if "acquisition_assets" in tables:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_acquisition_assets_perceptual_phash "
                    "ON acquisition_assets (perceptual_phash)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_acquisition_assets_quality_version "
                    "ON acquisition_assets (quality_version)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_acquisition_assets_perceptual_dhash "
                    "ON acquisition_assets (perceptual_dhash)"
                )
            )
            connection.execute(
                text("UPDATE acquisition_assets SET status = 'pending_review' WHERE status = 'deferred'")
            )

        if "acquisition_scripts" not in tables or "acquisition_source_scripts" not in tables:
            return
        for definition in SCRIPT_REGISTRY.values():
            values = {
                "key": definition.key,
                "name": definition.name,
                "version": definition.version,
                "page_format_key": definition.page_format_key,
                "description": definition.description,
                "parameter_schema_json": json.dumps([item.as_dict() for item in definition.parameters], ensure_ascii=False),
                "now": shanghai_now(),
            }
            connection.execute(
                text(
                    "INSERT INTO acquisition_scripts (key, name, version, page_format_key, description, parameter_schema_json, enabled, created_at, updated_at) "
                    "VALUES (:key, :name, :version, :page_format_key, :description, :parameter_schema_json, 1, :now, :now) "
                    "ON CONFLICT(key) DO UPDATE SET name=excluded.name, version=excluded.version, "
                    "page_format_key=excluded.page_format_key, description=excluded.description, "
                    "parameter_schema_json=excluded.parameter_schema_json, enabled=1, updated_at=:now"
                ),
                values,
            )

        if "acquisition_sources" in tables:
            legacy_sources = connection.execute(
                text(
                    "SELECT id, workspace_id, name, adapter_key, base_url FROM acquisition_sources "
                    "WHERE adapter_key IS NOT NULL AND adapter_key != ''"
                )
            ).mappings().all()
            for row in legacy_sources:
                script_key = LEGACY_SCRIPT_KEYS.get(str(row["adapter_key"]), str(row["adapter_key"]))
                definition = SCRIPT_REGISTRY.get(script_key)
                if definition is None:
                    continue
                legacy_aliases = {
                    "raindrop-ftxsri-workers-dev": {"raindrop.ftxsri.workers.dev"},
                    "shfwzwz-raindrop-page": {"shfwzwz.raindrop.page"},
                }
                canonical_base_urls = {
                    "raindrop-ftxsri-workers-dev": "https://raindrop.ftxsri.workers.dev",
                    "shfwzwz-raindrop-page": "https://shfwzwz.raindrop.page",
                }
                if str(row["name"]) in legacy_aliases.get(script_key, set()):
                    duplicate = connection.execute(
                        text(
                            "SELECT id FROM acquisition_sources WHERE name=:name AND id!=:source_id "
                            "AND (workspace_id=:workspace_id OR (workspace_id IS NULL AND :workspace_id IS NULL))"
                        ),
                        {"name": definition.name, "source_id": row["id"], "workspace_id": row["workspace_id"]},
                    ).first()
                    if duplicate is None:
                        connection.execute(
                            text("UPDATE acquisition_sources SET name=:name WHERE id=:source_id"),
                            {"name": definition.name, "source_id": row["id"]},
                        )
                if not row["base_url"]:
                    connection.execute(
                        text("UPDATE acquisition_sources SET base_url=:base_url WHERE id=:source_id"),
                        {"base_url": canonical_base_urls[script_key], "source_id": row["id"]},
                    )
                connection.execute(
                    text(
                        "INSERT OR IGNORE INTO acquisition_source_scripts "
                        "(source_id, script_key, enabled, default_parameters_json, created_at, updated_at) "
                        "VALUES (:source_id, :script_key, 1, '{}', :now, :now)"
                    ),
                    {"source_id": row["id"], "script_key": script_key, "now": shanghai_now()},
                )
                connection.execute(
                    text("UPDATE acquisition_sources SET page_format_key=:page_format_key WHERE id=:source_id"),
                    {"source_id": row["id"], "page_format_key": definition.page_format_key},
                )
                connection.execute(
                    text(
                        "UPDATE acquisition_runs SET script_key=:script_key, script_name_snapshot=:script_name, "
                        "script_version_snapshot=:version, source_name_snapshot=(SELECT name FROM acquisition_sources WHERE id=:source_id), "
                        "category_name_snapshot=(SELECT name FROM acquisition_categories WHERE id=acquisition_runs.category_id), "
                        "category_url_snapshot=(SELECT crawl_url FROM acquisition_categories WHERE id=acquisition_runs.category_id) "
                        "WHERE source_id=:source_id AND (script_key IS NULL OR script_key='')"
                    ),
                    {
                        "source_id": row["id"],
                        "script_key": script_key,
                        "script_name": definition.name,
                        "version": definition.version,
                    },
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
    is_fresh_database = not inspect(engine).get_table_names()
    Base.metadata.create_all(bind=engine)
    ensure_acquisition_schema(engine)
    ensure_workspace_scoped_name_constraints(engine)
    ensure_gallery_photo_type_unique_constraint(engine)
    ensure_video_seek_columns(engine)
    ensure_video_type_columns(engine)
    ensure_face_recognition_columns(engine)
    ensure_gallery_similarity_group_columns(engine)
    ensure_similarity_scan_columns(engine)
    if is_fresh_database:
        mark_timezone_baseline(engine)
    else:
        migrate_system_timestamps(engine)
    deleted_ignored_faces = cleanup_ignored_gallery_face_records(engine)
    if deleted_ignored_faces:
        logging.getLogger(__name__).info(
            "数据库迁移：已删除旧版遗留的已忽略图库人脸记录 count=%d",
            deleted_ignored_faces,
        )
    ensure_gallery_display_order_columns(engine)
    ensure_gallery_ingest_source_column(engine)
    ensure_gallery_photo_size_column(engine)


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
        acquisition = getattr(services, "acquisition", None)
        interrupted_runs = acquisition.recover_runs(db) if acquisition is not None else 0
        import_recovery = acquisition.recover_imports(db) if acquisition is not None else {"recovered": 0, "failed": 0}
        reconciled_items = acquisition.reconcile_run_metrics(db) if acquisition is not None else 0
        expired_exports = acquisition.cleanup_expired_exports(db) if acquisition is not None else 0
        if interrupted_runs or expired_exports or import_recovery["recovered"] or import_recovery["failed"] or reconciled_items:
            logger.warning(
                "应用启动：已处理采集状态 interrupted=%d import_recovered=%d import_failed=%d "
                "metrics_reconciled=%d expired_exports=%d",
                interrupted_runs,
                import_recovery["recovered"],
                import_recovery["failed"],
                reconciled_items,
                expired_exports,
            )
        videos_missing_sha = db.scalars(select(VideoItem).where(VideoItem.sha256.is_(None))).all()
        if videos_missing_sha:
            backfilled_count = 0
            for video in videos_missing_sha:
                try:
                    video.sha256 = services.videos.hash_object(video.object_key)
                    backfilled_count += 1
                except Exception:
                    logger.warning("应用启动：计算视频 SHA256 失败 video_id=%s object_key=%s", video.id, video.object_key)
            if backfilled_count > 0:
                db.commit()
                logger.info("应用启动：已补齐存量视频 SHA256 count=%d", backfilled_count)
    finally:
        db.close()

    logger.info(
        "应用启动完成：minio_bucket=%s qdrant_sample_collection=%s",
        settings.minio_bucket,
        settings.qdrant_known_collection,
    )
