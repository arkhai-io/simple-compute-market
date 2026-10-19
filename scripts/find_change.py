#!/usr/bin/env python3
"""Find an OpenSpec change's directory by its name, active or archived.

A change lives at `openspec/changes/<name>/` until closeout archives it, which
moves it to `openspec/changes/archive/<YYYY-MM-DD>-<name>/`. Closeout archives
before its review, so the steps that follow it — the closeout review, its
triage, validation, the round view, the citation check, archive cleanup — must
find an archived change by the same name. Design, planning, and implementation
take only an active change, and refuse an archived one (`--active`); archive
cleanup takes only an archived one, and refuses an active one (`--archived`). An active
change is preferred; an archived one is found only when exactly one archive
directory carries the name, since two would mean the name was reused and either
could be meant.

Run as a script, it prints the directory relative to the repository root, or
names the problem and exits non-zero.

Contract: openspec/specs/change-workflow/spec.md, "Phases and owner touchpoints".
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
CHANGES = Path("openspec/changes")
ARCHIVE = CHANGES / "archive"
# `openspec archive` prefixes the change's name with the date it was archived.
_ARCHIVED = re.compile(r"^\d{4}-\d{2}-\d{2}-(?P<name>.+)$")


class ChangeNotFound(LookupError):
    """No single change directory carries the name."""


def change_directory(root: Path, name: str) -> Path:
    """The directory of the change called `name`, active or archived."""
    if not name or name == "archive" or "/" in name or name.startswith("."):
        raise ChangeNotFound(f"{name!r} is not a change name")
    active = root / CHANGES / name
    if active.is_dir():
        return active
    archive = root / ARCHIVE
    archived = sorted(
        entry for entry in (archive.iterdir() if archive.is_dir() else [])
        if entry.is_dir() and (match := _ARCHIVED.match(entry.name))
        and match.group("name") == name)
    if len(archived) > 1:
        raise ChangeNotFound(
            f"change {name!r} is archived more than once: "
            + ", ".join(entry.relative_to(root).as_posix() for entry in archived))
    if not archived:
        raise ChangeNotFound(f"no change {name!r} under {CHANGES} or {ARCHIVE}")
    return archived[0]


def is_archived(root: Path, directory: Path) -> bool:
    return directory.parent == root / ARCHIVE


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    flags = {arg for arg in args if arg in ("--active", "--archived")}
    names = [arg for arg in args if arg not in flags]
    if len(names) != 1 or len(flags) > 1:
        print("usage: find_change.py [--active | --archived] <change>", file=sys.stderr)
        return 2
    try:
        directory = change_directory(root, names[0])
    except ChangeNotFound as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if "--active" in flags and is_archived(root, directory):
        print(f"ERROR: change {names[0]!r} is archived "
              f"({directory.relative_to(root).as_posix()}); design, planning, and "
              "implementation take an active change", file=sys.stderr)
        return 1
    if "--archived" in flags and not is_archived(root, directory):
        print(f"ERROR: change {names[0]!r} is not archived; archive cleanup follows "
              "closeout, which archives it", file=sys.stderr)
        return 1
    print(directory.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
