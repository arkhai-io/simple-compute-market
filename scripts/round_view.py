#!/usr/bin/env python3
"""Show an implementation round as uncommitted changes in the owner's workspace.

Implementation commits each section, so by the time the owner reads a round its
diff is spread across commits and the editor's source-control view is empty.
`start` moves the change's branch back to the round's base with a mixed reset:
the files stay exactly the round's commit's, and the round shows as uncommitted
changes the owner reads, and runs tests against, in place.

A change worked in its own clone is read in the owner's workspace, on the
workspace's copy of its branch, by name. `start` there refuses a workspace with
uncommitted changes, naming them (the owner puts their own work aside by hand
rather than the tool holding it), one where an unattended run is in progress,
and one with another change's view open; it fast-forwards the workspace's branch
from the clone, refusing one that has diverged, records where the workspace was,
checks the branch out, and resets it to the base. The clone is never touched, so
the branch every step runs on never moves. Run again while that change's view is
open, `start` moves the view to the branch's new head over the same base, so the
owner follows triage's fixes; it refuses while the workspace holds edits or
commits made during the view. Before each move of the worktree — opening,
refreshing, and returning — it refuses, naming them, files the workspace holds
untracked where the commit it moves to tracks one: Git overwrites an ignored file
there without a word. A change with no clone is worked on the checkout's own
branch, and its view resets that branch in place.

`done` returns the branch to the round's commit, leaving the files as they are,
so an edit the owner made while reading stays uncommitted on top of it, and then
returns the workspace to where it was, unless that would carry such an edit onto
another branch. A commit the owner made during the view — an editor's "commit
all" is one click — sits on the base: every path it changed holds what was on
disk then, the round's version with the owner's edits, and every path it did not
change the base's, which the owner did not mean as a revert. So `done` carries
each such commit, oldest first, onto the round's commit: each new commit sets the
paths the original changed to the original's version and keeps its author and
message, and one that holds nothing beyond the round's commit is dropped. A path
the round also changed is carried only when the commit's version
holds every change the round made to it, judged by the path's kind; otherwise,
and for a merge or a branch that has left the base's line, `done` refuses and
moves nothing, naming the file or commit and the way back. Staging done during the
view is not kept; the content is.

The base is the commit the change's latest `round` line recorded as the round
started, unless one is given. A repeat pass, over a fix triage committed after
recording another round, is given its base — the commit the earlier pass's review
read, which the next-step computation names — so the view shows the fix alone. A
round line naming no commit — one recorded after
the fact, with `--after` — falls back to the commit named by the latest triaged
validation record, where the previous round ended, which is the round's start
only when nothing landed on the branch between rounds.

While a view is open the branch it moved does not point at the round's commit,
so every step that describes a commit refuses in that checkout (`check`). The
state lives in the Git directory of the checkout whose branch the view moved.

Contract: openspec/specs/change-workflow/spec.md, "Triage of an implementation
round".
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from change_clone import clone_of, workspace_of  # noqa: E402
from find_change import ChangeNotFound, change_directory  # noqa: E402
from change_workflow.common import StepError  # noqa: E402
from change_workflow.log import LOG, read_log  # noqa: E402
from change_workflow.running import Run, runs_in_progress  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STATE = "round-view.json"
_NUMBERED = re.compile(r"^(\d+)-validation\.md$")
_VALIDATION_COMMIT = re.compile(r"^- \*\*Commit:\*\*\s*([0-9a-f]{7,40})\b", re.M)
# The mode `git diff-tree` gives a path absent on one side.
ABSENT = "000000"
# Symlinks and submodules, whose versions are carried only as the round left them.
_SPECIAL_MODES = {"120000", "160000"}
# Git reads a blob as binary when its first 8000 bytes hold a NUL.
_BINARY_PROBE = 8000

# The runs in progress in a checkout.
Runs = Callable[[Path], list[Run]]


class RoundError(RuntimeError):
    """The view could not be opened, refreshed, or closed.

    A refusal moves nothing. A Git command failing once the checkout has begun to
    move leaves the view's state recording where it stands, for `make round-done`.
    """


@dataclass(frozen=True)
class View:
    change: str
    branch: str
    base: str
    head: str
    # The change's clone, for a round read in the workspace from it; None for a
    # change worked on this checkout's own branch.
    clone: str | None = None
    # Where the workspace was before the view: a branch, or a commit when detached.
    returns_to: str | None = None
    detached: bool = False


@dataclass(frozen=True)
class Carried:
    original: str
    # None for a commit holding nothing beyond the round's commit — "commit all"
    # with no edit of the owner's — which is dropped rather than replayed empty.
    replacement: str | None


@dataclass(frozen=True)
class Closed:
    view: View
    carried: tuple[Carried, ...]
    # Where the workspace went back to, or why it stayed on the change's branch.
    returned_to: str | None = None
    stayed: str | None = None


def _git(root: Path, *args: str, env: dict[str, str] | None = None,
         stdin: str | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                            env=env, input=stdin)
    if result.returncode != 0:
        raise RoundError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _git_bytes(root: Path, *args: str) -> bytes:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True)
    if result.returncode != 0:
        raise RoundError(f"git {' '.join(args)} failed: {result.stderr.decode().strip()}")
    return result.stdout


def _git_path(root: Path, name: str) -> Path:
    path = Path(_git(root, "rev-parse", "--git-path", name))
    return path if path.is_absolute() else root / path


def _ancestor(root: Path, ancestor: str, commit: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, commit],
                          cwd=root, capture_output=True).returncode == 0


def round_base(reviews: Path) -> str | None:
    """The commit the latest recorded round started at, when its line names one.

    A round recorded after the fact names none, and an earlier round's commit is
    never taken for it.
    """
    try:
        rounds = [entry for entry in read_log(reviews / LOG) if entry.get("outcome") == "round"]
    except StepError as exc:
        raise RoundError(str(exc)) from exc
    commit = rounds[-1].get("commit") if rounds else None
    return commit if isinstance(commit, str) and commit else None


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


def open_view(root: Path) -> View | None:
    state = _git_path(root, STATE)
    return View(**json.loads(state.read_text("utf-8"))) if state.exists() else None


def _write_state(root: Path, view: View) -> None:
    _git_path(root, STATE).write_text(json.dumps(asdict(view)), "utf-8")


def _reviews(checkout: Path, change: str) -> Path:
    try:
        return change_directory(checkout, change) / "reviews"
    except ChangeNotFound as exc:
        raise RoundError(str(exc)) from exc


def _resolve_base(root: Path, reviews: Path, base: str | None, head: str) -> str:
    if base is None:
        base = round_base(reviews) or triaged_base(reviews)
        if base is None:
            raise RoundError("neither the latest round line nor a triaged validation record "
                             "names the round's base; give it explicitly (BASE=<commit>)")
    base = _git(root, "rev-parse", "--verify", f"{base}^{{commit}}")
    if base == head:
        raise RoundError("the base is the round's commit; the round has no commits to show")
    if not _ancestor(root, base, head):
        raise RoundError(f"{base[:12]} is not an ancestor of the round's commit {head[:12]}")
    return base


def _refuse_unclean(root: Path) -> None:
    status = _git(root, "status", "--porcelain", "--untracked-files=all")
    if status:
        raise RoundError("the worktree is not clean, and the view would mix these into the "
                         f"round; commit or put them aside first:\n{status}")


def _in_the_way(root: Path, current: str, target: str) -> list[str]:
    """The paths `target` tracks and `current` does not where something already sits
    on disk, or under a parent that is no directory.

    Git overwrites an ignored file wherever a checkout, a fast-forward, or a hard
    reset puts a tracked one, and the cleanliness checks do not list ignored files,
    so nothing else stops a move from destroying one: Git holds no copy of it.
    """
    status = _git(root, "diff", "--name-status", "--no-renames", "-z", current, target, "--")
    fields = [field for field in status.split("\0") if field]
    changes = list(zip(fields[::2], fields[1::2]))
    added = [path for kind, path in changes if kind == "A"]
    # A file `target` removes may be a parent of one it adds; Git replaces it.
    removed = {path for kind, path in changes if kind == "D"}
    blocked = []
    for path in added:
        parents = [Path(*Path(path).parts[:depth]).as_posix()
                   for depth in range(1, len(Path(path).parts))]
        if _occupied(root, path) or any(
                parent not in removed and os.path.lexists(root / parent)
                and (os.path.islink(root / parent) or not (root / parent).is_dir())
                for parent in parents):
            blocked.append(path)
    return blocked


def _occupied(root: Path, path: str) -> bool:
    """Whether something untracked sits at `path`: a file or link, or a directory
    holding an untracked file. A directory of tracked files only, which the target
    replaces with a file, Git removes itself."""
    if not os.path.lexists(root / path):
        return False
    if os.path.islink(root / path) or not (root / path).is_dir():
        return True
    return bool(_git(root, "ls-files", "--others", "-z", "--", path))


def _refuse_in_the_way(root: Path, current: str, target: str, move: str) -> None:
    if blocked := _in_the_way(root, current, target):
        raise RoundError(f"{move} would overwrite what the workspace holds, untracked, where "
                         f"{target[:12]} tracks a file: {', '.join(blocked)}; move it aside "
                         "first. Nothing was moved")


def _refuse_runs(root: Path, runs: Runs) -> None:
    if running := runs(root):
        raise RoundError("an unattended run is in progress in this checkout, and the view "
                         "would move the checkout under it: "
                         + "; ".join(run.describe() for run in running))


def start(root: Path, change: str, base: str | None = None, *,
          runs: Runs = runs_in_progress) -> View:
    """Open the view of `change`'s latest round, or refresh the one open onto the
    branch's new head."""
    if workspace_of(root) is not None:
        raise RoundError("this checkout is a change's clone, whose branch every step runs "
                         "on; read the round in the owner's workspace")
    view = open_view(root)
    if view is not None:
        if view.change != change:
            raise RoundError(f"a round view of {view.change} is open; close it with "
                             "`make round-done` first")
        if view.clone is None:
            # Its branch is the one its steps run on, and nothing moves it while
            # the view is open, so there is no new head to follow.
            raise RoundError("a round view is already open; close it with `make round-done`")
        if base is not None:
            raise RoundError(f"the view of {change} is open over {view.base[:12]}, and a "
                             "refresh keeps its base; close it with `make round-done` to "
                             "read from another")
        return _refresh(root, view, runs)
    clone = clone_of(root, change)
    if clone is None:
        return _start_in_place(root, change, base, runs)
    return _start_from_clone(root, change, clone, base, runs)


