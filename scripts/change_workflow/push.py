"""Check that HEAD may be pushed unattended to its own branch, and push it.

An unattended push needs a mechanical definition of "the change's own branch".
HEAD must be attached to a branch none of the workflow configuration's
`repository.protected-branches`, the worktree must be clean, untracked files
included, and the branch's upstream, if it has one, must be the branch of the same
name. The push goes to the upstream's remote, or the remote `--remote` names; a
branch with no upstream is pushed to the same name on the remote given and the
upstream set, and refused with none given. A change's clone gives its new branch
its upstream as it is made, so its first push needs no argument.

The check reports and never repairs: each refused state means something
unexpected happened, and fixing it automatically would hide that. The push sends
exactly HEAD and is never forced, so a remote branch that has moved on rejects it.

Before either action reports success, the configuration's `pre-push` hook reads what
the push would send, and may refuse it. Each of its commands runs through the hook
runner (`hooks`) as Git runs a pre-push hook: the remote as `{remote}`, and one line
on standard input naming the branch, `HEAD`, and an all-zero remote object, so it
reads every commit the remote's refs lack. Its output goes to standard error, where
its reasons belong, leaving standard output to the check's own report. Every
command runs whatever another reports, so one refusal names every reason. With no
`pre-push` declared, the push goes ahead once its own check passes. Each command
run is kept, as `pre-push`, for the line of the session pushing, with the command
it resolved to and its exit status.

Contract: openspec/specs/change-workflow/spec.md, CW-59c7, CW-p7kq, CW-q5fy;
openspec/specs/market-change-workflow/spec.md, MCW-farr, MCW-q8vd.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from . import config
from .common import SESSION_ID, StepError, repository_root
from .find import WORKSPACE_REMOTE
from .hooks import Hooks, Invoked, command_environment
from .running import invocations_directory, keep_invocations

PRE_PUSH = "pre-push"
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


def check(root: Path, protected: Sequence[str],
          remote: str | None = None) -> tuple[PushTarget | None, list[str]]:
    """The push HEAD may receive, or every reason it may not be pushed; `protected`
    the branches no step pushes, and `remote` the remote given for this push, in
    place of the upstream's."""
    problems: list[str] = []
    if remote in (WORKSPACE_REMOTE, "."):
        # A change's clone names the owner's workspace by this remote, and a step
        # pushes nothing into the owner's workspace.
        problems.append(f"{remote} is no remote a change's branch is pushed to")
    attached = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    branch = attached.stdout.strip() if attached.returncode == 0 else ""
    if not branch:
        problems.append("HEAD is detached; check out the change's branch")
    elif branch in protected:
        problems.append(f"{branch} is a protected branch; a step pushes only a change's "
                        "own branch")

    status = _git(root, "status", "--porcelain", "--untracked-files=all")
    if status.returncode != 0:
        problems.append(f"git status failed: {status.stderr.strip()}")
    elif status.stdout.strip():
        problems.append("the worktree is not clean:\n" + status.stdout.rstrip())

    target = None
    if branch:
        tracked = _git(root, "config", f"branch.{branch}.remote").stdout.strip()
        merge = _git(root, "config", f"branch.{branch}.merge").stdout.strip()
        if not tracked and not merge:
            if remote:
                target = PushTarget(branch, remote, set_upstream=True)
            else:
                problems.append(f"{branch} has no upstream, so the remote to push to is "
                                "unknown; give it with --remote <remote>")
        elif merge != f"refs/heads/{branch}" or not tracked or tracked == ".":
            upstream = (f"{tracked}/{merge.removeprefix('refs/heads/')}" if tracked and merge
                        else tracked or merge)
            problems.append(f"{branch} tracks {upstream}, not a branch of its own name")
        else:
            target = PushTarget(branch, remote or tracked, set_upstream=False)
    return (None if problems else target), problems


def _fed(line: str):
    """A hook command run with `line` on its standard input, as Git feeds a pre-push
    hook, its output, both streams in order, written to standard error."""
    def run(command: str, root: Path) -> int:
        result = subprocess.run(["sh", "-c", command], cwd=root, input=line, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                env=command_environment())
        sys.stderr.write(result.stdout)
        sys.stderr.flush()
        return result.returncode
    return run


def pre_push(root: Path, configuration: config.Configuration, target: PushTarget,
             environ: Mapping[str, str]) -> tuple[bool, list[Invoked]]:
    """Run the configuration's `pre-push` on what the push would send: whether it
    passed, a hook not declared passing, and every command it ran."""
    head = _git(root, "rev-parse", "--verify", "HEAD").stdout.strip()
    ref = f"refs/heads/{target.branch}"
    hooks = Hooks(root, configuration, environ,
                  shell=_fed(f"{ref} {head} {ref} {_NO_OBJECT}\n"),
                  echo=lambda shown: print(shown, file=sys.stderr, flush=True))
    try:
        passed = hooks.engine_hook(PRE_PUSH, {"remote": target.remote})
    except StepError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        passed = False
    return passed, hooks.invoked


def main(argv: Sequence[str] | None = None, root: Path | None = None,
         environ: Mapping[str, str] = os.environ) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("check", "push"))
    parser.add_argument("--remote", default=None,
                        help="the remote to push to, in place of the branch's upstream's")
    args = parser.parse_args(argv)
    try:
        root = repository_root() if root is None else root
        configuration = config.load(root)
        config.require(configuration, config.PROTECTED_BRANCHES, needed_by="the guarded push")
    except StepError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    target, problems = check(root, configuration.protected_branches or (), args.remote)
    if problems:
        for problem in problems:
            print(f"REFUSED: {problem}", file=sys.stderr)
        print("Nothing was pushed, and nothing was changed to make the check pass.",
              file=sys.stderr)
        return 1
    assert target is not None
    passed, invoked = pre_push(root, configuration, target, environ)
    # Kept for the line of the session pushing, whatever the hook found; a failure to
    # keep it is the record's, and refuses no push.
    try:
        keep_invocations(invocations_directory(root), environ.get(SESSION_ID),
                         [entry.entry() for entry in invoked])
    except (OSError, StepError) as exc:
        print(f"WARNING: the pre-push hook's commands could not be kept for the session's "
              f"line: {exc}", file=sys.stderr)
    if not passed:
        print("REFUSED: the repository's pre-push hook refused the push; nothing was pushed.",
              file=sys.stderr)
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
