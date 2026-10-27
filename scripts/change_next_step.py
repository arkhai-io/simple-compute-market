#!/usr/bin/env python3
"""Compute the next step of an OpenSpec change from its files and workflow log.

The orchestrating session runs whatever this names and never routes on its own
reading; the owner can run the same command by hand. It reads the change's row in
`openspec/changes/README.md` (status, `Depends on`, `Notes`), its numbered review
records and their triage, the sections and checks of its task list, its workflow
log, and whether a round view is open, and prints one JSON object:

- `{"step": <step>, "reason": …}` for a step to run: `design`, `plan`, `round`
  (with the `sections` of each session of the plan's next round, to be recorded
  `by: plan` as it starts), `implement` (with its `sections`), `round-view`,
  `validate`, `review` (with its `kind`), `validate-and-review`, `triage`,
  `closeout`, or `archive-cleanup`; for a change in its own clone, a `round-view`,
  or a validation or review that runs beside the owner's reading (`reading`),
  names the `workspace` the reading takes place in; the reading of a repeat pass,
  over a fix triage committed, names its `base`, the commit the view starts from;
- `{"step": "clone", "arguments": …}` when the change's clone is to be created,
  or finished, with `make change-clone` and those arguments;
  `{"step": "in-clone", "clone": …}` when the change is worked in its clone, where
  this computation and every step are run; `{"step": "wait", …}` while the
  clone's bootstrap runs and the step named would need it;
- `{"step": "owner", "reason": …}` when only the owner can move the change on: a
  merge in progress in the checkout (`merging`), named before anything else is
  read, a question to answer, a returned step to decide, a round the plan does not map, a
  validation that did not pass, a prerequisite to land, a failed bootstrap, a
  change whose records are in the workspace but whose branch is not; for a waiting
  run, its `seq` — a question or a stop is resumed by it;
- `{"step": "done", …}` for an archived change;
- `{"step": "unclassified", "reason": …, "read": …}` when no rule applies, with
  what it read, for the orchestrating session to work out.

The workflow's graph is the table in `change_workflow/graph.py`: each node's exits,
the join an exit waits on, and the guards on each exit with the step that remedies
each. This computation reads where the change stands and which exit its last step
chose, then follows that exit through its guards. A review's triage file records
under `## Next` whether the change advances, another review round runs, or the
triage returned the change to an earlier phase, and that token chooses the
triage's exit; the change then advances once the exit's guards hold — a passing
validation of the round's fix commit, of `HEAD` before closeout, and of a closeout
correction that changed more than documentation — without the owner.

A change is computed where it is worked: in the checkout that has its branch
checked out — its own name's branch, or one the owner's decision says it is
worked on — or in its own clone. Run anywhere else, the computation names the
clone, to compute there or to create, or the owner, for a change whose records
are in this workspace and so cannot simply be cloned. In a clone, implementation
and later steps wait for the clone's bootstrap, and the owner reads a round in
the workspace beside its validation and review, the workspace's view read
through the clone's `workspace` remote. Where the log and the files
disagree — a status set by hand — the files decide the step, and the result
carries a `disagreement` saying so. A
task list whose tasks sit under another section's heading is not routed on
(`task_problems`, which `scripts/check_tasks.py` runs for the skills). `--plain`
prints the result as lines rather than JSON.

Contract: openspec/specs/change-workflow/spec.md, "The next step is computed from
the files".
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from change_clone import (ABSENT as BOOTSTRAP_ABSENT, DEFAULT_FROM,  # noqa: E402
                          FAILED as BOOTSTRAP_FAILED, RUNNING as BOOTSTRAP_RUNNING, Bootstrap,
                          bootstrap_state, clone_of, default_branch, workspace_of)
from check_change_index import _DEPENDENCY, INDEX, Row, index_rows  # noqa: E402
from find_change import ChangeNotFound, change_directory, is_archived  # noqa: E402
from round_view import RoundError, View, open_view  # noqa: E402
from change_workflow import graph  # noqa: E402
from change_workflow.common import ORCHESTRATOR, StepError  # noqa: E402
from change_workflow.graph import (ARCHIVE_CLEANUP, CLOSEOUT,  # noqa: E402
                                   CLOSEOUT_REVIEW, CLOSEOUT_TRIAGE,
                                   DESIGN, DESIGN_REVIEW, DESIGN_TRIAGE,
                                   IMPLEMENTATION_REVIEW, IMPLEMENTATION_TRIAGE, PHASES,
                                   PLAN, PRE_CLOSEOUT_REVIEW, PRE_CLOSEOUT_TRIAGE, ROUND,
                                   ROUND_VIEW, VALIDATE, Node)
from change_workflow.graph import owner as _owner  # noqa: E402
from change_workflow.log import (branch_decisions, directed_step, log_path,  # noqa: E402
                                 read_log, redesigned_after_return)
from change_workflow.records import (ChangedSince, changed_since,  # noqa: E402
                                     is_documentation, is_record, latest_validation,
                                     validation_problem, validation_result)

ROOT = Path(__file__).resolve().parents[1]
_RECORD = re.compile(r"^(?P<number>\d+)-(?P<kind>[a-z-]+)\.md$")
_REVIEWED_COMMIT = re.compile(r"<!-- reviewed-commit: (\S+) -->")
# The change's task list, whose sections and checks say how far implementation got.
TASKS_FILE = "tasks.md"
_SECTION = re.compile(r"^## (?P<id>[0-9]+[A-Za-z]?)\. (?P<title>.+?)\s*$")
# A task is numbered for its section, `N.m`, when it is numbered at all.
_TASK = re.compile(r"^\s*- \[(?P<done>[ xX])\] "
                   r"(?P<number>(?P<section>[0-9]+[A-Za-z]?)\.[0-9]+\b)?")
# Where a log line's step sits among the phases, for comparing with the status.
_STEP_PHASE = {"design": "design", "plan": "planning", "implement": "implementation",
               "validate": "implementation", "triage": None, "review": None,
               "closeout": "closeout", "archive-cleanup": "closeout"}
# What a review's triage file records next, read from its `## Next` token.
ADVANCE, ANOTHER_ROUND, RETURNED, IN_PROGRESS, OWNER = (
    "advance", "another round", "returned", "in progress", "owner")


def _section_text(text: str, heading: str) -> str | None:
    """The body of a `## <heading>` section of a Markdown file, if it has one; words
    after a colon on the heading's own line (`## Next: Advance`) begin it. Only the
    bare heading counts: `## Next round` is another section."""
    match = re.search(rf"^## {re.escape(heading)}(?::(.*))?[ \t]*$", text, re.M)
    if match is None:
        return None
    rest = text[match.end():]
    end = re.search(r"^## ", rest, re.M)
    return (match.group(1) or "") + "\n" + (rest[:end.start()] if end else rest)


def _seconds(at: str) -> int:
    """A log line's `at`, UTC to the second, as seconds since the epoch."""
    return int(datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc).timestamp())


Result = dict[str, Any]


