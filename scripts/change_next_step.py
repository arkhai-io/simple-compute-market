#!/usr/bin/env python3
"""Compute the next step of an OpenSpec change from its files and workflow log.

The orchestrating session runs whatever this names and never routes on its own
reading; the owner can run the same command by hand. It reads the change's row in
`openspec/changes/README.md` (status, `Depends on`, `Notes`), its numbered review
records and their triage, the sections and checks of its task list, its workflow
log, and whether a round view is open, and prints one JSON object:

- `{"step": <step>, "reason": …}` for a step to run: `design`, `plan`,
  `implement` (with its `sections`), `round-view`, `validate`, `review` (with its
  `kind`), `validate-and-review`, `triage`, `closeout`, or `archive-cleanup`;
- `{"step": "owner", "reason": …}` when only the owner can move the change on: a
  question to answer, a gate or a returned step to decide, a round to agree, a
  prerequisite to land;
- `{"step": "done", …}` for an archived change;
- `{"step": "unclassified", "reason": …, "read": …}` when no rule applies, with
  what it read, for the orchestrating session to work out.

The rules follow each step's skill: its entry check, and the handoff that names
what comes after it. Where the log and the files disagree — a status set by hand —
the files decide the step, and the result carries a `disagreement` saying so.

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
from typing import Any, Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_change_index import _DEPENDENCY, INDEX, Row, index_rows  # noqa: E402
from find_change import ChangeNotFound, change_directory, is_archived  # noqa: E402
from round_view import RoundError, View, open_view  # noqa: E402
from run_change_step import (ORCHESTRATOR, StepError, log_path, read_log,  # noqa: E402
                             validation_problem)

ROOT = Path(__file__).resolve().parents[1]
PHASES = ("design", "planning", "implementation", "closeout")
_RECORD = re.compile(r"^(?P<number>\d+)-(?P<kind>[a-z-]+)\.md$")
# The change's task list, whose sections and checks say how far implementation got.
TASKS_FILE = "tasks.md"
_SECTION = re.compile(r"^## (?P<id>[0-9]+[A-Za-z]?)\. (?P<title>.+?)\s*$")
_TASK = re.compile(r"^\s*- \[(?P<done>[ xX])\] ")
# Where a log line's step sits among the phases, for comparing with the status.
_STEP_PHASE = {"design": "design", "plan": "planning", "implement": "implementation",
               "validate": "implementation", "triage": None, "review": None,
               "closeout": "closeout", "archive-cleanup": "closeout"}
_REVIEW_PHASE = {"design": "design", "implementation": "implementation",
                 "pre-closeout": "implementation", "closeout": "closeout"}
# The steps that run while a change is in each phase.
_PHASE_STEPS = {"design": ("design", "review", "triage"), "planning": ("plan",),
                "implementation": ("implement", "validate", "review", "triage"),
                "closeout": ("closeout", "review", "triage", "archive-cleanup")}

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

    def gate_passed(self) -> bool | None:
        """Whether its triage passed the gate: None while it is untriaged.

        Triage writes the owner's answer under `## Gate`, beginning "Passed" when
        the owner passed it.
        """
        if not self.triaged:
            return None
        text = self.triage.read_text("utf-8")
        gate = text.split("\n## Gate", 1)[1] if "\n## Gate" in text else ""
        return gate.strip().lower().startswith("passed")

    @property
    def review_kind(self) -> str | None:
        """The kind of review this record is, `-external` copies included."""
        kind = self.kind.removesuffix("-external")
        return kind if kind in _REVIEW_PHASE else None


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
    sections: list[Section] = field(default_factory=list)
    log: list[dict[str, Any]] = field(default_factory=list)
    view: View | None = None
    head: str | None = None

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


def _git_head(root: Path) -> str | None:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                          text=True)
    return head.stdout.strip() if head.returncode == 0 else None


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


def _phase(status: str) -> str | None:
    return next((phase for phase in PHASES if status.endswith(phase)), None)


def _step_lines(log: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry for entry in log if entry.get("step") != ORCHESTRATOR]


def _owner(reason: str, **extra: Any) -> Result:
    return {"step": "owner", "reason": reason, **extra}


def _waiting(entry: dict[str, Any]) -> Result | None:
    """The owner result for a step whose last run waits on the owner, if it does."""
    step, outcome = entry.get("step"), entry.get("outcome")
    if outcome == "question":
        return _owner(f"the {step} step asks: {entry.get('message', '')}",
                      awaiting=entry.get("awaiting"), resume=step)
    if outcome == "returned":
        return _owner(f"the {step} step proposes returning to {entry.get('return_to')}: "
                      f"{entry.get('message', '')}", return_to=entry.get("return_to"))
    if outcome == "blocked":
        return _owner(f"the {step} step is blocked on {entry.get('blocked_on')}: "
                      f"{entry.get('message', '')}", blocked_on=entry.get("blocked_on"))
    if outcome == "stopped":
        return _owner(f"the {step} step stopped: {entry.get('reason', '')}",
                      denials=entry.get("denials", []))
    return None


class Computation:
    def __init__(self, root: Path, change: str, *,
                 head: Callable[[Path], str | None] = _git_head,
                 view: Callable[[Path], View | None] = _open_view,
                 uncommitted: Callable[[Path, Path], bool] | None = None) -> None:
        self.root = root
        self.state = State(change)
        self._head = head
        self._view = view
        self._uncommitted = uncommitted or _uncommitted

    def run(self) -> Result:
        state = self.state
        state.view = self._view(self.root)
        if state.view is not None:
            # While a view is open the branch sits at the round's base, so nothing
            # else about the change can be read until it closes.
            return _owner(
                f"a round view of {state.view.change} is open: save the owner's notes on "
                "the round as the next NN-implementation-owner.md, then run "
                "`make round-done`", round_view=state.view.change)
        try:
            state.directory = change_directory(self.root, state.change)
        except ChangeNotFound as exc:
            return self.unclassified(str(exc))
        state.row = next((row for row in index_rows(self.root) if row.name == state.change),
                         None)
        state.notes = state.row.notes if state.row else ""
        state.records = read_records(state.directory / "reviews")
        state.sections = read_sections(state.directory / TASKS_FILE)
        state.log = read_log(log_path(self.root, state.change))
        state.head = self._head(self.root)
        if state.row is None:
            if is_archived(self.root, state.directory):
                return {"step": "done", "reason": "archived, and its index row pruned"}
            return self.unclassified(f"{INDEX} has no row for {state.change}")
        result = self.route()
        if result.get("step") not in ("owner", "unclassified", "done"):
            if disagreement := self.disagreement():
                result["disagreement"] = disagreement
        return result

    def unclassified(self, reason: str) -> Result:
        return {"step": "unclassified", "reason": reason, "read": self.state.summary()}

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
        return getattr(self, f"_{phase}")(status)

    def dependencies(self, phase: str) -> Result | None:
        """A dependency that gates `phase` or an earlier one, and is not yet released."""
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

    # The phases. Each is called with the change's status.

    def _design(self, status: str) -> Result:
        if status == "ready for design":
            return {"step": "design", "reason": "ready for design"}
        if blocked := self.blocked_on_prerequisite():
            return blocked
        if untriaged := self.untriaged(kinds=("design",)):
            return {"step": "triage", "reason": f"{untriaged} has no triage"}
        last = self.last(("design", "review", "triage"))
        if last and last.get("step") == "design" and last.get("outcome") == "finished":
            return {"step": "review", "kind": "design",
                    "reason": "the design discussion finished; its design review is next"}
        return {"step": "design", "reason": "in design"}

    def _planning(self, status: str) -> Result:
        if status == "ready for planning":
            return {"step": "plan", "reason": "ready for planning"}
        last = self.last(("plan",))
        if last and last.get("outcome") == "finished":
            return _owner("the plan is written: the owner accepts it in the planning "
                          "session, which sets the change ready for implementation",
                          resume="plan")
        return {"step": "plan", "reason": "in planning"}

    def _implementation(self, status: str) -> Result:
        state = self.state
        rounds = [e for e in state.log if e.get("outcome") == "round"]
        work = [s for s in state.sections if not s.closeout]
        if not state.sections:
            return self.unclassified("the task list has no sections")
        current = rounds[-1] if rounds else None
        round_sections = ([str(s) for session in current["sections"] for s in session]
                          if current else [])
        by_id = {s.id: s for s in state.sections}
        if current and (unknown := [s for s in round_sections if s not in by_id]):
            return self.unclassified(f"the agreed round names sections the task list lacks: "
                                     f"{', '.join(unknown)}")
        if current and any(not by_id[s].complete for s in round_sections):
            for session in current["sections"]:
                if any(not by_id[str(s)].complete for s in session):
                    return {
                        "step": "implement", "sections": session,
                        "reason": "the agreed round's sections are not all checked"}
        if current is None:
            if all(s.complete for s in work):
                return self._pre_closeout()
            return _owner("agree the next implementation round: which sections, and how "
                          "many sessions", round=[s.id for s in work if not s.complete])
        return self._round(current, work)

    def _round(self, current: dict[str, Any], work: list[Section]) -> Result:
        """The agreed round's sections are checked: its view, validation, review,
        and triage, then the next round or the pre-closeout review."""
        mine = [r for r in self.state.records if r.number > current.get("after", 0)]
        kinds = {r.review_kind or r.kind for r in mine}
        if not kinds & {"implementation-owner", "implementation", "validation"}:
            return {"step": "round-view",
                    "reason": "the round's sections are committed; the owner reads the round"}
        missing = [kind for kind in ("validation", "implementation") if kind not in kinds]
        if missing == ["validation", "implementation"]:
            return {"step": "validate-and-review", "kind": "implementation",
                    "reason": "the round has no validation or implementation review"}
        if missing == ["validation"]:
            return {"step": "validate", "reason": "the round has no validation"}
        if missing == ["implementation"]:
            return {"step": "review", "kind": "implementation",
                    "reason": "the round has no implementation review"}
        if untriaged := [r.path.name for r in mine if not r.triaged]:
            return {"step": "triage", "reason": f"{', '.join(untriaged)} have no triage"}
        if problem := self.validation_problem():
            return {"step": "validate", "reason": f"the round's fixes need validating: "
                                                  f"{problem}"}
        if all(s.complete for s in work):
            return self._pre_closeout()
        return _owner("the round is triaged: agree the next implementation round",
                      round=[s.id for s in work if not s.complete])

    def _pre_closeout(self) -> Result:
        if untriaged := self.untriaged(kinds=("pre-closeout",)):
            return {"step": "triage", "reason": f"{untriaged} has no triage"}
        reviews = [r for r in self.state.records if r.review_kind == "pre-closeout"]
        if reviews and reviews[-1].gate_passed() is False:
            return _owner(f"{reviews[-1].path.name}'s gate has not passed: decide what "
                          "happens before the next pre-closeout review")
        if problem := self.validation_problem():
            return {"step": "validate", "reason": f"a pre-closeout review needs a passing "
                                                  f"validation of HEAD: {problem}"}
        return {"step": "review", "kind": "pre-closeout",
                "reason": "every section before closeout is checked and validated"}

    def _closeout(self, status: str) -> Result:
        state = self.state
        if status == "ready for closeout" or not is_archived(self.root, state.directory):
            return {"step": "closeout", "reason": status}
        if self._uncommitted(self.root, state.directory):
            return {"step": "closeout", "reason": "the archive is not committed: closeout "
                                                  "resumes after its archive step"}
        if untriaged := self.untriaged(kinds=("closeout",)):
            return {"step": "triage", "reason": f"{untriaged} has no triage"}
        reviews = [r for r in state.records if r.review_kind == "closeout"]
        if not reviews:
            return {"step": "review", "kind": "closeout",
                    "reason": "the change is archived; its closeout review is next"}
        if reviews[-1].gate_passed():
            return {
                "step": "archive-cleanup", "reason": "the closeout gate has passed"}
        return _owner(f"{reviews[-1].path.name}'s gate has not passed")

    # Shared readings.

    def last(self, steps: Sequence[str]) -> dict[str, Any] | None:
        """The latest log line of one of `steps`."""
        return next((e for e in reversed(self.state.log) if e.get("step") in steps), None)

    def pending(self, phase: str) -> Result | None:
        """A step of `phase` whose latest run waits on the owner, if one does.

        A question is answered by resuming its session, and a returned, blocked, or
        stopped run is decided by the owner or the orchestrating session; none is
        routed past by running the step afresh. An `orchestrator` line records such
        a decision, so only runs after the latest one are read. A design that ended
        blocked on a prerequisite is the prerequisite rules', not this one's.
        """
        log = self.state.log
        decided = max((e["seq"] for e in log if e.get("outcome") == ORCHESTRATOR),
                      default=0)
        latest: dict[str, dict[str, Any]] = {}
        for entry in log:
            name = entry.get("step")
            if (entry["seq"] > decided and name in _PHASE_STEPS[phase]
                    and (name != "review"
                         or _REVIEW_PHASE.get(entry.get("kind", "")) == phase)):
                latest[name] = entry
        waiting = [entry for entry in latest.values()
                   if not (entry.get("step") == "design" and entry.get("outcome") == "blocked")
                   and _waiting(entry)]
        return _waiting(max(waiting, key=lambda e: e["seq"])) if waiting else None

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


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 1:
        print("usage: change_next_step.py <change>", file=sys.stderr)
        return 2
    result = compute(root, args[0])
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 1 if result["step"] == "unclassified" else 0


if __name__ == "__main__":
    sys.exit(main())
