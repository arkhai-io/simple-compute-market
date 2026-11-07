"""Fail if the installed uv is older than the repository's minimum.

uv releases write `uv.lock` differently, and `uv lock --check` asks only whether a
lock satisfies its project, not whether this uv would write the same bytes. The
drift runs both ways: whenever a uv release rewrites a lock it writes its own lock
revision, so a newer uv raises an older one's lock and an older uv lowers a newer
one's back. The minimum is the first release that writes the revision every
committed lock carries, which `check_locks.py` holds them to. The repository's
relock and environment refresh — `make lock`, `make review-locks`, and each
package's `make reinit` and `make init`, all through `scripts/uv_project.py` —
and validation, before it builds anything, run this first, refusing an older uv
rather than letting it write or judge the locks. A plain `uv run` that relocks
is not guarded; the revision check catches what it writes. The tests and
pipeline workflows install the minimum; the release workflows build and publish
without relocking. It stays a minimum, not an exact pin: a newer release writing
another revision is caught by the revision check too.

Conventions: docs/development/BUILD_AND_PACKAGING.md.
"""

from __future__ import annotations

import re
import subprocess
import sys
from typing import Callable

MINIMUM = (0, 12, 22)
_VERSION = re.compile(r"^uv (\d+)\.(\d+)(?:\.(\d+))?\b")


def installed(run: Callable[[], str]) -> tuple[int, ...] | None:
    """The version `uv --version` prints, or None when it prints none."""
    match = _VERSION.match(run().strip())
    return tuple(int(part) for part in match.groups() if part is not None) if match else None


def _uv_version() -> str:
    try:
        result = subprocess.run(["uv", "--version"], capture_output=True, text=True)
    except FileNotFoundError:
        return ""
    return result.stdout if result.returncode == 0 else ""


def problem(run: Callable[[], str] = _uv_version) -> str | None:
    minimum = ".".join(map(str, MINIMUM))
    version = installed(run)
    if version is None:
        return f"no uv version could be read from `uv --version`; uv {minimum} or newer is needed"
    if version < MINIMUM:
        return (f"uv {'.'.join(map(str, version))} is older than {minimum}, which writes this "
                f"repository's locks; install uv {minimum} or newer")
    return None


def main() -> int:
    if found := problem():
        print(f"ERROR: {found}", file=sys.stderr)
        return 1
    print("OK: uv meets the repository's minimum.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