def _start_in_place(root: Path, change: str, base: str | None, runs: Runs) -> View:
    reviews = _reviews(root, change)
    branch = _git(root, "branch", "--show-current")
    if not branch:
        raise RoundError("HEAD is detached; check out the change's branch")
    _refuse_unclean(root)
    _refuse_runs(root, runs)
    head = _git(root, "rev-parse", "HEAD")
    base = _resolve_base(root, reviews, base, head)
    view = View(change, branch, base, head)
    # The state is written first, so a view is never open without a record of
    # the commit to return to.
    _write_state(root, view)
    try:
        # -N keeps files the round added in the diff, as intent-to-add entries.
        _git(root, "reset", "--quiet", "--mixed", "-N", base)
    except RoundError:
        _git_path(root, STATE).unlink()
        raise
    return view


def _branch_commit(root: Path, branch: str) -> str:
    """The commit `branch` points at in `root`, or an empty string when it has none."""
    return subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
                          cwd=root, capture_output=True, text=True).stdout.strip()


def _fetch(root: Path, clone: Path, branch: str) -> str:
    """The clone's branch's commit, fetched into the workspace."""
    _git(root, "fetch", "--quiet", "--no-tags", str(clone), f"refs/heads/{branch}")
    return _git(root, "rev-parse", "FETCH_HEAD")


