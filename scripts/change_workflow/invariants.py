"""A run's invariants: the state the engine records as an unattended session starts,
and the seven checks against it once the session ends, whatever its outcome
(CW-q7ub). A violation stops the run (CW-f9le).

The sandbox stops what it can before a step does it; these checks find what it
cannot, after the session, and hold every run alike, one the sandbox could not
confine included (CW-v5ny). Nothing is repaired: a violation is reported, and the run
is logged `stopped`, naming each (`stopped`).

1. `history` — `HEAD` is on the branch it was on as the session started, and descends
   from the commit it was at;
2. `unchanged` — for validation and the review, `HEAD` and every tracked file are as
   they were;
3. `log` — the change's workflow log was only appended to: a review run beside a
   validation appends its line meanwhile;
4. `records` — each review record that existed is unchanged, and the change's ledger
   only grew at its end;
5. `stash` — `refs/stash` is unchanged;
6. `remote` — on each remote, the change's branch is where it was, at the last
   commit the session's guarded push sent there successfully, as its record names
   it (`running.ATTEMPTED_PUSH`), or at a commit not made in the run; and no
   protected branch holds a commit made in the run;
7. `closeout` — for closeout, every path changed since the session started,
   committed or not, is one closeout may change (CW-pkug): the repository's inert
   paths, changes' records, and the archive's own writes — the change's own
   documents and their move into the archive, the change index, and the
   specifications its deltas merge into.

Checks 2 and 7 compare the worktree as a tree: every file Git tracks or would track,
as it stands, written as a tree object through an index of the check's own, so the
checkout's index is never touched. A file changed and changed back between two
commits of the run reads as unchanged, which is what the checks ask: what the run
leaves.

A commit made in the run is one `HEAD` came to during it, as `HEAD`'s reflog records
every commit, amend, merge, and checkout, a branch since deleted or a detached `HEAD`
included; so a commit another party pushed to a protected branch during the run,
which a step's fetch brought in, is not the run's. Nor is a change branch the owner
moved during the run: the round view, opened in the owner's workspace beside a
review in the change's clone, checks the workspace's branch out at the round's base,
and closing it can leave the owner's own commits there; neither tip is a commit made
in the run. The check reads each remote's
tips by listing them, not by fetching, so a protected branch is checked at its tip:
a commit of the run that another party has since built on is not found. A remote the
engine cannot reach, as the session starts or after it, is not checked: the
sandbox's `git` is the guard, and this the backstop.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .common import CHANGES, Entry, StepError
from .config import Configuration
from .find import ARCHIVE, ChangeNotFound, change_directory, change_name
from .log import log_path
from .records import RECORD, git_contains, git_remotes, inert, is_record
from .running import ATTEMPTED_PUSH, invocations_directory, kept_invocations

# The steps that change nothing tracked: validation observes a commit and a review
# reads one.
OBSERVING = ("validate", "review")
CLOSEOUT = "closeout"
LEDGER = "interventions.jsonl"
_SPECS = "openspec/specs"
_STASH = "refs/stash"


@dataclass(frozen=True)
class Violation:
    """One check a run failed, by its name, and what it found."""

    check: str
    found: str

    def entry(self) -> Entry:
        return {"check": self.check, "found": self.found}


@dataclass(frozen=True)
class Prefix:
    """A file as it stood: its length, and the digest of its content."""

    length: int
    digest: str


@dataclass(frozen=True)
class Start:
    """What the checks compare against: the checkout as the session started."""

    step: str
    change: str
    commit: str | None
    branch: str | None
    tree: str | None
    tracked: frozenset[str]
    log: Prefix
    ledger: Prefix
    records: Mapping[str, str]
    stash: str | None
    # How many entries `HEAD`'s reflog held: those written after are the run's.
    moves: int
    # Each remote's change branch and protected branches, by branch; None for a remote
    # that could not be read.
    remotes: Mapping[str, Mapping[str, str] | None]
    capabilities: frozenset[str]
    inert_paths: tuple[str, ...]
    protected_branches: tuple[str, ...]


def _git(root: Path, *args: str, environ: Mapping[str, str] | None = None,
         stdin: str | None = None) -> str | None:
    """What Git prints, stripped; None where it fails."""
    found = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                           input=stdin, env=None if environ is None else dict(environ))
    return found.stdout.strip() if found.returncode == 0 else None


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path | None) -> bytes:
    return path.read_bytes() if path is not None and path.is_file() else b""


def _prefix(path: Path | None) -> Prefix:
    data = _read(path)
    return Prefix(len(data), _digest(data))


def _grew(path: Path | None, prefix: Prefix) -> bool:
    """Whether the file at `path` holds what `prefix` recorded, then perhaps more."""
    data = _read(path)
    return len(data) >= prefix.length and _digest(data[:prefix.length]) == prefix.digest


def _directory(root: Path, change: str) -> Path | None:
    try:
        return change_directory(root, change)
    except ChangeNotFound:
        return None


def _log(root: Path, change: str) -> Path | None:
    try:
        return log_path(root, change)
    except StepError:
        return None


def _records(directory: Path | None) -> dict[str, str]:
    reviews = directory / "reviews" if directory is not None else None
    if reviews is None or not reviews.is_dir():
        return {}
    return {entry.name: _digest(entry.read_bytes()) for entry in sorted(reviews.iterdir())
            if RECORD.match(entry.name) and entry.is_file()}


def worktree_tree(root: Path) -> str | None:
    """The worktree as a tree object: every file Git tracks or would track, as it
    stands; None outside a Git checkout. Written through a copy of the checkout's
    index, whose stat cache spares rehashing what has not changed, so the checkout's
    own index is left as it is."""
    index = _git(root, "rev-parse", "--git-path", "index")
    if index is None:
        return None
    with tempfile.TemporaryDirectory() as directory:
        own = Path(directory) / "index"
        if (current := root / index).is_file():
            shutil.copyfile(current, own)
        environ = {**os.environ, "GIT_INDEX_FILE": str(own)}
        if _git(root, "add", "--all", "--", ".", environ=environ) is None:
            return None
        return _git(root, "write-tree", environ=environ)


def _tracked(root: Path) -> frozenset[str]:
    listed = _git(root, "ls-files", "-z")
    return frozenset(path for path in (listed or "").split("\0") if path)


def _remote_branches(root: Path, remote: str, branches: Sequence[str]) -> dict[str, str] | None:
    """The commit each of `branches` is at on `remote`, from one listing; None where the
    remote cannot be read."""
    listed = _git(root, "ls-remote", "--heads", remote, *(f"refs/heads/{b}" for b in branches))
    if listed is None:
        return None
    found = {}
    for line in listed.splitlines():
        commit, _, ref = line.partition("\t")
        found[ref.removeprefix("refs/heads/")] = commit
    return found


def _moves(root: Path) -> list[str]:
    """The commit of each entry of `HEAD`'s reflog, the latest first."""
    return (_git(root, "reflog", "show", "--format=%H", "HEAD", "--") or "").split()


