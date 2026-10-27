#!/usr/bin/env python3
"""Find an OpenSpec change's directory by its name, active or archived, and its records.

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

A change's records — its `reviews/` directory — are untracked, so they are only
where the change was worked. A change worked in its own clone has them there until
archive cleanup copies them into the owner's workspace, at the same path, where a
session working another change finds them. `--records` therefore looks in this
checkout first, then, from a clone, in the workspace its `workspace` remote names.

Run as a script, it prints the directory relative to the repository root — the
records directory in the workspace as an absolute path — or names the problem and
exits non-zero.

Contract: openspec/specs/change-workflow/spec.md, "Phases and owner touchpoints"
and "Each change is worked in its own clone".
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
CHANGES = Path("openspec/changes")
ARCHIVE = CHANGES / "archive"
REVIEWS = "reviews"
# The remote a change's clone names the owner's workspace by.
WORKSPACE_REMOTE = "workspace"
# `openspec archive` prefixes the change's name with the date it was archived.
_ARCHIVED = re.compile(r"^\d{4}-\d{2}-\d{2}-(?P<name>.+)$")


class ChangeNotFound(LookupError):
    """No single change directory carries the name."""


def _check_name(name: str) -> None:
    if not name or name == "archive" or "/" in name or name.startswith("."):
        raise ChangeNotFound(f"{name!r} is not a change name")


def _archived(root: Path, name: str) -> list[Path]:
    archive = root / ARCHIVE
    return sorted(
        entry for entry in (archive.iterdir() if archive.is_dir() else [])
        if entry.is_dir() and (match := _ARCHIVED.match(entry.name))
        and match.group("name") == name)


def _only(root: Path, name: str, archived: list[Path]) -> Path:
    if len(archived) > 1:
        raise ChangeNotFound(
            f"change {name!r} is archived more than once: "
            + ", ".join(entry.relative_to(root).as_posix() for entry in archived))
    return archived[0]


def change_directory(root: Path, name: str) -> Path:
    """The directory of the change called `name`, active or archived."""
    _check_name(name)
    active = root / CHANGES / name
    if active.is_dir():
        return active
    archived = _archived(root, name)
    if not archived:
        raise ChangeNotFound(f"no change {name!r} under {CHANGES} or {ARCHIVE}")
    return _only(root, name, archived)


def is_archived(root: Path, directory: Path) -> bool:
    return directory.parent == root / ARCHIVE


def records_directory(root: Path, name: str) -> Path | None:
    """The `reviews/` directory of the change called `name` in the checkout at
    `root`, active or archived; None when the checkout holds no records of it.

    Only a directory holding `reviews/` counts: the workspace may have the change's
    active directory from its branch beside the archive copy that holds its
    history.
    """
    _check_name(name)
    active = root / CHANGES / name / REVIEWS
    if active.is_dir():
        return active
    archived = [entry for entry in _archived(root, name) if (entry / REVIEWS).is_dir()]
    return _only(root, name, archived) / REVIEWS if archived else None


def workspace_of(checkout: Path) -> Path | None:
    """The owner's workspace a change's clone was made from, read from its
    `workspace` remote; None for a checkout that is no change's clone."""
    toplevel = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=checkout,
                              capture_output=True, text=True)
    if toplevel.returncode != 0:
        return None
    remote = subprocess.run(["git", "remote", "get-url", WORKSPACE_REMOTE], cwd=checkout,
                            capture_output=True, text=True)
    url = remote.stdout.strip() if remote.returncode == 0 else ""
    if not url or not Path(url).is_dir():
        return None
    return Path(url).resolve()


def find_records(root: Path, name: str,
                 workspace: Callable[[Path], Path | None] = workspace_of) -> Path:
    """The records of the change called `name`: this checkout's, else, in a change's
    clone, the owner's workspace's."""
    here = records_directory(root, name)
    if here is not None:
        return here
    owner = workspace(root)
    there = records_directory(owner, name) if owner is not None else None
    if there is not None:
        return there
    raise ChangeNotFound(f"no records of change {name!r} in {root}"
                         + (f" or in the workspace {owner}" if owner is not None else ""))


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    flags = {arg for arg in args if arg in ("--active", "--archived", "--records")}
    names = [arg for arg in args if arg not in flags]
    if len(names) != 1 or len(flags) > 1:
        print("usage: find_change.py [--active | --archived | --records] <change>",
              file=sys.stderr)
        return 2
    try:
        if "--records" in flags:
            records = find_records(root, names[0])
            print(records.relative_to(root).as_posix() if records.is_relative_to(root)
                  else records)
            return 0
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
