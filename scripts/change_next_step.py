#!/usr/bin/env python3
"""Compute the next step of an OpenSpec change from its files and workflow log.

The orchestrating session runs whatever this names and never routes on its own
reading; the owner can run the same command by hand. It reads the change's row in
`openspec/changes/README.md` (status, `Depends on`, `Notes`), its numbered review
records and their triage, the sections and checks of its task list, its workflow
log, and whether a round view is open, and prints one JSON object:

- `{"step": <step>, "reason": …}` for a step to run: `design`, `plan`, `round`
  (with the `sections` of each session of the round, to be recorded with its `by`
  as it starts: the plan's next round, or sections a triage or the owner named out
  of the plan's order), `implement` (with its `sections`), `round-view`,
  `validate` (with the `target` it is for), `review` (with its `kind`),
  `validate-and-review` (with the review's `kind` and the validation's `target`),
  `triage` (with the `kind` of review it triages), `closeout`, or
  `archive-cleanup`; a step named as the remedy of a guard on an exit carries that
  exit as its `target`; for a change in its own clone, a `round-view`, or a
  validation or review that runs beside the owner's reading (`reading`), names the
  `workspace` the reading takes place in; the reading of a repeat pass, over a fix
  triage committed, names its `base`, the commit the view starts from;
- `{"step": "clone", "arguments": …}` when the change's clone is to be created,
  or finished, with `make change-clone` and those arguments;
  `{"step": "in-clone", "clone": …}` when the change is worked in its clone, where
  this computation and every step are run; `{"step": "wait", …}` while the
  clone's bootstrap runs and the step named would need it;
- `{"step": "owner", "reason": …}` when only the owner can move the change on: a
  merge in progress in the checkout (`merging`), named before anything else is
  read, a question to answer, a returned step to decide, a round the plan does not
  map, a validation that did not pass, a prerequisite to land, a failed bootstrap,
  a change whose records are in the workspace but whose branch is not, an exit its
  node does not declare (`choice`, and the node's `exits`), an exit whose target
  cannot be entered, or a change whose records predate the log's format, with the
  command that converts them (`convert`); for a waiting run, its `seq` — a question
  or a stop is resumed by it; for a guard on an exit no step can satisfy, the exit
  as `target`;
- `{"step": "done", …}` for an archived change, or once archive cleanup names it;
- `{"step": "unclassified", "reason": …, "read": …}` when no rule applies, with
  what it read, for the orchestrating session to work out.

The workflow's graph is the table in `change_workflow/graph.py`: each node's exits,
the join an exit waits on, the guards on each exit with the step that remedies
each, and each node's entry guards. This computation reads the route from the log
— the exit the last step's outcome named, or the owner's latest direction until a
run of the node it directs is logged — and checks it against the table. An exit
its node does not declare, a validation's exit other than the target it was given,
and an exit whose target's entry guard is not met name the owner; an unmet guard on
a declared exit names the step that remedies it, carrying the exit as `target`, or
the owner where no step can; a direction checks no exit guard. A validation that
clears a guard leaves the route where it was, so the guard is checked again. The
round's join is read from the records its members supply (`graph.ROUND_JOIN`). A
review's triage file routes nothing: a review whose triage file exists while no
triage outcome, and no conversion line, names it is a triage in progress.

Every line the workflow tooling appends to a log carries the log's format marker. A
change whose log holds a line without it, or that has numbered records and no log,
is routed on none of them: the owner converts its records first.

The files hold the change's state and the log its route: the step the route names
is named whatever the status says. Where the status is past that step — a step that
set its status and closed before recording its outcome — or the log's last step is
past the status, a status set back by hand, the result carries a `disagreement`
saying so.

A change is computed where it is worked: in the checkout that has its branch
checked out — its own name's branch, or one the owner's decision says it is
worked on — or in its own clone. Run anywhere else, the computation names the
clone, to compute there or to create, or the owner, for a change whose records
are in this workspace and so cannot simply be cloned. In a clone, implementation
and later steps wait for the clone's bootstrap, and the owner reads a round in
the workspace beside its validation and review, the workspace's view read
through the clone's `workspace` remote. A task list whose tasks sit under another
section's heading is not routed on (`task_problems`, which
`scripts/check_tasks.py` runs for the skills). `--plain` prints the result as
lines rather than JSON.

Contract: openspec/specs/change-workflow/spec.md, "The next step is computed from
the files".
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from change_clone import (ABSENT as BOOTSTRAP_ABSENT, DEFAULT_FROM,  # noqa: E402
                          FAILED as BOOTSTRAP_FAILED, RUNNING as BOOTSTRAP_RUNNING, Bootstrap,
                          bootstrap_state, clone_of, default_branch, workspace_of)
from check_change_index import _DEPENDENCY, INDEX, Row, index_rows  # noqa: E402
from find_change import ChangeNotFound, change_directory, is_archived  # noqa: E402
from round_view import RoundError, View, open_view  # noqa: E402
from change_workflow import graph  # noqa: E402
from change_workflow.common import ORCHESTRATOR, STEPS, StepError  # noqa: E402
from change_workflow.graph import (CLOSEOUT, CLOSEOUT_REVIEW, DESIGN, DONE,  # noqa: E402
                                   IMPLEMENTATION_REVIEW, IMPLEMENTATION_TRIAGE, PHASES,
                                   ROUND, ROUND_JOIN, ROUND_VIEW, VALIDATE, Join, Node,
                                   Standing, TargetError, entry_refusal, node_of)
from change_workflow.graph import owner as _owner  # noqa: E402
from change_workflow.log import (FORMAT, LOG, branch_decisions, log_path,  # noqa: E402
                                 ran, read_log, standing)
from change_workflow.records import (ChangedSince, changed_since,  # noqa: E402
                                     is_documentation, is_record, latest_validation,
                                     validation_problem, validation_result)

ROOT = Path(__file__).resolve().parents[1]
_RECORD = re.compile(r"^(?P<number>\d+)-(?P<kind>[a-z-]+)\.md$")
# A record as a triage's outcome names it, its file's name without `.md`.
_RECORD_NAME = re.compile(r"^(?P<number>\d+)-(?P<kind>[a-z-]+)$")
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
# The step a returned outcome's `return_to` names, for an outcome that gives the
# phase it returns to rather than its target.
_RETURN_STEP = {"design": "design", "planning": "plan", "implementation": ROUND.step}
# The records a member of a round's join supplies, besides the round's sections.
_SUPPLIES = {ROUND_VIEW: "implementation-owner", VALIDATE: "validation",
             IMPLEMENTATION_REVIEW: "implementation"}
# The target a validation in a round's join is given: the round's triage.
_ROUND_TRIAGE = {"step": IMPLEMENTATION_TRIAGE.step, "kind": IMPLEMENTATION_TRIAGE.kind}
CONVERT = "python3 scripts/run_change_step.py convert {change}"
RECORD = "python3 scripts/run_change_step.py record {change} {step} --outcome '<its outcome>'"

# How the log routes the change (`Route.how`): a step's exit; the owner's direction;
# a round started, by the line recording it; a directed validation that ran, naming
# the target it was given; a validation naming another target than it was given;
# and a finished run naming no exit.
EXIT, DIRECTED, ROUND_STARTED, VALIDATED, ELSEWHERE, NO_EXIT = (
    "exit", "directed", "round started", "validated", "elsewhere", "no exit")


Result = dict[str, Any]
Entry = dict[str, Any]


@dataclass(frozen=True)
class Record:
    """A numbered record in `reviews/`: a review, validation, or the owner's notes."""

    number: int
    kind: str
    path: Path

    @property
    def name(self) -> str:
        """The record as a triage's outcome names it, `NN-<kind>`."""
        return self.path.name[:-3]

    @property
    def triage(self) -> Path:
        return self.path.with_name(self.path.name[:-3] + ".triage.md")

    @property
    def triaged(self) -> bool:
        return self.triage.is_file()

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


