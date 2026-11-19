"""A time file: an injected instant one process writes and another reads.

A process with no route of its own to set its time, such as a command-line tool
started afresh for each step, reads its injected time from a file holding the
time document `{"now": <instant>}`, which whoever moves time rewrites. One
definition of the file serves both sides.

The reader reads the file on every call, so a running process sees a later
instant at its next read, and it never falls back to wall time: a file it cannot
read, or one holding an invalid value, raises, naming the file. The writer
replaces the file whole, by renaming a complete file written beside it, so a
reader sees either the previous document or the new one, never part of one.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from injected_time.source import INJECTED, SourceName
from injected_time.value import InvalidTime, parse_time, time_document


class TimeFileError(Exception):
    """A time file could not be read, or holds no valid instant."""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"time file {path}: {reason}")
        self.path = path


class TimeFile:
    """The time file at `path`; as a source, its instant is the file's."""

    name: SourceName = INJECTED

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def now(self) -> int:
        """The instant the file holds now."""
        try:
            raw = self.path.read_bytes()
        except OSError as error:
            raise TimeFileError(self.path, f"cannot be read: {error.strerror or error}") from error
        try:
            return parse_time(raw)
        except InvalidTime as error:
            raise TimeFileError(self.path, f"holds no valid instant: {error}") from error

    def write(self, instant: int) -> int:
        """Replace the file's document with one carrying `instant`, and return it.

        An invalid instant raises `InvalidTime` and leaves the file as it was.
        """
        text = json.dumps(time_document(instant))
        # The temporary file sits in the file's own directory, so the rename that
        # replaces the file never crosses a filesystem and is atomic.
        descriptor, temporary = tempfile.mkstemp(
            dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        return instant
