from __future__ import annotations

from datetime import datetime, timedelta, timezone


SHANGHAI_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def shanghai_now() -> datetime:
    """Return the current Shanghai wall-clock time for naive SQLite columns."""
    return datetime.now(SHANGHAI_TZ).replace(tzinfo=None)


def as_shanghai_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(SHANGHAI_TZ).replace(tzinfo=None)


def shanghai_isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=SHANGHAI_TZ)
    else:
        value = value.astimezone(SHANGHAI_TZ)
    return value.isoformat()
