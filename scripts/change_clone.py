#!/usr/bin/env python3
"""Create a change's own clone of the owner's workspace, and read its state.

A change is worked in a clone of the owner's workspace under one sibling
directory, `<workspace>.changes/<change>/`, holding the change's branch, its
records, environments, evidence, and step sessions. A clone rather than a
worktree, because a clone has refs of its own: the branch can be checked out in
the clone and, for reading a round, in the workspace at the same time. A local
clone hard-links its objects.

`create`, run in the workspace, takes the clone through five steps, each
recognised from what is on disk, so a rerun finishes whatever an interrupted one
left and never reclones:

1. clone the workspace, without a checkout, its remote named `workspace` — how
   every script in the clone finds the workspace;
2. set `origin` to the workspace's `origin` URL, so the push guard's upstream of
   the same name holds;
3. check out the branch: the existing one at its furthest point between the
   workspace and `origin`, or a new one from `--from`, refusing a branch whose two
   copies have diverged; it tracks `origin`'s branch when there is one and never
   the workspace's, so no push goes to the workspace;
4. link `.claude/settings.local.json` to the workspace's, so the owner's local
   permissions have one source;
5. start the bootstrap, `make init`, in the background, recording in the clone's
   Git directory its process and log while it runs, then its exit status.

A directory that is not a clone of the workspace, a clone with another branch
checked out, and one with uncommitted changes are refused, naming the directory,
and nothing is deleted: each means someone else's work is there. A rerun restarts
a failed bootstrap and leaves a running or succeeded one alone; a failed one is
never retried by itself, since `make init` failing is almost always the
environment, and a silent retry would hide it.

`remove`, run by the owner in the workspace once the change has merged, deletes
the clone. It copies the change's history into the workspace first
(`change_history.py`), then refuses, deleting nothing and naming each problem,
unless every file of that history is in the workspace with the clone's contents,
the branch is merged into `origin`'s `dev`, and the clone holds no commit `origin`
lacks, no uncommitted change, no stash, and no run in progress: anything else would
be lost with it.

`clone_of` and `bootstrap_state` are what the next-step computation and the round
view read; `workspace_of`, which `find_change.py` defines, tells a clone from any
other checkout. Importing the module does nothing.

Contract: openspec/specs/change-workflow/spec.md, "Each change is worked in its
own clone".
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from change_history import HistoryError, Synced, differences, report, sync
from change_workflow.running import runs_in_progress
from find_change import WORKSPACE_REMOTE, workspace_of

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FROM = "dev"
BOOTSTRAP_COMMAND = ("make", "init")
SETTINGS = Path(".claude/settings.local.json")
# In the clone's Git directory: which change and branch the clone was made for,
# the bootstrap's process and log, and its exit status once it has one.
MARKER = "change-clone.json"
BOOTSTRAP = "change-bootstrap.json"
BOOTSTRAP_LOG = "change-bootstrap.log"
BOOTSTRAP_STATUS = "change-bootstrap.status"
RUNNING, SUCCEEDED, FAILED, ABSENT = "running", "succeeded", "failed", "absent"

# Starts `command` in `cwd` detached from this process, its output to `log` and
# its exit status to `status` once it ends, and returns its process id.
Spawn = Callable[[Sequence[str], Path, Path, Path], int]


class CloneError(RuntimeError):
    """The clone was refused or could not be made; nothing was deleted."""


class RemovalRefused(CloneError):
    """The clone holds what deleting it would lose; its history was copied all the same."""

    def __init__(self, message: str, synced: Synced) -> None:
        super().__init__(message)
        self.synced = synced


@dataclass(frozen=True)
class Bootstrap:
    state: str
    log: Path | None


@dataclass(frozen=True)
class Created:
    clone: Path
    branch: str
    done: tuple[str, ...]
    bootstrap: Bootstrap


@dataclass(frozen=True)
class Removed:
    clone: Path
    synced: Synced


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise CloneError(f"git {' '.join(args)} failed in {cwd}: "
                         f"{(result.stderr or result.stdout).strip()}")
    return result


def _git_path(checkout: Path, name: str) -> Path:
    path = Path(_git(checkout, "rev-parse", "--git-path", name).stdout.strip())
    return path if path.is_absolute() else checkout / path


def default_branch(change: str) -> str:
    return f"feat/{change}"


def clone_directory(workspace: Path, change: str) -> Path:
    """`<workspace>.changes/<change>/`, beside the workspace rather than inside it:
    the scripts' tree walkers ignore `.gitignore`, so a clone nested in the
    workspace would be relocked and scanned as part of it."""
    workspace = workspace.resolve()
    return workspace.parent / f"{workspace.name}.changes" / change


def _check_name(change: str) -> None:
    if not change or change == "archive" or "/" in change or change.startswith("."):
        raise CloneError(f"{change!r} is not a change name")


def _toplevel(directory: Path) -> Path | None:
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=directory,
                            capture_output=True, text=True)
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else None


def _remote_url(checkout: Path, remote: str) -> str | None:
    result = _git(checkout, "remote", "get-url", remote, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _is_clone_of(directory: Path, workspace: Path) -> bool:
    return (_toplevel(directory) == directory.resolve()
            and workspace_of(directory) == workspace.resolve())


def _marker(clone: Path) -> dict[str, str]:
    path = _git_path(clone, MARKER)
    if not path.is_file():
        return {}
    try:
        recorded = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError:
        return {}
    return recorded if isinstance(recorded, dict) else {}


def _checked_out(clone: Path) -> bool:
    # A clone made without a checkout has no index until its branch is checked
    # out, so its empty worktree is never read as every file deleted.
    return _git_path(clone, "index").is_file()


def _current_branch(checkout: Path) -> str:
    return _git(checkout, "branch", "--show-current").stdout.strip()


def clone_of(workspace: Path, change: str) -> Path | None:
    """The change's clone when it exists, is a clone of `workspace`, and has the
    change's branch checked out; None otherwise."""
    directory = clone_directory(workspace, change)
    if not directory.is_dir() or not _is_clone_of(directory, workspace):
        return None
    branch = _marker(directory).get("branch") or default_branch(change)
    if not _checked_out(directory) or _current_branch(directory) != branch:
        return None
    return directory


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def bootstrap_state(clone: Path, alive: Callable[[int], bool] = _alive) -> Bootstrap:
    """`succeeded` or `failed` once the bootstrap recorded its exit status;
    `running` while its recorded process is alive; `failed` too for a process
    that died without recording one; `absent` when none was started."""
    status = _git_path(clone, BOOTSTRAP_STATUS)
    record = _git_path(clone, BOOTSTRAP)
    log = _git_path(clone, BOOTSTRAP_LOG)
    if status.is_file():
        text = status.read_text("utf-8").strip()
        return Bootstrap(SUCCEEDED if text == "0" else FAILED, log)
    if not record.is_file():
        return Bootstrap(ABSENT, None)
    try:
        pid = json.loads(record.read_text("utf-8")).get("pid")
    except (json.JSONDecodeError, AttributeError):
        pid = None
    if isinstance(pid, int) and not isinstance(pid, bool) and alive(pid):
        return Bootstrap(RUNNING, log)
    return Bootstrap(FAILED, log)


