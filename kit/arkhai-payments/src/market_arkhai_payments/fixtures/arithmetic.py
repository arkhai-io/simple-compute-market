"""UTC arithmetic for deterministic payments authority fixtures."""

from __future__ import annotations

import calendar
from collections.abc import Mapping
from datetime import datetime, timezone, timedelta
import re
from typing import Any

_DURATION = re.compile(
    r"^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?"
    r"(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$"
)


def add_duration(at: int, duration: str, count: int = 1) -> int:
    """UTC duration addition, multiplying once before calendar-day clamping."""

    match = _DURATION.fullmatch(duration)
    if match is None or not any(match.groups()) or count < 0:
        raise ValueError("unsupported payments duration")
    years, months, weeks, days, hours, minutes, seconds = (
        int(component or 0) * count for component in match.groups()
    )
    instant = datetime.fromtimestamp(at, timezone.utc)
    month = instant.year * 12 + instant.month - 1 + years * 12 + months
    year, month0 = divmod(month, 12)
    instant = instant.replace(
        year=year, month=month0 + 1,
        day=min(instant.day, calendar.monthrange(year, month0 + 1)[1]),
    )
    return int((instant + timedelta(
        weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds
    )).timestamp())


def periods_through(start: int, period: str, at: int, *, partial: bool = True) -> int:
    """Count periods with logarithmic boundary probes, including a cut if requested."""

    if add_duration(start, period) <= start:
        raise ValueError("rate period must advance time")
    if at <= start:
        return 0
    low, high = 0, 1
    while add_duration(start, period, high) < at:
        low, high = high, high * 2
    while high - low > 1:
        middle = (low + high) // 2
        if add_duration(start, period, middle) < at:
            low = middle
        else:
            high = middle
    return high if partial or add_duration(start, period, high) == at else high - 1


def initial_periods(part: Mapping[str, Any], approved_at: int) -> int:
    target = max(
        approved_at + 60,
        add_duration(approved_at, part["period"]),
        add_duration(approved_at, part["reserveAhead"]),
    )
    if "end" in part:
        target = min(target, max(approved_at, part["end"]["at"]))
    return periods_through(approved_at, part["period"], target)
