from collections.abc import Generator

import logging

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.config import get_settings


settings = get_settings()
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
logger = logging.getLogger(__name__)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
    cursor = getattr(dbapi_connection, "cursor", None)
    if cursor is None:
        return
    handle = cursor()
    handle.execute("PRAGMA foreign_keys=ON")
    handle.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()


TENANT_TABLES = (
    "persons",
    "sample_photos",
    "gallery_photos",
    "face_records",
    "tags",
    "video_items",
    "video_category_tags",
    "video_people",
    "video_upload_sessions",
    "tasks",
    "upload_history",
)


WORKSPACE_MEMBER_PERMISSION_COLUMNS = (
    "can_add_gallery",
    "can_delete_gallery",
    "can_edit_gallery",
    "can_add_samples",
    "can_delete_samples",
    "can_edit_samples",
    "can_add_videos",
    "can_delete_videos",
    "can_edit_videos",
)


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _tag_index_columns(connection, index_name: str) -> list[str]:
    rows = connection.exec_driver_sql(f"PRAGMA index_info({_quote_identifier(index_name)})").mappings().all()
    return [str(row["name"]) for row in rows]


def _rebuild_tags_table_for_workspace_unique() -> None:
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.exec_driver_sql("PRAGMA legacy_alter_table=ON")
        connection.commit()
        transaction = connection.begin()
        try:
            connection.execute(text("ALTER TABLE tags RENAME TO tags_old_global_unique"))
            connection.execute(text("""
                CREATE TABLE tags (
                    id INTEGER NOT NULL PRIMARY KEY,
                    workspace_id INTEGER,
                    name VARCHAR(128) NOT NULL,
                    is_system BOOLEAN DEFAULT 0 NOT NULL,
                    created_at DATETIME NOT NULL,
                    CONSTRAINT uq_tags_workspace_name UNIQUE (workspace_id, name),
                    FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
                )
            """))
            connection.execute(text("""
                INSERT INTO tags (id, workspace_id, name, is_system, created_at)
                SELECT id, workspace_id, name, COALESCE(is_system, 0), created_at
                FROM tags_old_global_unique
            """))
            connection.execute(text("DROP TABLE tags_old_global_unique"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tags_workspace_id ON tags(workspace_id)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tags_name ON tags(name)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tags_is_system ON tags(is_system)"))
            transaction.commit()
        except Exception:
            transaction.rollback()
            raise
        finally:
            connection.exec_driver_sql("PRAGMA legacy_alter_table=OFF")
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


def _ensure_tags_workspace_unique_constraint() -> None:
    inspector = inspect(engine)
    if "tags" not in inspector.get_table_names():
        return

    needs_rebuild = False
    with engine.begin() as connection:
        indexes = connection.exec_driver_sql("PRAGMA index_list(tags)").mappings().all()
        for index in indexes:
            index_name = str(index["name"])
            is_unique = bool(index["unique"])
            if not is_unique or _tag_index_columns(connection, index_name) != ["name"]:
                continue
            if index_name.startswith("sqlite_autoindex"):
                needs_rebuild = True
                continue
            connection.execute(text(f"DROP INDEX {_quote_identifier(index_name)}"))
        if not needs_rebuild:
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_tags_workspace_name ON tags(workspace_id, name)"))

    if needs_rebuild:
        _rebuild_tags_table_for_workspace_unique()


def _ensure_workspace_columns(inspector) -> None:
    table_names = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table_name in TENANT_TABLES:
            if table_name not in table_names:
                continue
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            if "workspace_id" not in columns:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN workspace_id INTEGER"))
            connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table_name}_workspace_id ON {table_name}(workspace_id)"))


def ensure_legacy_columns() -> None:
    inspector = inspect(engine)
    _ensure_workspace_columns(inspector)
    table_names = set(inspector.get_table_names())
    if "workspaces" in table_names:
        columns = {column["name"] for column in inspector.get_columns("workspaces")}
        statements: list[str] = []
        if "kind" not in columns:
            statements.append("ALTER TABLE workspaces ADD COLUMN kind VARCHAR(32) DEFAULT 'private' NOT NULL")
        if "owner_user_id" not in columns:
            statements.append("ALTER TABLE workspaces ADD COLUMN owner_user_id INTEGER")
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_workspaces_kind ON workspaces(kind)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_workspaces_owner_user_id ON workspaces(owner_user_id)"))
            connection.execute(text("""
                UPDATE workspaces
                SET owner_user_id = (
                    SELECT wm.user_id FROM workspace_members wm
                    WHERE wm.workspace_id = workspaces.id AND wm.role = 'owner'
                    ORDER BY wm.id LIMIT 1
                )
                WHERE owner_user_id IS NULL
            """))
            connection.execute(text("""
                UPDATE workspaces
                SET kind = CASE
                    WHEN (SELECT COUNT(*) FROM workspace_members wm WHERE wm.workspace_id = workspaces.id) > 1
                    THEN 'shared'
                    ELSE 'private'
                END
                WHERE kind IS NULL OR kind = ''
            """))
            connection.execute(text("""
                UPDATE workspaces
                SET kind = 'shared'
                WHERE (SELECT COUNT(*) FROM workspace_members wm WHERE wm.workspace_id = workspaces.id) > 1
            """))
    if "workspace_members" in table_names:
        columns = {column["name"] for column in inspector.get_columns("workspace_members")}
        statements = []
        for column_name in WORKSPACE_MEMBER_PERMISSION_COLUMNS:
            if column_name not in columns:
                statements.append(f"ALTER TABLE workspace_members ADD COLUMN {column_name} BOOLEAN DEFAULT 0 NOT NULL")
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
    if "persons" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("persons")}
        statements: list[str] = []
        if "display_name" not in columns:
            statements.append("ALTER TABLE persons ADD COLUMN display_name VARCHAR(256) DEFAULT '' NOT NULL")
        if "is_unknown" not in columns:
            statements.append("ALTER TABLE persons ADD COLUMN is_unknown BOOLEAN DEFAULT 0 NOT NULL")
        if "unknown_serial" not in columns:
            statements.append("ALTER TABLE persons ADD COLUMN unknown_serial INTEGER")
        if "updated_at" not in columns:
            statements.append("ALTER TABLE persons ADD COLUMN updated_at DATETIME")
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
            if "display_name" not in columns:
                connection.execute(text("UPDATE persons SET display_name = name WHERE display_name = ''"))
            if "updated_at" not in columns:
                connection.execute(text("UPDATE persons SET updated_at = created_at WHERE updated_at IS NULL"))
    if "gallery_photo_tags" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("gallery_photo_tags")}
        if "source" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE gallery_photo_tags ADD COLUMN source VARCHAR(32) DEFAULT 'manual' NOT NULL"))
    if "gallery_photos" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("gallery_photos")}
        statements: list[str] = []
        if "is_rich_text" not in columns:
            statements.append("ALTER TABLE gallery_photos ADD COLUMN is_rich_text BOOLEAN DEFAULT 0 NOT NULL")
        if "rich_text" not in columns:
            statements.append("ALTER TABLE gallery_photos ADD COLUMN rich_text TEXT")
        if "ocr_status" not in columns:
            statements.append("ALTER TABLE gallery_photos ADD COLUMN ocr_status VARCHAR(32)")
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
    if "tags" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("tags")}
        if "is_system" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE tags ADD COLUMN is_system BOOLEAN DEFAULT 0 NOT NULL"))
        _ensure_tags_workspace_unique_constraint()
    if "video_items" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("video_items")}
        statements: list[str] = []
        if "faststart_applied" not in columns:
            statements.append("ALTER TABLE video_items ADD COLUMN faststart_applied BOOLEAN DEFAULT 0 NOT NULL")
        if "processed_at" not in columns:
            statements.append("ALTER TABLE video_items ADD COLUMN processed_at DATETIME")
        if "processing_error" not in columns:
            statements.append("ALTER TABLE video_items ADD COLUMN processing_error TEXT")
        if "cover_object_key" not in columns:
            statements.append("ALTER TABLE video_items ADD COLUMN cover_object_key VARCHAR(512)")
        if "cover_content_type" not in columns:
            statements.append("ALTER TABLE video_items ADD COLUMN cover_content_type VARCHAR(128)")
        if "duration_seconds" not in columns:
            statements.append("ALTER TABLE video_items ADD COLUMN duration_seconds FLOAT")
        if "width" not in columns:
            statements.append("ALTER TABLE video_items ADD COLUMN width INTEGER")
        if "height" not in columns:
            statements.append("ALTER TABLE video_items ADD COLUMN height INTEGER")
        if "original_video_codec" not in columns:
            statements.append("ALTER TABLE video_items ADD COLUMN original_video_codec VARCHAR(64)")
        if "original_audio_codec" not in columns:
            statements.append("ALTER TABLE video_items ADD COLUMN original_audio_codec VARCHAR(64)")
        if "video_codec" not in columns:
            statements.append("ALTER TABLE video_items ADD COLUMN video_codec VARCHAR(64)")
        if "audio_codec" not in columns:
            statements.append("ALTER TABLE video_items ADD COLUMN audio_codec VARCHAR(64)")
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
        # Migration: old video imports used global uniqueness. New imports are unique per workspace.
        index_names = {idx["name"] for idx in inspector.get_indexes("video_items")}
        with engine.begin() as connection:
            if "ix_video_items_sha256" in index_names:
                connection.execute(text("DROP INDEX ix_video_items_sha256"))
            if "uq_video_items_filename_size" in index_names:
                connection.execute(text("DROP INDEX uq_video_items_filename_size"))
            duplicates = connection.execute(text("""
                SELECT workspace_id, filename, size_bytes, COUNT(*) AS duplicate_count
                FROM video_items
                GROUP BY workspace_id, filename, size_bytes
                HAVING COUNT(*) > 1
            """)).mappings().all()
            if duplicates:
                logger.warning(
                    "Skip creating video workspace uniqueness index because duplicate rows exist count=%s",
                    len(duplicates),
                )
            else:
                connection.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_video_items_workspace_filename_size "
                    "ON video_items(workspace_id, filename, size_bytes)"
                ))
    if "video_subtitle_tracks" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("video_subtitle_tracks")}
        statements: list[str] = []
        if "task_id" not in columns:
            statements.append("ALTER TABLE video_subtitle_tracks ADD COLUMN task_id VARCHAR(64)")
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
