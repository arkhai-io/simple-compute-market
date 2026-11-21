"""Check that HEAD may be pushed unattended to its own branch, and push it.

An unattended push needs a mechanical definition of "the change's own branch".
HEAD must be attached to a branch none of the workflow configuration's
`repository.protected-branches`, the worktree must be clean, untracked files
included, and the branch's upstream, if it has one, must be the branch of the same
name. The push goes to the upstream's remote, or the remote `--remote` names; a
branch with no upstream is pushed to the same name on the remote given and the
upstream set, and refused with none given. A change's clone gives its new branch
its upstream as it is made, so its first push needs no argument.

Under an unattended run the push differs in three ways. Its `git push` carries the
guarded push's marker (`GUARDED_PUSH`), so the engine's `git`, which the sandbox
mounts over the system's, lets it through while refusing every other push. It sets
no upstream, since the sandbox keeps `.git/config` read-only: once the session ends,
the engine sets a missing upstream outside the sandbox (`set_upstreams`), to the
remote of the run's last successful push of that branch. And each push it attempts is
kept for the session's line once Git returns (`ATTEMPTED_PUSH`): its branch, its
remote, the commit sent, and Git's exit status, which is what the engine reads
to set the upstream and the check after the run reads to tell the guarded push's
moves of the remote from any other.

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

Contract: openspec/specs/change-workflow/spec.md, CW-59c7, CW-p7kq, CW-q5fy, CW-j4cs;
openspec/specs/market-change-workflow/spec.md, MCW-farr, MCW-q8vd.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import config
from .common import (GUARDED_PUSH, SESSION_ID, UNATTENDED_RUN, Clock, StepError,
                     repository_root, utc_now)
from .find import WORKSPACE_REMOTE
from .hooks import Hooks, Invoked, command_environment
from .running import ATTEMPTED_PUSH, invocations_directory, keep_invocations

PRE_PUSH = "pre-push"
_NO_OBJECT = "0" * 40


@dataclass(frozen=True)
class PushTarget:
    branch: str
    remote: str
    set_upstream: bool

    def command(self) -> list[str]:
        return ["git", "push", *(["--set-upstream"] if self.set_upstream else []),
                self.remote, f"refs/heads/{self.branch}:refs/heads/{self.branch}"]


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


def _upstream(root: Path, branch: str) -> tuple[str, str]:
    """The remote and the merge ref `branch`'s upstream names, each empty where unset."""
    return (_git(root, "config", f"branch.{branch}.remote").stdout.strip(),
            _git(root, "config", f"branch.{branch}.merge").stdout.strip())


def set_upstreams(root: Path, invoked: Sequence[Mapping[str, Any]]) -> list[str]:
    """Give each branch the guarded push pushed with no upstream, as the session's
    `invoked` record it, the upstream of its own name on the remote of its last
    successful push, and none where no push of it succeeded; what was set, each as
    `<branch> -> <remote>/<branch>`. Run once the session has ended, outside the
    sandbox, which keeps `.git/config` read-only for the session (CW-59c7)."""
    remotes: dict[str, str] = {}
    for entry in invoked:
        if entry.get("hook") == ATTEMPTED_PUSH and entry.get("exit_status") == 0:
            remotes[str(entry["branch"])] = str(entry["remote"])
    done = []
    for branch, remote in remotes.items():
        if _upstream(root, branch) != ("", ""):
            continue
        for key, value in (("remote", remote), ("merge", f"refs/heads/{branch}")):
            if (found := _git(root, "config", f"branch.{branch}.{key}", value)).returncode:
                raise StepError(f"the upstream of {branch} could not be set to "
                                f"{remote}/{branch}: {found.stderr.strip()}")
        done.append(f"{branch} -> {remote}/{branch}")
    return done


def _keep(root: Path, environ: Mapping[str, str], entries: list[dict[str, Any]],
          what: str) -> None:
    """Keep `entries` for the line of the session pushing; a failure to keep them is the
    record's, and refuses no push."""
    try:
        keep_invocations(invocations_directory(root), environ.get(SESSION_ID), entries)
    except (OSError, StepError) as exc:
        print(f"WARNING: {what} could not be kept for the session's line: {exc}",
              file=sys.stderr)


def main(argv: Sequence[str] | None = None, root: Path | None = None,
         environ: Mapping[str, str] = os.environ, clock: Clock = utc_now) -> int:
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
    checked_target = target
    checked_head = _git(root, "rev-parse", "--verify", "HEAD").stdout.strip()
    unattended = bool(environ.get(UNATTENDED_RUN))
    untracked = target.set_upstream
    if unattended:
        target = replace(target, set_upstream=False)
    passed, invoked = pre_push(root, configuration, target, environ)
    # Kept whatever the hook found.
    _keep(root, environ, [entry.entry() for entry in invoked], "the pre-push hook's commands")
    if not passed:
        print("REFUSED: the repository's pre-push hook refused the push; nothing was pushed.",
              file=sys.stderr)
        return 1
    current_target, current_problems = check(
        root, configuration.protected_branches or (), args.remote,
    )
    head = _git(root, "rev-parse", "--verify", "HEAD").stdout.strip()
    if current_problems or current_target != checked_target or not checked_head or head != checked_head:
        print("REFUSED: the checked branch, target, tip or worktree changed during the pre-push hook; "
              "nothing was pushed.", file=sys.stderr)
        return 1
    if args.action == "check":
        upstream = ("upstream matches" if not untracked
                    else "no upstream yet; the engine sets it once the session ends" if unattended
                    else "no upstream yet; the push sets it")
        print(f"Ready to push {target.branch} to {target.remote} ({upstream}).")
        return 0
    command = target.command()
    print("+ " + " ".join(command), flush=True)
    started, begun = clock().strftime("%Y-%m-%dT%H:%M:%SZ"), time.monotonic()
    status = subprocess.run(command, cwd=root, env={**os.environ, GUARDED_PUSH: "1"}).returncode
    if unattended:
        _keep(root, environ, [{"hook": ATTEMPTED_PUSH, "command": " ".join(command),
                               "branch": target.branch, "remote": target.remote,
                               "commit": head, "exit_status": status, "started": started,
                               "seconds": round(time.monotonic() - begun, 3)}], "the push")
    # Git's own status, which may be any number, becomes a failed push's 1, named on
    # standard error, since Git or a hook may fail without saying why.
    if status == 0:
        return 0
    print(f"ERROR: git push exited with status {status}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
