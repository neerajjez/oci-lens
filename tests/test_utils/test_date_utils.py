"""Tests for src/utils/date_utils.py."""
from __future__ import annotations

from datetime import datetime, timezone

from src.utils.date_utils import collection_window, timestamp_slug, to_rfc3339, utcnow


def test_utcnow_returns_utc_datetime():
    dt = utcnow()
    assert isinstance(dt, datetime)
    assert dt.tzinfo == timezone.utc


def test_collection_window_returns_tuple():
    start, end = collection_window(7)
    assert isinstance(start, datetime)
    assert isinstance(end, datetime)


def test_collection_window_correct_span():
    start, end = collection_window(7)
    delta = end - start
    assert delta.days == 7


def test_collection_window_end_is_midnight():
    _, end = collection_window(7)
    assert end.hour == 0
    assert end.minute == 0
    assert end.second == 0


def test_to_rfc3339_with_tz():
    dt = datetime(2024, 5, 1, 12, 30, 0, tzinfo=timezone.utc)
    result = to_rfc3339(dt)
    assert result == "2024-05-01T12:30:00Z"


def test_to_rfc3339_naive_assumes_utc():
    dt = datetime(2024, 5, 1, 12, 30, 0)
    result = to_rfc3339(dt)
    assert result == "2024-05-01T12:30:00Z"


def test_timestamp_slug_format():
    slug = timestamp_slug()
    assert len(slug) == 15
    assert slug[8] == "_"
    assert slug.replace("_", "").isdigit()
