from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path
import tempfile

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker


_TEST_RUNTIME_PATH = Path(tempfile.mkdtemp(prefix="pictureshow-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_RUNTIME_PATH / 'app.db').as_posix()}"
os.environ["DATA_DIR"] = str(_TEST_RUNTIME_PATH)

from app.db import Base


@pytest.fixture
def db_session(tmp_path) -> Iterator[Session]:
    database_path = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
