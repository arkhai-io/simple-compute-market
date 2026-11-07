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
2. add the change's push remote — the remote the workspace's branch of the change
   tracks, else the one its landing branch tracks, as Git records them; the engine
   names no remote of its own — and the landing branch's upstream remote, each under
   its workspace name and URL, so the push guard's upstream of the same name holds;
3. check out the branch: the existing one at its furthest point between the
   workspace and the push remote, or a new one from the branch the change lands on,
   refusing a branch whose two copies have diverged; it tracks its branch of the
   same name on the push remote, so its first push goes there, and never the
   workspace's, so no push goes to the workspace; with no push remote it tracks
   nothing, and the guarded push refuses it;
4. link `.claude/settings.local.json` to the workspace's, so the owner's local
   permissions have one source;
5. start the bootstrap, the workflow configuration's `post-clone` as the clone's
   checkout declares it, in the background, recording in the clone's Git directory
   the commands it resolved to, its process and log while it runs, then its exit
   status; with no `post-clone` declared it succeeds at once, running nothing.

The branch the change lands on is the workspace's checked-out branch when the clone
is made, or `--from`; it is recorded in the clone's marker (`find.landing_branch`)
and kept on every rerun, so running orchestration again from another branch does not
move it.

A directory that is not a clone of the workspace, a clone with another branch
checked out, and one with uncommitted changes are refused, naming the directory,
and nothing is deleted: each means someone else's work is there. A rerun restarts
a failed bootstrap and leaves a running or succeeded one alone; a failed one is
never retried by itself, since a bootstrap failing is almost always the
environment, and a silent retry would hide it.

`remove`, run by the owner in the workspace once the change has merged, deletes
the clone. It copies the change's history into the workspace first
(`history`), then refuses, deleting nothing and naming each problem,
unless every file of that history is in the workspace with the clone's contents,
the branch is merged into the branch the change lands on on its upstream's remote,
and the clone holds no commit that remote lacks, no uncommitted change, no stash,
and no run in progress: anything else would be lost with it. A branch given
(`--base`) overrides the recorded one for the removal; a clone whose marker records
none is removed only with one given, refused before anything is copied without it.

`clone_of` and `bootstrap_state` are what the next-step computation and the round
view read; `where` is what `clone where` answers, a usable clone told apart from
none and from one that cannot be used; `workspace_of`, which `find` defines, tells
a clone from any other checkout. Importing the module does nothing.

Contract: openspec/specs/change-workflow/spec.md, CW-yib2, CW-8jyb, CW-8npg, and
CW-xx5f; openspec/specs/market-change-workflow/spec.md, MCW-uqlq.
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

from . import config
from .common import StepError, repository_root
from .find import CLONE_MARKER, WORKSPACE_REMOTE, clone_directory, clone_marker, workspace_of
from .history import HistoryError, Synced, differences, report, sync
from .running import runs_in_progress

POST_CLONE = "post-clone"
SETTINGS = Path(".claude/settings.local.json")
# In the clone's Git directory: which change and branch the clone was made for and
# the branch it lands on (`find`), the bootstrap's process and log, and its exit
# status once it has one.
MARKER = CLONE_MARKER
BOOTSTRAP = "change-bootstrap.json"
BOOTSTRAP_LOG = "change-bootstrap.log"
BOOTSTRAP_STATUS = "change-bootstrap.status"
RUNNING, SUCCEEDED, FAILED, ABSENT = "running", "succeeded", "failed", "absent"

# Starts the bootstrap's shell commands in `cwd` detached from this process, as a
# hook's list runs (`bootstrap_command`), recording them, its output to `log` and its
# exit status to `status` once it ends, and returns its process id.
Spawn = Callable[[Sequence[str], Path, Path, Path], int]
# The bootstrap's commands as the clone's checkout declares them, unfilled; None when
# it declares no `post-clone`.
PostClone = Callable[[Path], Sequence[str] | None]


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
    return clone_marker(clone)


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


