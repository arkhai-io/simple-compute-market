"""A prerequisite's proposal worktree, which the engine makes for a design that needs
another change first (CW-k8dn).

A design that cannot proceed until another change lands ends with a question naming
the prerequisite. On the owner's word the orchestrating session runs `propose
<change> <prerequisite>`, which makes the worktree `../<prerequisite>-proposal`,
beside the checkout, on a new branch `propose-<prerequisite>` from the branch the
change lands on, as its remote holds it: fetched first, so the proposal starts from
what the landing branch's next merge will see. The branch tracks nothing, since
tracking would write `.git/config`, which no step's sandbox lets it write, and the
worktree is never on the blocked change's branch. One that exists, as a directory or
as a branch, is refused, never reused: a second proposal of the same prerequisite is
the owner's to reconcile. Making a worktree is mechanical, so the engine does it; the
resumed design session, whose sandbox makes each such worktree writable (`scope`),
writes and checks the proposal there.

`propose` is provisional: a public subcommand whose successor is expected once the
workflow moves to its own repository.

Contract: openspec/specs/change-workflow/spec.md, CW-k8dn and CW-dtpz.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from .common import StepError, repository_root
from .find import (WORKSPACE_REMOTE, ChangeNotFound, change_directory, check_name,
                   landing_branch, workspace_of)
from .graph import PROPOSAL_SUFFIX

# The prefix of a proposal's branch, before the prerequisite's name.
BRANCH_PREFIX = "propose-"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def _remote(root: Path, branch: str) -> str | None:
    """The remote the landing branch tracks, as Git records it in the owner's workspace
    when `root` is a change's clone, else in `root`: one `root` has, other than the
    workspace itself. The engine names no remote of its own, so a fork's landing branch
    tracking the repository it was forked from is fetched from there."""
    for checkout in dict.fromkeys(filter(None, (workspace_of(root), root))):
        remote = _git(checkout, "config", f"branch.{branch}.remote").stdout.strip()
        if remote not in ("", ".", WORKSPACE_REMOTE) and _git(
                root, "remote", "get-url", remote).returncode == 0:
            return remote
    return None


def worktree(root: Path, prerequisite: str) -> Path:
    """Where a prerequisite's proposal worktree sits: beside the checkout at `root`."""
    return root.parent / f"{prerequisite}{PROPOSAL_SUFFIX}"


def propose(root: Path, change: str, prerequisite: str, base: str | None = None) -> Path:
    """Make the prerequisite's proposal worktree for `change`, whose checkout is at
    `root`, from `base` or the branch the change lands on, as its remote holds it; its
    path. Refused, as a `StepError` naming why, where the change is unknown, no landing
    branch is known, the worktree or its branch exists, or Git fails."""
    try:
        check_name(prerequisite)
        change_directory(root, change)
    except ChangeNotFound as exc:
        raise StepError(str(exc)) from exc
    base = base or landing_branch(root, change)
    if base is None:
        raise StepError(f"the proposal starts from the branch {change} lands on, and none is "
                        "recorded, since the change has no clone that recorded one: give it "
                        "with --base <branch>")
    path, branch = worktree(root, prerequisite), f"{BRANCH_PREFIX}{prerequisite}"
    if path.exists():
        raise StepError(f"{path} exists; a prerequisite's proposal worktree is made once")
    if _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0:
        raise StepError(f"the branch {branch} exists; a prerequisite's proposal branch is "
                        "made once")
    remote = _remote(root, base)
    if remote is None:
        raise StepError(f"{base}, the branch {change} lands on, tracks no remote this "
                        "checkout has, so there is no copy of it to start the proposal from")
    # Into the remote-tracking branch, never `FETCH_HEAD`, which a fetch run beside
    # this one would replace before the worktree reads it.
    tracking = f"refs/remotes/{remote}/{base}"
    fetched = _git(root, "fetch", "--quiet", remote, f"+refs/heads/{base}:{tracking}")
    if fetched.returncode != 0:
        raise StepError(f"cannot fetch {base} from {remote}: {fetched.stderr.strip()}")
    made = _git(root, "worktree", "add", "--quiet", "--no-track", "-b", branch, str(path),
                tracking)
    if made.returncode != 0:
        raise StepError(f"cannot make the worktree {path}: {made.stderr.strip()}")
    return path


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    """`propose <change> <prerequisite> [--base <branch>]`, as `cli` hands it on."""
    parser = argparse.ArgumentParser(prog="change-workflow propose")
    parser.add_argument("change")
    parser.add_argument("prerequisite")
    parser.add_argument("--base", default=None)
    args = parser.parse_args(argv)
    try:
        path = propose(repository_root() if root is None else root, args.change,
                       args.prerequisite, args.base)
    except StepError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Proposal worktree for {args.prerequisite}: {path} on "
          f"{BRANCH_PREFIX}{args.prerequisite}")
    return 0