@dataclass(frozen=True)
class Record:
    """A numbered record in `reviews/`: a review, validation, or the owner's notes."""

    number: int
    kind: str
    path: Path

    @property
    def triage(self) -> Path:
        return self.path.with_name(self.path.name[:-3] + ".triage.md")

    @property
    def triaged(self) -> bool:
        return self.triage.is_file()

    def next_token(self) -> str | None:
        """What a review's triage recorded next; None while it is untriaged.

        Triage writes `## Next` last, its first words `Advance`, `Another round`,
        or, for a triage that returns the change to an earlier phase, `Returned`,
        and the change is routed on that token alone: `ADVANCE`, `ANOTHER_ROUND`,
        `RETURNED`, `OWNER` for any other first words, and `IN_PROGRESS` for a
        triage file without the section, a triage not yet finished. A file from
        before `## Next` ends with `## Gate`; one beginning "Passed" reads as
        `ADVANCE`, so nothing already passed reopens, and any other goes to the
        owner.
        """
        if not self.triaged:
            return None
        text = self.triage.read_text("utf-8")
        if (following := _section_text(text, "Next")) is not None:
            words = following.strip().lower()
            return (ADVANCE if words.startswith("advance")
                    else ANOTHER_ROUND if words.startswith("another round")
                    else RETURNED if words.startswith("returned") else OWNER)
        if (gate := _section_text(text, "Gate")) is not None:
            return ADVANCE if gate.strip().lower().startswith("passed") else OWNER
        return IN_PROGRESS

    @property
    def needs_no_triage(self) -> bool:
        """Whether this is a validation record with nothing to triage: `passed`, or
        `inconclusive`, which is missing evidence for the owner, never a finding."""
        return (self.kind == "validation"
                and validation_result(self.path) in ("passed", "inconclusive"))

    @property
    def review_kind(self) -> str | None:
        """The kind of review this record is, `-external` copies included."""
        kind = self.kind.removesuffix("-external")
        return kind if graph.review_phase(kind) else None

    @property
    def reviewed_commit(self) -> str | None:
        """The commit a review record says it reviewed: the last marker, since a
        review may quote an earlier record's."""
        commits = _REVIEWED_COMMIT.findall(self.path.read_text("utf-8"))
        return commits[-1] if commits else None


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    open_tasks: int
    done_tasks: int

    @property
    def complete(self) -> bool:
        return self.open_tasks == 0 and self.done_tasks > 0

    @property
    def closeout(self) -> bool:
        # Plans title it "Closeout", "Plan closeout", "Repository closeout", …
        return "closeout" in self.title.lower()


@dataclass
class State:
    """Everything the computation read, reported back when no rule applies."""

    change: str
    directory: Path | None = None
    row: Row | None = None
    notes: str = ""
    records: list[Record] = field(default_factory=list)
    tasks: str = ""
    sections: list[Section] = field(default_factory=list)
    log: list[dict[str, Any]] = field(default_factory=list)
    view: View | None = None
    head: str | None = None
    # Set when this checkout is the change's clone: the workspace it is a clone
    # of, that workspace's open view of this change's round, and its bootstrap.
    workspace: Path | None = None
    workspace_view: View | None = None
    bootstrap: Bootstrap | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "status": self.row.status if self.row else None,
            "depends_on": self.row.depends_on if self.row else None,
            "notes": self.notes,
            "records": [f"{r.path.name}{' (triaged)' if r.triaged else ''}"
                        for r in self.records],
            "sections": {s.id: f"{s.done_tasks} done, {s.open_tasks} open"
                         for s in self.sections},
            "last_log_lines": self.log[-3:],
            "round_view": self.view.change if self.view else None,
            "head": self.head,
            "workspace": str(self.workspace) if self.workspace else None,
            "workspace_round_view": bool(self.workspace_view),
            "bootstrap": self.bootstrap.state if self.bootstrap else None,
        }


def read_records(reviews: Path) -> list[Record]:
    records = []
    for entry in sorted(reviews.iterdir()) if reviews.is_dir() else []:
        match = _RECORD.match(entry.name)
        if match and not entry.name.endswith(".triage.md"):
            records.append(Record(int(match["number"]), match["kind"], entry))
    return sorted(records, key=lambda r: (r.number, r.path.stat().st_mtime))


def read_sections(tasks: Path) -> list[Section]:
    """Each `## N. Title` section of a task list, with its open and checked tasks."""
    sections: list[Section] = []
    for line in tasks.read_text("utf-8").splitlines() if tasks.is_file() else []:
        if match := _SECTION.match(line):
            sections.append(Section(match["id"], match["title"], 0, 0))
        elif sections and (task := _TASK.match(line)):
            last = sections[-1]
            sections[-1] = (Section(last.id, last.title, last.open_tasks, last.done_tasks + 1)
                            if task["done"] in "xX"
                            else Section(last.id, last.title, last.open_tasks + 1,
                                         last.done_tasks))
    return sections


def task_problems(text: str) -> list[str]:
    """Each numbered task of a task list that sits under another section's heading.

    Sections are read from `## N. Title` headings alone, so a heading lost in an
    edit silently hands its tasks to the section before it, and anything routing
    on the sections then repeats or skips work. A task numbered `N.m` under a
    heading other than `## N.` is that loss made visible. Only tasks under a
    recognised heading are checked, so a list in another format is unaffected.
    """
    problems: list[str] = []
    heading: tuple[str, str] | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if match := _SECTION.match(line):
            heading = (match["id"].lower(), line.strip())
        elif line.startswith("## "):
            # An unnumbered heading, such as a deferred-work list: not a section.
            heading = None
        elif heading and (task := _TASK.match(line)) and task["section"] \
                and task["section"].lower() != heading[0]:
            problems.append(f"line {number}: task {task['number']} sits under `{heading[1]}`")
    return problems


def _git_head(root: Path) -> str | None:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                          text=True)
    return head.stdout.strip() if head.returncode == 0 else None


def _merging(root: Path) -> bool:
    """Whether a merge is in progress in the checkout: its Git directory holds
    `MERGE_HEAD`, from a merge stopped at its conflicts until it is concluded."""
    merge = subprocess.run(["git", "rev-parse", "--quiet", "--verify", "MERGE_HEAD"],
                           cwd=root, capture_output=True, text=True)
    return merge.returncode == 0


def _uncommitted(root: Path, path: Path) -> bool:
    """Whether `path` has changes Git has not committed, or Git cannot say."""
    status = subprocess.run(["git", "status", "--porcelain", "--", str(path)], cwd=root,
                            capture_output=True, text=True)
    return status.returncode != 0 or bool(status.stdout.strip())


def _open_view(root: Path) -> View | None:
    try:
        return open_view(root)
    except RoundError:
        return None


def _current_branch(root: Path) -> str | None:
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=root,
                            capture_output=True, text=True)
    if branch.returncode != 0:
        return None
    return branch.stdout.strip() or None


def _phase(status: str) -> str | None:
    return next((phase for phase in PHASES if status.endswith(phase)), None)


def _step_lines(log: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry for entry in log if entry.get("step") != ORCHESTRATOR]


