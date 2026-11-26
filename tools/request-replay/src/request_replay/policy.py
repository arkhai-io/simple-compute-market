"""How long a reservation lives, from what the request states and the clock.

Every instant here is an integer number of seconds on the caller's time source.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Resolution(str, Enum):
    """How an exact retry of a request already seen is resolved."""

    #: The handler runs again; no response is recorded. A held lease is refused as
    #: in progress, and an ended one is reclaimed by one retry.
    RERUN = "rerun"
    #: The first attempt's response is recorded and answers every exact retry. The
    #: request is never dispatched twice: a retry finding no response after the
    #: lease ended is told the outcome is unknown.
    RECORDED = "recorded"


@dataclass(frozen=True)
class Policy:
    """The clock bounds a replay guard applies.

    ``skew_seconds`` is the tolerance the caller's signature check grants a
    request's signing time, either way. A captured request signed at T stays
    acceptable until T + skew, and T may be as late as its arrival + skew, so a
    reservation refusing its replay must outlive its origin by twice the skew.
    ``retention_seconds`` is how long a recorded response answers an exact retry,
    counted from the request's origin. ``lease_seconds`` is how long an attempt
    holds its request before a retry may judge it ended; a running attempt renews
    it.
    """

    skew_seconds: int
    retention_seconds: int
    lease_seconds: int

    def __post_init__(self) -> None:
        for name in ("skew_seconds", "retention_seconds", "lease_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    def bound(self, resolution: Resolution, origin: int) -> int:
        """The last instant the request alone needs its row.

        A re-run request needs its row only to refuse a replay; a recorded one
        also to answer a retry for the retention, which a retry signed at the
        retention's end may reach a skew later.
        """

        if resolution is Resolution.RERUN:
            return origin + 2 * self.skew_seconds
        return origin + max(self.retention_seconds + self.skew_seconds, 2 * self.skew_seconds)

    def expires_at(self, resolution: Resolution, origin: int, lease_until: int) -> int:
        """A row's expiry: its bound, or its lease's end if later.

        The lease floor keeps the row of an attempt still running, whose bound
        may already have passed when its origin is old: without it a sweep could
        delete the row mid-attempt, and a concurrent retry finding no row would
        dispatch a second time.
        """

        return max(self.bound(resolution, origin), lease_until)

    def admits_first_use(self, origin: int, now: int) -> bool:
        """Whether a recorded request with this origin may be a first use.

        A first use is signed now, so its origin is within the skew; an older
        origin is a retry, which only a row can answer.
        """

        return origin >= now - self.skew_seconds

    def retention_passed(self, origin: int, now: int) -> bool:
        """Whether a recorded response for this origin is past its retention."""

        return origin < now - self.retention_seconds
