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

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
