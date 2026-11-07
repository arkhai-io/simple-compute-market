"""The runtime dependencies `pyproject.toml` declares, and a check of their floors.

`make test-floor` runs this module in its own environment before the unit tests: it
prints each runtime dependency's installed version and fails unless that is the
lowest release the project declares, so the floor run can never test the lock by
mistake. Run from the tool's directory as `python -m tests.floor`.
"""

from __future__ import annotations

import importlib.metadata
import re
import sys
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
# A runtime dependency is declared with a lower bound and nothing else: no upper bound,
# no marker, no extra.
_REQUIREMENT = re.compile(r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)>=(?P<floor>[0-9]+(\.[0-9]+)*)")


def runtime_floors(pyproject: Path = PYPROJECT) -> dict[str, str]:
    """Each runtime dependency's name and lowest declared release."""
    declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["dependencies"]
    floors = {}
    for requirement in declared:
        match = _REQUIREMENT.fullmatch(requirement)
        if match is None:
            raise ValueError(f"{requirement!r} is not declared as `<name>>=<release>`")
        floors[match["name"]] = match["floor"]
    return floors


def same_release(installed: str, floor: str) -> bool:
    """Whether two releases are equal, `42` and `42.0.0` alike."""

    def release(version: str) -> tuple[int, ...] | str:
        try:
            parts = [int(part) for part in version.split(".")]
        except ValueError:
            return version
        while len(parts) > 1 and parts[-1] == 0:
            parts.pop()
        return tuple(parts)

    return release(installed) == release(floor)


def main() -> int:
    mismatched = []
    for name, floor in runtime_floors().items():
        installed = importlib.metadata.version(name)
        print(f"{name} {installed} (declared floor {floor})")
        if not same_release(installed, floor):
            mismatched.append(f"{name} is {installed}, not its declared floor {floor}")
    for problem in mismatched:
        print(problem, file=sys.stderr)
    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main())
