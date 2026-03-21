from __future__ import annotations

from datetime import timedelta, timezone

from src.utils.time import utcnow


def test_utcnow_returns_timezone_aware_utc_datetime() -> None:
    now = utcnow()

    assert now.tzinfo is timezone.utc
    assert now.utcoffset() == timedelta(0)
