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


def ensure_legacy_columns() -> None:
    inspector = inspect(engine)
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
        # Migration: drop sha256 unique index and add (filename, size_bytes) unique index
        index_names = {idx["name"] for idx in inspector.get_indexes("video_items")}
        with engine.begin() as connection:
            if "ix_video_items_sha256" in index_names:
                connection.execute(text("DROP INDEX ix_video_items_sha256"))
            # Remove duplicate (filename, size_bytes) rows, keep newest
            connection.execute(text("""
                DELETE FROM video_items WHERE id NOT IN (
                    SELECT MAX(id) FROM video_items GROUP BY filename, size_bytes
                )
            """))
            if "uq_video_items_filename_size" not in index_names:
                connection.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_video_items_filename_size ON video_items(filename, size_bytes)"
                ))

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
