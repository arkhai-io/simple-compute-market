#!/usr/bin/env python3
"""Show an implementation round's changes as uncommitted changes in a worktree.

Implementation commits each section, so by the time the owner reads a round the
diff is spread across commits and an editor's source-control view is empty. This
checks out the round's base in a worktree beside the checkout, then overlays
HEAD's files on it: the worktree's own status and diff are then exactly the
round, deletions included, while the commits themselves stay as they are.

The base is the commit named by the latest validation record that has been
triaged — the commit the previous round ended on — unless one is given. Other
changes' directories under `openspec/changes/` keep their base contents, since
a branch can carry more than one change and the owner reads one at a time.

The worktree is disposable: each run replaces it. It lives outside the checkout
so the repository's own scans never see a second copy of the tree.

Contract: openspec/specs/change-workflow/spec.md, "Triage of an implementation
round".
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
CHANGES = "openspec/changes"
_NUMBERED = re.compile(r"^(\d+)-validation\.md$")
_VALIDATION_COMMIT = re.compile(r"^- \*\*Commit:\*\*\s*([0-9a-f]{7,40})\b", re.M)


class RoundError(RuntimeError):
    """The round's worktree could not be prepared."""


@dataclass(frozen=True)
class Round:
    base: str
    head: str
    path: Path


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RoundError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def triaged_base(reviews: Path) -> str | None:
    """The commit of the latest validation record with a triage file beside it."""
    records = sorted((int(match.group(1)), entry) for entry in
                     (reviews.glob("[0-9]*-validation.md") if reviews.is_dir() else [])
                     if (match := _NUMBERED.match(entry.name))
                     and entry.with_name(entry.name.replace(".md", ".triage.md")).exists())
    for _, record in reversed(records):
        commit = _VALIDATION_COMMIT.search(record.read_text("utf-8"))
        if commit:
            return commit.group(1)
    return None


def default_path(root: Path, change: str) -> Path:
    return root.parent / f"{root.name}-round-{change}"


def _registered_worktrees(root: Path) -> set[Path]:
    listing = _git(root, "worktree", "list", "--porcelain")
    return {Path(line.removeprefix("worktree ")).resolve()
            for line in listing.splitlines() if line.startswith("worktree ")}


def prepare(root: Path, change: str, base: str | None = None,
            path: Path | None = None) -> Round:
    """Replace the round's worktree: `base` checked out, HEAD's files over it."""
    if not change or change == "archive" or not (root / CHANGES / change).is_dir():
        raise RoundError(f"no active change '{change}' under {CHANGES}")
    if base is None:
        base = triaged_base(root / CHANGES / change / "reviews")
        if base is None:
            raise RoundError("no triaged validation record names the previous round's "
                             "commit; give the base explicitly (BASE=<commit>)")
    base = _git(root, "rev-parse", "--verify", f"{base}^{{commit}}")
    head = _git(root, "rev-parse", "HEAD")
    path = (path or default_path(root, change)).resolve()

    # A worktree directory deleted by hand stays registered until pruned, and a
    # registered path cannot be added again.
    _git(root, "worktree", "prune")
    if path.exists():
        if path not in _registered_worktrees(root):
            raise RoundError(f"{path} exists and is not a worktree of this repository; "
                             "nothing was removed")
        _git(root, "worktree", "remove", "--force", str(path))
    _git(root, "worktree", "add", "--quiet", "--detach", str(path), base)

    # `git restore` without --overlay removes what HEAD lacks, so deletions show.
    _git(path, "restore", f"--source={head}", "--worktree", "--", ".",
         f":(exclude){CHANGES}")
    own = (f"{CHANGES}/{change}", f"{CHANGES}/README.md")
    in_head = [p for p in own if _exists(root, head, p)]
    if in_head:
        _git(path, "restore", f"--source={head}", "--worktree", "--", *in_head)
    # A pathspec HEAD lacks cannot be restored; the change's directory removed in
    # the round, as an archived change's is, shows as deleted instead.
    for gone in (p for p in own if p not in in_head and (path / p).exists()):
        if (path / gone).is_dir():
            shutil.rmtree(path / gone)
        else:
            (path / gone).unlink()

    # Intent-to-add makes new files part of the worktree's diff, not only its
    # status. Only the files the round adds, ignored or not: `--all` would also
    # stage deletions, splitting the round between the index and the worktree.
    # NUL separation keeps paths Git would otherwise quote.
    added = _git(root, "diff", "--name-only", "-z", "--no-renames", "--diff-filter=A",
                 base, head).split("\0")
    new = [p for p in added if p and (path / p).exists()]
    if new:
        _git(path, "add", "--force", "--intent-to-add", "--", *new)
    return Round(base, head, path)


def _exists(root: Path, commit: str, path: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{commit}:{path}"], cwd=root,
                          capture_output=True).returncode == 0


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("change")
    parser.add_argument("--base", help="the commit the round starts after")
    parser.add_argument("--path", type=Path, help="where to put the worktree")
    args = parser.parse_args(argv)
    try:
        prepared = prepare(root, args.change, args.base, args.path)
        ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", prepared.base,
                                   prepared.head], cwd=root).returncode == 0
        log = _git(root, "log", "--oneline", f"{prepared.base}..{prepared.head}")
        stat = _git(prepared.path, "diff", "--stat")
    except RoundError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Round of {args.change}: {prepared.base[:12]}..{prepared.head[:12]}")
    if not ancestor:
        print("WARNING: the base is not an ancestor of HEAD; the diff includes whatever "
              "the history rewrote", file=sys.stderr)
    print(log or "(no commits)")
    print(stat or "(no changes outside other changes' directories)")
    print(f"Open {prepared.path} in your editor: its uncommitted changes are the round.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