def _triage_phase(before: Sequence[dict[str, Any]]) -> str | None:
    """The phase a triage run belongs to: that of the review or validation it
    followed, the nearest one logged before it; None with none logged."""
    for entry in reversed(before):
        if entry.get("step") == "review":
            return graph.review_phase(entry.get("kind", ""))
        if entry.get("step") == "validate":
            return "implementation"
    return None


def governing(reviews: Sequence[Record]) -> Record:
    """The review whose triage decides what follows: the latest, unless its triage
    file has no `## Next` and an earlier review was triaged with it.

    Two reviews triaged together — one from `make review`, one pasted — may carry
    `## Next` in one triage file only; the earlier one's was written after the
    latest review was published. An earlier review triaged before that belongs to
    an earlier round, whose token says nothing of this one.
    """
    latest = reviews[-1]
    if latest.next_token() != IN_PROGRESS:
        return latest
    published = latest.path.stat().st_mtime_ns
    return next((r for r in reversed(reviews[:-1])
                 if r.next_token() not in (None, IN_PROGRESS)
                 and r.triage.stat().st_mtime_ns >= published), latest)


def _waiting(entry: dict[str, Any], read: bool = True) -> Result | None:
    """The owner result for a step whose last run waits on the owner, if it does.

    A stopped run waits, its denials on the result, until a decision resolves it
    or its resumed run supersedes it; its reading alone settles nothing, since
    the resume is refused for a resolved run. Any other run whose denials are
    not yet `read` waits for their reading first, whatever its outcome: a run
    can be denied a call and still ask a question or propose a return, and the
    reading answers neither, so the question or return waits after it as it
    would without the denial.
    """
    step, outcome = entry.get("step"), entry.get("outcome")
    if outcome == "stopped":
        return _owner(f"the {step} step stopped: {entry.get('reason', '')}",
                      denials=entry.get("denials", []))
    if (denials := entry.get("denials")) and not read:
        waits = {"question": "question", "returned": "return", "blocked": "block"}.get(outcome)
        return _owner(f"the {step} step ended {outcome} but was denied {len(denials)} tool "
                      "call(s): read them against its rules and record the reading"
                      + (f"; its {waits} waits after that" if waits else ""),
                      denials=denials, outcome=outcome)
    if outcome == "question":
        return _owner(f"the {step} step asks: {entry.get('message', '')}",
                      awaiting=entry.get("awaiting"), resume=step)
    if outcome == "returned":
        return _owner(f"the {step} step proposes returning to {entry.get('return_to')}: "
                      f"{entry.get('message', '')}", return_to=entry.get("return_to"))
    if outcome == "blocked":
        return _owner(f"the {step} step is blocked on {entry.get('blocked_on')}: "
                      f"{entry.get('message', '')}", blocked_on=entry.get("blocked_on"))
    return None


