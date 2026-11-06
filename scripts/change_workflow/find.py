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

The branch a change lands on is recorded in its clone's marker as the clone is made
(`landing_branch`): read in the clone, or, from the workspace, in the change's clone
beside it. A change worked in place, or whose clone's marker records none, has none.

Run as a command, it prints the directory relative to the repository root — the
records directory in the workspace as an absolute path — or names the problem and
exits 1, or 2 for a malformed argument. With `--json` it prints the change as an
object a program reads (`found`).

Contract: openspec/specs/change-workflow/spec.md, CW-1iaz, CW-c3he, and CW-s3ju.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

from .common import CHANGES, FORMAT, StepError, repository_root

ARCHIVE = CHANGES / "archive"
REVIEWS = "reviews"
# The remote a change's clone names the owner's workspace by.
WORKSPACE_REMOTE = "workspace"
# In a clone's Git directory: which change and branch the clone was made for, and
# the branch the change lands on.
CLONE_MARKER = "change-clone.json"
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


def clone_directory(workspace: Path, change: str) -> Path:
    """`<workspace>.changes/<change>/`, beside the workspace rather than inside it:
    the scripts' tree walkers ignore `.gitignore`, so a clone nested in the
    workspace would be relocked and scanned as part of it."""
    workspace = workspace.resolve()
    return workspace.parent / f"{workspace.name}.changes" / change


def clone_marker(checkout: Path) -> dict[str, str]:
    """What the checkout's clone marker records, or nothing for a checkout that is
    no change's clone, or whose marker cannot be read."""
    found = subprocess.run(["git", "rev-parse", "--git-path", CLONE_MARKER], cwd=checkout,
                           capture_output=True, text=True)
    if found.returncode != 0:
        return {}
    path = Path(found.stdout.strip())
    path = path if path.is_absolute() else checkout / path
    try:
        recorded = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return recorded if isinstance(recorded, dict) else {}


def landing_branch(root: Path, name: str) -> str | None:
    """The branch the change called `name` lands on, as its clone recorded it: read
    in this checkout when it is the change's clone, else in the change's clone of
    this workspace; None when none is recorded, as for a name no change can have."""
    try:
        _check_name(name)
    except ChangeNotFound:
        return None
    for checkout in (root, clone_directory(workspace_of(root) or root, name)):
        if not checkout.is_dir():
            continue
        recorded = clone_marker(checkout)
        if recorded.get("change") == name and isinstance(recorded.get("base"), str):
            return recorded["base"]
    return None


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


def found(root: Path, name: str, directory: Path) -> dict[str, object]:
    """The change as `--json` prints it, for a program to read: its name, its
    directory relative to the repository, whether it is archived, its records
    directory in this checkout, or None when this checkout holds none, the
    record-set format this engine reads and writes them in, and the branch it
    lands on, or None when none is recorded."""
    records = records_directory(root, name)
    return {"name": name, "directory": directory.relative_to(root).as_posix(),
            "archived": is_archived(root, directory),
            "records": records.relative_to(root).as_posix() if records is not None else None,
            "format": FORMAT, "base": landing_branch(root, name)}


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    flags = {arg for arg in args if arg in ("--active", "--archived", "--records")}
    as_json = "--json" in args
    names = [arg for arg in args if arg not in flags and arg != "--json"]
    if len(names) != 1 or len(flags) > 1 or (as_json and "--records" in flags):
        print("usage: find [--active | --archived | --records] [--json] <change>; --json "
              "prints the records of this checkout alone, so it takes no --records",
              file=sys.stderr)
        return 2
    try:
        root = repository_root() if root is None else root
    except StepError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
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
    try:
        print(json.dumps(found(root, names[0], directory)) if as_json
              else directory.relative_to(root).as_posix())
    except ChangeNotFound as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