def _start_from_clone(root: Path, change: str, clone: Path, base: str | None,
                      runs: Runs) -> View:
    _refuse_unclean(root)
    _refuse_runs(root, runs)
    branch = _git(clone, "branch", "--show-current")
    head = _fetch(root, clone, branch)
    base = _resolve_base(root, _reviews(clone, change), base, head)
    local = _branch_commit(root, branch)
    if local and local != head and not _ancestor(root, local, head):
        raise RoundError(f"the workspace's {branch} ({local[:12]}) holds commits the "
                         f"clone's ({head[:12]}) lacks, or has diverged from it; triage "
                         "pulls the owner's commits into the clone. Nothing was moved")
    current = _git(root, "branch", "--show-current")
    before = _git(root, "rev-parse", "HEAD")
    _refuse_in_the_way(root, before, head, f"checking out {branch}")
    returns_to = current or before
    view = View(change, branch, base, head, clone=str(clone), returns_to=returns_to,
                detached=not current)
    # Written before the checkout moves, as in place, so the way back is recorded.
    _write_state(root, view)
    try:
        if current == branch:
            _git(root, "merge", "--quiet", "--ff-only", head)
        else:
            _git(root, "update-ref", f"refs/heads/{branch}", head, local)
            _git(root, "checkout", "--quiet", branch)
    except RoundError:
        if (_git(root, "branch", "--show-current"), _git(root, "rev-parse", "HEAD")) == (
                current, before):
            # The checkout did not move, so there is no view to close; a branch ref
            # moved for it goes back, so a refused opening leaves nothing moved.
            # The state goes first: a failed restore must not leave a view open.
            _git_path(root, STATE).unlink()
            if current != branch and _branch_commit(root, branch) == head != local:
                if local:
                    _git(root, "update-ref", f"refs/heads/{branch}", local, head)
                else:
                    _git(root, "update-ref", "-d", f"refs/heads/{branch}", head)
        raise
    _git(root, "reset", "--quiet", "--mixed", "-N", base)
    return view


