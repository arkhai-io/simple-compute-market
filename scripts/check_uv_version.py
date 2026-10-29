"""Fail if the installed uv is older than the repository's minimum.

uv releases write `uv.lock` differently, and `uv lock --check` asks only whether a
lock satisfies its project, not whether this uv would write the same bytes: locks
written by an older uv pass `check-locks`, and the next `uv sync` on a newer one
rewrites them. So `make lock` runs this first, and validation runs it before it
builds anything, refusing an older uv rather than letting it write or judge the
locks. The tests and pipeline workflows install a uv at least the minimum; the
release workflows build and publish without relocking.

Conventions: docs/development/BUILD_AND_PACKAGING.md.
"""

from __future__ import annotations

import re
import subprocess
import sys
from typing import Callable

MINIMUM = (0, 12)
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
