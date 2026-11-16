"""The process's one source of the time of the world.

A process reads every instant it stores, signs, sends to another party, or
compares with an instant another party knows from the source its composition
root installs, through `now()`, and from no other read. Until a root installs
another, the source is wall time.

An injected source returns exactly the instant last set, until it is set again,
so time moves only when whoever holds the source moves it: two processes set to
one instant agree exactly, and nothing elapses unseen between sets. It starts at
the wall instant it was made, and moves only forward.

A duration of the process's own activity — a timeout, a backoff, an interval — is
not the time of the world: it is measured on the monotonic clock, which neither
stops while injected time is held nor jumps when it is set.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Final, Literal, Protocol

from injected_time.value import check_instant

SourceName = Literal["wall", "injected"]

WALL: Final = "wall"
INJECTED: Final = "injected"
SOURCES: Final[tuple[SourceName, ...]] = (WALL, INJECTED)


class TimeSource(Protocol):
    """Something a process reads the time of the world from."""

    @property
    def name(self) -> SourceName:
        """`wall`, or `injected` for a source whose instant is set."""
        ...

    def now(self) -> int:
        """The current instant, in Unix seconds."""
        ...


class TimeMovesForward(Exception):
    """A set named an instant earlier than the source's own; nothing changed.

    `code` is `time_moves_forward`.
    """

    code = "time_moves_forward"

    def __init__(self, current: int, requested: int) -> None:
        super().__init__(
            f"time moves only forward: the source is at {current}, and {requested} is earlier")
        self.current = current
        self.requested = requested


class InvalidTimeSource(ValueError):
    """A configured source value is neither `wall` nor `injected`."""

    def __init__(self, setting: str, value: object) -> None:
        super().__init__(f'{setting} is "wall" or "injected", not {value!r}')
        self.setting = setting
        self.value = value


class WallTime:
    """The wall clock, in whole Unix seconds.

    `wall` reads the clock in seconds, `time.time` unless a test gives its own.
    """

    name: SourceName = WALL

    def __init__(self, wall: Callable[[], float] = time.time) -> None:
        self._wall = wall

    def now(self) -> int:
        return int(self._wall())


class InjectedTime:
    """An instant that holds until it is set again, and is set only forward.

    With no `start`, it starts at the wall instant `wall` reads when it is made,
    and reads the wall clock never again.
    """

    name: SourceName = INJECTED

    def __init__(self, start: int | None = None,
                 wall: Callable[[], float] = time.time) -> None:
        self._now = check_instant(int(wall()) if start is None else start)
        # Two sets racing must not both pass the forward check against the same
        # instant and leave the earlier one in place.
        self._lock = threading.Lock()

    def now(self) -> int:
        return self._now

    def set(self, instant: int) -> int:
        """Move to `instant` and return it.

        Refuses an invalid instant (`InvalidTime`) and an earlier one
        (`TimeMovesForward`), changing nothing; setting the current instant
        again succeeds and changes nothing.
        """
        check_instant(instant)
        with self._lock:
            if instant < self._now:
                raise TimeMovesForward(self._now, instant)
            self._now = instant
        return instant


def source_for(value: object, *, setting: str) -> WallTime | InjectedTime:
    """The source a configured value names: `wall` or `injected`.

    Any other value is refused naming `setting` and the value, so a misspelled
    source never runs a process on a clock its operator did not choose.
    """
    if value == WALL:
        return WallTime()
    if value == INJECTED:
        return InjectedTime()
    raise InvalidTimeSource(setting, value)


_installed: TimeSource = WallTime()


def install(source: TimeSource) -> TimeSource:
    """Make `source` the process's source, and return it."""
    global _installed
    _installed = source
    return source


def installed() -> TimeSource:
    """The process's source."""
    return _installed


def now() -> int:
    """The current instant of the process's source, in Unix seconds."""
    return _installed.now()


def now_datetime() -> datetime:
    """The current instant of the process's source, as an aware UTC `datetime`.

    Whole seconds, as `now()` is: its microsecond is always 0.
    """
    return datetime.fromtimestamp(_installed.now(), timezone.utc)