class Computation:
    def __init__(self, root: Path, change: str, *,
                 head: Callable[[Path], str | None] = _git_head,
                 view: Callable[[Path], View | None] = _open_view,
                 uncommitted: Callable[[Path, Path], bool] | None = None,
                 changed_since: ChangedSince = changed_since,
                 branch: Callable[[Path], str | None] = _current_branch,
                 workspace: Callable[[Path], Path | None] = workspace_of,
                 clone: Callable[[Path, str], Path | None] = clone_of,
                 bootstrap: Callable[[Path], Bootstrap] = bootstrap_state,
                 merging: Callable[[Path], bool] = _merging) -> None:
        self.root = root
        self.state = State(change)
        self._merging = merging
        self._head = head
        self._view = view
        self._uncommitted = uncommitted or _uncommitted
        self._changed_since = changed_since
        self._branch = branch
        self._workspace = workspace
        self._clone = clone
        self._bootstrap = bootstrap

    def run(self) -> Result:
        state = self.state
        if self._merging(self.root):
            # The change's state is half merged until the merge concludes, so
            # nothing read from it can route; a restarted orchestrating session
            # would otherwise run a step over the conflicts.
            return _owner("a merge is in progress in this checkout: its conflicts are "
                          "resolved — the workflow's files by the orchestrating session, "
                          "code by the owner or an implementation run — and the merge "
                          "concluded before the change is routed", merging=True)
        state.view = self._view(self.root)
        try:
            state.directory = change_directory(self.root, state.change)
        except ChangeNotFound as exc:
            return self.unclassified(str(exc))
        state.row = next((row for row in index_rows(self.root) if row.name == state.change),
                         None)
        state.log = read_log(log_path(self.root, state.change))
        if is_archived(self.root, state.directory) and (
                state.row is None or state.row.status == "archived"):
            return {"step": "done", "reason": "archived" if state.row else
                    "archived, and its index row pruned"}
        if located := self.locate():
            return located
        if state.view is not None:
            # While a view is open the branch sits at the round's base, so nothing
            # else about the change can be read until it closes.
            return _owner(
                f"a round view of {state.view.change} is open: save the owner's notes on "
                "the round as the next NN-implementation-owner.md, then run "
                "`make round-done`", round_view=state.view.change)
        state.notes = state.row.notes if state.row else ""
        state.records = read_records(state.directory / "reviews")
        tasks = state.directory / TASKS_FILE
        state.tasks = tasks.read_text("utf-8") if tasks.is_file() else ""
        state.sections = read_sections(tasks)
        state.head = self._head(self.root)
        if state.row is None:
            return self.unclassified(f"{INDEX} has no row for {state.change}")
        if state.workspace is not None:
            if held := self.bootstrap_held():
                return held
        result = self.route()
        if result.get("step") not in ("owner", "unclassified", "done"):
            if waiting := self.bootstrapping(result):
                return waiting
            if disagreement := self.disagreement():
                result["disagreement"] = disagreement
        return result

    def unclassified(self, reason: str) -> Result:
        return {"step": "unclassified", "reason": reason, "read": self.state.summary()}

    # Where the change is worked.

    def locate(self) -> Result | None:
        """Where to compute the change, when it is not this checkout: its clone; a
        clone to create or finish; or the owner, for a change whose records are
        here though its branch is not. None when the change is worked here.

        The change is here when this checkout has its branch checked out — its own
        name's branch, or one the owner's decision says it is worked on — or, in a
        clone, when this is the clone of it. A workspace showing a round from a
        clone has the branch checked out for reading only, so that change is in
        its clone. In a clone, the workspace's view of the change is read through
        the clone's `workspace` remote.
        """
        state = self.state
        view = state.view
        if view is not None and view.clone and view.change == state.change:
            return self.in_clone(Path(view.clone),
                                 "its round is open in this workspace's view")
        workspace = self._workspace(self.root)
        if workspace is not None:
            clone = self._clone(workspace, state.change)
            if clone is None or clone.resolve() != self.root.resolve():
                return _owner(f"this checkout is a clone, but not {state.change}'s: compute "
                              f"its next step in the owner's workspace, {workspace}")
            state.workspace = workspace
            workspace_view = self._view(workspace)
            state.workspace_view = (workspace_view if workspace_view
                                    and workspace_view.change == state.change else None)
            return None
        # A clone first, whatever this checkout has checked out: the owner may have
        # the branch of a change in a clone checked out to commit on it, or left it
        # so after a round's reading.
        clone = self._clone(self.root, state.change)
        if clone is not None:
            if self._bootstrap(clone).state == BOOTSTRAP_ABSENT:
                return self.clone_step(f"{clone} was left unfinished",
                                       {"CHANGE": state.change})
            return self.in_clone(clone, "it is worked in its own clone")
        branch = self._branch(self.root)
        if branch and (branch == default_branch(state.change)
                       or branch_decisions(state.log, branch, state.change)):
            return None
        if view is not None:
            # This checkout's branch is another change's, moved to show its round.
            return None
        reviews = state.directory / "reviews" if state.directory else None
        if reviews is not None and reviews.is_dir() and any(reviews.iterdir()):
            return _owner(
                f"{state.change}'s branch is not checked out here, but its records are in "
                "this workspace's reviews/, which a clone would start without: check out "
                f"its branch here and go on in the workspace, or move it into a clone by "
                "hand as docs/agents/change-workflow.md describes",
                routes=["work it in the workspace", "move it into a clone by hand"])
        return self.clone_step(
            f"{state.change}'s branch is checked out neither here nor in a clone of its own",
            {"CHANGE": state.change, "BRANCH": default_branch(state.change),
             "FROM": DEFAULT_FROM})

    def in_clone(self, clone: Path, why: str) -> Result:
        return {"step": "in-clone", "clone": str(clone),
                "reason": f"{self.state.change} is computed in its clone, {clone}, since "
                          f"{why}: run this computation and every step there"}

    def clone_step(self, why: str, arguments: dict[str, str]) -> Result:
        command = " ".join(["make change-clone",
                            *(f"{name}={value}" for name, value in arguments.items())])
        return {"step": "clone", "arguments": arguments,
                "reason": f"{why}: run `{command}` in the owner's workspace"}

    def bootstrap_held(self) -> Result | None:
        """In a clone, a bootstrap never started, or one that failed, ahead of any
        step: the first is an unfinished clone, the second the owner's to remedy."""
        state = self.state
        state.bootstrap = self._bootstrap(self.root)
        if state.bootstrap.state == BOOTSTRAP_ABSENT:
            return self.clone_step("this clone's bootstrap was never started, so its "
                                   "creation is unfinished", {"CHANGE": state.change})
        if state.bootstrap.state == BOOTSTRAP_FAILED:
            # Not retried by itself: `make init` failing is almost always the
            # environment, and a silent retry would hide it.
            return _owner(f"the clone's bootstrap, `make init`, failed — an environmental "
                          f"failure; its log is {state.bootstrap.log}, and `make change-clone "
                          f"CHANGE={state.change}` in the workspace restarts it",
                          environmental=True, log=str(state.bootstrap.log))
        return None

    def bootstrapping(self, result: Result) -> Result | None:
        """The step `result` names, held while the clone's bootstrap runs, unless it
        is a design or planning step, which need no environment: design and plan
        themselves, and a review or triage of the design phase. With
        `bootstrap_held`, this is the table's held guard `graph.BOOTSTRAPPED`."""
        state = self.state
        if state.bootstrap is None or state.bootstrap.state != BOOTSTRAP_RUNNING:
            return None
        phase = _phase(state.row.status if state.row else "")
        if result.get("step") in ("design", "plan") or phase in ("design", "planning"):
            return None
        return {"step": "wait", "waits": result,
                "reason": f"the clone's bootstrap, `make init`, is still running (log: "
                          f"{state.bootstrap.log}); {result['step']} waits for it"}

    def route(self) -> Result:
        state = self.state
        status = state.row.status if state.row else ""
        if status == "archived":
            return {"step": "done", "reason": "archived"}
        if status == "deferred":
            return _owner(f"deferred: {state.notes}")
        if status.startswith("blocked in"):
            return _owner(f"{status}: {state.notes}")
        phase = _phase(status)
        if phase is None:
            return self.unclassified(f"status {status!r} names no phase")
        if waiting := self.dependencies(phase):
            return waiting
        if waiting := self.pending(phase):
            return waiting
        if directed := self.directed():
            return directed
        return getattr(self, f"_{phase}")(status)

    def dependencies(self, phase: str) -> Result | None:
        """A dependency that gates `phase` or an earlier one, and is not yet released:
        the table's held guards on the exits into planning, implementation, and
        closeout (`graph.PLANNING_RELEASED`, `graph.IMPLEMENTATION_RELEASED`,
        `graph.CLOSEOUT_RELEASED`), and a dependency gating design, which holds the
        change before its first node."""
        depends_on = self.state.row.depends_on if self.state.row else None
        if depends_on in (None, "", "—"):
            return None
        for entry in (part.strip() for part in depends_on.split(",")):
            match = _DEPENDENCY.match(entry)
            if match is None:
                return self.unclassified(f"Depends on entry {entry!r} is not a change name "
                                         "with an optional (phase)")
            gates = match["phase"] or "implementation"
            if gates not in PHASES or PHASES.index(gates) > PHASES.index(phase):
                continue
            name = match["name"]
            try:
                directory = change_directory(self.root, name)
            except ChangeNotFound:
                return _owner(f"{name}, which {gates} depends on, has no directory on this "
                              "branch: merge dev once its proposal has landed there",
                              prerequisite=name)
            if is_archived(self.root, directory):
                return _owner(f"{name} is archived on this branch: release the dependency "
                              f"(drop it from Depends on, leaving the status), then resume "
                              f"{gates}", release=name)
            return _owner(f"{gates} waits on {name}, which is not archived",
                          prerequisite=name)
        return None

    # Where the change stands in the graph, and the exit its last step chose, read
    # from the status, the latest runs of its steps, and the `## Next` tokens of its
    # triage files; each exit is then followed through its guards in the table
    # (`follow`). The status's phase says where to start reading, and each phase's
    # reading is called with the status.

    def _design(self, status: str) -> Result:
        if status == "ready for design":
            return DESIGN.result("ready for design")
        if blocked := self.blocked_on_prerequisite():
            return blocked
        if untriaged := self.untriaged(kinds=("design",)):
            return self.follow(DESIGN_REVIEW, DESIGN_TRIAGE, f"{untriaged} has no triage")
        last = self.last(("design", "review", "triage"))
        if last and last.get("step") == "design":
            if last.get("outcome") == "finished":
                if waiver := self.waived_design_review(last):
                    planned = next((e for e in reversed(self.state.log)
                                    if e.get("step") == "plan" and e["seq"] > waiver["seq"]),
                                   None)
                    if planned is None:
                        return {"step": "plan",
                                "reason": f"the owner waived another design review after "
                                          f"the return (seq {waiver['seq']})"}
                    # Planning ran on the waiver and the change is still in design: it
                    # did not take the change on, so the owner decides, never a rerun.
                    if waiting := _waiting(planned):
                        return {**waiting, "seq": planned["seq"]}
                    return _owner(f"planning ran on the owner's waiver (seq "
                                  f"{planned['seq']}) but left the change in design: the "
                                  "files decide, so the status is the owner's to correct")
                return self.follow(DESIGN, DESIGN_REVIEW, "the design discussion finished; "
                                                          "its design review is next")
            return DESIGN.result("in design")
        reviews = [r for r in self.state.records if r.review_kind == "design"]
        if not reviews:
            return DESIGN.result("in design")
        review = reviews[-1]
        if waiting := self.not_advancing(review, DESIGN_TRIAGE):
            return waiting
        if review.next_token() == RETURNED:
            return self.follow(DESIGN_TRIAGE, DESIGN, f"{review.triage.name} returned the "
                                                      "change to design", review=review)
        if review.next_token() == ANOTHER_ROUND:
            return self.follow(DESIGN_TRIAGE, DESIGN_REVIEW,
                               f"{review.triage.name} records another round", review=review)
        return self.follow(DESIGN_TRIAGE, PLAN, f"{review.triage.name} records that the change "
                                                "advances", review=review)

    def _planning(self, status: str) -> Result:
        if status == "ready for planning":
            return PLAN.result("ready for planning")
        last = self.last(("plan",))
        if last and last.get("outcome") == "finished":
            # Planning sets the change ready for implementation as it finishes.
            return _owner("the plan finished but left the change in planning: the files "
                          "decide, so the status is the owner's to correct")
        return PLAN.result("in planning")

    def _implementation(self, status: str) -> Result:
        state = self.state
        rounds = [e for e in state.log if e.get("outcome") == "round"]
        work = [s for s in state.sections if not s.closeout]
        if not state.sections:
            return self.unclassified("the task list has no sections")
        if problems := task_problems(state.tasks):
            # The skills check the task list before acting on it; this is the
            # backstop for the one phase routed on its sections, since a list
            # missing a heading would have whole sections repeated or skipped.
            return self.unclassified("the task list is malformed: " + "; ".join(problems))
        current = rounds[-1] if rounds else None
        if current and self.set_aside(current):
            # Read before the round's sections: the amended plan may have renumbered
            # or dropped them. The next round's own validation covers the
            # work-in-progress commit the return left, so none is asked for before it.
            return self.planned(work)
        round_sections = ([str(s) for session in current["sections"] for s in session]
                          if current else [])
        by_id = {s.id: s for s in state.sections}
        if current and (unknown := [s for s in round_sections if s not in by_id]):
            return self.unclassified(f"the agreed round names sections the task list lacks: "
                                     f"{', '.join(unknown)}")

        def unfinished(section: Any) -> bool:
            # The closeout section is closeout's, never a round's to implement.
            return not by_id[str(section)].complete and not by_id[str(section)].closeout

        # The round's join waits first for its sections, each session in turn.
        if current and any(unfinished(s) for s in round_sections):
            for session in current["sections"]:
                if any(unfinished(s) for s in session):
                    return {
                        "step": "implement", "sections": session,
                        "reason": "the agreed round's sections are not all checked"}
        if current is None:
            return self.planned(work)
        return self.in_round(current, work)

    def planned(self, work: list[Section]) -> Result:
        """The plan's exit: its next round, or, with nothing left to implement, the
        pre-closeout review."""
        if all(s.complete for s in work):
            return self.pre_closeout(PLAN)
        if unmet := self.unmet(PLAN, ROUND):
            return unmet
        return self.next_round(work)

    def next_round(self, work: list[Section]) -> Result:
        """The next round of the latest plan's mapping, for the orchestrating session
        to record `by: plan` as it starts; the owner when there is no mapping.

        The governing plan line is the latest `finished` plan line, so an amended
        plan's mapping replaces the earlier one for the sections it maps; the next
        round is the first of its `rounds` with a section the task list does not
        show complete. A change planned before plans carried a mapping, or whose
        first open section no planned round names — one a triage appended — is the
        owner's to distribute, once per round. A closeout section a plan maps is
        left out of the round, since closeout implements it, and so is a section
        already complete. A round naming a section the task list lacks goes to the
        owner before anything is recorded: the mapping no longer describes the plan,
        and a round line naming it would leave the round unclassifiable.
        """
        open_ids = [s.id for s in work if not s.complete]
        by_id = {s.id: s for s in self.state.sections}
        plan = next((e for e in reversed(self.state.log)
                     if e.get("step") == "plan" and e.get("outcome") == "finished"), None)
        planned = plan.get("rounds") if plan else None
        if isinstance(planned, list) and planned:
            mapped = {str(s) for round_ in planned for session in round_ for s in session}
            if open_ids[0] not in mapped:
                return _owner("agree the next implementation round: the plan maps no round "
                              f"for section {open_ids[0]}", round=open_ids)
            for round_ in planned:
                if any(str(s) in open_ids for session in round_ for s in session):
                    if unknown := [str(s) for session in round_ for s in session
                                   if str(s) not in by_id]:
                        return _owner("agree the next implementation round: the plan's round "
                                      "names sections the task list lacks: "
                                      + ", ".join(unknown), round=open_ids)
                    sessions = [kept for session in round_
                                if (kept := [s for s in session if str(s) in open_ids])]
                    return {"step": "round", "sections": sessions, "by": "plan",
                            "reason": f"the plan's next round (seq {plan['seq']}): record "
                                      "it as it starts, then implement it"}
        return _owner("agree the next implementation round: which sections, and how many "
                      "sessions; the plan maps none", round=open_ids)

    def in_round(self, current: dict[str, Any], work: list[Section]) -> Result:
        """The round's sections are checked: the rest of its join — its reading,
        validation, and review — then its triage, and the exit that triage chose.

        A change worked in this checkout is read first, since its view moves the
        branch its own steps run on. A change in its own clone is read in the
        owner's workspace while its validation and review run in the clone, so the
        reading holds triage alone: triage is named once the owner record, the
        review, and the validation all exist and the workspace's view is closed.

        A triage that records another round over a committed fix opens a repeat
        pass, read in the same way from the commit that triage's review read: the
        fix is work the owner has not seen, and the repeat round exists because it
        changed something central. The pass's reading is an owner record saved after
        that triage finished — in a clone the first pass's record may be numbered
        after the review, since it is read beside it — and the result naming the
        reading carries the pass's `base`.
        """
        state = self.state
        mine = [r for r in state.records if r.number > current.get("after", 0)]
        kinds = {r.review_kind or r.kind for r in mine}
        in_clone = state.workspace is not None
        if not in_clone and not kinds & {"implementation-owner", "implementation",
                                         "validation"}:
            return ROUND_VIEW.result("the round's sections are committed; the owner reads "
                                     "the round")
        again = next((r for r in reversed(mine) if r.review_kind == "implementation"
                      and r.next_token() == ANOTHER_ROUND), None)
        base = again.reviewed_commit if again and self.fixed_since(again) else None
        if again is None:
            unread = in_clone and "implementation-owner" not in kinds
        else:
            # Records are never rewritten, so a record's time is when it was saved,
            # and a triage file's is when `## Next` ended it.
            finished = again.triage.stat().st_mtime_ns
            unread = base is not None and not any(
                r.kind == "implementation-owner" and r.number > again.number
                and r.path.stat().st_mtime_ns > finished for r in mine)
        pass_base = {"base": base} if base else {}
        view = state.workspace_view if in_clone else None
        # A view the owner left open over an earlier round, or an earlier pass,
        # following its fixes, is not this pass's reading; this one needs it closed
        # first. A base may be named by an abbreviated commit, a pasted review's.
        started = base or current.get("commit")
        if view is not None and started and not (view.base.startswith(started)
                                                  or started.startswith(view.base)):
            if unread:
                return _owner("a view of an earlier round, or of this round's earlier pass, "
                              "is open in the workspace: run `make round-done` there, so this "
                              "pass can be read over its own base", round_view=state.change,
                              workspace=str(state.workspace))
            view = None
        viewing = view is not None
        missing = [kind for kind in ("validation", "implementation") if kind not in kinds]
        if missing:
            result: Result = (
                {"step": "validate-and-review", "kind": "implementation",
                 "reason": "the round has no validation or implementation review"}
                if missing == ["validation", "implementation"]
                else VALIDATE.result("the round has no validation")
                if missing == ["validation"]
                else IMPLEMENTATION_REVIEW.result("the round has no implementation review"))
            if unread and not viewing:
                result.update(reading=True, workspace=str(state.workspace))
                result["reason"] += ("; the owner reads the round in the workspace beside "
                                     "them")
            return result
        # A validation that passed, or was inconclusive, has no finding: the fix
        # commit's validation alone opens no triage, though one opened for the
        # round's other records triages it beside them. A repeat pass's owner record
        # waits for the pass's own review, as a first pass's does.
        reviewing = again is not None and not any(
            r.review_kind == "implementation" and r.number > again.number for r in mine)
        untriaged = [r for r in mine if not r.triaged
                     and not (reviewing and r.kind == "implementation-owner")]
        if any(not r.needs_no_triage for r in untriaged):
            if viewing:
                return _owner(("the owner is reading the round in the workspace: save their "
                               "answer as this clone's next NN-implementation-owner.md, then "
                               "run `make round-done` in the workspace, before triage")
                              if unread else
                              ("the owner's answer on the round is saved, and its view is "
                               "still open in the workspace: run `make round-done` there "
                               "before triage"),
                              round_view=state.change, workspace=str(state.workspace))
            # Before a repeat pass's review is in, a fix commit's failed validation
            # is triaged alone, and the reading waits for the review.
            if unread and not reviewing:
                return {"step": "round-view", **pass_base,
                        **({"workspace": str(state.workspace)} if in_clone else {}),
                        "reason": "the round's validation and review are in, and the owner "
                                  "reads the round" + (" in the workspace" if in_clone else "")
                                  + " before triage"}
            return self.follow(IMPLEMENTATION_REVIEW, IMPLEMENTATION_TRIAGE,
                               ", ".join(r.path.name for r in untriaged) + " have no triage")
        review = governing([r for r in mine if r.review_kind == "implementation"])
        if waiting := self.not_advancing(review, IMPLEMENTATION_TRIAGE):
            return waiting
        if review.next_token() == ANOTHER_ROUND:
            result = self.follow(IMPLEMENTATION_TRIAGE, IMPLEMENTATION_REVIEW,
                                 f"{review.triage.name} records another round", review=review,
                                 unread=unread, in_clone=in_clone, base=pass_base)
            if unread and not viewing and result["step"] in ("validate", "review"):
                result.update(reading=True, workspace=str(state.workspace), **pass_base)
                result["reason"] += "; the owner reads the fix in the workspace beside it"
            return result
        # Anything else advances: a return waits above until the owner confirms it,
        # and once confirmed has set the round aside before it is read here.
        if all(s.complete for s in work):
            if unmet := self.unmet(IMPLEMENTATION_TRIAGE, PRE_CLOSEOUT_REVIEW):
                return unmet
            return self.pre_closeout(IMPLEMENTATION_TRIAGE)
        if unmet := self.unmet(IMPLEMENTATION_TRIAGE, ROUND):
            return unmet
        return self.next_round(work)

    def pre_closeout(self, source: Node) -> Result:
        """The pre-closeout review, reached by `source`'s exit to it, and where its
        triage leads: the review is named once that exit's guards hold."""
        if untriaged := self.untriaged(kinds=("pre-closeout",)):
            return self.follow(PRE_CLOSEOUT_REVIEW, PRE_CLOSEOUT_TRIAGE,
                               f"{untriaged} has no triage")
        reviews = [r for r in self.state.records if r.review_kind == "pre-closeout"]
        review = governing(reviews) if reviews else None
        if review is not None and (waiting := self.not_advancing(review, PRE_CLOSEOUT_TRIAGE)):
            return waiting
        # A review whose triage returned the change describes work the return
        # replaced, so the work implemented since is reviewed afresh.
        if review is None or review.next_token() == RETURNED:
            return self.follow(source, PRE_CLOSEOUT_REVIEW,
                               "every section before closeout is checked and validated")
        # From here closeout is next, and its own checks read the documentation, so
        # a triage's commit of documents alone needs no validation.
        if review.next_token() == ANOTHER_ROUND:
            return self.follow(PRE_CLOSEOUT_TRIAGE, PRE_CLOSEOUT_REVIEW,
                               f"{review.triage.name} records another round", review=review)
        return self.follow(PRE_CLOSEOUT_TRIAGE, CLOSEOUT,
                           f"{review.triage.name} records that the change advances, and "
                           "HEAD is validated", review=review)

    def _closeout(self, status: str) -> Result:
        state = self.state
        if status == "ready for closeout" or not is_archived(self.root, state.directory):
            return CLOSEOUT.result(status)
        if self._uncommitted(self.root, state.directory):
            return CLOSEOUT.result("the archive is not committed: closeout resumes after its "
                                   "archive step")
        if untriaged := self.untriaged(kinds=("closeout",)):
            return self.follow(CLOSEOUT_REVIEW, CLOSEOUT_TRIAGE, f"{untriaged} has no triage")
        reviews = [r for r in state.records if r.review_kind == "closeout"]
        if not reviews:
            return self.follow(CLOSEOUT, CLOSEOUT_REVIEW,
                               "the change is archived; its closeout review is next")
        review = governing(reviews)
        if waiting := self.not_advancing(review, CLOSEOUT_TRIAGE):
            return waiting
        if review.next_token() == RETURNED:
            # The table gives a closeout triage no return among its exits.
            return _owner(f"{review.triage.name} records a return, and an archived change "
                          "has no earlier phase to return to: the owner directs its "
                          "correction")
        if review.next_token() == ANOTHER_ROUND:
            return self.follow(CLOSEOUT_TRIAGE, CLOSEOUT_REVIEW,
                               f"{review.triage.name} records another round", review=review)
        return self.follow(CLOSEOUT_TRIAGE, ARCHIVE_CLEANUP,
                           f"{review.triage.name} records that the change advances",
                           review=review, first=reviews[0])

    # Following an exit through the table.

    def unmet(self, source: Node, target: Node | None = None, *, when: str | None = None,
              **context: Any) -> Result | None:
        """The first unmet guard's result on the exit of `source` to `target`, or taken
        on `when`, in the table's order; None when every guard holds. A held guard
        is skipped: `dependencies` holds the change on it before it is read, and
        `bootstrap_held` and `bootstrapping` around whatever is named. The exits a
        return may take share their guard, so a return names no target."""
        found = graph.exits(source, target=target, when=when)
        if not found:
            raise StepError(f"the workflow graph gives {source.label} no exit "
                            f"{target.label if target else when}")
        for guard in found[0].guards:
            if guard.check is not None and (result := guard.check(self, context)):
                return result
        return None

    def follow(self, source: Node, target: Node, reason: str, **context: Any) -> Result:
        """The exit of `source` to `target`: the first unmet guard's remedy, or
        `target`'s step once every guard holds."""
        return self.unmet(source, target, **context) or target.result(reason)

    # Shared readings.

    def last(self, steps: Sequence[str]) -> dict[str, Any] | None:
        """The latest log line of one of `steps`."""
        return next((e for e in reversed(self.state.log) if e.get("step") in steps), None)

    def pending(self, phase: str) -> Result | None:
        """A step whose latest run waits on the owner, if one does.

        A question is answered by resuming its session; a returned, blocked, or
        stopped run is decided by the owner or the orchestrating session; none is
        routed past by running the step afresh. A run that went on past a denial
        waits first for the orchestrating session's reading of it, an
        `orchestrator` line that `reads` the run, and then for its outcome's
        answer or decision as any other. A decision line names the run it
        resolves, and only that run stops waiting: a decision about one step's
        run says nothing about another's, and a line that resolves a run counts
        as having read it. A design that ended blocked on a prerequisite is the
        prerequisite rules', not this one's, once its denials, if any, are read.

        A question, return, block, or stop without unread denials waits only in
        the phase it was raised in: a crashed design triage must not hold
        implementation. Unread denials wait whatever the phase, since the step
        that recorded them may be the one that moved the change on — a design
        triage recording `Advance` sets the status to the next phase in the same run
        — and the reading is owed before any step runs; a stopped run with
        denials waits, in any phase, until a line resolves it or its resumed run
        supersedes it as its step's latest. The result names the waiting run's
        `seq`, which a resume must give.
        """
        log = self.state.log
        decisions = [e for e in log if e.get("outcome") == ORCHESTRATOR]
        resolved = {e.get("resolves") for e in decisions}
        read = {e.get("reads") for e in decisions} | resolved
        latest: dict[str, dict[str, Any]] = {}
        latest_any: dict[str, dict[str, Any]] = {}
        steps = graph.phase_steps(phase)
        for index, entry in enumerate(log):
            name = entry.get("step")
            if name == ORCHESTRATOR:
                continue
            latest_any[name] = entry
            if name not in steps:
                continue
            if name == "review" and graph.review_phase(entry.get("kind", "")) != phase:
                continue
            if name == "triage" and _triage_phase(log[:index]) not in (phase, None):
                continue
            latest[name] = entry
        waiting = [(entry["seq"], result) for entry in latest_any.values()
                   if entry.get("denials")
                   and entry["seq"] not in (resolved if entry.get("outcome") == "stopped"
                                            else read)
                   and (result := _waiting(entry, read=False))]
        unread = {seq for seq, _ in waiting}
        waiting += [(entry["seq"], result) for entry in latest.values()
                    if entry["seq"] not in resolved and entry["seq"] not in unread
                    and (result := _waiting(entry, read=entry["seq"] in read))
                    and not (entry.get("step") == "design" and "blocked_on" in result)]
        if not waiting:
            return None
        seq, result = max(waiting)
        return {**result, "seq": seq}

    def directed(self) -> Result | None:
        """The step the latest decision directs, until that step has run.

        An `orchestrator` line with `next` is the owner's word on a step: a
        confirmed return names the phase's step, which sets the status when it
        runs, and resolves the returned run, which would otherwise wait ahead of
        it; a review asked for again outside a triage names `review` and its kind,
        and no run; and the owner's waiver of the validation `_closeout` names
        directs archive cleanup, and no run, ahead of that validation. A line
        directing any step but a review is the owner's alone, so one the log
        attributes to anyone else directs nothing. It still resolves its run: a
        triage's return the phase's routing then finds unconfirmed, and any other
        returned run is left resolved, as by a decline.
        """
        log = self.state.log
        decision = next((e for e in reversed(log)
                         if e.get("outcome") == ORCHESTRATOR and directed_step(e)
                         and (directed_step(e) == "review" or e.get("by") == "owner")), None)
        if decision is None:
            return None
        step = directed_step(decision)
        kind = (decision["next"].get("kind") if isinstance(decision["next"], dict)
                else decision.get("kind"))
        if any(e["seq"] > decision["seq"] and e.get("step") == step
               and (step != "review" or kind is None or e.get("kind") == kind)
               for e in log):
            return None
        result = {"step": step, "reason": f"directed by the decision at seq {decision['seq']}: "
                                          f"{decision.get('decision', '')}"}
        if kind:
            result["kind"] = kind
        return result

    def waived_design_review(self, design: dict[str, Any]) -> dict[str, Any] | None:
        """The owner's waiver of another design review, recorded after `design`, the
        finished design run that followed a confirmed return, if there is one: a
        decision directing planning and naming no run."""
        log = self.state.log
        if not redesigned_after_return(log):
            return None
        return next((entry for entry in reversed(log)
                     if entry.get("outcome") == ORCHESTRATOR and entry.get("by") == "owner"
                     and directed_step(entry) == "plan" and entry.get("resolves") is None
                     and entry["seq"] > design["seq"]), None)

    def not_advancing(self, review: Record, triage: Node) -> Result | None:
        """The step while `review`'s triage, the node `triage`, records no token the
        phase can route on: the triage, while it has no `## Next`; the owner, for a
        legacy gate not passed, a `## Next` without a token, or a return whose guard
        does not hold, where `triage` has a return among its exits."""
        token = review.next_token()
        if token == IN_PROGRESS:
            return triage.result(f"{review.triage.name} has no `## Next`: its triage is in "
                                 "progress")
        if token == OWNER:
            return _owner(f"{review.triage.name} records neither Advance, Another round, nor "
                          "Returned under `## Next`, or a gate it did not pass: the owner "
                          "decides what follows")
        if token == RETURNED and graph.exits(triage, when=graph.RETURN):
            return self.unmet(triage, when=graph.RETURN, review=review)
        return None

    def return_confirmed(self, review: Record) -> bool:
        """Whether the owner confirmed the return `review`'s triage records: the
        owner's decision resolving a returned triage run and directing design or
        planning, recorded once that triage wrote its `## Next`.

        Triage writes `## Next` as its last edit and is never rewritten after it,
        so the file's time is when the return was proposed, and a decision from
        before it confirmed some earlier return. A triage run's log line does not
        name the review it triaged, so the file's time is what ties the two. Until
        the owner decides, the returned run waits in `pending`, ahead of the
        phase's routing; a decision resolving it without directing design or
        planning declines the return, and the triage's `Returned` no longer says
        what follows."""
        log = self.state.log
        returned = {e["seq"] for e in log
                    if e.get("step") == "triage" and e.get("outcome") == "returned"}
        proposed = review.triage.stat().st_mtime_ns // 1_000_000_000
        return any(e.get("outcome") == ORCHESTRATOR and e.get("by") == "owner"
                   and e.get("resolves") in returned
                   and directed_step(e) in ("design", "plan")
                   and isinstance(e.get("at"), str) and _seconds(e["at"]) >= proposed
                   for e in log)

    def set_aside(self, current: dict[str, Any]) -> bool:
        """Whether a confirmed return set the current round aside: the review that
        governs it — its implementation review, or the pre-closeout review after
        it — records `Returned`, and the owner confirmed it.

        What the design or plan made of the return is a round of its own, read,
        validated, and reviewed afresh, even where it reworks one of this round's
        sections, so this round's records no longer decide anything."""
        reviews = [r for r in self.state.records if r.number > current.get("after", 0)
                   and r.review_kind in ("implementation", "pre-closeout")]
        if not reviews:
            return False
        review = governing(reviews)
        return review.next_token() == RETURNED and self.return_confirmed(review)

    def validated(self, why: str, exempt: Callable[[str], bool] = is_record) -> Result | None:
        """None when the latest validation passed for `HEAD`, or for an ancestor it
        differs from only in `exempt` paths, changes' records by default. Otherwise
        validation, when the latest record describes another commit; or the owner,
        when it describes `HEAD` and did not pass — an `inconclusive` result is
        missing evidence, never a pass."""
        head = self.state.head
        reviews = self.state.directory / "reviews"
        if head is None:
            return {"step": "validate", "reason": f"{why}: HEAD cannot be read"}
        if problem := validation_problem(reviews, head, self.root, self._changed_since,
                                         require_passed=False, exempt=exempt):
            return {"step": "validate", "reason": f"{why}: {problem}"}
        record = latest_validation(reviews)
        result = validation_result(record) if record else None
        if result != "passed":
            # Nothing the owner records clears it: a validation that passes does.
            # Before archive cleanup the owner's waiver routes past it (`directed`)
            # without clearing it.
            return _owner(f"{why}, and {record.name if record else 'the validation'} of HEAD "
                          f"is {result or 'without a result'}: the owner decides how the "
                          "missing evidence is had, and validation runs again",
                          validation=result)
        return None

    def fixed_since(self, review: Record, exempt: Callable[[str], bool] = is_record) -> bool:
        """Whether `HEAD` changed more than `exempt` paths, changes' records by
        default, since `review` read it: a fix the triage accepted has been
        committed."""
        reviewed, head = review.reviewed_commit, self.state.head
        if reviewed is None or head is None or head.startswith(reviewed):
            return False
        changed = self._changed_since(self.root, reviewed, head)
        if changed is None:
            # Not an ancestor: HEAD is not the reviewed commit, however it moved.
            return True
        return any(not exempt(path) for path in changed)

    def changed_outside_documentation(self, review: Record) -> str | None:
        """A path outside `openspec/` and `docs/` that `HEAD` changes since the commit
        `review` read, if there is one: a correction that needs validating."""
        reviewed, head = review.reviewed_commit, self.state.head
        if reviewed is None or head is None or head.startswith(reviewed):
            return None
        changed = self._changed_since(self.root, reviewed, head)
        if changed is None:
            # Not an ancestor: what HEAD changes since it cannot be told.
            return f"{head[:12]}, which does not descend from {reviewed[:12]},"
        return next((path for path in changed if not is_documentation(path)), None)

    def untriaged(self, kinds: Sequence[str]) -> str | None:
        for record in reversed(self.state.records):
            if record.review_kind in kinds and not record.triaged:
                return record.path.name
        return None

    def blocked_on_prerequisite(self) -> Result | None:
        """A design that ended blocked, until its prerequisite's row reaches this
        branch by merging dev and the dependency is recorded."""
        last = self.last(("design",))
        if not last or last.get("outcome") != "blocked":
            return None
        name = last.get("blocked_on", "")
        depends_on = (self.state.row.depends_on or "") if self.state.row else ""
        try:
            prerequisite = change_directory(self.root, name)
        except ChangeNotFound:
            return _owner(f"the design is blocked on {name}, whose proposal is not on this "
                          "branch: merge dev once it has landed there", prerequisite=name)
        if is_archived(self.root, prerequisite):
            # Landed and merged in: once its dependency is released, design resumes.
            return None
        if f"`{name}`" not in depends_on:
            return {"step": "design", "reason": f"{name} has reached this branch: record "
                                                "the dependency, gating design"}
        return None

    def validation_problem(self) -> str | None:
        head = self.state.head
        if head is None:
            return "HEAD cannot be read"
        return validation_problem(self.state.directory / "reviews", head, self.root)

    def disagreement(self) -> str | None:
        """How the log's last step disagrees with the status, if it does."""
        lines = [e for e in _step_lines(self.state.log) if _STEP_PHASE.get(e.get("step"))]
        status = self.state.row.status if self.state.row else ""
        phase = _phase(status)
        if not lines or phase is None:
            return None
        logged = _STEP_PHASE[lines[-1]["step"]]
        if PHASES.index(logged) > PHASES.index(phase):
            return (f"the status is {status!r}, but the log's last step was "
                    f"{lines[-1]['step']} (seq {lines[-1]['seq']}); the files decide")
        return None