def _edits(root: Path, head: str) -> list[str]:
    """What the worktree holds beyond `head`: changed and untracked paths."""
    changed = _git(root, "diff", "--name-only", head, "--").splitlines()
    untracked = _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    return [path for path in changed + untracked if path]


def _refresh(root: Path, view: View, runs: Runs) -> View:
    branch = _git(root, "branch", "--show-current")
    if branch != view.branch:
        raise RoundError(f"the view was opened on {view.branch}, but HEAD is now "
                         f"{branch or 'detached'}; switch back and run `make round-done`")
    current = _git(root, "rev-parse", "HEAD")
    if current != view.base:
        made = _git(root, "rev-list", "--reverse", f"{view.head}..{current}").split()
        raise RoundError(
            ("commits were made during the view, and refreshing it would leave them "
             f"behind: {', '.join(c[:12] for c in made)}" if made else
             f"{branch} has moved off the round's base, to {current[:12]}")
            + "; run `make round-done` first")
    if edits := _edits(root, view.head):
        raise RoundError("the workspace holds edits made during the view, and refreshing it "
                         "would overwrite them: " + ", ".join(edits)
                         + "; run `make round-done` first")
    _refuse_runs(root, runs)
    new = _fetch(root, Path(view.clone or ""), view.branch)
    if new == view.head:
        return view
    if not _ancestor(root, view.head, new):
        raise RoundError(f"the clone's {view.branch} ({new[:12]}) no longer descends from "
                         f"the view's commit {view.head[:12]}; nothing was moved")
    _refuse_in_the_way(root, view.head, new, "refreshing the view")
    refreshed = View(**{**asdict(view), "head": new})
    # The worktree holds exactly the view's commit, checked above, and nothing
    # ignored sits where the new commit adds a file, so the hard reset overwrites
    # nothing of the owner's. The state follows the branch: written once it is at
    # the new head, before it moves back to the base.
    _git(root, "reset", "--quiet", "--hard", new)
    _write_state(root, refreshed)
    _git(root, "reset", "--quiet", "--mixed", "-N", view.base)
    return refreshed


