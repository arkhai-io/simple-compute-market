"""One source of the time of the world per process: wall time, or injected time.

A process's composition root installs its source from its configuration —
`install(source_for(value, setting="time.source"))` — and every read of the time
of the world goes through `now()`. Injected time holds the instant last set and
moves only forward; a time file carries an injected instant to a process with no
route of its own; `TimeRouteService` answers a service's setting route and status
section. The component depends on the standard library alone.
"""

from injected_time.routes import TimeRouteError, TimeRouteService
from injected_time.source import (
    INJECTED,
    SOURCES,
    WALL,
    InjectedTime,
    InvalidTimeSource,
    SourceName,
    TimeMovesForward,
    TimeSource,
    WallTime,
    install,
    installed,
    now,
    source_for,
)
from injected_time.time_file import TimeFile, TimeFileError
from injected_time.value import (
    MAX_INSTANT,
    MIN_INSTANT,
    InvalidTime,
    check_instant,
    parse_time,
    read_time,
    time_document,
)

__all__ = [
    "INJECTED",
    "MAX_INSTANT",
    "MIN_INSTANT",
    "SOURCES",
    "WALL",
    "InjectedTime",
    "InvalidTime",
    "InvalidTimeSource",
    "SourceName",
    "TimeFile",
    "TimeFileError",
    "TimeMovesForward",
    "TimeRouteError",
    "TimeRouteService",
    "TimeSource",
    "WallTime",
    "check_instant",
    "install",
    "installed",
    "now",
    "parse_time",
    "read_time",
    "source_for",
    "time_document",
]