def _watched(branch: str | None, protected: Sequence[str]) -> list[str]:
    return list(dict.fromkeys([*([branch] if branch else []), *protected]))


def record(root: Path, step: str, change: str, *, inert_paths: Sequence[str] = (),
           protected_branches: Sequence[str] = ()) -> Start:
    """The state the checks compare against, read as the session of a run of `step`
    for `change` starts; `inert_paths` and `protected_branches` the configuration's."""
    branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    directory = _directory(root, change)
    watched = _watched(branch, protected_branches)
    specs = directory / "specs" if directory is not None else None
    return Start(
        step=step, change=change, commit=_git(root, "rev-parse", "--verify", "HEAD"),
        branch=branch, tree=worktree_tree(root), tracked=_tracked(root),
        log=_prefix(_log(root, change)),
        ledger=_prefix(directory / LEDGER if directory is not None else None),
        records=_records(directory),
        stash=_git(root, "rev-parse", "--verify", "--quiet", _STASH),
        moves=len(_moves(root)),
        remotes={remote: _remote_branches(root, remote, watched)
                 for remote in sorted(git_remotes(root))},
        capabilities=frozenset(entry.name for entry in (
            specs.iterdir() if specs is not None and specs.is_dir() else ()) if entry.is_dir()),
        inert_paths=tuple(inert_paths), protected_branches=tuple(protected_branches))