# Carrying the owner's commits onto the round's commit.

Entry = tuple[str, str]  # (mode, blob), the mode ABSENT for a path that is not there


def _changes(root: Path, old: str, new: str) -> dict[str, tuple[Entry, Entry]]:
    """Each path `new` changes against `old`, with both sides' mode and blob."""
    raw = _git_bytes(root, "diff-tree", "-r", "-z", "--no-renames", "--no-commit-id", old, new)
    fields = raw.split(b"\0")
    changes: dict[str, tuple[Entry, Entry]] = {}
    index = 0
    while index + 1 < len(fields) and fields[index].startswith(b":"):
        old_mode, new_mode, old_blob, new_blob, _ = fields[index][1:].decode().split(" ")
        changes[fields[index + 1].decode()] = ((old_mode, old_blob), (new_mode, new_blob))
        index += 2
    return changes


def _binary(root: Path, entry: Entry) -> bool:
    if entry[0] == ABSENT:
        return False
    return b"\0" in _git_bytes(root, "cat-file", "blob", entry[1])[:_BINARY_PROBE]


def _holds_round(root: Path, base: Entry, head: Entry, commit: Entry) -> bool:
    """Whether a text file's version in `commit` holds every change the round made
    to it: merging the round's change, `base` to `head`, into it is clean and
    leaves it as it is."""
    versions = {name: _git_bytes(root, "cat-file", "blob", entry[1])
                for name, entry in (("commit", commit), ("base", base), ("head", head))}
    with tempfile.TemporaryDirectory() as scratch:
        files = []
        for name, text in versions.items():
            (Path(scratch) / name).write_bytes(text)
            files.append(str(Path(scratch) / name))
        merged = subprocess.run(["git", "merge-file", "-p", "-q", *files], capture_output=True)
    return merged.returncode == 0 and merged.stdout == versions["commit"]


def _refusal(root: Path, round_change: tuple[Entry, Entry], commit: Entry) -> str | None:
    """Why a commit made during the view cannot carry its version of a path the
    round changed, or None when it can.

    The kinds are told by presence, mode, and blob on each side, so an absent path
    is never taken for an empty file. Only a text file present at both ends of the
    round has a merge to test; any other the commit may hold only as the round
    left it, since the files cannot say whether a difference is an edit of the
    owner's or a round change the owner did not stage.
    """
    base, head = round_change
    if base[0] == ABSENT:
        if commit != head:
            return "the round added it, and the commit's version is not the round's"
        return None
    if head[0] == ABSENT:
        if commit[0] != ABSENT:
            return "the round deleted it, and the commit does not delete it"
        return None
    if base[0] != head[0] or {base[0], head[0], commit[0]} & _SPECIAL_MODES \
            or _binary(root, base) or _binary(root, head) or _binary(root, commit):
        if commit != head:
            return ("the round changed it as a binary file, a link, or a mode, and the "
                    "commit's version is not the round's")
        return None
    if commit[0] == ABSENT:
        return "the round changed it, and the commit deletes it"
    if commit[0] != head[0]:
        return "the round changed it, and the commit changes its mode"
    if not _holds_round(root, base, head, commit):
        return ("the commit's version lacks some of the round's changes to it, or "
                "conflicts with them")
    return None