@dataclass(frozen=True)
class Route:
    """Where the log sends the change, and the line that sends it there: `how` is
    one of `EXIT`, `DIRECTED`, `ROUND_STARTED`, `VALIDATED`, `ELSEWHERE`, `NO_EXIT`.
    `target` is the exit or direction's target, `source` the node of the run that
    named an exit, and `given` the target a validation was given."""

    how: str
    line: Entry
    target: Mapping[str, Any] | None = None
    source: Node | None = None
    given: Mapping[str, Any] | None = None

    @property
    def node(self) -> Node | None:
        try:
            return node_of(self.target) if self.target is not None else None
        except TargetError:
            return None


@dataclass(frozen=True)
class Pass:
    """A round's records and the owner's reading of them, in its first pass or in a
    repeat pass that a triage choosing another review opened over a committed fix:
    `again` is that review, and `base` the commit the pass's reading starts from."""

    mine: list[Record]
    kinds: set[str]
    in_clone: bool
    again: Record | None
    base: str | None
    unread: bool
    # The workspace's view of this pass, None when there is none or it is stale;
    # `stale` names the owner when a stale view must close before this pass is read.
    view: View | None
    stale: Result | None

    @property
    def pass_base(self) -> dict[str, str]:
        return {"base": self.base} if self.base else {}


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


def _triaged_reviews(entry: Mapping[str, Any]) -> list[tuple[int, str]]:
    """The reviews a triage or conversion line names in `triaged`, each as its
    number and kind, `-external` copies by their kind, in order of number."""
    found = []
    for name in entry.get("triaged") or ():
        if isinstance(name, str) and (match := _RECORD_NAME.match(name)):
            kind = match["kind"].removesuffix("-external")
            if graph.review_phase(kind):
                found.append((int(match["number"]), kind))
    return sorted(found)


