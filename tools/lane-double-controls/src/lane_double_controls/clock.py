"""A lane double's perceived clock: wall time plus an offset only a control moves.

Each double evaluates due state lazily at each read against this clock, so moving
it forward makes a notice stop, funding exhaustion or a matured hold visible at
the next read, with nothing running in the background. The offset only grows,
except for a reset back to zero, which bounds an advance to the run of work that
made it. A record a double made while its clock was ahead stays readable after a
reset: the payments engine evaluates a transaction at the later of its clock and
the transaction's own instant, and the mediation double keeps every record's time
as it signed it.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

WallClock = Callable[[], int]


def wall_clock() -> int:
    return int(time.time())


class PerceivedClock:
    """Unix seconds: ``wall()`` plus a nonnegative offset."""

    def __init__(self, wall: WallClock = wall_clock) -> None:
        self._wall = wall
        self._offset = 0
        self._lock = threading.Lock()

    def __call__(self) -> int:
        return self._wall() + self._offset

    @property
    def offset(self) -> int:
        return self._offset

    def advance(self, seconds: int) -> None:
        """Move the clock forward by ``seconds``, which must be positive."""

        if seconds <= 0:
            raise ValueError("the perceived clock only moves forward")
        with self._lock:
            self._offset += seconds

    def reset(self) -> None:
        """Return the clock to wall time."""

        with self._lock:
            self._offset = 0


__all__ = ["PerceivedClock", "WallClock", "wall_clock"]