def compute(root: Path, change: str, **seams: Any) -> Result:
    try:
        return Computation(root, change, **seams).run()
    except (StepError, OSError) as exc:
        return {"step": "unclassified", "reason": f"{type(exc).__name__}: {exc}"}


def plain(result: Result) -> str:
    """The result as lines of `field: value`, for reading rather than parsing:
    the step and its reason first, then what else it carries — a waiting run's
    `seq` and what it asks, a review's kind, a round's sections."""
    first = [key for key in ("step", "reason") if key in result]
    keys = first + sorted(key for key in result if key not in first)
    shown = {key: value if isinstance(value, str)
             else json.dumps(value, ensure_ascii=False, default=str)
             for key, value in result.items()}
    return "\n".join(f"{key}: {shown[key]}" for key in keys)


def main(argv: Sequence[str] | None = None, root: Path = ROOT, **seams: Any) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    as_text = "--plain" in args
    args = [arg for arg in args if arg != "--plain"]
    if len(args) != 1:
        print("usage: change_next_step.py <change> [--plain]", file=sys.stderr)
        return 2
    result = compute(root, args[0], **seams)
    print(plain(result) if as_text else json.dumps(result, ensure_ascii=False, default=str))
    return 1 if result["step"] == "unclassified" else 0


if __name__ == "__main__":
    sys.exit(main())