def _changed(root: Path, before: str, after: str) -> list[str]:
    # Without --no-renames a file moved would be listed only at its new path, hiding
    # where it was.
    listed = _git(root, "diff", "--name-only", "--no-renames", "-z", before, after)
    return [path for path in (listed or "").split("\0") if path]


def archive_writes(path: str, change: str, capabilities: frozenset[str]) -> bool:
    """Whether `path` is one of the archive's own writes for `change`: its own
    documents, active or archived; the change index; or the specification of one of
    `capabilities`, those its deltas merge into."""
    parts = Path(path).parts
    changes, archive = Path(CHANGES).parts, Path(ARCHIVE).parts
    if parts[:len(archive)] == archive and len(parts) > len(archive) + 1:
        return change_name(Path(*parts[:len(archive) + 1])) == change
    if parts[:len(changes)] == changes and len(parts) > len(changes):
        return parts[len(changes)] == change or path == f"{CHANGES}/README.md"
    return any(path == f"{_SPECS}/{capability}/spec.md" for capability in capabilities)


def _made_in_run(root: Path, start: Start) -> set[str]:
    """The commits `HEAD` came to during the run: those its reflog gained since the
    start."""
    moves = _moves(root)
    return set(moves[:max(0, len(moves) - start.moves)])


def _pushed(invoked: Sequence[Mapping[str, Any]], remote: str, branch: str) -> str | None:
    """The commit the session's last successful guarded push of `branch` to `remote`
    sent, as its record names it."""
    sent = [entry.get("commit") for entry in invoked
            if entry.get("hook") == ATTEMPTED_PUSH and entry.get("exit_status") == 0
            and entry.get("remote") == remote and entry.get("branch") == branch]
    return str(sent[-1]) if sent else None


def _short(commit: str | None) -> str:
    return commit[:12] if commit else "nothing"


def check(root: Path, start: Start, invoked: Sequence[Mapping[str, Any]] = ()) -> list[Violation]:
    """Every check the run fails against `start`, as the session left the checkout;
    `invoked`, what the session kept, among it each push its guarded push attempted."""
    found: list[Violation] = []
    commit = _git(root, "rev-parse", "--verify", "HEAD")
    if start.commit is not None:
        branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
        if start.branch is not None and branch != start.branch:
            found.append(Violation("history", f"HEAD is on {branch or 'no branch'}, not "
                                              f"{start.branch}, the branch it was on"))
        if commit is None or not git_contains(root, commit, start.commit):
            found.append(Violation("history", f"HEAD {_short(commit)} does not descend from "
                                              f"{_short(start.commit)}, where it started"))
    tree = worktree_tree(root) if start.tree is not None else None
    changed = _changed(root, start.tree, tree) if start.tree and tree else []
    if start.step in OBSERVING:
        if commit != start.commit:
            found.append(Violation("unchanged", f"HEAD moved from {_short(start.commit)} to "
                                                f"{_short(commit)}"))
        tracked = start.tracked | _tracked(root)
        if files := [path for path in changed if path in tracked]:
            found.append(Violation("unchanged", "tracked files changed: " + ", ".join(files)))
    if not _grew(_log(root, start.change), start.log):
        found.append(Violation("log", "the workflow log was changed other than by appending "
                                      "to it"))
    directory = _directory(root, start.change)
    now = _records(directory)
    if altered := [name for name, digest in start.records.items() if now.get(name) != digest]:
        found.append(Violation("records", "review records changed or removed: "
                                          + ", ".join(altered)))
    if not _grew(directory / LEDGER if directory is not None else None, start.ledger):
        found.append(Violation("records", "the ledger was changed other than by appending to "
                                          "it"))
    if (stash := _git(root, "rev-parse", "--verify", "--quiet", _STASH)) != start.stash:
        found.append(Violation("stash", f"refs/stash moved from {_short(start.stash)} to "
                                        f"{_short(stash)}"))
    found += _remote_violations(root, start, invoked)
    if start.step == CLOSEOUT:
        if outside := [path for path in changed if not (
                inert(path, start.inert_paths) or is_record(path)
                or archive_writes(path, start.change, start.capabilities))]:
            found.append(Violation("closeout", "paths closeout may not change were changed: "
                                               + ", ".join(outside)))
    return found