def _message_and_author(root: Path, commit: str) -> tuple[str, dict[str, str]]:
    raw = _git_bytes(root, "cat-file", "commit", commit).decode("utf-8", "surrogateescape")
    message = raw.split("\n\n", 1)[1] if "\n\n" in raw else ""
    name, email, date = _git(root, "show", "-s", "--date=raw",
                             "--format=%an%x00%ae%x00%ad", commit).split("\0")
    return message, {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
                     "GIT_AUTHOR_DATE": date}


def _carry(root: Path, view: View, commits: Sequence[str]) -> tuple[Carried, ...]:
    """Each of `commits` replayed onto the round's commit, every one judged before
    any is made, so a refusal names the first path that cannot be carried and
    leaves the branch where it is."""
    round_changes = _changes(root, view.base, view.head)
    plans = []
    parent = view.base
    for commit in commits:
        changed = _changes(root, parent, commit)
        for path, (_, entry) in sorted(changed.items()):
            if path in round_changes and (why := _refusal(root, round_changes[path], entry)):
                raise RoundError(
                    f"{commit[:12]} cannot be carried onto the round's commit: {path}: {why}. "
                    f"Nothing was moved; to return, `git reset --mixed {view.head}` and "
                    "`make round-done`, then commit it again on the round's commit")
        plans.append((commit, changed))
        parent = commit
    carried = []
    previous = view.head
    with tempfile.TemporaryDirectory() as scratch:
        # A private index, so the checkout's own, which holds the view, is untouched.
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(scratch) / "index")}
        for commit, changed in plans:
            _git(root, "read-tree", previous, env=env)
            info = "".join(
                f"0 {'0' * len(old[1])}\t{path}\0" if new[0] == ABSENT
                else f"{new[0]} {new[1]}\t{path}\0"
                for path, (old, new) in sorted(changed.items()))
            _git(root, "update-index", "-z", "--index-info", env=env, stdin=info)
            tree = _git(root, "write-tree", env=env)
            if tree == _git(root, "rev-parse", f"{previous}^{{tree}}"):
                carried.append(Carried(commit, None))
                continue
            message, author = _message_and_author(root, commit)
            replacement = _git(root, "commit-tree", tree, "-p", previous,
                               env={**os.environ, **author}, stdin=message)
            carried.append(Carried(commit, replacement))
            previous = replacement
    return tuple(carried)


def done(root: Path, *, runs: Runs = runs_in_progress) -> Closed:
    """End the view: the branch back at the round's commit, with any commit made
    during the view carried onto it, and the workspace back where it was."""
    view = open_view(root)
    if view is None:
        raise RoundError("no round view is open")
    # Closing moves the checkout too: the branch reset, and the return.
    _refuse_runs(root, runs)
    branch = _git(root, "branch", "--show-current")
    current = _git(root, "rev-parse", "HEAD")
    if branch != view.branch:
        raise RoundError(f"the view was opened on {view.branch}, but HEAD is now "
                         f"{branch or 'detached'}; switch back to {view.branch} and run "
                         "`make round-done` again. Nothing was reset")
    carried: tuple[Carried, ...] = ()
    if current == view.head or _ancestor(root, view.head, current):
        # Already back, by hand or by an interrupted run, perhaps with commits
        # of the owner's own on top: the branch holds the round. Unless a merge
        # brought the round's commit in over a commit made on the base during the
        # view, which would reach the clone uncarried.
        if merged := [commit for commit in
                      _git(root, "rev-list", f"{view.head}..{current}").split()
                      if not _ancestor(root, view.head, commit)]:
            raise RoundError(
                f"{merged[-1][:12]}, made on the round's base during the view, was merged "
                "with the round's commit rather than carried onto it. Nothing was reset; "
                f"to return, `git reset --mixed {view.head}`, then run `make round-done` "
                "again and commit it again on the round's commit")
    elif _ancestor(root, current, view.head) and _ancestor(root, view.base, current):
        # At the base, or reset to one of the round's commits: nothing of the
        # owner's is committed.
        _git(root, "reset", "--quiet", "--mixed", view.head)
    else:
        way_back = (f"Nothing was reset; to return, `git reset --mixed {view.head}`, then "
                    "run `make round-done` again")
        if not _ancestor(root, view.base, current) or _git(
                root, "merge-base", current, view.head) != view.base:
            raise RoundError(f"{branch} is at {current[:12]}, which has left the line of the "
                             f"round's base {view.base[:12]} — an amend, a reset, or a "
                             f"rebase. {way_back}")
        if merges := _git(root, "rev-list", "--min-parents=2", f"{view.base}..{current}"):
            raise RoundError(f"{merges.split()[0][:12]}, made during the view, is a merge, "
                             f"which cannot be carried onto the round's commit. {way_back}")
        commits = _git(root, "rev-list", "--reverse", f"{view.base}..{current}").split()
        carried = _carry(root, view, commits)
        last = next((c.replacement for c in reversed(carried) if c.replacement), view.head)
        _git(root, "reset", "--quiet", "--mixed", last)
    _git_path(root, STATE).unlink()
    returned_to, stayed = _return(root, view)
    return Closed(view, carried, returned_to, stayed)


