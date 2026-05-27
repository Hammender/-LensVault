from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.config import get_settings


settings = get_settings()
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})


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
            # Remove duplicate (filename, size_bytes) rows, keep newest
            connection.execute(text("""
                DELETE FROM video_items WHERE id NOT IN (
                    SELECT MAX(id) FROM video_items GROUP BY workspace_id, filename, size_bytes
                )
            """))
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