def _remote_violations(root: Path, start: Start,
                       invoked: Sequence[Mapping[str, Any]]) -> list[Violation]:
    found = []
    watched = _watched(start.branch, start.protected_branches)
    made = _made_in_run(root, start)
    for remote, before in start.remotes.items():
        if before is None or (after := _remote_branches(root, remote, watched)) is None:
            continue
        if start.branch is not None:
            was, now = before.get(start.branch), after.get(start.branch)
            pushed = _pushed(invoked, remote, start.branch)
            if now not in (was, pushed) and now in made:
                found.append(Violation(
                    "remote", f"{remote}'s {start.branch} is at {_short(now)}, a commit made "
                              f"in the run, neither where it was, {_short(was)}, nor the "
                              f"guarded push's last, {_short(pushed)}"))
        for protected in start.protected_branches:
            now = after.get(protected)
            if now is not None and now != before.get(protected) and now in made:
                found.append(Violation("remote", f"{remote}'s {protected}, a protected branch, "
                                                 f"holds {_short(now)}, a commit made in the run"))
    return found


def broken(violations: Sequence[Violation]) -> str:
    """The reason a run whose checks found `violations` stopped, naming each."""
    return "the run broke its invariants: " + "; ".join(
        f"{violation.check}: {violation.found}" for violation in violations)


def stopped(outcome: Entry, violations: Sequence[Violation]) -> Entry:
    """The outcome a run whose checks found `violations` is logged with: `stopped`,
    naming each, the step's own message kept ahead of the reason."""
    reason = broken(violations)
    said = outcome.get("message")
    return {"outcome": "stopped",
            "message": f"{said}\n\n{reason}" if isinstance(said, str) and said.strip() else reason,
            "reason": reason, "denials": outcome.get("denials", [])}


@dataclass
class Invariants:
    """One run's invariants: the state recorded as its session starts (`begin`), and
    the checks against it after (`violations`), given the sessions whose kept
    invocations hold its pushes."""

    root: Path
    step: str
    change: str
    inert_paths: Sequence[str] = ()
    protected_branches: Sequence[str] = ()
    # Where the sessions' invocations are kept until their line takes them.
    invocations: Callable[[Path], Path | None] = invocations_directory
    start: Start | None = field(default=None, init=False)

    @classmethod
    def of(cls, configuration: Configuration, root: Path, step: str, change: str,
           invocations: Callable[[Path], Path | None] = invocations_directory) -> Invariants:
        """A run's invariants, with the configuration's inert paths and protected
        branches."""
        return cls(root, step, change, configuration.repository_inert_paths(),
                   configuration.protected_branches or (), invocations)

    def begin(self) -> None:
        self.start = record(self.root, self.step, self.change, inert_paths=self.inert_paths,
                            protected_branches=self.protected_branches)

    def violations(self, sessions: Sequence[str] = ()) -> list[Violation]:
        if self.start is None:
            return []
        directory = self.invocations(self.root)
        invoked = [entry for session in sessions
                   for entry in kept_invocations(directory, session, self.change)]
        return check(self.root, self.start, invoked)
