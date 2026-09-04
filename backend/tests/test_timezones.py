from datetime import datetime, timezone

from app.core.timezones import as_shanghai_naive, shanghai_isoformat
from app.schemas.base import BaseModel, ShanghaiDateTime


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