def _triage_phase(entry: Mapping[str, Any], before: Sequence[dict[str, Any]]) -> str | None:
    """The phase a triage run belongs to: that of the latest review its outcome
    names, or, for a run that named none, of the review or validation it followed,
    the nearest one logged before it; None with none logged."""
    if reviews := _triaged_reviews(entry):
        return graph.review_phase(reviews[-1][1])
    for earlier in reversed(before):
        if earlier.get("step") == "review":
            return graph.review_phase(earlier.get("kind", ""))
        if earlier.get("step") == "validate":
            return "implementation"
    return None


def _run_node(entry: Mapping[str, Any]) -> Node | None:
    """The node a step's run is a run of: a review by its kind, a triage by the kind
    of the latest review its outcome names; None for a run that names no kind."""
    step = entry.get("step")
    if step == "review":
        node = Node(step, entry.get("kind"))
    elif step == "triage":
        reviews = _triaged_reviews(entry)
        node = Node(step, reviews[-1][1]) if reviews else Node(step)
    else:
        node = next((d.node for d in graph.TABLE if d.runs == step and not d.node.kind),
                    Node(str(step)))
    return node if node in graph.NODES else None


def _exit_of(entry: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The exit a run's outcome names: its target `next` when it finished or
    returned; a return that gives only the phase it returns to names that phase's
    step. None for a run that took no exit."""
    if entry.get("outcome") not in ("finished", "returned"):
        return None
    target = entry.get("next")
    if isinstance(target, Mapping):
        return target
    if entry.get("outcome") == "returned" and entry.get("return_to") in _RETURN_STEP:
        return {"step": _RETURN_STEP[entry["return_to"]]}
    return None


def _same(one: Mapping[str, Any], other: Mapping[str, Any]) -> bool:
    """Whether two targets name the same node, with the same sections, and, for a
    validation, the same target."""
    try:
        node = node_of(one)
        if node != node_of(other) or one.get("sections") != other.get("sections"):
            return False
    except TargetError:
        return False
    return node != VALIDATE or _same(one["target"], other["target"])


def _label(target: Mapping[str, Any]) -> str:
    """A target as a reason writes it, `review:pre-closeout`; never parsed."""
    try:
        node = node_of(target)
    except TargetError:
        return json.dumps(target, ensure_ascii=False, default=str)
    if node == VALIDATE:
        return f"{node.label} for {_label(target['target'])}"
    if target.get("sections"):
        return f"{target['step']} {json.dumps(target['sections'])}"
    return node.label


def _members(join: Join) -> set[Node]:
    return {node for _, node in join.waits_for}


def _in_join(route: Route | None, join: Join) -> bool:
    """Whether the route leads into the round's join: a round started, the exit of
    one of the join's members into the round's triage, or the owner's direction to
    the round view, which reads the join."""
    if route is None:
        return False
    return route.how == ROUND_STARTED or (
        route.how == EXIT and route.source in _members(join)
        and route.node == IMPLEMENTATION_TRIAGE) or (
        route.how == DIRECTED and route.node == ROUND_VIEW)


def _given(route: Route | None, joined: bool) -> Mapping[str, Any] | None:
    """The target the computation gave a validation run under `route`: the round's
    triage in its join, the target an owner's direction to validation names, and
    otherwise the exit whose guard it remedies."""
    if route is None:
        return None
    if joined:
        return _ROUND_TRIAGE
    if route.how == DIRECTED:
        return route.target.get("target") if route.node == VALIDATE else None
    if route.how in (EXIT, VALIDATED):
        return route.target
    return None


def route_of(log: Sequence[Entry], join: Join = ROUND_JOIN) -> Route | None:
    """Where the log sends the change: the exit the last step's outcome named, or
    the owner's latest direction while no run of the node it directs is logged after
    it; None while neither is logged.

    A round's line records it starting. A run that took no exit — a question, a
    block, a stop — leaves the route where it was, so its step is named again once
    the owner answers or resolves it. A run of a member of the round's join that
    names no exit leaves the round where it was too, since the round's records say
    how far it got; any other finished run naming none is the owner's. A validation
    naming the target it was given leaves the route where it was, so the guards it
    remedied are checked again; one directed by the owner leads to its target once
    it passed. The conversion line names no exit, and routes nothing.
    """
    route: Route | None = None
    for entry in log:
        step = entry.get("step")
        if step == ORCHESTRATOR:
            if entry.get("outcome") == "round":
                route = Route(ROUND_STARTED, entry, {"step": ROUND.step}, ROUND)
            elif entry.get("by") == "owner" and isinstance(entry.get("next"), Mapping):
                route = Route(DIRECTED, entry, entry["next"])
            continue
        if step not in STEPS:
            continue
        if route is not None and route.how == DIRECTED and route.node is not None \
                and graph.NODES[route.node].runs and not ran(route.node, entry):
            # A direction stands until a run of its node; a node no run is logged
            # for, as the round's reading, gives way to the next run of any step.
            continue
        joined = _in_join(route, join)
        exit_ = _exit_of(entry)
        if exit_ is None:
            if entry.get("outcome") == "finished" and not (
                    joined and step in {graph.NODES[m].runs for m in _members(join)}):
                route = Route(NO_EXIT, entry)
            continue
        source = _run_node(entry)
        if source is None:
            route = Route(NO_EXIT, entry)
        elif source == VALIDATE:
            given = _given(route, joined)
            if given is None or not _same(exit_, given):
                route = Route(ELSEWHERE, entry, exit_, source, given)
            elif route is not None and route.how == DIRECTED and route.node == VALIDATE:
                route = Route(VALIDATED, entry, given)
        else:
            route = Route(EXIT, entry, exit_, source)
    return route


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
        target = _exit_of(entry)
        return _owner(f"the {step} step proposes returning to "
                      f"{_label(target) if target else entry.get('return_to')}: "
                      f"{entry.get('message', '')}", target=target)
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
                 merging: Callable[[Path], bool] = _merging,
                 join: Join = ROUND_JOIN) -> None:
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
        self._join = join

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
        if unconverted := self.unconverted():
            return unconverted
        if state.workspace is not None:
            if held := self.bootstrap_held():
                return held
        result = self.route()
        if result.get("step") not in ("owner", "unclassified", "done"):
            if waiting := self.bootstrapping(result):
                return waiting
            if "disagreement" not in result and (disagreement := self.disagreement()):
                result["disagreement"] = disagreement
        return result

    def unclassified(self, reason: str) -> Result:
        return {"step": "unclassified", "reason": reason, "read": self.state.summary()}

    def unconverted(self) -> Result | None:
        """The owner, with the command that converts the change's records, while
        they are not in the log's format: a line of the log without its marker, or
        numbered records under `reviews/` and no log. Such a log is routed on not at
        all, since an older line's shapes — a decision's string `next` and `kind`,
        a return with no target, triage tokens in files — would be read as the new
        format's."""
        state = self.state
        if any(entry.get("format") != FORMAT for entry in state.log):
            unmarked = next(entry for entry in state.log if entry.get("format") != FORMAT)
            why = f"its workflow log holds lines without the log's format, from seq " \
                  f"{unmarked['seq']}"
        elif not state.log and state.records:
            why = "it has numbered records under reviews/ and no workflow log"
        else:
            return None
        command = CONVERT.format(change=state.change)
        return _owner(f"{state.change}'s records are not in the workflow log's format: {why}; "
                      f"the owner converts them, between steps, with `{command}`",
                      convert=command)

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
        route = route_of(state.log, self._join)
        # A step the owner directed into another phase sets its status as it
        # starts, so a run of it that stopped before doing so waits in its own phase.
        phases = {phase, *(graph.NODES[route.node].phases if route and route.node else ())}
        if waiting := self.pending(phases):
            return waiting
        if phase == "design" and status != "ready for design" and (
                blocked := self.blocked_on_prerequisite()):
            return blocked
        if route is None:
            return self.unrouted(status, phase)
        return {EXIT: self.chosen, DIRECTED: self.directed, ROUND_STARTED: self.round_join,
                VALIDATED: self.validated_direction, ELSEWHERE: self.elsewhere,
                NO_EXIT: self.no_exit}[route.how](route)

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

    # The route, checked against the table.

    def unrouted(self, status: str, phase: str) -> Result:
        """Before the log names any exit or direction: a change in design is at its
        first step; any later status, set with no step's exit or the owner's
        direction logged, is the owner's to direct."""
        if phase == "design":
            return DESIGN.result(status)
        return _owner(f"the status is {status!r}, and the workflow log names no step's exit "
                      "and no direction of the owner's to say where the change goes: the "
                      "owner directs it")

    def chosen(self, route: Route) -> Result:
        """A step's exit: the owner for an exit its node does not declare; the first
        unmet guard's remedy, carrying the exit as `target`; the owner for a target
        whose unwaivable entry guard is not met; otherwise the target's step. An exit
        into the round's triage waits on the round's join."""
        source, target, line = route.source, route.target, route.line
        assert source is not None and target is not None
        run = f"the {source.label} run at seq {line['seq']}"
        try:
            node = node_of(target)
        except TargetError as exc:
            return _owner(f"{run} names no node of the workflow graph as its exit: {exc}",
                          choice=target)
        declared = graph.exits(source, target=node)
        if len(declared) > 1:
            out_of_order = target.get("step") == "implement"
            declared = [e for e in declared
                        if (e.when == graph.OUT_OF_ORDER) == out_of_order] or declared
        if not declared:
            exits = [e.target.label for e in graph.NODES[source].exits]
            return _owner(f"{run} names {_label(target)} as its exit, which {source.label} "
                          f"does not declare; its exits are {', '.join(exits) or 'none'}",
                          choice=target, exits=exits)
        exit_ = declared[0]
        if exit_.join is not None:
            return self.round_join(route)
        context = self.context(route)
        if isinstance(context, str):
            return _owner(f"{run} chose {_label(target)}, but {context}", choice=target)
        if guarded := self.guarded(exit_, target, context):
            result = guarded
        else:
            result = self.entered(node, target, f"{run} chose {_label(target)}", line,
                                  by=source.step)
            if result.get("step") == node.step and (missing := self.passed_by_status(node)):
                result["disagreement"] = missing
        if source == IMPLEMENTATION_TRIAGE and node == IMPLEMENTATION_REVIEW:
            return self.read_beside(result, context["pass"])
        return result

    def guarded(self, exit_: graph.Exit, target: Mapping[str, Any],
                context: Mapping[str, Any]) -> Result | None:
        """The first unmet checked guard on `exit_`, in the table's order, naming its
        remedy or the owner and carrying `target`; None when each holds. A held
        guard is skipped: `dependencies` holds the change on it before it is read,
        and `bootstrap_held` and `bootstrapping` around whatever is named."""
        for guard in exit_.guards:
            if guard.check is not None and (result := guard.check(self, context)):
                return {**result, "target": dict(target)}
        return None

    def entered(self, node: Node, target: Mapping[str, Any], reason: str, line: Entry, *,
                by: str) -> Result:
        """`target`, reached by a step's exit, once its unwaivable entry guards hold;
        the owner, naming the guard, while one does not."""
        if refusal := entry_refusal(target, self.standing(), directed=False):
            return _owner(f"{reason}, and {refusal}", choice=dict(target))
        return self.enter(node, target, reason, line, by=by)

    def enter(self, node: Node, target: Mapping[str, Any], reason: str, line: Entry, *,
              by: str) -> Result:
        """The result naming `target`'s step, for the route `line` chose.

        A step named with no run of it logged since is in progress or next, and the
        reason says so: only the owner knows whether an interactive session of it is
        open, or closed before it recorded its outcome.
        """
        state = self.state
        if node == DONE:
            return {"step": DONE.step, "reason": "archived"}
        reason += self.in_progress(node, line)
        if node == VALIDATE:
            result: Result = {"step": VALIDATE.step, "target": dict(target["target"]),
                              "reason": reason}
        elif node == ROUND:
            if problem := self.sections_problem():
                return problem
            if target.get("step") == "implement":
                result = {"step": ROUND.step, "sections": target["sections"], "by": by,
                          "reason": f"{reason}: record the round as it starts, then "
                                    "implement it"}
            else:
                result = self.next_round()
        elif node == CLOSEOUT_REVIEW and self._uncommitted(self.root, state.directory):
            result = CLOSEOUT.result("the archive is not committed: closeout resumes after "
                                     "its archive step")
        else:
            result = node.result(reason)
        return result

    def in_progress(self, node: Node, line: Entry) -> str:
        """What the reason adds for a step named with no run of it logged after
        `line`: a session of it may be open, or may have ended without recording."""
        runs = graph.NODES[node].runs
        if runs is None or node == ROUND or any(
                entry["seq"] > line["seq"] and ran(node, entry) for entry in self.state.log):
            return ""
        return ("; no run of it is logged since: if no session of it is open, an interactive "
                "one ended without recording — resume it, or record its outcome with "
                f"`{RECORD.format(change=self.state.change, step=runs)}`")

    def passed_by_status(self, node: Node) -> str | None:
        """Why the status is past `node`, a step's exit named, when it is: the step
        set the status as it finished and its session closed before it recorded the
        outcome, which alone carries its exit. An owner's direction back to an
        earlier step is not this: the step it directs sets its status as it
        starts."""
        status = self.state.row.status if self.state.row else ""
        phase = _phase(status)
        phases = graph.NODES[node].phases
        if phase is None or not phases or PHASES.index(phase) <= max(map(PHASES.index, phases)):
            return None
        step = graph.NODES[node].runs or node.step
        return (f"the status is {status!r}, past {node.label}, but no {step} outcome is "
                f"recorded: if its session ended without recording, record it with "
                f"`{RECORD.format(change=self.state.change, step=step)}`")

    def directed(self, route: Route) -> Result:
        """The owner's direction, until a run of its node is logged: no exit guard is
        checked, and the node's unwaivable entry guards, which the log's writer
        checked as it wrote the direction, are checked again on the change as it now
        stands."""
        line, target = route.line, route.target
        assert target is not None
        why = f"the owner directed {_label(target)} at seq {line['seq']}: " \
              f"{line.get('decision', '')}"
        try:
            node = node_of(target)
            refusal = entry_refusal(target, self.standing(), directed=True)
        except TargetError as exc:
            return _owner(f"{why}, which names no node: {exc}", choice=dict(target))
        if refusal:
            return _owner(f"{why}, and {refusal}", choice=dict(target))
        if node == ROUND_VIEW:
            # No run of the round view is logged: the round's own records say
            # whether its reading is still due.
            return self.round_join()
        return self.enter(node, target, why, line, by="owner")

    def validated_direction(self, route: Route) -> Result:
        """A validation the owner directed, run and naming its target: the target
        once the validation passed, its entry guards checked; the owner when it
        failed or was inconclusive."""
        target, line = route.target, route.line
        assert target is not None
        why = f"the owner directed a validation before {_label(target)}, which ran at seq " \
              f"{line['seq']}"
        if result := self.validated(why):
            return {**result, "target": dict(target)}
        return self.entered(node_of(target), target, why, line, by="owner")

    def elsewhere(self, route: Route) -> Result:
        """A validation that named another exit than the target it was given."""
        given = _label(route.given) if route.given else "no target the log records"
        return _owner(f"the validation at seq {route.line['seq']} names "
                      f"{_label(route.target or {})} as its exit, but it was given {given}: "
                      "the owner decides where it leads", choice=route.target,
                      given=route.given)

    def no_exit(self, route: Route) -> Result:
        line = route.line
        return _owner(f"the {line.get('step')} run at seq {line['seq']} finished naming no "
                      "exit, so nothing says where the change goes: the owner directs it")

    def context(self, route: Route) -> dict[str, Any] | str:
        """What the guards on a step's exit read: the run, the review a triage's
        outcome names of its kind, the first closeout review, and, for the triage of
        an implementation round, its pass. A string says why one is missing."""
        source, line = route.source, route.line
        assert source is not None
        records = self.state.records
        review = None
        if source.step == "triage":
            named = [number for number, kind in _triaged_reviews(line) if kind == source.kind]
            review = next((r for r in reversed(records) if named and r.number == named[-1]
                           and r.review_kind == source.kind), None)
            if review is None:
                return "the review its outcome names is not in reviews/"
        closeouts = [r for r in records if r.review_kind == "closeout"]
        context: dict[str, Any] = {"run": line, "review": review,
                                   "first": closeouts[0] if closeouts else review}
        if source == IMPLEMENTATION_TRIAGE:
            again = review if route.node == IMPLEMENTATION_REVIEW else None
            current = self.current_round() or {}
            work = self.round_pass(current, again)
            if work.stale:
                return "a view of an earlier round, or of this round's earlier pass, is open " \
                       "in the workspace: run `make round-done` there first"
            context.update(unread=work.unread, in_clone=work.in_clone, base=work.pass_base,
                           **{"pass": work})
        return context

    def standing(self) -> Standing:
        directory = self.state.directory
        assert directory is not None
        return standing(directory / "reviews" / LOG, self.state.log)

    # The round.

    def sections_problem(self) -> Result | None:
        """Why the task list cannot be routed on: it has no sections, or a task sits
        under another section's heading. The skills check the task list before
        acting on it; this is the backstop for routing on its sections, since a
        list missing a heading would have whole sections repeated or skipped."""
        state = self.state
        if not state.sections:
            return self.unclassified("the task list has no sections")
        if problems := task_problems(state.tasks):
            return self.unclassified("the task list is malformed: " + "; ".join(problems))
        return None

    def current_round(self) -> Entry | None:
        return next((e for e in reversed(self.state.log) if e.get("outcome") == "round"), None)

    def next_round(self) -> Result:
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
        open_ids = [s.id for s in self.state.sections if not s.closeout and not s.complete]
        if not open_ids:
            return _owner("the next round is named, but every section before closeout is "
                          "checked: the owner directs what follows")
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

    def triage_line(self, record: Record) -> Entry | None:
        """The latest finished or returned triage line, or the conversion line, that
        names `record` among what it triaged: the outcome of its triage."""
        return next((e for e in reversed(self.state.log)
                     if record.name in (e.get("triaged") or ())
                     and ((e.get("step") == "triage"
                           and e.get("outcome") in ("finished", "returned"))
                          or e.get("step") == "convert")), None)

    def repeat_review(self, mine: Sequence[Record]) -> Record | None:
        """The latest of the round's implementation reviews whose triage chose the
        implementation review again: the review a repeat pass follows."""
        for record in reversed(mine):
            if record.review_kind == "implementation" and (line := self.triage_line(record)):
                exit_ = _exit_of(line)
                if exit_ is not None and _same(exit_, {"step": "review",
                                                       "kind": "implementation"}):
                    return record
        return None

    def round_pass(self, current: Mapping[str, Any], again: Record | None) -> Pass:
        """The round's records and the owner's reading of them.

        A triage that chose another review over a committed fix opens a repeat
        pass, read from the commit that triage's review read: the fix is work the
        owner has not seen, and the repeat round exists because it changed
        something central. The pass's reading is an owner record saved after that
        triage finished — in a clone the first pass's record may be numbered after
        the review, since it is read beside it. A change in its own clone is read in
        the owner's workspace while its validation and review run in the clone, so
        a first pass is unread there until its owner record exists.
        """
        state = self.state
        mine = [r for r in state.records if r.number > current.get("after", 0)]
        kinds = {r.review_kind or r.kind for r in mine}
        in_clone = state.workspace is not None
        base = again.reviewed_commit if again and self.fixed_since(again) else None
        if again is None:
            unread = in_clone and "implementation-owner" not in kinds
        else:
            # Records are never rewritten, so a record's time is when it was saved,
            # and a triage file's is when its triage last wrote it.
            finished = again.triage.stat().st_mtime_ns if again.triaged else 0
            unread = base is not None and not any(
                r.kind == "implementation-owner" and r.number > again.number
                and r.path.stat().st_mtime_ns > finished for r in mine)
        view = state.workspace_view if in_clone else None
        stale = None
        # A view the owner left open over an earlier round, or an earlier pass,
        # following its fixes, is not this pass's reading; this one needs it closed
        # first. A base may be named by an abbreviated commit, a pasted review's.
        started = base or current.get("commit")
        if view is not None and started and not (view.base.startswith(started)
                                                  or started.startswith(view.base)):
            if unread:
                stale = _owner("a view of an earlier round, or of this round's earlier pass, "
                               "is open in the workspace: run `make round-done` there, so this "
                               "pass can be read over its own base", round_view=state.change,
                               workspace=str(state.workspace))
            view = None
        return Pass(mine, kinds, in_clone, again, base, unread, view, stale)

    def read_beside(self, result: Result, work: Pass) -> Result:
        """A repeat pass's validation or review, in a clone, run beside the owner's
        reading of the fix in the workspace."""
        if work.unread and work.view is None and result["step"] in ("validate", "review"):
            result.update(reading=True, workspace=str(self.state.workspace), **work.pass_base)
            result["reason"] += "; the owner reads the fix in the workspace beside it"
        return result

    def round_join(self, route: Route | None = None) -> Result:
        """The round's join, read from the records its members supply: its sessions'
        sections checked, each in turn; then the owner's reading, its validation,
        and its implementation review; then its triage, once every record but a
        validation with nothing to triage has its triage file.

        A change worked in this checkout is read first, since its view moves the
        branch its own steps run on. A change in its own clone is read in the
        owner's workspace while its validation and review run in the clone, so the
        reading holds triage alone: triage is named once the owner record, the
        review, and the validation all exist and the workspace's view is closed. A
        member the join does not wait for supplies nothing it waits on.
        """
        state = self.state
        if problem := self.sections_problem():
            return problem
        current = self.current_round()
        if current is None:
            return self.unclassified("the route leads into a round's join, and no round is "
                                     "recorded")
        members = _members(self._join)
        by_id = {s.id: s for s in state.sections}
        round_sections = [str(s) for session in current["sections"] for s in session]
        if unknown := [s for s in round_sections if s not in by_id]:
            return self.unclassified(f"the agreed round names sections the task list lacks: "
                                     f"{', '.join(unknown)}")
        if ROUND in members:
            for session in current["sections"]:
                # The closeout section is closeout's, never a round's to implement.
                if any(not by_id[str(s)].complete and not by_id[str(s)].closeout
                       for s in session):
                    return {"step": "implement", "sections": session,
                            "reason": "the agreed round's sections are not all checked"}
        reading = ROUND_VIEW in members
        work = self.round_pass(current, self.repeat_review(
            [r for r in state.records if r.number > current.get("after", 0)]))
        supplied = {_SUPPLIES[member] for member in members if member in _SUPPLIES}
        if reading and not work.in_clone and not work.kinds & supplied:
            return ROUND_VIEW.result("the round's sections are committed; the owner reads "
                                     "the round")
        if work.stale:
            return work.stale
        viewing = work.view is not None
        unread = reading and work.unread
        missing = [node for node in (VALIDATE, IMPLEMENTATION_REVIEW)
                   if node in members and _SUPPLIES[node] not in work.kinds]
        if missing:
            result: Result = (
                {"step": "validate-and-review", "kind": IMPLEMENTATION_REVIEW.kind,
                 "target": dict(_ROUND_TRIAGE),
                 "reason": "the round has no validation or implementation review"}
                if len(missing) == 2
                else {"step": VALIDATE.step, "target": dict(_ROUND_TRIAGE),
                      "reason": "the round has no validation"}
                if missing == [VALIDATE]
                else IMPLEMENTATION_REVIEW.result("the round has no implementation review"))
            if unread and not viewing:
                result.update(reading=True, workspace=str(state.workspace))
                result["reason"] += ("; the owner reads the round in the workspace beside "
                                     "them")
            return result
        # A validation that passed, or was inconclusive, has no finding, so it alone
        # opens no triage, though one opened for the round's other records triages
        # it beside them.
        untriaged = [r for r in work.mine if not r.triaged]
        if any(not r.needs_no_triage for r in untriaged):
            if reading and viewing:
                return _owner(("the owner is reading the round in the workspace: save their "
                               "answer as this clone's next NN-implementation-owner.md, then "
                               "run `make round-done` in the workspace, before triage")
                              if unread else
                              ("the owner's answer on the round is saved, and its view is "
                               "still open in the workspace: run `make round-done` there "
                               "before triage"),
                              round_view=state.change, workspace=str(state.workspace))
            if unread:
                return {"step": ROUND_VIEW.step, **work.pass_base,
                        **({"workspace": str(state.workspace)} if work.in_clone else {}),
                        "reason": "the round's validation and review are in, and the owner "
                                  "reads the round"
                                  + (" in the workspace" if work.in_clone else "")
                                  + " before triage"}
            return self.triage(", ".join(r.path.name for r in untriaged) + " have no triage")
        reviews = [r for r in work.mine if r.review_kind == "implementation"]
        if reviews and self.triage_line(reviews[-1]) is None:
            return self.triage(f"{reviews[-1].triage.name} names no recorded outcome: its "
                               "triage is in progress")
        return self.unclassified("the round's records are triaged, and no triage outcome "
                                 "after them routes the change")

    def triage(self, reason: str) -> Result:
        """The round's triage, once an implementation review awaits it: its entry
        guard holds the rest of the round's records, which only a review's triage
        triages beside it."""
        target = dict(_ROUND_TRIAGE)
        if refusal := entry_refusal(target, self.standing(), directed=False):
            return _owner(f"{reason}, and {refusal}", choice=target)
        return IMPLEMENTATION_TRIAGE.result(reason)

    # Shared readings.

    def last(self, steps: Sequence[str]) -> dict[str, Any] | None:
        """The latest log line of one of `steps`."""
        return next((e for e in reversed(self.state.log) if e.get("step") in steps), None)

    def pending(self, phases: set[str]) -> Result | None:
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
        `phases`, the phase it was raised in — the status's, or that of the step
        the log routes to: a crashed design triage must not hold implementation.
        Unread denials wait whatever the phase, since the step
        that recorded them may be the one that moved the change on — a design
        triage that advances sets the status to the next phase in the same run —
        and the reading is owed before any step runs; a stopped run with
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
        steps = {step for phase in phases for step in graph.phase_steps(phase)}
        for index, entry in enumerate(log):
            name = entry.get("step")
            if name == ORCHESTRATOR or name not in STEPS:
                continue
            latest_any[name] = entry
            if name not in steps:
                continue
            if name == "review" and graph.review_phase(entry.get("kind", "")) not in phases:
                continue
            if name == "triage" and _triage_phase(entry, log[:index]) not in (*phases, None):
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

    def return_confirmed(self, run: Mapping[str, Any]) -> bool:
        """Whether the owner confirmed the return `run` proposed: a decision of the
        owner's that resolves the run and directs a step. Until the owner decides,
        the returned run waits in `pending`; a decision resolving it without
        directing a step declines the return, and the owner decides what follows."""
        return any(e.get("outcome") == ORCHESTRATOR and e.get("by") == "owner"
                   and e.get("resolves") == run.get("seq")
                   and isinstance(e.get("next"), Mapping) for e in self.state.log)

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
            # Nothing the owner records clears it: a validation that passes does, or
            # the owner's direction past it, which checks no exit guard.
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
        """How the log's last step is past the status, if it is: the status was set
        back by hand, which the route the log names does not follow. An owner's
        direction after that step accounts for it, since the step it directs sets
        its own status as it starts."""
        log = self.state.log
        lines = [e for e in _step_lines(log) if _STEP_PHASE.get(e.get("step"))]
        status = self.state.row.status if self.state.row else ""
        phase = _phase(status)
        if not lines or phase is None or any(
                e.get("outcome") == ORCHESTRATOR and e.get("by") == "owner"
                and isinstance(e.get("next"), Mapping) and e["seq"] > lines[-1]["seq"]
                for e in log):
            return None
        logged = _STEP_PHASE[lines[-1]["step"]]
        if PHASES.index(logged) > PHASES.index(phase):
            return (f"the status is {status!r}, but the log's last step was "
                    f"{lines[-1]['step']} (seq {lines[-1]['seq']}): the result follows the "
                    "log's route, and a status set back by hand is the owner's to direct")
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
