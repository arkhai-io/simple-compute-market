"""The buyer's time source: wall time, or injected time read from a lane-time file.

The buyer is a command started afresh for each step, with no route to set its
time, so under injected time it reads a lane-time file its configuration names,
``{"now": <Unix seconds>}``, on every read: a running command sees an instant
written to the file at its next read. A file it cannot read, or one holding an
invalid value, fails the read naming the file, and nothing falls back to wall
time. The source is installed once, before any command body runs, from the
``[time]`` table of the buyer configuration ``market`` loads — the file
``market --config`` names, or the XDG one:

- ``source``: ``"wall"``, the default, or ``"injected"``; any other value
  refuses the start, naming the setting and the value;
- ``file``: the lane-time file, required under injected time and read once at
  the start, so a missing or invalid file refuses the start naming it.

A command's own ``--config`` names a domain's configuration and does not choose
the process's time. A buyer whose configuration states no source keeps the
process's wall time. Injected time is announced, and warned of beside any table
stating ``livemode = true``, a payments section configured for live receipts,
which a role on a test clock should never be; nothing refuses it.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import injected_time
from injected_time import WALL, TimeFile, TimeSource, source_for

TIME_SOURCE_SETTING = "[time] source"
TIME_FILE_SETTING = "[time] file"


class TimeConfigurationError(ValueError):
    """The ``[time]`` table cannot name a source the buyer can run on."""


def configured_time_source(config: Mapping[str, Any]) -> TimeSource | None:
    """The source the configuration's ``[time]`` table names, or None if it names none.

    Raises ``InvalidTimeSource`` for a source other than ``"wall"`` or
    ``"injected"``, ``TimeConfigurationError`` for an injected source with no
    ``file``, and ``TimeFileError`` for a file that cannot be read or holds no
    valid instant.
    """
    section = config.get("time")
    if section is None:
        return None
    if not isinstance(section, Mapping):
        raise TimeConfigurationError("[time] is a table of source and file")
    value = section.get("source")
    if value is None:
        return None
    source = source_for(value, setting=TIME_SOURCE_SETTING)
    if source.name == WALL:
        return source
    path = section.get("file")
    if not isinstance(path, str) or not path:
        raise TimeConfigurationError(
            f'{TIME_SOURCE_SETTING} is "injected" and {TIME_FILE_SETTING} names no '
            "lane-time file")
    time_file = TimeFile(Path(path).expanduser())
    # Read once now, so a missing or invalid file refuses the start rather than
    # failing whatever command first reads the time.
    time_file.now()
    return time_file


def live_sections(config: Mapping[str, Any]) -> list[str]:
    """Every table stating ``livemode = true``, as ``[dotted.name]``, in file order.

    Read wherever the table sits — ``[Settlement.arkhai_payments]`` for the
    compute buyers, ``[bare_metal.arkhai_payments]`` for bare metal — since core
    names no domain's layout and no settlement mechanism.
    """
    return [f"[{'.'.join(path)}]" for path in _live_paths(config, ())]


def _live_paths(table: Mapping[str, Any], path: tuple[str, ...]) -> Iterator[tuple[str, ...]]:
    if path and table.get("livemode") is True:
        yield path
    for key, value in table.items():
        if isinstance(value, Mapping):
            yield from _live_paths(value, (*path, str(key)))


def install_configured_time_source(config: Mapping[str, Any]) -> TimeSource | None:
    """Install the configured source; None, and nothing installed, if none is stated."""
    source = configured_time_source(config)
    if source is not None:
        injected_time.install(source)
    return source


def announcement(source: TimeSource | None) -> str | None:
    """The line announcing an injected source at the start, or None for any other."""
    if not isinstance(source, TimeFile):
        return None
    return f"{TIME_SOURCE_SETTING} is injected: time is read from {source.path}, now {source.now()}"


def live_warnings(source: TimeSource | None, config: Mapping[str, Any]) -> list[str]:
    """A warning per live table, when the source is injected; none otherwise."""
    if not isinstance(source, TimeFile):
        return []
    return [f"{TIME_SOURCE_SETTING} is injected while {section} states livemode = true"
            for section in live_sections(config)]


__all__ = [
    "TIME_FILE_SETTING",
    "TIME_SOURCE_SETTING",
    "TimeConfigurationError",
    "announcement",
    "configured_time_source",
    "install_configured_time_source",
    "live_sections",
    "live_warnings",
]
