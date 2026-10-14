from sqlalchemy import text

from app.db import engine


def test_sqlite_connections_wait_for_writers_and_use_wal() -> None:
    assert engine.dialect.name == "sqlite"
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar_one().lower() == "wal"
        assert int(connection.execute(text("PRAGMA busy_timeout")).scalar_one()) == 30_000
        assert int(connection.execute(text("PRAGMA temp_store")).scalar_one()) == 2
        assert int(connection.execute(text("PRAGMA wal_autocheckpoint")).scalar_one()) == 1000
