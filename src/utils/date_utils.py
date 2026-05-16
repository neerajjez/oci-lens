from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def collection_window(period_days: int) -> tuple[datetime, datetime]:
    end = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=period_days)
    return start, end


def to_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def timestamp_slug() -> str:
    return utcnow().strftime("%Y%m%d_%H%M%S")