def _return(root: Path, view: View) -> tuple[str | None, str | None]:
    """Check out where the workspace was before a view from a clone, unless edits
    made during the view would be carried along onto it."""
    if view.clone is None or view.returns_to is None:
        return None, None
    if _git(root, "status", "--porcelain", "--untracked-files=all"):
        return None, (f"the workspace stays on {view.branch}, since its uncommitted edits "
                      f"would otherwise be carried onto {view.returns_to}; commit or "
                      f"discard them, then `git checkout {view.returns_to}`")
    if blocked := _in_the_way(root, _git(root, "rev-parse", "HEAD"),
                              _git(root, "rev-parse", f"{view.returns_to}^{{commit}}")):
        return None, (f"the workspace stays on {view.branch}, since checking out "
                      f"{view.returns_to} would overwrite what it holds, untracked, where "
                      f"{view.returns_to} tracks a file: {', '.join(blocked)}; move it "
                      f"aside, then `git checkout {view.returns_to}`")
    target = ["--detach", view.returns_to] if view.detached else [view.returns_to]
    try:
        _git(root, "checkout", "--quiet", *target)
    except RoundError as error:
        return None, f"the workspace stays on {view.branch}: {error}"
    return view.returns_to, None


def check(root: Path) -> None:
    view = open_view(root)
    if view:
        raise RoundError(f"a round view of {view.change} is open, so the branch need not "
                         f"point at the round's commit {view.head[:12]}; run "
                         "`make round-done` first")


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    actions = parser.add_subparsers(dest="action", required=True)
    opening = actions.add_parser("start")
    opening.add_argument("change")
    opening.add_argument("--base")
    actions.add_parser("done")
    actions.add_parser("check")
    args = parser.parse_args(argv)
    try:
        if args.action == "start":
            view = start(root, args.change, args.base)
            print(f"Round of {view.change}: {view.base[:12]}..{view.head[:12]} is now "
                  f"uncommitted changes on {view.branch} in this checkout.")
            print(_git(root, "log", "--oneline", f"{view.base}..{view.head}"))
            print("Read it in your editor, then `make round-done`.")
        elif args.action == "done":
            closed = done(root)
            print(f"{closed.view.branch} is back at the round's commit "
                  f"{closed.view.head[:12]}.")
            for carried in closed.carried:
                print(f"Carried {carried.original[:12]}, made during the view, onto it as "
                      f"{carried.replacement[:12]}." if carried.replacement else
                      f"Dropped {carried.original[:12]}, made during the view: it held "
                      "nothing beyond the round's commit.")
            edits = _git(root, "status", "--short")
            print(f"Your edits, uncommitted:\n{edits}" if edits else "The worktree is clean.")
            if closed.stayed:
                print(f"Not returned: {closed.stayed}.")
            elif closed.returned_to:
                print(f"The workspace is back on {closed.returned_to}.")
        else:
            check(root)
    except RoundError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