# The supervisor's first act records its own process, before the command starts,
# so a rerun after the spawning process is interrupted reads the bootstrap as
# started. Only a rerun that read the clone between the spawn and that first act
# would start a second one, and a rerun's Git checks on the clone, which `create`
# runs before it reads the bootstrap, take far longer than a shell's first command.
# The record and the status each go through a temporary file, so neither is ever
# read half-written.
_SUPERVISOR = ('log=$1; status=$2; record=$3; fields=$4; shift 4; '
               'printf \'{"pid": %s, %s\\n\' "$$" "$fields" >"$record.$$.tmp" '
               '&& mv "$record.$$.tmp" "$record"; '
               '"$@" >"$log" 2>&1; code=$?; '
               'printf "%s\\n" "$code" >"$status.tmp" && mv "$status.tmp" "$status"')


def _record_fields(command: Sequence[str], log: Path) -> dict[str, object]:
    return {"command": list(command), "log": str(log),
            "started": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def _spawn(command: Sequence[str], cwd: Path, log: Path, status: Path) -> int:
    # Run from `make change-clone`, the bootstrap would otherwise run under that
    # make's flags, as a sub-make of it.
    environment = {key: value for key, value in os.environ.items()
                   if key not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES")}
    # The record sits beside the status, in the clone's Git directory.
    record = status.with_name(BOOTSTRAP)
    fields = json.dumps(_record_fields(command, log))[1:]
    process = subprocess.Popen(["sh", "-c", _SUPERVISOR, "sh", str(log), str(status),
                                str(record), fields, *command], cwd=cwd, env=environment,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    return process.pid


def start_bootstrap(clone: Path, command: Sequence[str] = BOOTSTRAP_COMMAND,
                    spawn: Spawn = _spawn) -> Bootstrap:
    """Start the bootstrap, forgetting a failed one's record and status first."""
    status = _git_path(clone, BOOTSTRAP_STATUS)
    log = _git_path(clone, BOOTSTRAP_LOG)
    record = _git_path(clone, BOOTSTRAP)
    status.unlink(missing_ok=True)
    record.unlink(missing_ok=True)
    pid = spawn(command, clone, log, status)
    if not record.is_file():
        # The supervisor has not run yet, or the spawn is one that writes no
        # record; the pid is the same either way.
        aside = record.with_name(f"{BOOTSTRAP}.{os.getpid()}.tmp")
        aside.write_text(json.dumps({"pid": pid, **_record_fields(command, log)}), "utf-8")
        aside.replace(record)
    return bootstrap_state(clone)


def _remote_branches(clone: Path, names: Sequence[str]) -> set[str]:
    """Which of `names` are branches on `origin`, fetched as `origin/<name>`."""
    listed = _git(clone, "ls-remote", "--heads", "origin",
                  *(f"refs/heads/{name}" for name in names), check=False)
    if listed.returncode != 0:
        raise CloneError(f"could not read origin's branches from {clone}: "
                         f"{listed.stderr.strip()}")
    found = {line.split("\t", 1)[1].removeprefix("refs/heads/")
             for line in listed.stdout.splitlines() if "\t" in line}
    for name in sorted(found):
        _git(clone, "fetch", "--quiet", "origin",
             f"+refs/heads/{name}:refs/remotes/origin/{name}")
    return found


def _ref(clone: Path, ref: str) -> str | None:
    result = _git(clone, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _ancestor(clone: Path, ancestor: str, commit: str) -> bool:
    return _git(clone, "merge-base", "--is-ancestor", ancestor, commit,
                check=False).returncode == 0


def _merged(clone: Path, head: str, into: str) -> bool:
    """Whether `into` holds all that `head` brings.

    A squash or rebase merge leaves `head` no ancestor of `into`, so the content is
    compared instead: merging `head` into `into` must apply cleanly and change
    nothing. A later commit on `into` that undid part of `head` reads as not merged,
    the safe way to be wrong before deleting.
    """
    if _ancestor(clone, head, into):
        return True
    merge = _git(clone, "merge-tree", "--write-tree", into, head, check=False)
    tree = _git(clone, "rev-parse", f"{into}^{{tree}}").stdout.strip()
    return merge.returncode == 0 and merge.stdout.strip() == tree


def _furthest(clone: Path, name: str, on_origin: set[str]) -> tuple[str, str] | None:
    """`name` at its furthest point among the workspace's branch and `origin`'s, as
    (ref, commit); refused when the two have diverged, since either could be meant."""
    candidates = [(ref, commit) for ref in (f"refs/remotes/{WORKSPACE_REMOTE}/{name}",
                                            *([f"refs/remotes/origin/{name}"]
                                              if name in on_origin else []))
                  if (commit := _ref(clone, ref))]
    if not candidates:
        return None
    (ref, commit), *rest = candidates
    for other_ref, other in rest:
        if other == commit or _ancestor(clone, other, commit):
            continue
        if _ancestor(clone, commit, other):
            ref, commit = other_ref, other
            continue
        raise CloneError(f"{name} has diverged between the workspace ({commit[:12]}) and "
                         f"origin ({other[:12]}); reconcile them, then run this again")
    return ref, commit


def _uncommitted(clone: Path) -> list[str]:
    status = _git(clone, "status", "--porcelain", "--untracked-files=all")
    return [line for line in status.stdout.splitlines() if line.strip()]


def _check_out(clone: Path, branch: str, from_ref: str) -> None:
    # The workspace's branches as they are now, not as they were when the clone
    # was made: a rerun after the owner reconciled a diverged branch reads that.
    _git(clone, "fetch", "--quiet", "--prune", WORKSPACE_REMOTE)
    on_origin = _remote_branches(clone, [branch, from_ref])
    existing = _furthest(clone, branch, on_origin)
    if existing is not None:
        start = existing[1]
    else:
        start_from = _furthest(clone, from_ref, on_origin)
        start = start_from[1] if start_from else _ref(clone, from_ref)
        if start is None:
            raise CloneError(f"{branch} does not exist, and --from {from_ref} names no "
                             "branch of the workspace or origin, nor a commit")
    # No index yet: nothing was ever checked out here, so the worktree holds no
    # tracked work for the forced checkout to overwrite.
    _git(clone, "checkout", "--quiet", "--force", "--no-track", "-B", branch, start)


def _settle_upstreams(clone: Path, branch: str) -> None:
    """No branch of the clone tracks the workspace, so the push guard, which pushes
    a branch to its upstream's remote, never pushes into the owner's workspace.

    Run on every pass, not only after the checkout, so a run interrupted between
    the checkout and this is finished by the next.
    """
    if _remote_url(clone, "origin") and _ref(clone, f"refs/remotes/origin/{branch}"):
        _git(clone, "branch", "--quiet", f"--set-upstream-to=origin/{branch}", branch)
    elif _git(clone, "config", f"branch.{branch}.remote", check=False).stdout.strip():
        _git(clone, "branch", "--quiet", "--unset-upstream", branch)
    tracking = _git(clone, "for-each-ref", "--format=%(refname:short) %(upstream:remotename)",
                    "refs/heads/").stdout.splitlines()
    for name, _, remote in (line.partition(" ") for line in tracking):
        if remote == WORKSPACE_REMOTE and name != branch:
            # The branch `git clone` made, a copy of the workspace's: the safe delete
            # drops it, and one it refuses, holding commits its upstream lacks, is
            # kept without the upstream.
            if _git(clone, "branch", "--quiet", "-d", name, check=False).returncode != 0:
                _git(clone, "branch", "--quiet", "--unset-upstream", name)


def create(workspace: Path, change: str, *, branch: str | None = None,
           from_ref: str = DEFAULT_FROM, bootstrap: Sequence[str] = BOOTSTRAP_COMMAND,
           spawn: Spawn = _spawn) -> Created:
    """Create the change's clone, or finish one an interrupted run left."""
    _check_name(change)
    workspace = workspace.resolve()
    if workspace_of(workspace) is not None:
        raise CloneError(f"{workspace} is itself a change's clone; run this in the owner's "
                         "workspace")
    origin = _remote_url(workspace, "origin")
    if not origin:
        raise CloneError(f"the workspace {workspace} has no origin remote, which the clone's "
                         "pushes go to")
    target = clone_directory(workspace, change)
    done: list[str] = []

    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        if not target.is_dir() or not _is_clone_of(target, workspace):
            raise CloneError(f"{target} exists and is not a clone of {workspace}; nothing was "
                             "deleted")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        _git(workspace, "clone", "--quiet", "--no-checkout", "--origin", WORKSPACE_REMOTE,
             str(workspace), str(target))
        done.append("cloned")

    recorded = _marker(target)
    if recorded.get("change") not in (None, change):
        raise CloneError(f"{target} is the clone of {recorded['change']}, not {change}; "
                         "nothing was deleted")
    if branch and recorded.get("branch") not in (None, branch):
        raise CloneError(f"{target} holds {recorded['branch']}, not {branch}; nothing was "
                         "deleted")
    branch = branch or recorded.get("branch") or default_branch(change)

    # What is already in the clone is refused before anything is written to it.
    current_origin = _remote_url(target, "origin")
    if current_origin not in (None, origin):
        raise CloneError(f"{target}'s origin is {current_origin}, not the workspace's "
                         f"{origin}; nothing was changed")
    checked_out = _checked_out(target)
    if checked_out:
        current = _current_branch(target)
        if current != branch:
            raise CloneError(f"{target} has {current or 'a detached HEAD'} checked out, not "
                             f"{branch}; nothing was deleted")
        # Settled even in a clone refused below: it touches only upstreams and the
        # branch `git clone` made, never work, and a branch left tracking the
        # workspace would push into it.
        _settle_upstreams(target, branch)
        if dirty := _uncommitted(target):
            raise CloneError(f"{target} has uncommitted changes; nothing was deleted:\n"
                             + "\n".join(dirty))

    if current_origin is None:
        _git(target, "remote", "add", "origin", origin)
        done.append("remotes")
    if not checked_out:
        _check_out(target, branch, from_ref)
        _settle_upstreams(target, branch)
        done.append("branch")
    if not recorded:
        # Recorded once the branch is checked out, so a run refused before that
        # leaves another `--branch` free to be asked for.
        _git_path(target, MARKER).write_text(json.dumps({"change": change, "branch": branch}),
                                             "utf-8")

    link = target / SETTINGS
    wanted = workspace / SETTINGS
    if link.is_symlink() and Path(os.readlink(link)) == wanted:
        pass
    elif link.exists() or link.is_symlink():
        raise CloneError(f"{link} exists and is not the link to {wanted}; nothing was "
                         "deleted")
    else:
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(wanted)
        done.append("settings")

    state = bootstrap_state(target)
    if state.state in (ABSENT, FAILED):
        state = start_bootstrap(target, bootstrap, spawn)
        done.append("bootstrap")
    return Created(target, branch, tuple(done), state)


def _left_behind(clone: Path, branch: str) -> list[str]:
    """What deleting the clone would lose beyond its history: a branch not merged,
    commits `origin` lacks, a stash, uncommitted changes."""
    _git(clone, "fetch", "--quiet", "--prune", "origin")
    merged_into = f"refs/remotes/origin/{DEFAULT_FROM}"
    problems = []
    head = _ref(clone, f"refs/heads/{branch}")
    if head is None:
        problems.append(f"{branch} is not a branch of the clone, so its merge cannot be shown")
    elif _ref(clone, merged_into) is None or not _merged(clone, head, merged_into):
        problems.append(f"{branch} is not merged into origin/{DEFAULT_FROM}")
    unpushed = _git(clone, "rev-list", "--branches", "--not", "--remotes=origin").stdout.split()
    if unpushed:
        problems.append(f"{len(unpushed)} commit(s) origin lacks, the latest "
                        f"{unpushed[0][:12]}")
    if _ref(clone, "refs/stash"):
        problems.append("a stash")
    if dirty := _uncommitted(clone):
        problems.append("uncommitted changes:\n" + "\n".join(f"  {line}" for line in dirty))
    return problems


def remove(workspace: Path, change: str) -> Removed:
    """Delete the change's clone, copying its history into the workspace first, once
    nothing in the clone would be lost with it."""
    _check_name(change)
    workspace = workspace.resolve()
    if workspace_of(workspace) is not None:
        raise CloneError(f"{workspace} is itself a change's clone; run this in the owner's "
                         "workspace")
    target = clone_directory(workspace, change)
    if not target.is_dir() or not _is_clone_of(target, workspace):
        raise CloneError(f"{target} is not a clone of {workspace}; nothing was deleted")
    recorded = _marker(target)
    if recorded.get("change") not in (None, change):
        raise CloneError(f"{target} is the clone of {recorded['change']}, not {change}; "
                         "nothing was deleted")
    if runs := runs_in_progress(target):
        raise CloneError(f"{target} has a run in progress, so nothing was deleted: "
                         + "; ".join(run.describe() for run in runs))
    if bootstrap_state(target).state == RUNNING:
        raise CloneError(f"{target}'s bootstrap is still running; nothing was deleted")
    try:
        synced = sync(target, workspace, change)
        missing = differences(target, workspace, change)
    except HistoryError as exc:
        raise CloneError(f"{exc}; nothing was deleted") from exc
    problems = [f"history: {line}" for line in missing]
    try:
        problems += _left_behind(target, recorded.get("branch") or default_branch(change))
    except CloneError as exc:
        problems.append(str(exc))
    if problems:
        raise RemovalRefused(f"{target} holds what deleting it would lose, or could not "
                             "be shown not to, so nothing was deleted:\n"
                             + "\n".join(f"- {problem}" for problem in problems), synced)
    try:
        shutil.rmtree(target)
    except OSError as exc:
        raise RemovalRefused(f"{target} was only partly deleted: {exc}; its history is "
                             "in the workspace, and what is left holds nothing else",
                             synced) from exc
    return Removed(target, synced)


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    actions = parser.add_subparsers(dest="action", required=True)
    creating = actions.add_parser("create", help="create or finish a change's clone")
    creating.add_argument("change")
    creating.add_argument("--branch", default=None,
                          help="the change's branch; feat/<change> by default")
    creating.add_argument("--from", dest="from_ref", default=DEFAULT_FROM,
                          help="where a new branch starts; dev by default")
    removing = actions.add_parser("remove", help="delete a merged change's clone once its "
                                  "history is in the workspace")
    removing.add_argument("change")
    args = parser.parse_args(argv)
    if args.action == "remove":
        try:
            removed = remove(root, args.change)
        except RemovalRefused as error:
            print(report(error.synced, root.resolve()))
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        except CloneError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print(report(removed.synced, root.resolve()))
        print(f"Removed the clone of {args.change}: {removed.clone}.")
        return 0
    try:
        created = create(root, args.change, branch=args.branch or None,
                         from_ref=args.from_ref or DEFAULT_FROM)
    except CloneError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Clone of {args.change}: {created.clone}, on {created.branch}.")
    print("Done now: " + ", ".join(created.done) if created.done else "Nothing left to do.")
    log = f" (log: {created.bootstrap.log})" if created.bootstrap.log else ""
    print(f"Bootstrap: {created.bootstrap.state}{log}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
