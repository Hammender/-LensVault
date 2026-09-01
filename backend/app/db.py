from collections.abc import Generator

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.config import get_settings


settings = get_settings()
database_url = make_url(settings.database_url)
is_sqlite = database_url.get_backend_name() == "sqlite"
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30} if is_sqlite else {},
)


@event.listens_for(engine, "connect")
def _configure_sqlite_connection(dbapi_connection: object, _: object) -> None:
    if not is_sqlite:
        return
    cursor = getattr(dbapi_connection, "cursor", None)
    if cursor is None:
        return
    handle = cursor()
    handle.execute("PRAGMA foreign_keys=ON")
    # SQLite only permits one writer. Waiting for a short transaction avoids
    # immediately failing concurrent API/background-task writes.
    handle.execute("PRAGMA busy_timeout=30000")
    handle.execute("PRAGMA synchronous=NORMAL")
    handle.close()


@event.listens_for(engine, "first_connect")
def _enable_sqlite_wal(dbapi_connection: object, _: object) -> None:
    """Persist WAL once instead of asking every request connection to change it."""
    if not is_sqlite:
        return
    cursor = getattr(dbapi_connection, "cursor", None)
    if cursor is None:
        return
    handle = cursor()
    handle.execute("PRAGMA journal_mode=WAL")
    handle.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()


def get_db(request: Request) -> Generator[Session, None, None]:
    """Yield a session from the application that is serving the request."""
    session_factory = request.app.state.session_factory
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
