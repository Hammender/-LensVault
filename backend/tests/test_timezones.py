from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from app.core.timezones import as_shanghai_naive, shanghai_isoformat
from app.schemas.base import BaseModel, ShanghaiDateTime
from app.services.timezone_migration import migrate_system_timestamps


class TimestampPayload(BaseModel):
    created_at: ShanghaiDateTime
    taken_at: ShanghaiDateTime


def test_shanghai_time_helpers_and_schema_serialization() -> None:
    utc_value = datetime(2026, 7, 29, 7, 30, tzinfo=timezone.utc)
    assert as_shanghai_naive(utc_value) == datetime(2026, 7, 29, 15, 30)
    assert shanghai_isoformat(utc_value) == "2026-07-29T15:30:00+08:00"

    payload = TimestampPayload(
        created_at=datetime(2026, 7, 29, 15, 30),
        taken_at=datetime(2020, 1, 2, 9, 15),
    ).model_dump(mode="json")
    assert payload["created_at"] == "2026-07-29T15:30:00+08:00"
    assert payload["taken_at"] == "2020-01-02T09:15:00+08:00"


def test_timestamp_migration_backs_up_is_idempotent_and_preserves_exif(tmp_path) -> None:
    database_path = tmp_path / "timezone.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE gallery_photos ("
                "id INTEGER PRIMARY KEY, created_at DATETIME, updated_at DATETIME, taken_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO gallery_photos (id, created_at, updated_at, taken_at) VALUES "
                "(1, '2026-07-29 07:30:00.123456', '2026-12-31 20:30:00', '2020-01-02 09:15:00')"
            )
        )

    backup_path, updated_rows = migrate_system_timestamps(engine)
    assert backup_path is not None and backup_path.is_file()
    assert updated_rows == 2
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT created_at, updated_at, taken_at FROM gallery_photos WHERE id=1")
        ).one()
    assert row.created_at == "2026-07-29 15:30:00.123456"
    assert row.updated_at == "2027-01-01 04:30:00"
    assert row.taken_at == "2020-01-02 09:15:00"

    second_backup, second_updated_rows = migrate_system_timestamps(engine)
    assert second_backup is None
    assert second_updated_rows == 0
