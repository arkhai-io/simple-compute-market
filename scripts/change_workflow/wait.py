"""`scripts/change-workflow wait`: block until a file holds a line matching a pattern.

An unattended step runs a long command in the background and must wait for it inside
one call, since under the wrapper a turn's end is the run's outcome. Following the
command's output with `tail -f … | grep -m1` hangs whenever the matching line is the
last the command prints: `grep` exits on the match, but `tail` notices only on its next
write, which never comes. This wait reads the file itself and returns the moment the
line is there, including a line written before the wait began, and gives up within a
bound shorter than one call's limit, so the caller waits again instead of being killed.

Exit 0 prints the first matching line; exit 1 says no line matched within the bound.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from typing import Callable

# Under the harness's ten-minute limit on one call, with room to start and print.
DEFAULT_TIMEOUT_S = 540.0
POLL_INTERVAL_S = 1.0


def wait_for(path: Path, pattern: re.Pattern[str], *, timeout: float,
             clock: Callable[[], float] = time.monotonic,
             sleep: Callable[[float], None] = time.sleep,
             interval: float = POLL_INTERVAL_S) -> str | None:
    """The first complete line of `path` matching `pattern`, read as the file grows;
    None when none has appeared within `timeout` seconds. A missing file is waited for
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
            for line in lines:
                if pattern.search(line):
                    return line
            if pending and pattern.search(pending):
                return pending
        remaining = deadline - clock()
        if remaining <= 0:
            return None
        sleep(min(interval, remaining))


def run(path: Path, pattern: re.Pattern[str], *, timeout: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep) -> int:
    """Wait, then print the matching line and exit 0, or say none matched and exit 1."""
    line = wait_for(path, pattern, timeout=timeout, clock=clock, sleep=sleep)
    if line is None:
        print(f"ERROR: no line of {path} matched {pattern.pattern!r} within "
              f"{timeout:g}s; wait again", file=sys.stderr)
        return 1
    print(line)
    return 0