def where(workspace: Path, change: str) -> Path | None:
    """The change's clone of `workspace`, once it is usable: a clone of the workspace,
    with the change's branch checked out and its bootstrap succeeded. None when no
    clone directory exists, so the change is worked in place.

    A clone directory that exists but is not usable raises `CloneError`, naming why,
    so neither a broken clone nor a misspelled name is taken for a change worked in
    place.
    """
    _check_name(change)
    directory = clone_directory(workspace, change)
    if not directory.exists():
        return None
    if not directory.is_dir() or not _is_clone_of(directory, workspace):
        raise CloneError(f"{directory} is not a clone of {workspace.resolve()}")
    branch = _marker(directory).get("branch") or default_branch(change)
    if not _checked_out(directory) or _current_branch(directory) != branch:
        raise CloneError(f"{directory} does not have {branch} checked out")
    bootstrap = bootstrap_state(directory)
    if bootstrap.state != SUCCEEDED:
        log = f"; its log is {bootstrap.log}" if bootstrap.log else ""
        raise CloneError(f"{directory}'s bootstrap is {bootstrap.state}{log}")
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


def _configured_post_clone(clone: Path) -> Sequence[str] | None:
    """The `post-clone` the clone's checkout declares, which the bootstrap runs: the
    change's branch may change it, and the bootstrap prepares that branch."""
    return config.load(clone).hook(POST_CLONE)


def bootstrap_command(commands: Sequence[str]) -> list[str]:
    """One process running each of the hook's commands with `sh -c`, in order,
    whatever an earlier one reported, and exiting with the first failure's status,
    as a hook's list runs."""
    if len(commands) == 1:
        return ["sh", "-c", commands[0]]
    script = 'status=0; for command in "$@"; do sh -c "$command" || ' \
             '{ code=$?; [ "$status" -ne 0 ] || status=$code; }; done; exit "$status"'
    return ["sh", "-c", script, "sh", *commands]


