"""The Agreement window every commit and recovery uses.

The window comes from the deal's servicing delivery record and nothing else:
its Agreement start and term end, in whole seconds. There is no current-time
start and no default duration, because a guessed window commits capacity the
buyer never accepted and moves the end the deadline and billing are anchored
to. Late settlement shortens service and never moves the end.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from market_deal_servicing import DeliveryRecord


class TimingInvalid(ValueError):
    """The deal's accepted timing is missing or conflicts with what was recorded."""


@dataclass(frozen=True)
class AgreementWindow:
    """``[start, end)`` in Unix seconds, as the Agreement accepted it."""

    start: int
    end: int

    @property
    def duration_seconds(self) -> int:
        return self.end - self.start

    @property
    def start_utc(self) -> str:
        return utc_text(self.start)

    @property
    def end_utc(self) -> str:
        return utc_text(self.end)


def utc_text(at: int) -> str:
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


def utc_seconds(value: object) -> int:
    """Whole seconds of a site timestamp; an unreadable one is a ``TimingInvalid``."""
    if not isinstance(value, str) or not value:
        raise TimingInvalid(f"timestamp {value!r} is not an ISO-8601 instant")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TimingInvalid(f"timestamp {value!r} is not an ISO-8601 instant") from exc
    if parsed.tzinfo is None:
        raise TimingInvalid(f"timestamp {value!r} names no offset")
    return int(parsed.timestamp())


def agreement_window(record: DeliveryRecord) -> AgreementWindow:
    """The window the deal's servicing record holds, refusing an empty one.

    A record whose term ends where it starts sells nothing and cannot be
    committed; the record itself already refuses an end before its start.
    """
    if record.term_end <= record.start_at:
        raise TimingInvalid(
            f"accepted term [{record.start_at}, {record.term_end}) is empty"
        )
    return AgreementWindow(start=record.start_at, end=record.term_end)


def require_committed_window(
    window: AgreementWindow, committed: Mapping[str, Any]
) -> int:
    """Check a commit's answer against the Agreement window; the lease's end.

    The site keeps the window its first commit recorded, and only a truncation
    moves it, always earlier. So the committed start is the Agreement's, and the
    committed end is the Agreement's or earlier; anything else is a lease
    committed under other timing, which this deal cannot adopt.
    """
    start = utc_seconds(committed.get("lease_start_utc"))
    end = utc_seconds(committed.get("lease_end_utc"))
    if start != window.start:
        raise TimingInvalid(
            f"the site committed a lease starting at {start}, not the Agreement's {window.start}"
        )
    if end > window.end:
        raise TimingInvalid(
            f"the site committed a lease ending at {end}, outside the Agreement's {window.end}"
        )
    return end
