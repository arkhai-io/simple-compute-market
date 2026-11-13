#!/usr/bin/env python3
"""Fail unless every wheel builds with build requirements the root declaration pins.

A wheel's bytes depend on the build backend that wrote it: hatchling stamps its
own version into every wheel's `WHEEL` file, and a build plugin can change a
wheel's contents as surely. A release's version check refuses a version whose
bytes changed, so an unpinned backend would make the first backend release after
a marketplace release change every wheel without a version bump. The root
`build-constraints.txt`, beside `.python-version`, pins each build requirement
exactly, and every Makefile that runs `uv build` exports it as
`UV_BUILD_CONSTRAINT`, which uv applies to the build environment.

This check refuses:

- a line of the declaration that is not `<name>==<version>`, or a name pinned
  twice;
- a project whose `[build-system]` requires something the declaration does not
  pin;
- a Makefile that runs `uv build` without exporting `UV_BUILD_CONSTRAINT` from
  the declaration by a path that resolves to it.

It pins direct build requirements only, not the backend's own dependencies.
Moving a pin changes every wheel, so it bumps every declared distribution's
version (`docs/development/RELEASING.md`, "Versioning policy").
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = "build-constraints.txt"
SKIPPED_DIRS = {".venv", "venv", "node_modules", "openspec", ".git", ".dist", "target"}

_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.+!_-]*)$")
_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_RUNS_UV_BUILD = re.compile(r"\buv\s+build\b")
_EXPORT = re.compile(
    r"^export UV_BUILD_CONSTRAINT := \$\(or \$\(wildcard \$\(abspath (\S+)\)\),"
    r"\$\(error \S+ not found\)\)\s*$",
    re.MULTILINE,
)


def _normalised(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _files(root: Path, name: str) -> list[Path]:
    return sorted(path for path in root.rglob(name)
                  if path.is_file() and not SKIPPED_DIRS & set(path.relative_to(root).parts))


def _uncommented(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def pins(root: Path = ROOT) -> tuple[dict[str, str], list[str]]:
    """The declaration's pins, by normalised name, and its malformed lines."""
    path = root / DECLARATION
    if not path.is_file():
        return {}, [f"{DECLARATION} is missing"]
    found: dict[str, str] = {}
    problems: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        match = _PIN.match(line)
        if not match:
            problems.append(f"{DECLARATION}:{number}: {line!r} is not an exact pin, "
                            "<name>==<version>")
            continue
        name = _normalised(match.group(1))
        if name in found:
            problems.append(f"{DECLARATION}:{number}: {match.group(1)} is pinned twice")
        found[name] = match.group(2)
    return found, problems


def project_problems(root: Path, pinned: dict[str, str]) -> list[str]:
    """Each `[build-system]` requirement the declaration does not pin."""
    problems: list[str] = []
    for pyproject in _files(root, "pyproject.toml"):
        where = pyproject.relative_to(root)
        try:
            document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as error:
            problems.append(f"{where}: is not valid TOML: {error}")
            continue
        for requirement in (document.get("build-system") or {}).get("requires") or []:
            match = _REQUIREMENT_NAME.match(requirement) if isinstance(requirement, str) else None
            if not match:
                problems.append(f"{where}: build requirement {requirement!r} names no package")
            elif _normalised(match.group(1)) not in pinned:
                problems.append(f"{where}: requires {requirement!r} to build, which "
                                f"{DECLARATION} does not pin")
    return problems


def makefile_problems(root: Path) -> list[str]:
    """Each Makefile that runs `uv build` without applying the declaration."""
    problems: list[str] = []
    for makefile in _files(root, "Makefile"):
        text = makefile.read_text(encoding="utf-8")
        if not _RUNS_UV_BUILD.search(_uncommented(text)):
            continue
        match = _EXPORT.search(text)
        if not match or (makefile.parent / match.group(1)).resolve() != (root / DECLARATION).resolve():
            problems.append(f"{makefile.relative_to(root)}: runs uv build without exporting "
                            f"UV_BUILD_CONSTRAINT from {DECLARATION}")
    return problems


def problems(root: Path = ROOT) -> list[str]:
    pinned, found = pins(root)
    if not (root / DECLARATION).is_file():
        return found
    return found + project_problems(root, pinned) + makefile_problems(root)


def main(root: Path = ROOT) -> int:
    found = problems(root)
    for problem in found:
        print(problem)
    if found:
        print(f"\n{len(found)} build requirement problem(s). "
              "See docs/development/BUILD_AND_PACKAGING.md.")
        return 1
    print(f"OK: every build requirement is pinned in {DECLARATION}, and every uv build applies it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
