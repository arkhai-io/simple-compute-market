#!/usr/bin/env python3
"""Check that HEAD may be pushed unattended to its own branch, and push it.

An unattended push needs a mechanical definition of "the change's own branch".
HEAD must be attached to a branch other than `main` or `dev`, the worktree must be
clean, untracked files included, and the branch's upstream, if it has one, must be
the branch of the same name. A branch with no upstream yet is pushed to the same
name on `origin` and the upstream set, because every new change branch starts
that way.

The check reports and never repairs: each refused state means something
unexpected happened, and fixing it automatically would hide that. The push sends
exactly HEAD and is never forced, so a remote branch that has moved on rejects it.

Contract: openspec/specs/change-workflow/spec.md, "Guarded push of a change
branch".
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = ("main", "dev")
DEFAULT_REMOTE = "origin"


@dataclass(frozen=True)
class PushTarget:
    branch: str
    remote: str
    set_upstream: bool

    def command(self) -> list[str]:
        return ["git", "push", *(["--set-upstream"] if self.set_upstream else []),
                self.remote, f"HEAD:refs/heads/{self.branch}"]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def check(root: Path = ROOT) -> tuple[PushTarget | None, list[str]]:
    """The push HEAD may receive, or every reason it may not be pushed."""
    problems: list[str] = []
    attached = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    branch = attached.stdout.strip() if attached.returncode == 0 else ""
    if not branch:
        problems.append("HEAD is detached; check out the change's branch")
    elif branch in PROTECTED:
        problems.append(f"{branch} is a protected branch; validation pushes only a change's "
                        "own branch")

    status = _git(root, "status", "--porcelain", "--untracked-files=all")
    if status.returncode != 0:
        problems.append(f"git status failed: {status.stderr.strip()}")
    elif status.stdout.strip():
        problems.append("the worktree is not clean:\n" + status.stdout.rstrip())

    target = None
    if branch:
        remote = _git(root, "config", f"branch.{branch}.remote").stdout.strip()
        merge = _git(root, "config", f"branch.{branch}.merge").stdout.strip()
        if not remote and not merge:
            target = PushTarget(branch, DEFAULT_REMOTE, set_upstream=True)
        elif merge != f"refs/heads/{branch}" or not remote or remote == ".":
            upstream = f"{remote}/{merge.removeprefix('refs/heads/')}" if remote else merge
            problems.append(f"{branch} tracks {upstream}, not a branch of its own name")
        else:
            target = PushTarget(branch, remote, set_upstream=False)
    return (None if problems else target), problems


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("check", "push"))
    args = parser.parse_args(argv)
    target, problems = check(root)
    if problems:
        for problem in problems:
            print(f"REFUSED: {problem}", file=sys.stderr)
        print("Nothing was pushed, and nothing was changed to make the check pass.",
              file=sys.stderr)
        return 1
    assert target is not None
    if args.action == "check":
        upstream = "no upstream yet; the push sets it" if target.set_upstream else "upstream matches"
        print(f"Ready to push {target.branch} to {target.remote} ({upstream}).")
        return 0
    print("+ " + " ".join(target.command()), flush=True)
    return subprocess.run(target.command(), cwd=root).returncode


if __name__ == "__main__":
    sys.exit(main())