def _spawn(commands: Sequence[str], cwd: Path, log: Path, status: Path) -> int:
    # Run from `make change-clone`, the bootstrap would otherwise run under that
    # make's flags, as a sub-make of it.
    environment = {key: value for key, value in os.environ.items()
                   if key not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES")}
    # The record sits beside the status, in the clone's Git directory.
    record = status.with_name(BOOTSTRAP)
    fields = json.dumps(_record_fields(commands, log))[1:]
    process = subprocess.Popen(["sh", "-c", _SUPERVISOR, "sh", str(log), str(status),
                                str(record), fields, *bootstrap_command(commands)], cwd=cwd,
                               env=environment, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    return process.pid


def start_bootstrap(clone: Path, commands: Sequence[str] | None,
                    spawn: Spawn = _spawn) -> Bootstrap:
    """Start the bootstrap running `commands`, the hook's resolved commands,
    forgetting a failed one's record and status first; with none, record it
    succeeded at once, having run nothing."""
    status = _git_path(clone, BOOTSTRAP_STATUS)
    log = _git_path(clone, BOOTSTRAP_LOG)
    record = _git_path(clone, BOOTSTRAP)
    status.unlink(missing_ok=True)
    record.unlink(missing_ok=True)
    if not commands:
        log.write_text(f"{config.CONFIGURATION.as_posix()} declares no {POST_CLONE} "
                       "commands, so the bootstrap ran nothing.\n", "utf-8")
        record.write_text(json.dumps({"pid": None, **_record_fields([], log)}), "utf-8")
        status.write_text("0\n", "utf-8")
        return bootstrap_state(clone)
    pid = spawn(commands, clone, log, status)
    if not record.is_file():
        # The supervisor has not run yet, or the spawn is one that writes no
        # record; the pid is the same either way.
        aside = record.with_name(f"{BOOTSTRAP}.{os.getpid()}.tmp")
        aside.write_text(json.dumps({"pid": pid, **_record_fields(commands, log)}), "utf-8")
        aside.replace(record)
    return bootstrap_state(clone)


def _remote_branches(clone: Path, remote: str | None, names: Sequence[str]) -> set[str]:
    """Which of `names` are branches on `remote`, the change's push remote, fetched as
    `<remote>/<name>`; none with no remote."""
    if remote is None:
        return set()
    listed = _git(clone, "ls-remote", "--heads", remote,
                  *(f"refs/heads/{name}" for name in names), check=False)
    if listed.returncode != 0:
        raise CloneError(f"could not read {remote}'s branches from {clone}: "
                         f"{listed.stderr.strip()}")
    found = {line.split("\t", 1)[1].removeprefix("refs/heads/")
             for line in listed.stdout.splitlines() if "\t" in line}
    for name in sorted(found):
        _git(clone, "fetch", "--quiet", remote,
             f"+refs/heads/{name}:refs/remotes/{remote}/{name}")
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


def _furthest(clone: Path, name: str, remote: str | None,
              on_remote: set[str]) -> tuple[str, str] | None:
    """`name` at its furthest point among the workspace's branch and `remote`'s, as
    (ref, commit); refused when the two have diverged, since either could be meant."""
    candidates = [(ref, commit) for ref in (f"refs/remotes/{WORKSPACE_REMOTE}/{name}",
                                            *([f"refs/remotes/{remote}/{name}"]
                                              if name in on_remote else []))
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
                         f"{remote} ({other[:12]}); reconcile them, then run this again")
    return ref, commit


def _uncommitted(clone: Path) -> list[str]:
    status = _git(clone, "status", "--porcelain", "--untracked-files=all")
    return [line for line in status.stdout.splitlines() if line.strip()]


def _check_out(clone: Path, branch: str, from_ref: str, remote: str | None) -> None:
    # The workspace's branches as they are now, not as they were when the clone
    # was made: a rerun after the owner reconciled a diverged branch reads that.
    _git(clone, "fetch", "--quiet", "--prune", WORKSPACE_REMOTE)
    on_remote = _remote_branches(clone, remote, [branch, from_ref])
    existing = _furthest(clone, branch, remote, on_remote)
    if existing is not None:
        start = existing[1]
    else:
        start_from = _furthest(clone, from_ref, remote, on_remote)
        start = start_from[1] if start_from else _ref(clone, from_ref)
        if start is None:
            where = f"the workspace or {remote}" if remote else "the workspace"
            raise CloneError(f"{branch} does not exist, and {from_ref}, the branch it lands "
                             f"on, names no branch of {where}, nor a commit")
    # No index yet: nothing was ever checked out here, so the worktree holds no
    # tracked work for the forced checkout to overwrite.
    _git(clone, "checkout", "--quiet", "--force", "--no-track", "-B", branch, start)


def _settle_upstreams(clone: Path, branch: str, remote: str | None) -> None:
    """The change's branch tracks its branch of the same name on `remote`, the
    change's push remote (`_push_remote`), so the guarded push, which pushes a branch
    to its upstream's remote, needs no fallback for the first push; with no remote it
    tracks nothing, and its push refuses. No branch of the clone tracks the
    workspace, so no push goes into the owner's workspace.

    Run on every pass, not only after the checkout, so a run interrupted between
    the checkout and this is finished by the next.
    """
    if remote and _remote_url(clone, remote) and _ref(clone, f"refs/remotes/{remote}/{branch}"):
        _git(clone, "branch", "--quiet", f"--set-upstream-to={remote}/{branch}", branch)
    elif remote and _remote_url(clone, remote):
        # The branch does not exist there yet, so Git's own --set-upstream-to, which
        # needs the remote-tracking ref, cannot name it.
        _git(clone, "config", f"branch.{branch}.remote", remote)
        _git(clone, "config", f"branch.{branch}.merge", f"refs/heads/{branch}")
    elif remote is None and _git(clone, "config", f"branch.{branch}.remote",
                                 check=False).stdout.strip():
        # A push remote not added to the clone yet leaves the upstream as it is: the
        # pass after the remote is added settles it.
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


def _upstream_remote(workspace: Path, name: str) -> str | None:
    """The remote the workspace's branch `name` tracks, when it is a branch that
    tracks one other than the workspace itself."""
    remote = _git(workspace, "config", f"branch.{name}.remote", check=False).stdout.strip()
    return remote if remote not in ("", ".", WORKSPACE_REMOTE) else None


def _push_remote(workspace: Path, branch: str, landing: str) -> str | None:
    """The remote the change's branch pushes to, as Git records it in the workspace:
    the change's branch's own upstream remote when the workspace has the branch and it
    tracks one, else the landing branch's. The engine names no remote of its own, so
    a workspace with no `origin` clones, and a fork's change branch tracking the fork
    keeps it while its landing branch tracks the repository it was forked from. An
    upstream naming a remote the workspace does not have is passed over, as if the
    branch tracked none."""
    return next((name for name in (_upstream_remote(workspace, branch),
                                   _upstream_remote(workspace, landing))
                 if name and _remote_url(workspace, name)), None)


def create(workspace: Path, change: str, *, branch: str | None = None,
           from_ref: str | None = None, bootstrap: PostClone = _configured_post_clone,
           spawn: Spawn = _spawn) -> Created:
    """Create the change's clone, or finish one an interrupted run left. The branch
    the change lands on is `from_ref`, or the workspace's checked-out branch. The
    bootstrap runs the `post-clone` the clone's checkout declares (`bootstrap`)."""
    _check_name(change)
    workspace = workspace.resolve()
    if workspace_of(workspace) is not None:
        raise CloneError(f"{workspace} is itself a change's clone; run this in the owner's "
                         "workspace")
    target = clone_directory(workspace, change)
    done: list[str] = []
    given = from_ref or _current_branch(workspace)
    unknown = (f"the workspace {workspace} has no branch checked out, so the branch the "
               "change lands on is unknown; give it with --from <branch>")
    if not given and not target.exists():
        raise CloneError(unknown)

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
    if from_ref and recorded.get("base") not in (None, from_ref):
        raise CloneError(f"{target} lands on {recorded['base']}, not {from_ref}; nothing was "
                         "changed")
    # The recorded landing branch stands, whichever branch the workspace has now.
    landing = recorded.get("base") or given
    if not landing:
        raise CloneError(unknown)
    remote = _push_remote(workspace, branch, landing)
    # The push remote, and the landing branch's upstream remote, which the merge
    # fetches the landing branch from, each under its workspace name and URL.
    wanted = {name: url
              for name in dict.fromkeys((remote, _upstream_remote(workspace, landing)))
              if name is not None and (url := _remote_url(workspace, name))}

    # What is already in the clone is refused before anything is written to it.
    for name, url in wanted.items():
        current_url = _remote_url(target, name)
        if current_url not in (None, url):
            raise CloneError(f"{target}'s {name} is {current_url}, not the workspace's "
                             f"{url}; nothing was changed")
    checked_out = _checked_out(target)
    if checked_out:
        current = _current_branch(target)
        if current != branch:
            raise CloneError(f"{target} has {current or 'a detached HEAD'} checked out, not "
                             f"{branch}; nothing was deleted")
        # Settled even in a clone refused below: it touches only upstreams and the
        # branch `git clone` made, never work, and a branch left tracking the
        # workspace would push into it.
        _settle_upstreams(target, branch, remote)
        if dirty := _uncommitted(target):
            raise CloneError(f"{target} has uncommitted changes; nothing was deleted:\n"
                             + "\n".join(dirty))

    added = False
    for name, url in wanted.items():
        if _remote_url(target, name) is None:
            _git(target, "remote", "add", name, url)
            added = True
    if added:
        done.append("remotes")
        if checked_out:
            # Settled above before the remote it tracks was there.
            _settle_upstreams(target, branch, remote)
    if not checked_out:
        _check_out(target, branch, landing, remote)
        _settle_upstreams(target, branch, remote)
        done.append("branch")
    if not recorded:
        # Recorded once the branch is checked out, so a run refused before that
        # leaves another `--branch` free to be asked for.
        _git_path(target, MARKER).write_text(
            json.dumps({"change": change, "branch": branch, "base": landing}), "utf-8")

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
        try:
            commands = bootstrap(target)
            resolved = [config.fill(command, {"change": change, "base": landing})
                        for command in commands or ()]
        except StepError as exc:
            raise CloneError(f"the clone's bootstrap cannot be started: {exc}; the clone is "
                             "made, and running this again starts it") from exc
        state = start_bootstrap(target, resolved, spawn)
        done.append("bootstrap")
    return Created(target, branch, tuple(done), state)


def _left_behind(clone: Path, branch: str, base: str) -> list[str]:
    """What deleting the clone would lose beyond its history: a branch not merged
    into `base`, the branch it lands on, on the branch's upstream remote, commits
    that remote lacks, a stash, uncommitted changes."""
    problems = []
    head = _ref(clone, f"refs/heads/{branch}")
    remote = _git(clone, "config", f"branch.{branch}.remote", check=False).stdout.strip()
    if head is None:
        problems.append(f"{branch} is not a branch of the clone, so its merge cannot be shown")
    if remote in ("", ".", WORKSPACE_REMOTE):
        if head is not None:
            problems.append(f"{branch} tracks no remote, so where it was merged and pushed "
                            "cannot be shown")
    else:
        _git(clone, "fetch", "--quiet", "--prune", remote)
        merged_into = f"refs/remotes/{remote}/{base}"
        if head is not None and (_ref(clone, merged_into) is None
                                 or not _merged(clone, head, merged_into)):
            problems.append(f"{branch} is not merged into {remote}/{base}")
        unpushed = _git(clone, "rev-list", "--branches", "--not",
                        f"--remotes={remote}").stdout.split()
        if unpushed:
            problems.append(f"{len(unpushed)} commit(s) {remote} lacks, the latest "
                            f"{unpushed[0][:12]}")
    if _ref(clone, "refs/stash"):
        problems.append("a stash")
    if dirty := _uncommitted(clone):
        problems.append("uncommitted changes:\n" + "\n".join(f"  {line}" for line in dirty))
    return problems


def remove(workspace: Path, change: str, base: str | None = None) -> Removed:
    """Delete the change's clone, copying its history into the workspace first, once
    nothing in the clone would be lost with it: its branch merged into the branch it
    lands on, `base` when given, else as the clone recorded it."""
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
    # A base given overrides the recorded one for this removal, as the merge's own
    # argument overrides it: a change merged onto another branch is judged there.
    landing = base or recorded.get("base")
    if not landing:
        raise CloneError(f"{target} recorded no branch the change lands on, so its merge "
                         "cannot be judged; give it with --base <branch>; nothing was deleted")
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
        problems += _left_behind(target, recorded.get("branch") or default_branch(change),
                                 landing)
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


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    actions = parser.add_subparsers(dest="action", required=True)
    creating = actions.add_parser("create", help="create or finish a change's clone")
    creating.add_argument("change")
    creating.add_argument("--branch", default=None,
                          help="the change's branch; feat/<change> by default")
    creating.add_argument("--from", dest="from_ref", default=None,
                          help="the branch the change lands on, where a new branch starts; "
                               "the workspace's checked-out branch by default")
    removing = actions.add_parser("remove", help="delete a merged change's clone once its "
                                  "history is in the workspace")
    removing.add_argument("change")
    removing.add_argument("--base", default=None,
                          help="the branch the change landed on, for a clone that recorded "
                               "none")
    args = parser.parse_args(argv)
    try:
        root = repository_root() if root is None else root
    except StepError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if args.action == "remove":
        try:
            removed = remove(root, args.change, args.base)
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
                         from_ref=args.from_ref or None)
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
