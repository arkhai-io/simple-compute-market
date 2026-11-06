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

Before either action reports success, the repository's pre-push checks, those it
provides, read what the push would send, and any of them may refuse it. Here they
are the two public-content checks: `check_public_content.py`'s rules and the pinned
gitleaks of `check_secrets.py`, the same pair `scripts/hooks/pre-push` runs. Each
check is a command the engine runs, never a module it imports, so the engine loads
in a repository that provides none. Each is run as Git runs a pre-push hook: the
remote as its argument, and one line on standard input naming the branch, `HEAD`,
and an all-zero remote object, so it reads every commit the remote's refs lack.
Every check runs whatever another reports, so one refusal names every reason.
Each check run is kept, as `pre-push`, for the line of the session pushing, with
the command it ran and its exit status.

Contract: openspec/specs/change-workflow/spec.md, CW-59c7, CW-p7kq, CW-q5fy;
openspec/specs/market-change-workflow/spec.md, MCW-farr, MCW-q8vd.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .common import SESSION_ID, Clock, StepError, repository_root, utc_now
from .hooks import Invoked
from .running import invocations_directory, keep_invocations

PROTECTED = ("main", "dev")
DEFAULT_REMOTE = "origin"
# The repository's pre-push checks, each a Python script relative to its root run
# with the engine's own interpreter, and the arguments before the remote's name. A
# script absent is a check the repository does not provide.
PRE_PUSH_CHECKS = (("scripts/check_public_content.py", "--pre-push"),
                   ("scripts/check_secrets.py", "--pre-push"))
_NO_OBJECT = "0" * 40


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


def check(root: Path) -> tuple[PushTarget | None, list[str]]:
    """The push HEAD may receive, or every reason it may not be pushed."""
    problems: list[str] = []
    attached = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    branch = attached.stdout.strip() if attached.returncode == 0 else ""
    if not branch:
        problems.append("HEAD is detached; check out the change's branch")
    elif branch in PROTECTED:
        problems.append(f"{branch} is a protected branch; a step pushes only a change's "
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
            upstream = (f"{remote}/{merge.removeprefix('refs/heads/')}" if remote and merge
                        else remote or merge)
            problems.append(f"{branch} tracks {upstream}, not a branch of its own name")
        else:
            target = PushTarget(branch, remote, set_upstream=False)
    return (None if problems else target), problems


def pre_push_findings(root: Path, target: PushTarget,
                      invoked: list[Invoked] | None = None,
                      clock: Clock = utc_now) -> list[str]:
    """Every reason the repository's pre-push checks refuse the push, of those it
    provides; each check run is added to `invoked`."""
    head = _git(root, "rev-parse", "--verify", "HEAD").stdout.strip()
    ref = f"refs/heads/{target.branch}"
    findings: list[str] = []
    for script, *arguments in PRE_PUSH_CHECKS:
        if not (root / script).is_file():
            continue
        command = [sys.executable, str(root / script), *arguments, target.remote]
        started, begun = clock().strftime("%Y-%m-%dT%H:%M:%SZ"), time.monotonic()
        result = subprocess.run(command, cwd=root, input=f"{ref} {head} {ref} {_NO_OBJECT}\n",
                                capture_output=True, text=True)
        if invoked is not None:
            invoked.append(Invoked(hook="pre-push", command=shlex.join(command),
                                   exit_status=result.returncode, started=started,
                                   seconds=time.monotonic() - begun))
        if result.returncode == 0:
            continue
        # A check may give its reasons on either stream, as a Git hook may.
        reasons = [line.removeprefix("REFUSED: ")
                   for line in (result.stderr + result.stdout).splitlines() if line.strip()]
        findings.extend(reasons or [f"the pre-push check {script} exited with status "
                                    f"{result.returncode}"])
    return findings


def main(argv: Sequence[str] | None = None, root: Path | None = None,
         environ: Mapping[str, str] = os.environ) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("check", "push"))
    args = parser.parse_args(argv)
    try:
        root = repository_root() if root is None else root
    except StepError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    target, problems = check(root)
    if problems:
        for problem in problems:
            print(f"REFUSED: {problem}", file=sys.stderr)
        print("Nothing was pushed, and nothing was changed to make the check pass.",
              file=sys.stderr)
        return 1
    assert target is not None
    invoked: list[Invoked] = []
    findings = pre_push_findings(root, target, invoked)
    # Kept for the line of the session pushing, whatever the checks found; a failure
    # to keep it is the record's, and refuses no push.
    try:
        keep_invocations(invocations_directory(root), environ.get(SESSION_ID),
                         [entry.entry() for entry in invoked])
    except (OSError, StepError) as exc:
        print(f"WARNING: the pre-push checks run could not be kept for the session's line: "
              f"{exc}", file=sys.stderr)
    if findings:
        for finding in findings:
            print("REFUSED: " + finding, file=sys.stderr)
        return 1
    if args.action == "check":
        upstream = "no upstream yet; the push sets it" if target.set_upstream else "upstream matches"
        print(f"Ready to push {target.branch} to {target.remote} ({upstream}).")
        return 0
    print("+ " + " ".join(target.command()), flush=True)
    # Git's own status, which may be any number, becomes a failed push's 1, named on
    # standard error, since Git or a hook may fail without saying why.
    status = subprocess.run(target.command(), cwd=root).returncode
    if status == 0:
        return 0
    print(f"ERROR: git push exited with status {status}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
