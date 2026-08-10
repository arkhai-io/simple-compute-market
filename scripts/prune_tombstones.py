#!/usr/bin/env python3
"""Delete every file whose contents are a tombstone.

A tombstone marks a file as pending deletion: its entire contents are replaced
by a single comment stating why. Applying a fileset that contains one restores
the tombstone rather than the deletion, so a repository can carry tombstones a
reviewer has already actioned. Running this makes the deletion idempotent —
apply, prune, and the tree is the same either way.

A file qualifies only when the tombstone is the whole file. A module that merely
mentions the marker, and documentation that shows one inside a fenced example,
are left alone: the marker must be the first non-blank line and the file must
carry no other content.

Directories left empty by pruning are removed, because a package directory whose
modules were all tombstoned is not an empty package — it is a deleted one.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from tombstones import MARKER, is_tombstone, reason  # noqa: F401


#: Directories the vacancy sweep may enter. A deletion utility should not be able
#: to reach an arbitrary path, and every namespace this convention applies to
#: lives under a source root.
SOURCE_ROOTS = ("domains", "kit", "core", "provisioning", "e2e-tests")

#: Never walked. Build outputs and dependency trees can contain anything.
SKIP_DIRS = frozenset({
    ".git",
    ".venv",
    ".ruff_cache",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "build",
    "dist",
    "htmlcov",
    ".mypy_cache",
})



def find_tombstones(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if SKIP_DIRS & set(path.relative_to(root).parts):
            continue
        if is_tombstone(path):
            found.append(path)
    return found


def _is_vacant(directory: Path) -> bool:
    """True when nothing but build artifacts and other vacant directories remain.

    A directory holding only ``__pycache__`` is empty as far as source is
    concerned, and so is one holding only an empty subpackage. Checking a single
    level would leave the husk of a nested package — ``negotiation/`` surviving
    because ``negotiation/rl/`` still existed, holding nothing.
    """
    for item in directory.iterdir():
        if item.is_dir():
            if item.name in SKIP_DIRS or _is_vacant(item):
                continue
        return False
    return True


def _prune_empty_parents(directory: Path, stop: Path) -> list[Path]:
    """Remove directories emptied by pruning, up to but not including ``stop``."""
    removed: list[Path] = []
    current = directory
    while current != stop and current.is_dir() and _is_vacant(current):
        shutil.rmtree(current)
        removed.append(current)
        current = current.parent
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would be deleted and change nothing",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    tombstones = find_tombstones(root)

    verb = "Would delete" if args.dry_run else "Deleted"
    directories: set[Path] = set()
    if not tombstones:
        print("No tombstoned files found.")
    for path in tombstones:
        why = reason(path)
        print(f"  {path.relative_to(root)}")
        if why:
            print(f"      {why}")
        if not args.dry_run:
            path.unlink()
            directories.add(path.parent)

    # Sweep every vacant directory, not only the parents of files deleted in this
    # run. A tombstone can be actioned in one run and the last non-source sibling
    # removed by hand in between — a binary that cannot carry a tombstone, for
    # instance — leaving a husk no single run is responsible for. The repository
    # holds no intentionally empty source directory, so a vacant one is residue.
    emptied: list[Path] = []
    if not args.dry_run:
        candidates = [
            d
            for source_root in SOURCE_ROOTS
            if (root / source_root).is_dir()
            for d in (root / source_root).rglob("*")
            if d.is_dir()
        ]
        for directory in sorted(candidates, key=lambda p: len(p.parts), reverse=True):
            if not directory.exists():
                continue
            if SKIP_DIRS & set(directory.relative_to(root).parts):
                continue
            if _is_vacant(directory):
                shutil.rmtree(directory)
                emptied.append(directory)
    for directory in emptied:
        print(f"  removed vacant directory {directory.relative_to(root)}")

    if tombstones:
        print(f"\n{verb} {len(tombstones)} tombstoned file(s).")
    if args.dry_run:
        return 0
    print(
        "Re-run after applying a fileset: a fileset carrying a tombstone "
        "restores it rather than the deletion."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
