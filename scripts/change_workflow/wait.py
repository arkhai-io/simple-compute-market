"""`scripts/change-workflow wait`: block until a file holds a line matching a pattern.

An unattended step runs a long command in the background and must wait for it inside
one call, since under the wrapper a turn's end is the run's outcome. Following the
command's output with `tail -f … | grep -m1` hangs whenever the matching line is the
last the command prints: `grep` exits on the match, but `tail` notices only on its next
write, which never comes. This wait reads the file itself and returns the moment the
line is there, including a line written before the wait began, and gives up within a
bound shorter than one call's limit, so the caller waits again instead of being killed.

A pattern that never matches the command's output would hold the caller for the whole
bound, and again on every retry, after the command had already finished. The harness
ends a background command's output file with `[exited with code N]`, after which
nothing more is written, so the wait stops at that line: the output is complete, and
the caller reads it rather than waiting for a line that cannot come.

Exit 0 prints the first matching line; exit 1 says no line matched within the bound;
exit 3 says the command ended with no line matching.
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Under the harness's ten-minute limit on one call, with room to start and print.
DEFAULT_TIMEOUT_S = 540.0
POLL_INTERVAL_S = 1.0
# The harness's last line of a background command's output file.
EXITED = re.compile(r"^\[exited with code (-?\d+)\]$")
ENDED_STATUS = 3


@dataclass(frozen=True)
class Ended:
    """The command ended, its output holding no line that matched."""

    line: str


def wait_for(path: Path, pattern: re.Pattern[str], *, timeout: float,
             clock: Callable[[], float] = time.monotonic,
             sleep: Callable[[float], None] = time.sleep,
             interval: float = POLL_INTERVAL_S) -> str | Ended | None:
    """The first complete line of `path` matching `pattern`, read as the file grows;
    `Ended` when the harness's exit line comes first, since nothing follows it; None
    when neither has appeared within `timeout` seconds. A missing file is waited for
    like a line not yet written. The file's last line is matched before its newline
    arrives, since a command's final line may never get one."""
    deadline = clock() + timeout
    offset = 0
    pending = ""
    while True:
        if path.is_file():
            with path.open(encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                chunk = handle.read()
                offset = handle.tell()
            *lines, pending = (pending + chunk).split("\n")
            for line in [*lines, pending] if pending else lines:
                if pattern.search(line):
                    return line
                if EXITED.match(line):
                    return Ended(line)
        remaining = deadline - clock()
        if remaining <= 0:
            return None
        sleep(min(interval, remaining))


def run(path: Path, pattern: re.Pattern[str], *, timeout: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep) -> int:
    """Wait, then print the matching line and exit 0; say the command ended with no line
    matching and exit 3; or say none matched within the bound and exit 1."""
    line = wait_for(path, pattern, timeout=timeout, clock=clock, sleep=sleep)
    if isinstance(line, Ended):
        print(f"ERROR: the command ended ({line.line}) with no line of {path} matching "
              f"{pattern.pattern!r}; its output is complete, so read it rather than "
              f"waiting again", file=sys.stderr)
        return ENDED_STATUS
    if line is None:
        print(f"ERROR: no line of {path} matched {pattern.pattern!r} within "
              f"{timeout:g}s; wait again", file=sys.stderr)
        return 1
    print(line)
    return 0
