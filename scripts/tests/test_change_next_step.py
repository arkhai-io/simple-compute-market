"""The next step of a change is computed from its files and its workflow log."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import change_clone as clones
from change_workflow import graph
from change_workflow.common import StepError
from change_workflow.log import (append_entry, log_path, note_orchestrator, note_round,
                                 read_log, record_outcome, unused_direction)
from find_change import change_directory

SCRIPTS = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered before it runs: its dataclasses look their module up by name.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


nxt = _load("change_next_step")
rounds = sys.modules["round_view"]

CHANGE = "shape-bounds"
# The review kind the design records below are named for.
KIND = "design"
HEAD ="0123456789abcdef0123456789abcdef01234567"
TASKS = """## 1. First

- [x] 1.1 Done.

## 2. Second

- [ ] 2.1 Open.

## 3. Third

- [ ] 3.1 Open.

## 4. Closeout

- [ ] 4.1 Archive.
"""
SECOND_DONE = TASKS.replace("- [ ] 2.1", "- [x] 2.1")
ALL_WORK_DONE = SECOND_DONE.replace("- [ ] 3.1", "- [x] 3.1")
QUESTION = {"outcome": "question", "message": "Which option?", "awaiting": "a choice"}
PLANNED = [[[2]], [[3]]]


def _to(step: str, kind: str | None = None, **more) -> dict:
    """A target, as an exit or a direction names it."""
    return {"step": step, **({"kind": kind} if kind else {}), **more}


def _done(target: dict, **more) -> dict:
    """A finished outcome naming `target` as its exit."""
    return {"outcome": "finished", "message": "Done.", "next": target, **more}


def _returned(target: dict) -> dict:
    return {"outcome": "returned", "message": "Needs a decision.", "evidence": "the notes",
            "next": target}


ROUND_TRIAGE = _to("triage", "implementation")


def _repository(tmp_path: Path, status: str, *, depends_on: str = "—", tasks: str = TASKS,
                others: dict[str, str] | None = None, archived: bool = False) -> Path:
    changes = tmp_path / "openspec/changes"
    directory = (changes / "archive" / f"2026-10-20-{CHANGE}") if archived \
        else changes / CHANGE
    (directory / "reviews").mkdir(parents=True)
    (directory / nxt.TASKS_FILE).write_text(tasks, "utf-8")
    link = f"archive/2026-10-20-{CHANGE}/" if archived else f"{CHANGE}/"
    rows = [f"| [`{CHANGE}`]({link}) | {status} | {depends_on} | the notes | x |"]
    for name, other_status in (others or {}).items():
        other = (changes / "archive" / f"2026-10-01-{name}") if other_status == "archived" \
            else changes / name
        other.mkdir(parents=True)
        rows.append(f"| [`{name}`]({name}/) | {other_status} | — | — | x |")
    (changes / "README.md").write_text(
        "| Change | Status | Depends on | Notes | Acceptance boundary |\n"
        "|---|---|---|---|---|\n" + "\n".join(rows) + "\n", "utf-8")
    return tmp_path


def _reviews(root: Path) -> Path:
    return change_directory(root, CHANGE) / "reviews"


def _next_section(words: str) -> str:
    return f"# Triage\n\n### F1 — x\n\n## Next\n\n{words}\n"


def _record(root: Path, name: str, *, triage: str | None = None, text: str = "x",
            reviewed: str | None = None) -> None:
    """A numbered record, and, with `triage`, its triage file, whose `## Next` is the
    prose given: nothing routes on it."""
    if reviewed is not None:
        text = f"{text}\n<!-- reviewed-commit: {reviewed} -->\n"
    (_reviews(root) / name).write_text(text, "utf-8")
    if triage is not None:
        (_reviews(root) / name.replace(".md", ".triage.md")).write_text(
            _next_section(triage), "utf-8")


def _validation(commit: str = HEAD, result: str = "passed") -> str:
    return f"# Validation\n\n- **Commit:** {commit} on feat/x\n- **Result:** {result}\n"


def _log(root: Path, step_name: str, outcome: dict, **extra) -> dict:
    return record_outcome(log_path(root, CHANGE), step_name, outcome, session="s",
                          commit=HEAD, extra=extra or None)


def _review(root: Path, name: str, *, reviewed: str | None = None,
            outcome: dict | None = None) -> dict:
    """A review run: its record published and its line logged, naming its triage."""
    _record(root, name, reviewed=reviewed)
    kind = name.split("-", 1)[1].removesuffix(".md").removesuffix("-external")
    return record_outcome(log_path(root, CHANGE), "review",
                          outcome or _done(_to("triage", kind)), session="codex:x",
                          commit=HEAD, extra={"kind": kind, "record": name})


def _triage(root: Path, *names: str, to: dict | None = None, returned: dict | None = None,
            words: str = "The target, and the owner's words.") -> dict:
    """A triage run over `names`: each one's triage file written, and the outcome
    logged naming them in `triaged` and its exit."""
    for name in names:
        triage = _reviews(root) / name.replace(".md", ".triage.md")
        if not triage.exists():
            triage.write_text(_next_section(words), "utf-8")
    outcome = _returned(returned) if returned is not None else _done(to)
    return _log(root, "triage", {**outcome, "triaged": [name[:-3] for name in names]})


def _decide(root: Path, decision: str = "decided", **fields) -> dict:
    return note_orchestrator(log_path(root, CHANGE), decision, "a reason", **fields)


def _direct(root: Path, step: str, decision: str = "directed", **fields) -> dict:
    return _decide(root, decision, by="owner", next_step=step, **fields)


def _round(root: Path, sections, after: int | None = None) -> None:
    note_round(log_path(root, CHANGE), sections, "owner", after)


def _planned(root: Path, rounds_=PLANNED) -> dict:
    """A plan that finished naming its next round, mapping `rounds_`."""
    return _log(root, "plan", _done(_to("round"), rounds=rounds_))


def _unmarked(root: Path, line: dict) -> None:
    """A line as the older tooling appended it, without the log's format."""
    with log_path(root, CHANGE).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(line) + "\n")


# What HEAD changed since a reviewed commit: a fix in code, unless a test says otherwise.
FIX = ["scripts/change_next_step.py"]
RECORDS_ONLY = [f"openspec/changes/{CHANGE}/interventions.jsonl"]


# The change is worked in the checkout the computation runs in, with no clone,
# unless a test says otherwise.
HERE = {"branch": lambda _: f"feat/{CHANGE}", "workspace": lambda _: None,
        "clone": lambda *_: None, "merging": lambda _: False}


def _next(root: Path, *, uncommitted: bool = False, changed: list[str] | None = FIX,
          **seams) -> dict:
    return nxt.compute(root, CHANGE, head=lambda _: HEAD, view=lambda _: None,
                       uncommitted=lambda *_: uncommitted, changed_since=lambda *_: changed,
                       **{**HERE, **seams})


def _check(root: Path, tasks: str) -> None:
    (change_directory(root, CHANGE) / nxt.TASKS_FILE).write_text(tasks, "utf-8")


# Design and planning.

def test_ready_for_design_runs_design(tmp_path: Path) -> None:
    assert _next(_repository(tmp_path, "ready for design"))["step"] == "design"


def test_a_finished_design_goes_to_the_exit_it_named(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    run = _log(root, "design", _done(_to("review", "design")))

    result = _next(root)

    assert (result["step"], result["kind"]) == ("review", "design")
    assert f"the design run at seq {run['seq']} chose review:design" in result["reason"]


def test_a_published_design_review_is_triaged(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _log(root, "design", _done(_to("review", "design")))
    _review(root, f"01-{KIND}.md")

    assert (_next(root)["step"], _next(root)["kind"]) == ("triage", "design")


def test_a_design_question_waits_for_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    run = _log(root, "design", QUESTION)

    result = _next(root)

    assert (result["step"], result["resume"], result["awaiting"]) == ("owner", "design",
                                                                      "a choice")
    assert "Which option?" in result["reason"]
    # The run a resume must name.
    assert result["seq"] == run["seq"]


def test_a_task_under_another_sections_heading_is_not_routed_on(tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for implementation",
                       tasks=TASKS.replace("## 3. Third\n\n", ""))
    _planned(root)

    result = _next(root)

    assert result["step"] == "unclassified"
    assert "3.1 sits under `## 2. Second`" in result["reason"]


@pytest.mark.parametrize("target,expected", [
    (_to("plan"), ("plan", None)),
    (_to("review", "design"), ("review", "design")),
])
def test_a_design_triage_routes_on_the_exit_its_outcome_names(
        tmp_path: Path, target: dict, expected: tuple) -> None:
    root = _repository(tmp_path, "in design")
    _log(root, "design", _done(_to("review", "design")))
    _review(root, f"01-{KIND}.md")
    # The prose says otherwise; nothing routes on it.
    _triage(root, f"01-{KIND}.md", to=target, words="Another round, then advance.")

    result = _next(root)

    assert (result["step"], result.get("kind")) == expected


def test_planning_in_progress_continues(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in planning")
    _review(root, f"01-{KIND}.md")
    _triage(root, f"01-{KIND}.md", to=_to("plan"))

    assert _next(root)["step"] == "plan"


def test_a_steps_exit_its_node_does_not_declare_goes_to_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _log(root, "design", _done(_to("plan")))

    result = _next(root)

    # Single-exit nodes included: a step naming an exit it lacks is the owner's.
    assert (result["step"], result["choice"], result["exits"]) == (
        "owner", {"step": "plan"}, ["review:design"])
    assert "does not declare" in result["reason"]


# A triage in progress: its file exists, and no outcome names its review.

@pytest.mark.parametrize("status,name", [("in design", f"01-{KIND}.md"),
                                         ("in closeout", "05-closeout.md")])
def test_a_triage_whose_outcome_is_not_recorded_is_in_progress(
        tmp_path: Path, status: str, name: str) -> None:
    root = _repository(tmp_path, status, archived=status == "in closeout")
    _review(root, name)
    # A new triage file whose prose begins with an older token's words.
    _record(root, name, triage="Advance to planning — the owner: \"advance.\"")

    result = _next(root)

    assert (result["step"], result["kind"]) == ("triage", name[3:-3])
    assert "no run of it is logged since" in result["reason"]


def test_a_triage_file_ending_with_a_gate_is_in_progress(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _review(root, f"01-{KIND}.md")
    (_reviews(root) / "01-design.triage.md").write_text("# Triage\n\n## Gate\n\nPassed.\n",
                                                         "utf-8")

    assert (_next(root)["step"], _next(root)["kind"]) == ("triage", "design")


def test_an_interactive_session_that_ended_without_recording_is_in_progress(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _review(root, f"01-{KIND}.md")

    result = _next(root)

    assert (result["step"], result["kind"]) == ("triage", "design")
    assert "if no session of it is open, an interactive one ended without recording" in (
        result["reason"])
    assert f"run_change_step.py record {CHANGE} triage" in result["reason"]


def test_an_interactive_plan_that_set_its_status_and_recorded_nothing(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for implementation")
    _review(root, f"01-{KIND}.md")
    _triage(root, f"01-{KIND}.md", to=_to("plan"))

    result = _next(root)

    # Planning, and no round: the plan's outcome carries its exit and its rounds.
    assert result["step"] == "plan"
    assert "no plan outcome is recorded" in result["disagreement"]
    assert f"run_change_step.py record {CHANGE} plan" in result["disagreement"]


# Implementation rounds.

@pytest.mark.parametrize("status", ["ready for planning", "ready for implementation",
                                    "ready for closeout"])
def test_a_status_past_design_with_nothing_logged_goes_to_the_owner(
        tmp_path: Path, status: str) -> None:
    result = _next(_repository(tmp_path, status))

    # No step is inferred from the phase.
    assert result["step"] == "owner" and "names no step's exit" in result["reason"]


def test_the_agreed_rounds_next_session_is_implemented(tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for implementation")
    _round(root, [[1], [2, 3]])

    result = _next(root)

    assert (result["step"], result["sections"]) == ("implement", [2, 3])


def test_a_finished_session_with_sections_left_implements_the_next(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2], [3]])
    _check(root, SECOND_DONE)
    _log(root, "implement", _done(ROUND_TRIAGE), sections=[2])

    assert (_next(root)["step"], _next(root)["sections"]) == ("implement", [3])


def test_an_implementation_returning_to_design_waits_for_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    _log(root, "implement", _returned(_to("design")), sections=[2])

    result = _next(root)

    assert (result["step"], result["target"]) == ("owner", {"step": "design"})


def test_a_committed_round_is_read_by_the_owner_first(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    _check(root, SECOND_DONE)

    assert _next(root)["step"] == "round-view"


@pytest.mark.parametrize("records,expected", [
    (["01-implementation-owner.md"], ("validate-and-review", "implementation")),
    (["01-implementation-owner.md", "02-validation.md"], ("review", "implementation")),
    (["01-implementation-owner.md", "02-implementation.md"], ("validate", None)),
])
def test_after_the_round_view_validation_and_review_run(
        tmp_path: Path, records: list[str], expected: tuple) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    _check(root, SECOND_DONE)
    for name in records:
        _record(root, name)

    result = _next(root)

    assert (result["step"], result.get("kind")) == expected
    if "validate" in result["step"]:
        # A validation is named with the target it is for: the round's triage.
        assert result["target"] == ROUND_TRIAGE


def test_a_rounds_validation_starts_before_its_review_is_published(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    _check(root, SECOND_DONE)
    _record(root, "01-implementation-owner.md")

    both = _next(root)
    _record(root, "02-validation.md", text=_validation())
    _log(root, "validate", _done(ROUND_TRIAGE))
    reviewing = _next(root)

    assert (both["step"], both["target"]) == ("validate-and-review", ROUND_TRIAGE)
    # Its exit is the target it was given, so the round's join is read on.
    assert (reviewing["step"], reviewing["kind"]) == ("review", "implementation")


def test_reviews_and_validation_await_triage(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    _check(root, SECOND_DONE)
    _record(root, "01-validation.md", text=_validation())
    _review(root, "02-implementation.md")

    result = _next(root)

    assert result == {"step": "triage", "kind": "implementation",
                      "reason": "01-validation.md, 02-implementation.md have no triage"}


def test_a_rounds_triage_whose_outcome_is_not_recorded_is_in_progress(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    _check(root, SECOND_DONE)
    _record(root, "01-validation.md", text=_validation(), triage="Evidence.")
    _review(root, "02-implementation.md")
    _record(root, "02-implementation.md", triage="Advance — the owner: \"advance.\"")

    result = _next(root)

    assert result["step"] == "triage" and "in progress" in result["reason"]


def _triaged_round(root: Path, *, to: dict, validated: str = HEAD,
                   reviewed: str = "e" * 40) -> dict:
    """A round whose validation and review were triaged, the triage naming `to`."""
    _round(root, [[2]])
    _check(root, SECOND_DONE)
    _record(root, "01-validation.md", text=_validation(validated))
    _review(root, "02-implementation.md", reviewed=reviewed)
    return _triage(root, "01-validation.md", "02-implementation.md", to=to)


def test_a_triaged_round_with_fixes_since_its_validation_is_validated_again(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _triaged_round(root, to=_to("round"), validated="f" * 40)

    result = _next(root)

    assert (result["step"], result["target"]) == ("validate", {"step": "round"})
    assert "also changes scripts/" in result["reason"]


def test_a_triaged_round_with_sections_left_waits_for_the_next_round(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _triaged_round(root, to=_to("round"))

    result = _next(root)

    assert (result["step"], result["round"]) == ("owner", ["3"])


def test_the_last_round_triaged_goes_to_the_pre_closeout_review(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _triaged_round(root, to=_to("review", "pre-closeout"))
    _check(root, ALL_WORK_DONE)

    assert (_next(root)["step"], _next(root)["kind"]) == ("review", "pre-closeout")


def test_a_published_pre_closeout_review_is_triaged(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation", tasks=ALL_WORK_DONE)
    _triaged_round(root, to=_to("review", "pre-closeout"))
    _review(root, "03-pre-closeout.md")

    assert (_next(root)["step"], _next(root)["kind"]) == ("triage", "pre-closeout")


def test_a_triage_naming_sections_out_of_the_plans_order(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _planned(root)
    _triaged_round(root, to=_to("implement", sections=[["3"]]))
    _check(root, TASKS)

    result = _next(root)

    # The second section is open, and the triage names the third: a round of its
    # own, recorded as it starts.
    assert (result["step"], result["sections"], result["by"]) == ("round", [["3"]], "triage")


# Another round runs the review of the same kind again: for pre-closeout, once
# the fix commit is validated; with no fix, on the same commit.

def _pre_closeout(root: Path, *, to: dict | None = None, returned: dict | None = None,
                  reviewed: str, validated: str = "e" * 40) -> dict:
    """The last round triaged, its pre-closeout review published and triaged naming
    `to`, or proposing to return to `returned`."""
    _triaged_round(root, to=_to("review", "pre-closeout"), validated=validated,
                   reviewed=validated)
    _check(root, ALL_WORK_DONE)
    _review(root, "03-pre-closeout.md", reviewed=reviewed)
    return _triage(root, "03-pre-closeout.md", to=to, returned=returned)


def test_another_pre_closeout_round_is_validated_then_reviewed_again(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _pre_closeout(root, to=_to("review", "pre-closeout"), reviewed="e" * 40)

    unvalidated = _next(root)
    _record(root, "04-validation.md", text=_validation(HEAD))
    _log(root, "validate", _done(_to("review", "pre-closeout")))
    validated = _next(root)

    assert (unvalidated["step"], unvalidated["target"]) == (
        "validate", {"step": "review", "kind": "pre-closeout"})
    assert "also changes" in unvalidated["reason"]
    assert (validated["step"], validated["kind"]) == ("review", "pre-closeout")


def test_another_round_with_no_fix_reviews_the_same_commit_again(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation", tasks=ALL_WORK_DONE)
    _triaged_round(root, to=_to("review", "implementation"), reviewed=HEAD)

    assert (_next(root)["step"], _next(root)["kind"]) == ("review", "implementation")


def test_another_closeout_round_is_reviewed_again(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _review(root, "05-closeout.md", reviewed="e" * 40)
    _triage(root, "05-closeout.md", to=_to("review", "closeout"))

    assert (_next(root)["step"], _next(root)["kind"]) == ("review", "closeout")


# A return: once the owner confirms it, by a decision that resolves its run and
# directs the step returned to, the returned review no longer governs.

def _returned_round(root: Path) -> dict:
    """A round whose triage returned the change to planning; the returned run."""
    _planned(root)
    _round(root, [[2]])
    _check(root, SECOND_DONE)
    _record(root, "01-validation.md", text=_validation("e" * 40))
    _review(root, "02-implementation.md", reviewed="e" * 40)
    return _triage(root, "01-validation.md", "02-implementation.md", returned=_to("plan"))


def test_a_confirmed_return_from_a_round_goes_to_the_amended_plans_next_round(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    run = _returned_round(root)
    _direct(root, "plan", "return to planning confirmed", resolves=run["seq"])
    directed = _next(root)
    _planned(root, [[[3]]])

    result = _next(root)

    assert directed["step"] == "plan" and "return to planning confirmed" in directed["reason"]
    assert "disagreement" not in directed
    # The work-in-progress commit is validated with the next round, not before it.
    assert (result["step"], result["sections"]) == ("round", [[3]])


def test_a_return_that_reworks_the_rounds_own_section_is_a_round_of_its_own(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    run = _returned_round(root)
    _direct(root, "plan", "return to planning confirmed", resolves=run["seq"])
    _planned(root)
    _check(root, TASKS.replace("- [ ] 2.1 Open.", "- [x] 2.1 Open.\n- [ ] 2.2 Rework."))

    planned = _next(root)
    _round(root, [[2]])
    implementing = _next(root)

    # Read, validated, and reviewed as a round, never under the returned one.
    assert (planned["step"], planned["sections"]) == ("round", [[2]])
    assert (implementing["step"], implementing["sections"]) == ("implement", [2])


def test_a_return_whose_plan_drops_the_rounds_section_goes_to_the_next_round(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    run = _returned_round(root)
    _direct(root, "plan", "return to planning confirmed", resolves=run["seq"])
    _planned(root, [[[3]]])
    _check(root, TASKS.replace("## 2. Second\n\n- [ ] 2.1 Open.\n\n", ""))

    result = _next(root)

    assert (result["step"], result["sections"]) == ("round", [[3]])


def test_a_direction_naming_no_run_leaves_the_return_waiting(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    run = _returned_round(root)
    _direct(root, "design", "back to design")

    result = _next(root)

    assert (result["step"], result["seq"], result["target"]) == ("owner", run["seq"],
                                                                 {"step": "plan"})


def test_a_return_waits_for_the_owner_and_a_declined_one_stays_theirs(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    run = _returned_round(root)

    unconfirmed = _next(root)
    _decide(root, "return declined", by="owner", resolves=run["seq"])
    declined = _next(root)

    assert (unconfirmed["step"], unconfirmed["target"]) == ("owner", {"step": "plan"})
    assert declined["step"] == "owner" and "not confirmed" in declined["reason"]
    assert declined["target"] == {"step": "plan"}


def test_a_confirmation_the_log_does_not_attribute_to_the_owner_confirms_nothing(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    run = _returned_round(root)
    # Appended past the writer, which refuses this line, to stand for a log holding one.
    append_entry(log_path(root, CHANGE), {
        "step": "orchestrator", "outcome": "orchestrator", "by": "orchestrator",
        "decision": "return to planning confirmed", "reason": "a reason",
        "resolves": run["seq"], "next": {"step": "plan"}})

    result = _next(root)

    # Neither directed to planning nor past the round it would set aside.
    assert result["step"] == "owner" and "not confirmed" in result["reason"]


def test_a_confirmed_return_from_pre_closeout_reviews_the_work_again(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    run = _pre_closeout(root, returned=_to("plan"), reviewed="e" * 40)
    _direct(root, "plan", "return to planning confirmed", resolves=run["seq"])
    _log(root, "plan", _done(_to("review", "pre-closeout")))

    unvalidated = _next(root)
    _record(root, "04-validation.md", text=_validation(HEAD))
    validated = _next(root)

    assert (unvalidated["step"], unvalidated["target"]) == (
        "validate", {"step": "review", "kind": "pre-closeout"})
    assert (validated["step"], validated["kind"]) == ("review", "pre-closeout")


def test_a_closeout_triage_that_returns_goes_to_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _review(root, "05-closeout.md", reviewed="e" * 40)
    run = _triage(root, "05-closeout.md", returned=_to("plan"))
    # No direction crosses the archive: planning's entry guard refuses it.
    with pytest.raises(StepError, match="the change is archived"):
        _direct(root, "plan", "return to planning confirmed", resolves=run["seq"])
    _decide(root, "return declined", by="owner", resolves=run["seq"])

    result = _next(root)

    # The table gives a closeout triage no return.
    assert result["step"] == "owner" and "does not declare" in result["reason"]


# An implementation round advances on a passing validation of its fix commit.

def _advanced_round(root: Path, validated: str = HEAD, result: str = "passed") -> None:
    _planned(root)
    _triaged_round(root, to=_to("round"), validated="e" * 40)
    if validated:
        _record(root, "03-validation.md", text=_validation(validated, result))


def test_an_advancing_round_validates_its_fix_commit_then_starts_the_next_planned_round(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _advanced_round(root, validated="")

    unvalidated = _next(root)
    _record(root, "03-validation.md", text=_validation(HEAD))
    _log(root, "validate", _done(_to("round")))
    validated = _next(root)

    assert (unvalidated["step"], unvalidated["target"]) == ("validate", {"step": "round"})
    assert validated == {"step": "round", "sections": [[3]], "by": "plan",
                         "reason": validated["reason"]}


def test_an_inconclusive_validation_of_the_fix_commit_goes_to_the_owner(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _advanced_round(root, result="inconclusive")

    result = _next(root)

    # The owner, with the next round as the exit the validation holds.
    assert (result["step"], result["validation"], result["target"]) == (
        "owner", "inconclusive", {"step": "round"})


def test_the_last_planned_round_advancing_goes_to_the_pre_closeout_review(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _planned(root)
    _triaged_round(root, to=_to("review", "pre-closeout"), validated="e" * 40)
    _check(root, ALL_WORK_DONE)

    unvalidated = _next(root)
    _record(root, "03-validation.md", text=_validation(HEAD))
    validated = _next(root)

    assert (unvalidated["step"], unvalidated["target"]) == (
        "validate", {"step": "review", "kind": "pre-closeout"})
    assert (validated["step"], validated["kind"]) == ("review", "pre-closeout")


def test_a_pre_closeout_triage_that_advances_goes_to_closeout_once_head_is_validated(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _pre_closeout(root, to=_to("closeout"), reviewed=HEAD)

    unvalidated = _next(root)
    _record(root, "04-validation.md", text=_validation(HEAD))
    _log(root, "validate", _done(_to("closeout")))
    validated = _next(root)

    assert (unvalidated["step"], unvalidated["target"]) == ("validate", {"step": "closeout"})
    assert validated["step"] == "closeout"


def test_a_validation_naming_another_exit_than_its_target_goes_to_the_owner(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _pre_closeout(root, to=_to("closeout"), reviewed=HEAD)
    _record(root, "04-validation.md", text=_validation(HEAD))
    _log(root, "validate", _done(ROUND_TRIAGE))

    result = _next(root)

    assert (result["step"], result["choice"], result["given"]) == (
        "owner", ROUND_TRIAGE, {"step": "closeout"})


# After a pre-closeout review, closeout's own checks read the documentation, so a
# triage's commit of documents alone needs no validation; before it, only records.
DOCUMENTS = ["openspec/changes/README.md", f"openspec/changes/{CHANGE}/specs/x/spec.md",
             "docs/agents/change-workflow.md"]


def test_a_pre_closeout_triages_document_commit_goes_to_closeout_unvalidated(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _pre_closeout(root, to=_to("closeout"), reviewed="e" * 40)

    assert _next(root, changed=DOCUMENTS)["step"] == "closeout"
    assert _next(root, changed=DOCUMENTS + FIX)["step"] == "validate"


def test_another_pre_closeout_round_over_documents_reviews_again_unvalidated(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _pre_closeout(root, to=_to("review", "pre-closeout"), reviewed="e" * 40)

    result = _next(root, changed=DOCUMENTS)

    assert (result["step"], result["kind"]) == ("review", "pre-closeout")


def test_an_implementation_triages_document_commit_is_validated(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _advanced_round(root, validated="e" * 40)

    assert _next(root, changed=DOCUMENTS)["step"] == "validate"
    assert _next(root, changed=RECORDS_ONLY)["step"] == "round"


# A closeout triage that advances: archive cleanup, after a validation when a
# correction changed more than documentation.

def _closeout_triaged(root: Path, *, reviewed: str = "e" * 40) -> dict:
    _review(root, "05-closeout.md", reviewed=reviewed)
    return _triage(root, "05-closeout.md", to=_to("archive-cleanup"))


def test_a_closeout_correction_awaits_validation(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _closeout_triaged(root)

    unvalidated = _next(root, changed=[".agents/skills/change-triage/SKILL.md"])
    _record(root, "06-validation.md", text=_validation(HEAD))
    validated = _next(root, changed=FIX)

    assert (unvalidated["step"], unvalidated["target"]) == (
        "validate", {"step": "archive-cleanup"})
    assert ".agents/" in unvalidated["reason"]
    assert validated["step"] == "archive-cleanup"


def test_a_documentation_correction_at_closeout_needs_no_validation(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _closeout_triaged(root)

    result = _next(root, changed=["docs/agents/change-workflow.md",
                                  "openspec/specs/change-workflow/spec.md"])

    assert result["step"] == "archive-cleanup"


def test_the_owners_waiver_directs_archive_cleanup_past_a_missing_validation(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _closeout_triaged(root)

    held = _next(root, changed=FIX)
    _direct(root, "archive-cleanup", "waive archive cleanup's validation")
    directed = _next(root, changed=FIX)
    _log(root, "archive-cleanup", QUESTION)
    asked = _next(root, changed=FIX)
    _log(root, "archive-cleanup", _done(_to("done")))
    ran = _next(root, changed=FIX)

    assert held["step"] == "validate"
    assert directed["step"] == "archive-cleanup" and "waive" in directed["reason"]
    # Archive cleanup's own check asks, naming the paths, and records the waiver.
    assert asked["step"] == "owner"
    assert ran == {"step": "done", "reason": "archived"}


def test_archive_cleanup_that_names_done_finishes_the_change(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _closeout_triaged(root, reviewed=HEAD)
    _log(root, "archive-cleanup", _done(_to("done")))

    assert _next(root) == {"step": "done", "reason": "archived"}


def test_a_steps_exit_whose_target_cannot_be_entered_goes_to_the_owner(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout")
    _log(root, "closeout", _done(_to("review", "closeout")))

    result = _next(root)

    # Not the closeout review: the change is not archived.
    assert (result["step"], result["choice"]) == ("owner", {"step": "review",
                                                            "kind": "closeout"})
    assert "the change is not archived" in result["reason"]


# The plan's mapping of rounds.

def test_a_two_round_plan_names_the_second_round_only_after_the_first_advanced(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for implementation")
    _planned(root)

    first = _next(root)
    _round(root, [[2]])
    implementing = _next(root)
    _check(root, SECOND_DONE)
    viewing = _next(root)

    assert (first["step"], first["sections"], first["by"]) == ("round", [[2]], "plan")
    assert (implementing["step"], implementing["sections"]) == ("implement", [2])
    assert viewing["step"] == "round-view"


def test_an_amended_plan_governs_the_rounds_it_maps(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _planned(root)
    _planned(root, [[[2], [3]]])

    result = _next(root)

    assert (result["step"], result["sections"]) == ("round", [[2], [3]])


@pytest.mark.parametrize("mapping", [None, [[[3]]]])
def test_a_first_open_section_no_planned_round_names_goes_to_the_owner(
        tmp_path: Path, mapping) -> None:
    root = _repository(tmp_path, "ready for implementation")
    _log(root, "plan", _done(_to("round"), **({"rounds": mapping} if mapping else {})))

    result = _next(root)

    assert (result["step"], result["round"]) == ("owner", ["2", "3"])
    assert "agree the next implementation round" in result["reason"]


def test_a_later_unmapped_section_does_not_hold_the_next_planned_round(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for implementation")
    _planned(root, [[[2]]])

    assert (_next(root)["step"], _next(root)["sections"]) == ("round", [[2]])


def test_a_closeout_section_a_plan_maps_is_left_out_of_its_round(tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for implementation")
    _planned(root, [[[2], [3, 4]]])

    planned = _next(root)
    _round(root, [[2], [3, 4]])
    _check(root, ALL_WORK_DONE)
    recorded = _next(root)

    assert planned["sections"] == [[2], [3]]
    # A round recorded with the closeout section is not held open by it.
    assert recorded["step"] == "round-view"


@pytest.mark.parametrize("title", ["Closeout", "Plan closeout", "Repository closeout",
                                   "Closeout after review follow-up"])
def test_a_closeout_section_is_known_by_its_title(tmp_path: Path, title: str) -> None:
    root = _repository(tmp_path, "ready for implementation",
                       tasks=SECOND_DONE.replace("## 4. Closeout", f"## 4. {title}"))
    _planned(root, [[[2], [3, 4]]])

    assert _next(root)["sections"] == [[3]]


def test_a_planned_round_naming_a_section_the_task_list_lacks_goes_to_the_owner(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for implementation")
    _planned(root, [[[2, 9]], [[3]]])

    result = _next(root)

    assert (result["step"], result["round"]) == ("owner", ["2", "3"])
    assert "task list lacks: 9" in result["reason"] and "sections" not in result


def test_a_complete_section_a_plan_maps_is_left_out_of_its_round(tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for implementation")
    _planned(root, [[[1], [1, 2], [3]]])

    assert _next(root)["sections"] == [[2], [3]]


def test_a_next_round_named_with_every_section_checked_goes_to_the_owner(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation", tasks=ALL_WORK_DONE)
    _planned(root)

    result = _next(root)

    assert result["step"] == "owner" and "every section before closeout" in result["reason"]


def test_a_plan_with_nothing_to_implement_goes_to_pre_closeout_after_validation(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for implementation", tasks=ALL_WORK_DONE)
    _log(root, "plan", _done(_to("review", "pre-closeout")))
    _record(root, "01-validation.md", text=_validation("f" * 40))

    unvalidated = _next(root)
    _record(root, "02-validation.md", text=_validation(HEAD, "inconclusive"))
    inconclusive = _next(root)

    assert unvalidated["step"] == "validate" and "pre-closeout" in unvalidated["reason"]
    assert (inconclusive["step"], inconclusive["validation"]) == ("owner", "inconclusive")


# Another implementation round runs the review again, validating only a fix
# committed since; a repeat pass is read over the commit that review read.

def _saved_earlier(root: Path, *names: str) -> None:
    """Dates each named file of `reviews/`, in order, long before anything the test
    writes next: a pass's records and its triage were saved before the next pass."""
    for offset, name in enumerate(names):
        os.utime(_reviews(root) / name, (1000 + offset, 1000 + offset))


def _first_pass(root: Path, *records: str, reviewed: str = "e" * 40,
                review: str = "03-implementation.md") -> None:
    """A first pass of records, then `review`, triaged choosing the review again."""
    for name in records:
        _record(root, name, text=_validation(reviewed) if name.endswith("validation.md")
                else "x")
    _review(root, review, reviewed=reviewed)
    _triage(root, *records, review, to=_to("review", "implementation"))
    _saved_earlier(root, *records, review, review.replace(".md", ".triage.md"))


def _committed_round(root: Path, *records: str) -> None:
    _round(root, [[2]])
    _check(root, SECOND_DONE)
    for name in records:
        _record(root, name, text=_validation() if name.endswith("validation.md") else "x")


def test_another_implementation_round_with_a_fix_is_read_then_validated(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root)
    _first_pass(root, "01-validation.md", "02-implementation-owner.md")

    unread = _next(root)
    _record(root, "04-implementation-owner.md")
    unvalidated = _next(root)
    _record(root, "05-validation.md", text=_validation(HEAD))
    validated = _next(root)

    # The first pass's owner record is not the fix's reading.
    assert (unread["step"], unread["base"]) == ("round-view", "e" * 40)
    assert unread["target"] == {"step": "review", "kind": "implementation"}
    assert "workspace" not in unread
    assert (unvalidated["step"], unvalidated["target"]) == (
        "validate", {"step": "review", "kind": "implementation"})
    assert (validated["step"], validated["kind"]) == ("review", "implementation")


def test_another_round_with_no_fix_runs_whatever_the_validation_said(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root)
    _record(root, "01-validation.md", text=_validation(HEAD, "inconclusive"))
    _review(root, "02-implementation.md", reviewed=HEAD)
    _triage(root, "01-validation.md", "02-implementation.md",
            to=_to("review", "implementation"))

    assert (_next(root)["step"], _next(root)["kind"]) == ("review", "implementation")


def test_a_code_fix_from_an_earlier_closeout_round_is_validated_before_cleanup(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _review(root, "05-closeout.md", reviewed="a" * 40)
    _triage(root, "05-closeout.md", to=_to("review", "closeout"))
    # The latest review read the fix commit, HEAD: only the archive commit shows it.
    _review(root, "07-closeout.md", reviewed=HEAD)
    _triage(root, "07-closeout.md", to=_to("archive-cleanup"))

    assert _next(root)["step"] == "validate"


def test_the_owner_may_direct_a_repeat_review_with_no_fix(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _pre_closeout(root, to=_to("closeout"), reviewed=HEAD, validated=HEAD)
    _direct(root, "review", "review again", kind="pre-closeout")

    directed = _next(root)
    _review(root, "04-pre-closeout.md", reviewed=HEAD)
    after = _next(root)

    assert (directed["step"], directed["kind"]) == ("review", "pre-closeout")
    assert "review again" in directed["reason"]
    assert (after["step"], after["kind"]) == ("triage", "pre-closeout")


# Closeout.

def _to_closeout(root: Path) -> None:
    """A pre-closeout triage that chose closeout, `HEAD` validated."""
    _pre_closeout(root, to=_to("closeout"), reviewed=HEAD, validated=HEAD)


def test_closeout_not_yet_archived_continues(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", tasks=ALL_WORK_DONE)
    _to_closeout(root)

    result = _next(root)

    assert result["step"] == "closeout" and "no run of it is logged" in result["reason"]


def test_an_archived_change_has_its_closeout_review(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _log(root, "closeout", _done(_to("review", "closeout")))

    assert (_next(root)["step"], _next(root)["kind"]) == ("review", "closeout")


def test_an_uncommitted_archive_resumes_closeout(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _log(root, "closeout", _done(_to("review", "closeout")))

    assert _next(root, uncommitted=True)["step"] == "closeout"


def test_a_published_closeout_review_is_triaged(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _log(root, "closeout", _done(_to("review", "closeout")))
    _review(root, "05-closeout.md")

    assert (_next(root)["step"], _next(root)["kind"]) == ("triage", "closeout")


def test_a_closeout_triage_that_advances_goes_to_archive_cleanup(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _closeout_triaged(root, reviewed=HEAD)

    assert _next(root)["step"] == "archive-cleanup"


def test_an_archived_change_is_done(tmp_path: Path) -> None:
    root = _repository(tmp_path, "archived", archived=True)

    assert _next(root)["step"] == "done"


# The owner's directions: any node, past its exit guards, within its entry guards.

def test_the_owner_directs_past_a_guard(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _pre_closeout(root, to=_to("closeout"), reviewed=HEAD)
    _record(root, "04-validation.md", text=_validation(HEAD, "failed"))

    failed = _next(root)
    _direct(root, "closeout", "closeout despite the validation")
    directed = _next(root)

    assert (failed["step"], failed["validation"]) == ("owner", "failed")
    assert directed["step"] == "closeout"


def test_closeout_finding_a_design_defect_before_the_archive_is_directed_to_design(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", tasks=ALL_WORK_DONE)
    _to_closeout(root)
    _direct(root, "design", "back to design from closeout")

    directed = _next(root)
    # The design step sets the status as it starts, before it logs a line.
    (root / "openspec/changes/README.md").write_text(
        (root / "openspec/changes/README.md").read_text("utf-8").replace(
            "| in closeout |", "| in design |"), "utf-8")
    started = _next(root)

    assert directed["step"] == started["step"] == "design"
    # A direction back is not a missing outcome, nor a status set back by hand.
    assert "disagreement" not in directed and "disagreement" not in started


def test_the_owner_directs_sections_out_of_the_plans_order(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _planned(root)
    _direct(root, "implement", "the third section first", sections=[["3"]])

    result = _next(root)

    assert (result["step"], result["sections"], result["by"]) == ("round", [["3"]], "owner")


def test_a_direction_to_the_round_view_reads_the_rounds_join(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root)
    _direct(root, "round-view", "read the round")

    unread = _next(root)
    _record(root, "01-implementation-owner.md")
    both = _next(root)
    _record(root, "02-validation.md", text=_validation())
    _log(root, "validate", _done(ROUND_TRIAGE))
    validated = _next(root)
    _review(root, "03-implementation.md")
    reviewed = _next(root)

    # No run of the round view is logged, so its records say when the reading is done.
    assert unread["step"] == "round-view"
    assert (both["step"], both["target"]) == ("validate-and-review", ROUND_TRIAGE)
    # The validation named the target it was given, in the join the direction reads.
    assert (validated["step"], validated["kind"]) == ("review", "implementation")
    assert (reviewed["step"], reviewed["kind"]) == ("triage", "implementation")


def test_a_directed_review_that_stopped_is_still_directed_once_resolved(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _pre_closeout(root, to=_to("closeout"), reviewed=HEAD)
    _direct(root, "review", "review again", kind="pre-closeout")
    run = record_outcome(log_path(root, CHANGE), "review", CRASHED, session=None,
                         commit=HEAD, extra={"kind": "pre-closeout"})
    _decide(root, "rerun the review", resolves=run["seq"])

    result = _next(root)

    # The run took no exit: the review is still the step directed, as the review's
    # own entry check reads the direction (`unused_direction`).
    assert (result["step"], result["kind"]) == ("review", "pre-closeout")
    assert unused_direction(read_log(log_path(root, CHANGE)))["next"] == {
        "step": "review", "kind": "pre-closeout"}


def test_the_owner_directs_a_validation_before_closeout(tmp_path: Path) -> None:
    passing = _repository(tmp_path / "passing", "in implementation")
    failing = _repository(tmp_path / "failing", "in implementation")
    results = []
    for root, result in ((passing, "passed"), (failing, "failed")):
        _pre_closeout(root, to=_to("review", "pre-closeout"), reviewed=HEAD)
        _direct(root, "validate", "validate, then closeout", target="closeout")
        directed = _next(root)
        _record(root, "04-validation.md", text=_validation(HEAD, result))
        _log(root, "validate", _done(_to("closeout")))
        results.append((directed, _next(root)))

    (directed, passed), (_, failed) = results
    assert directed["step"] == "validate" and directed["target"] == {"step": "closeout"}
    assert passed["step"] == "closeout"
    assert (failed["step"], failed["target"]) == ("owner", {"step": "closeout"})


def test_a_direction_whose_entry_guard_no_longer_holds_goes_to_the_owner(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _pre_closeout(root, to=_to("closeout"), reviewed=HEAD)
    # Appended past the writer, which refuses it now that every pre-closeout review
    # has its triage, to stand for a direction written before that triage ran.
    append_entry(log_path(root, CHANGE), {
        "step": "orchestrator", "outcome": "orchestrator", "by": "owner",
        "decision": "triage again", "reason": "a reason",
        "next": {"step": "triage", "kind": "pre-closeout"}})

    result = _next(root)

    assert result["step"] == "owner" and "no pre-closeout review awaits triage" in (
        result["reason"])


# Statuses that wait on the owner, and dependencies.

@pytest.mark.parametrize("status", ["blocked in design", "blocked in implementation",
                                    "deferred"])
def test_a_blocked_or_deferred_change_waits_for_the_owner(tmp_path: Path, status: str) -> None:
    result = _next(_repository(tmp_path, status))

    assert result["step"] == "owner" and "the notes" in result["reason"]


def test_a_design_gating_prerequisite_not_archived_waits(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design", depends_on="`split-pools` (design)",
                       others={"split-pools": "in implementation"})

    result = _next(root)

    assert (result["step"], result["prerequisite"]) == ("owner", "split-pools")
    assert "waits on split-pools" in result["reason"]


def test_a_design_gating_prerequisite_archived_here_proposes_the_release(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design", depends_on="`split-pools` (design)",
                       others={"split-pools": "archived"})

    result = _next(root)

    assert (result["step"], result["release"]) == ("owner", "split-pools")


def test_a_dependency_gating_a_later_phase_does_not_hold_design(tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for design", depends_on="`split-pools`",
                       others={"split-pools": "in design"})

    assert _next(root)["step"] == "design"


def test_a_design_blocked_on_an_unlanded_prerequisite_waits_for_dev(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _log(root, "design", {"outcome": "blocked", "message": "Needs split-pools.",
                          "blocked_on": "split-pools"})

    result = _next(root)

    assert (result["step"], result["prerequisite"]) == ("owner", "split-pools")
    assert "merge dev" in result["reason"]


def test_a_prerequisite_merged_in_is_recorded_by_design(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design", others={"split-pools": "ready for design"})
    _log(root, "design", {"outcome": "blocked", "message": "Needs split-pools.",
                          "blocked_on": "split-pools"})

    result = _next(root)

    assert result["step"] == "design" and "record the dependency" in result["reason"]


def test_a_dependency_with_no_directory_here_waits_for_dev(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design", depends_on="`split-pools` (design)")

    result = _next(root)

    assert (result["step"], result["prerequisite"]) == ("owner", "split-pools")
    assert "merge dev" in result["reason"]


def test_a_malformed_dependency_is_unclassified(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design", depends_on="split pools")

    assert _next(root)["step"] == "unclassified"


def test_a_released_prerequisite_lets_design_resume(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design", others={"split-pools": "archived"})
    _log(root, "design", {"outcome": "blocked", "message": "Needs split-pools.",
                          "blocked_on": "split-pools"})

    result = _next(root)

    assert result == {"step": "design", "reason": "in design"}


# A change whose records predate the log's format is converted before it is routed.

def test_a_log_not_yet_converted_goes_to_the_owner_with_the_command(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _log(root, "design", _done(_to("review", "design")))
    _unmarked(root, {"seq": 2, "at": "2026-10-20T10:00:00Z", "step": "orchestrator",
                     "outcome": "orchestrator", "by": "owner", "decision": "review again",
                     "reason": "a reason", "next": "review", "kind": "design"})

    result = _next(root)

    command = f"python3 scripts/run_change_step.py convert {CHANGE}"
    assert (result["step"], result["convert"]) == ("owner", command)
    assert "seq 2" in result["reason"] and command in result["reason"]


def test_an_older_return_awaiting_confirmation_goes_to_the_conversion(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _unmarked(root, {"seq": 1, "at": "2026-10-20T10:00:00Z", "step": "triage",
                     "outcome": "returned", "message": "Back.", "return_to": "planning",
                     "evidence": "the notes"})

    result = _next(root)

    # Not the waiting return: no line of the log is read as the new format.
    assert result["step"] == "owner" and "convert" in result
    assert "seq" not in result


def test_a_change_with_records_and_no_log_goes_to_the_conversion(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _record(root, f"03-{KIND}.md", triage="Advance")

    result = _next(root)

    assert result["step"] == "owner" and "convert" in result
    assert "no workflow log" in result["reason"]


def test_an_older_wrapper_appending_after_the_conversion_needs_it_again(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    append_entry(log_path(root, CHANGE), {"step": "convert", "outcome": "converted",
                                          "triaged": [], "message": "converted"})
    _direct(root, "review", "the change stands at a design review", kind="design")
    converted = _next(root)
    _unmarked(root, {"seq": 3, "at": "2026-10-20T10:00:00Z", "step": "review",
                     "outcome": "finished", "message": "Done.", "next": "triage",
                     "kind": "design"})

    assert (converted["step"], converted["kind"]) == ("review", "design")
    assert _next(root)["step"] == "owner" and "convert" in _next(root)


# The round's join is the table's: what it waits for decides what is named.

def test_a_join_that_does_not_wait_for_a_member_names_none_of_its_step(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root)
    join = graph.Join(tuple((what, node) for what, node in graph.ROUND_JOIN.waits_for
                            if node != graph.ROUND_VIEW))

    full = _next(root)
    without_reading = _next(root, join=join)

    assert full["step"] == "round-view"
    assert (without_reading["step"], without_reading["target"]) == (
        "validate-and-review", ROUND_TRIAGE)


def test_a_record_of_a_member_the_join_lacks_does_not_stand_for_the_reading(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root, "01-validation.md")
    join = graph.Join(tuple((what, node) for what, node in graph.ROUND_JOIN.waits_for
                            if node != graph.VALIDATE))

    # The round's validation is in, but a join without validation still reads first.
    assert _next(root)["step"] == "review"
    assert _next(root, join=join)["step"] == "round-view"


def test_a_join_that_does_not_wait_for_validation_triages_without_it(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root, "01-implementation-owner.md")
    _review(root, "02-implementation.md")
    join = graph.Join(tuple((what, node) for what, node in graph.ROUND_JOIN.waits_for
                            if node != graph.VALIDATE))

    assert _next(root)["step"] == "validate"
    assert (_next(root, join=join)["step"], _next(root, join=join)["kind"]) == (
        "triage", "implementation")


# What the files say over the log, and what cannot be classified.

def test_a_status_set_back_by_hand_is_reported(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _planned(root)

    result = _next(root)

    # The log's route, and the disagreement for the owner.
    assert result["step"] == "round"
    assert "status set back by hand" in result["disagreement"]


def test_an_open_round_view_waits_for_the_owner_before_anything_else(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    view = rounds.View(CHANGE, "feat/x", "a" * 40, HEAD)

    result = nxt.compute(root, CHANGE, head=lambda _: HEAD, view=lambda _: view,
                         uncommitted=lambda *_: False, **HERE)

    assert (result["step"], result["round_view"]) == ("owner", CHANGE)
    assert "make round-done" in result["reason"]


@pytest.mark.parametrize("setup,reason", [
    (lambda root: (root / "openspec/changes/README.md").write_text("", "utf-8"), "has no row"),
    (lambda root: (_planned(root), _check(root, "No sections.\n")), "has no sections"),
    (lambda root: _round(root, [[9]]), "lacks: 9"),
])
def test_a_state_no_rule_covers_is_unclassified_with_what_was_read(
        tmp_path: Path, setup, reason: str) -> None:
    root = _repository(tmp_path, "in implementation")
    setup(root)

    result = _next(root)

    assert result["step"] == "unclassified" and reason in result["reason"]
    if "has no row" not in reason:
        assert result["read"]["status"] == "in implementation"


def test_a_status_outside_the_legend_is_unclassified(tmp_path: Path) -> None:
    result = _next(_repository(tmp_path, "active"))

    assert result["step"] == "unclassified" and "names no phase" in result["reason"]


def test_an_unknown_change_is_unclassified(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")

    assert nxt.compute(root, "missing", head=lambda _: HEAD, view=lambda _: None,
                       uncommitted=lambda *_: False, **HERE)["step"] == "unclassified"


def test_a_malformed_log_is_unclassified(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    (_reviews(root) / "workflow.jsonl").write_text("not json\n", "utf-8")

    result = _next(root)

    assert result["step"] == "unclassified" and "workflow.jsonl:1" in result["reason"]


def test_the_command_prints_the_result(tmp_path: Path,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path, "ready for design")

    assert nxt.main([CHANGE], root=root, **HERE) == 0
    assert json.loads(capsys.readouterr().out)["step"] == "design"
    assert nxt.main(["missing"], root=root) == 1


def test_plain_prints_the_result_as_lines(tmp_path: Path,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path, "in design")
    run = _log(root, "design", {**QUESTION, "denials": [{"tool_name": "Bash"}]})

    assert nxt.main([CHANGE, "--plain"], root=root, **HERE) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "step: owner" and lines[1].startswith("reason: the design step ended")
    assert lines[2:] == ['denials: [{"tool_name": "Bash"}]', "outcome: question",
                         f"seq: {run['seq']}"]


# The round view, read from Git as round_view keeps it.

def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def test_a_round_view_opened_and_closed_in_git_is_seen_and_then_not(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    # The change's own branch, so the computation finds the change worked here.
    _git(root, "init", "-q", "-b", f"feat/{CHANGE}")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    base = _git(root, "rev-parse", "HEAD")
    _check(root, SECOND_DONE)
    _git(root, "commit", "-qam", "section 2")

    rounds.start(root, CHANGE, base=base)
    during = nxt.compute(root, CHANGE)
    rounds.done(root)
    after = nxt.compute(root, CHANGE)

    assert (during["step"], during["round_view"]) == ("owner", CHANGE)
    assert after["step"] == "round-view"


# A merge in progress names the owner before anything else is read.

def _states(root: Path, state: str | None) -> None:
    """The change in `state`: each a different routing the merge must come before."""
    if state == "question":
        _log(root, "design", QUESTION)
    elif state == "implemented":
        _committed_round(root)
    elif state == "untriaged":
        _review(root, f"01-{KIND}.md")


@pytest.mark.parametrize("status,state", [
    ("ready for design", None), ("in design", "question"), ("in design", "untriaged"),
    ("in implementation", "implemented"), ("in closeout", None),
])
def test_a_merge_in_progress_names_the_owner_whatever_the_changes_state(
        tmp_path: Path, status: str, state: str | None) -> None:
    root = _repository(tmp_path, status)
    _states(root, state)

    result = nxt.compute(root, CHANGE, head=lambda _: HEAD, view=lambda _: None,
                         **{**HERE, "merging": lambda _: True})

    assert (result["step"], result["merging"]) == ("owner", True)
    assert result["reason"].startswith("a merge is in progress")


def test_a_merge_in_progress_comes_before_an_open_view_and_the_clone(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")

    result = nxt.compute(root, CHANGE, head=lambda _: HEAD, merging=lambda _: True,
                         view=lambda _: pytest.fail("the view was read"),
                         workspace=lambda _: pytest.fail("the workspace was read"),
                         clone=lambda *_: pytest.fail("the clone was read"))

    assert result["step"] == "owner" and result["merging"]


def _commit_all(repo: Path, message: str = "commit") -> str:
    _git(repo, "add", "--all")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def test_a_conflicted_merge_is_seen_in_git_until_it_is_concluded(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.invalid")
    root = _repository(tmp_path, "ready for design")
    script = root / "script.py"
    script.write_text("base\n", "utf-8")
    _git(root, "init", "-q", "-b", "dev")
    _commit_all(root, "base")
    _git(root, "checkout", "-q", "-b", f"feat/{CHANGE}")
    script.write_text("the change's\n", "utf-8")
    _commit_all(root, "the change's")
    _git(root, "checkout", "-q", "dev")
    script.write_text("dev's\n", "utf-8")
    _commit_all(root, "dev's")
    _git(root, "checkout", "-q", f"feat/{CHANGE}")
    before = nxt.compute(root, CHANGE)

    conflicted = subprocess.run(["git", "merge", "-q", "dev"], cwd=root, capture_output=True)
    during = nxt.compute(root, CHANGE)
    script.write_text("both\n", "utf-8")
    _git(root, "add", "script.py")
    _git(root, "commit", "-q", "--no-edit")
    after = nxt.compute(root, CHANGE)

    assert conflicted.returncode != 0
    assert before["step"] == after["step"] == "design"
    assert (during["step"], during["merging"]) == ("owner", True)


# A step whose latest run waits on the owner is never run afresh.

STOPPED = {"outcome": "stopped", "message": "Denied.", "reason": "denied",
           "denials": [{"tool_name": "Bash"}]}
# A run that ended without an outcome, as the wrapper logs it: no denial to read.
CRASHED = {"outcome": "stopped", "message": "exit 1", "reason": "exit 1", "denials": []}


def test_a_triage_question_waits_for_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root, "01-validation.md")
    _review(root, "02-implementation.md")
    _log(root, "triage", QUESTION)

    result = _next(root)

    assert (result["step"], result["resume"]) == ("owner", "triage")


def test_a_validation_question_waits_beside_a_finished_review(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root, "01-implementation-owner.md")
    _log(root, "validate", {**QUESTION, "awaiting": "environmental remedy"})
    _review(root, "02-implementation.md")

    result = _next(root)

    assert (result["step"], result["resume"], result["awaiting"]) == (
        "owner", "validate", "environmental remedy")


def test_a_stopped_run_waits_until_a_decision_resolves_it(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root, "01-implementation-owner.md", "02-validation.md")
    run = record_outcome(log_path(root, CHANGE), "review", STOPPED, session=None,
                         commit=HEAD, extra={"kind": "implementation"})

    stopped = _next(root)
    _decide(root, "rerun the review")
    undecided = _next(root)
    _decide(root, "rerun the review", resolves=run["seq"])
    decided = _next(root)

    assert (stopped["step"], stopped["denials"]) == ("owner", [{"tool_name": "Bash"}])
    assert undecided["step"] == "owner"
    assert (decided["step"], decided["kind"]) == ("review", "implementation")


def test_a_decision_about_one_run_leaves_another_steps_question_waiting(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root, "01-implementation-owner.md")
    _log(root, "validate", {**QUESTION, "awaiting": "environmental remedy"})
    review = record_outcome(log_path(root, CHANGE), "review", STOPPED, session=None,
                            commit=HEAD, extra={"kind": "implementation"})
    _decide(root, "rerun the review", resolves=review["seq"])

    result = _next(root)

    assert (result["step"], result["resume"], result["awaiting"]) == (
        "owner", "validate", "environmental remedy")


def test_a_run_that_went_on_past_a_denial_waits_for_its_reading(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    run = _log(root, "implement", _done(ROUND_TRIAGE, denials=[{"tool_name": "Bash"}]),
               sections=[2])

    unread = _next(root)
    _decide(root, "gap: proposed Bash(cat *)", reads=run["seq"])
    read = _next(root)

    assert unread["step"] == "owner" and "denied 1 tool call" in unread["reason"]
    assert unread["denials"] == [{"tool_name": "Bash"}]
    assert read["step"] == "implement"


def test_a_line_that_resolves_a_finished_run_counts_as_its_reading(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    run = _log(root, "implement", _done(ROUND_TRIAGE, denials=[{"tool_name": "Bash"}]),
               sections=[2])
    _decide(root, "gap: proposed Bash(cat *)", resolves=run["seq"])

    assert _next(root)["step"] == "implement"


# A run can be denied a call and still ask or propose a return: its denials are
# read first, and its question or return waits after the reading as it would
# without the denial.

def test_a_question_with_denials_waits_for_its_reading_then_its_answer(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root, "01-implementation-owner.md")
    run = _log(root, "validate", {**QUESTION, "awaiting": "environmental remedy",
                                  "denials": [{"tool_name": "Bash"}]})

    unread = _next(root)
    _decide(root, "gap: proposed Bash(gh run view *)", reads=run["seq"])
    read = _next(root)
    _record(root, "02-validation.md", text=_validation())
    _log(root, "validate", _done(ROUND_TRIAGE))
    answered = _next(root)

    assert unread["step"] == "owner" and "its question waits after that" in unread["reason"]
    assert (unread["denials"], unread["outcome"]) == ([{"tool_name": "Bash"}], "question")
    assert "resume" not in unread
    assert (read["step"], read["resume"], read["awaiting"]) == (
        "owner", "validate", "environmental remedy")
    assert (answered["step"], answered["kind"]) == ("review", "implementation")


def test_a_return_with_denials_waits_for_its_reading_then_its_confirmation(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    run = _log(root, "implement", {**_returned(_to("design")),
                                   "denials": [{"tool_name": "Bash"}]}, sections=[2])

    unread = _next(root)
    _decide(root, "workaround: none", reads=run["seq"])
    read = _next(root)
    _direct(root, "design", "return to design confirmed", resolves=run["seq"])
    confirmed = _next(root)

    assert unread["step"] == "owner" and unread["denials"] == [{"tool_name": "Bash"}]
    assert "target" not in unread
    assert (read["step"], read["target"]) == ("owner", {"step": "design"})
    assert confirmed["step"] == "design"


def test_a_blocked_design_with_denials_waits_for_their_reading_first(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    run = _log(root, "design", {"outcome": "blocked", "message": "Needs split-pools.",
                                "blocked_on": "split-pools",
                                "denials": [{"tool_name": "Bash"}]})

    unread = _next(root)
    _decide(root, "gap: proposed Bash(cat *)", reads=run["seq"])
    read = _next(root)

    assert unread["step"] == "owner" and "its block waits after that" in unread["reason"]
    assert unread["denials"] == [{"tool_name": "Bash"}]
    assert (read["step"], read["prerequisite"]) == ("owner", "split-pools")


def test_a_stopped_run_is_not_cleared_by_its_reading_alone(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root, "01-implementation-owner.md", "02-validation.md")
    run = record_outcome(log_path(root, CHANGE), "review", STOPPED, session=None,
                         commit=HEAD, extra={"kind": "implementation"})

    _decide(root, "gap: proposed Bash(cat *)", reads=run["seq"])
    read = _next(root)
    _decide(root, "rerun the review", reads=run["seq"], resolves=run["seq"])
    resolved = _next(root)

    assert read["step"] == "owner" and "stopped" in read["reason"]
    assert (resolved["step"], resolved["kind"]) == ("review", "implementation")


def test_a_read_stop_waits_until_its_resumed_run_supersedes_it(tmp_path: Path) -> None:
    # A stop recovered with a one-run grant: its reading leaves it waiting, and
    # the resumed run's line, not a resolves line, is what moves the change on.
    root = _repository(tmp_path, "in implementation")
    _committed_round(root, "01-implementation-owner.md")
    run = _log(root, "validate", STOPPED)

    _decide(root, "gap: proposed Bash(make lock) as a one-run grant", reads=run["seq"])
    read = _next(root)
    _log(root, "validate", _done(ROUND_TRIAGE), granted=["Bash(make lock)"])
    resumed = _next(root)

    assert (read["step"], read["seq"]) == ("owner", run["seq"]) and "stopped" in read["reason"]
    assert resumed["step"] != "owner"


def test_a_decision_that_resolves_a_question_ends_its_wait(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root, "01-implementation-owner.md")
    run = _log(root, "validate", {**QUESTION, "denials": [{"tool_name": "Bash"}]})
    _decide(root, "validate afresh", by="owner", resolves=run["seq"])

    assert _next(root)["step"] == "validate-and-review"


def test_the_owner_confirms_a_return(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    run = _log(root, "implement", _returned(_to("design")), sections=[2])

    unconfirmed = _next(root)
    _direct(root, "design", "return to design confirmed", resolves=run["seq"])
    confirmed = _next(root)

    assert (unconfirmed["step"], unconfirmed["target"]) == ("owner", {"step": "design"})
    assert confirmed["step"] == "design" and "confirmed" in confirmed["reason"]


def test_a_directed_step_that_has_run_is_no_longer_directed(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    run = _log(root, "implement", _returned(_to("design")))
    _direct(root, "design", "return to design confirmed", resolves=run["seq"])
    _log(root, "design", _done(_to("review", "design")))

    assert (_next(root)["step"], _next(root)["kind"]) == ("review", "design")


def test_a_round_recorded_after_the_fact_owns_the_records_above_its_after(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _check(root, SECOND_DONE)
    _review(root, f"01-{KIND}.md")
    _triage(root, f"01-{KIND}.md", to=_to("plan"))
    _record(root, "02-implementation-owner.md")
    _record(root, "03-validation.md", text=_validation())
    _review(root, "04-implementation.md")

    _round(root, [[2]], after=1)
    recorded = _next(root)

    assert recorded == {"step": "triage", "kind": "implementation",
                        "reason": "02-implementation-owner.md, 03-validation.md, "
                                  "04-implementation.md have no triage"}


def test_a_blocked_step_other_than_design_waits_for_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    _log(root, "implement", {"outcome": "blocked", "message": "Needs another change.",
                             "blocked_on": "split-pools"}, sections=[2])

    assert (_next(root)["step"], _next(root)["blocked_on"]) == ("owner", "split-pools")


def test_a_design_reviews_stopped_run_does_not_hold_implementation(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    record_outcome(log_path(root, CHANGE), "review", CRASHED, session=None,
                   commit=HEAD, extra={"kind": "design"})
    _round(root, [[2]])

    assert _next(root)["step"] == "implement"


def test_a_design_triages_stopped_run_does_not_hold_implementation(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    record_outcome(log_path(root, CHANGE), "review", _done(_to("triage", "design")),
                   session="codex:x", commit=HEAD, extra={"kind": "design"})
    _log(root, "triage", CRASHED)
    _round(root, [[2]])

    assert _next(root)["step"] == "implement"


# Unread denials wait whatever the phase: the run that recorded them may be the
# one that moved the change on, and the reading is owed before any step runs.

def test_a_design_triages_denials_are_read_before_planning_starts(tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for planning")
    _review(root, f"01-{KIND}.md")
    run = _log(root, "triage", _done(_to("plan"), triaged=["01-design"],
                                     denials=[{"tool_name": "Bash"}]))

    unread = _next(root)
    _decide(root, "gap: proposed Bash(cat *)", reads=run["seq"])
    read = _next(root)

    assert (unread["step"], unread["seq"], unread["denials"]) == (
        "owner", run["seq"], [{"tool_name": "Bash"}])
    assert "denied 1 tool call" in unread["reason"]
    assert read["step"] == "plan"


def test_a_pre_closeout_triages_denials_are_read_before_closeout_starts(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for closeout", tasks=ALL_WORK_DONE)
    _triaged_round(root, to=_to("review", "pre-closeout"))
    _review(root, "03-pre-closeout.md", reviewed=HEAD)
    run = _log(root, "triage", _done(_to("closeout"), triaged=["03-pre-closeout"],
                                     denials=[{"tool_name": "Bash"}]))
    _record(root, "03-pre-closeout.md", triage="Closeout.", reviewed=HEAD)

    unread = _next(root)
    _decide(root, "gap: proposed Bash(cat *)", reads=run["seq"])
    read = _next(root)

    assert (unread["step"], unread["seq"]) == ("owner", run["seq"])
    assert read["step"] == "closeout"


def test_a_stopped_design_run_with_denials_holds_until_a_line_resolves_it(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    run = _log(root, "design", STOPPED)
    _round(root, [[2]])

    held = _next(root)
    _decide(root, "gap: proposed Bash(cat *)", reads=run["seq"])
    read = _next(root)
    _decide(root, "rerun it", resolves=run["seq"])

    assert (held["step"], held["seq"]) == ("owner", run["seq"]) and "stopped" in held["reason"]
    assert read["step"] == "owner" and "stopped" in read["reason"]
    assert _next(root)["step"] == "implement"


def test_a_plans_denials_are_read_before_implementation_starts(tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for implementation")
    run = _log(root, "plan", _done(_to("round"), denials=[{"tool_name": "Bash"}]))

    unread = _next(root)
    _decide(root, "gap: proposed Bash(cat *)", reads=run["seq"])
    read = _next(root)

    assert (unread["step"], unread["seq"]) == ("owner", run["seq"])
    assert "denied 1 tool call" in unread["reason"]
    assert read["step"] == "owner" and "agree the next implementation round" in read["reason"]


def test_an_earlier_phases_question_with_denials_waits_only_for_their_reading(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for planning")
    _review(root, f"01-{KIND}.md")
    _triage(root, f"01-{KIND}.md", to=_to("plan"))
    run = _log(root, "design", {**QUESTION, "denials": [{"tool_name": "Bash"}]})

    unread = _next(root)
    _decide(root, "gap: proposed Bash(cat *)", reads=run["seq"])
    read = _next(root)

    assert (unread["step"], unread["seq"]) == ("owner", run["seq"])
    assert read["step"] == "plan"


def test_a_status_that_never_routes_on_sections_ignores_a_malformed_list(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "blocked in closeout",
                       tasks=TASKS.replace("## 3. Third\n\n", ""))

    assert _next(root)["step"] == "owner"


def test_a_triage_with_no_review_before_it_holds_any_phase(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _log(root, "triage", STOPPED)
    _round(root, [[2]])

    assert _next(root)["step"] == "owner"


def test_a_return_raised_in_an_earlier_phase_does_not_wait_in_a_later_one(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _log(root, "design", _returned(_to("design")))
    _round(root, [[2]])

    assert _next(root)["step"] == "implement"


def test_an_archived_change_whose_row_was_pruned_is_done(tmp_path: Path) -> None:
    root = _repository(tmp_path, "archived", archived=True)
    (root / "openspec/changes/README.md").write_text("", "utf-8")

    assert _next(root)["step"] == "done"


def test_a_round_agreed_after_triage_starts_with_its_own_view(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _triaged_round(root, to=_to("round"), validated="f" * 40)
    _check(root, ALL_WORK_DONE)
    _round(root, [[3]])

    assert _next(root)["step"] == "round-view"


def test_a_closeout_question_waits_for_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _log(root, "closeout", QUESTION)

    assert (_next(root)["step"], _next(root)["resume"]) == ("owner", "closeout")


def test_an_archive_cleanup_that_stopped_waits_for_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _closeout_triaged(root, reviewed=HEAD)
    _log(root, "archive-cleanup", STOPPED)

    assert _next(root)["step"] == "owner"


def test_an_external_implementation_review_counts_for_the_round(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root, "01-validation.md")
    _review(root, "02-implementation-external.md")

    assert (_next(root)["step"], _next(root)["kind"]) == ("triage", "implementation")


# The owner's waiver of another design review is a direction like any other.

def _redesigned(root: Path) -> None:
    returned = _log(root, "plan", _returned(_to("design")))
    _direct(root, "design", "return to design confirmed", resolves=returned["seq"])
    _log(root, "design", _done(_to("review", "design")))


def test_the_owners_waiver_after_a_return_names_planning(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _redesigned(root)
    before = _next(root)

    waiver = _direct(root, "plan", "waive another design review")

    assert (before["step"], before["kind"]) == ("review", "design")
    assert _next(root)["step"] == "plan"
    assert waiver["next"] == {"step": "plan"} and "resolves" not in waiver


def test_planning_that_stopped_on_the_waiver_is_not_run_again(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _redesigned(root)
    _direct(root, "plan", "waive another design review")
    planned = _log(root, "plan", {"outcome": "stopped", "message": "In design.",
                                  "reason": "status", "denials": []})

    result = _next(root)

    assert result["step"] == "owner" and "the plan step stopped" in result["reason"]
    assert result["seq"] == planned["seq"]


# A change in its own clone: routed to its clone from the workspace, and in the
# clone held to its bootstrap and read beside the owner's view of the round.

WORKSPACE = Path("/the/workspace")


def _bootstrap(state: str) -> nxt.Bootstrap:
    return nxt.Bootstrap(state, None if state == "absent" else Path("/clone/.git/log"))


def _from_workspace(root: Path, *, clone: Path | None = None, bootstrap: str = "succeeded",
                    branch: str | None = "dev", view=None, change: str = CHANGE) -> dict:
    """The computation run in the workspace, whose branch is `branch`."""
    return nxt.compute(root, change, head=lambda _: HEAD, view=lambda _: view,
                       uncommitted=lambda *_: False, changed_since=lambda *_: FIX,
                       branch=lambda _: branch, workspace=lambda _: None,
                       clone=lambda *_: clone, bootstrap=lambda _: _bootstrap(bootstrap))


def _in_clone(root: Path, *, bootstrap: str = "succeeded", view=None) -> dict:
    """The computation run in the change's clone, `root`, beside the workspace's view."""
    return nxt.compute(root, CHANGE, head=lambda _: HEAD,
                       view=lambda checkout: view if checkout == WORKSPACE else None,
                       uncommitted=lambda *_: False, changed_since=lambda *_: FIX,
                       branch=lambda _: f"feat/{CHANGE}", workspace=lambda _: WORKSPACE,
                       clone=lambda workspace, _: root if workspace == WORKSPACE else None,
                       bootstrap=lambda _: _bootstrap(bootstrap))


def test_a_change_with_no_clone_and_no_records_names_its_clone(tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for design")

    result = _from_workspace(root)

    assert result["step"] == "clone"
    assert result["arguments"] == {"CHANGE": CHANGE, "BRANCH": f"feat/{CHANGE}", "FROM": "dev"}
    assert f"make change-clone CHANGE={CHANGE} BRANCH=feat/{CHANGE} FROM=dev" in (
        result["reason"])


def test_a_change_whose_records_are_in_the_workspace_goes_to_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _record(root, f"01-{KIND}.md", triage="Advance")

    result = _from_workspace(root)

    assert result["step"] == "owner"
    assert "check out" in result["reason"] and "into a clone by hand" in result["reason"]
    assert result["routes"] == ["work it in the workspace", "move it into a clone by hand"]


def test_a_change_whose_clone_exists_is_computed_in_the_clone(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    clone = tmp_path / "work.changes" / CHANGE

    result = _from_workspace(root, clone=clone)

    assert (result["step"], result["clone"]) == ("in-clone", str(clone))


def test_a_change_with_a_clone_is_computed_there_while_the_workspace_has_its_branch(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    clone = tmp_path / "work.changes" / CHANGE

    # The owner checked the branch out in the workspace to commit an edit on it.
    result = _from_workspace(root, clone=clone, branch=f"feat/{CHANGE}")

    assert (result["step"], result["clone"]) == ("in-clone", str(clone))


def test_an_unfinished_clone_names_the_clone_again(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")

    result = _from_workspace(root, clone=tmp_path / "clone", bootstrap="absent")

    assert (result["step"], result["arguments"]) == ("clone", {"CHANGE": CHANGE})


def test_an_unknown_change_is_unclassified_wherever_it_is_computed(tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for design")

    assert _from_workspace(root, change="missing")["step"] == "unclassified"


def test_a_change_worked_in_the_workspace_routes_as_before(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _review(root, f"01-{KIND}.md")

    assert _from_workspace(root, branch=f"feat/{CHANGE}")["step"] == "triage"


def test_the_owners_branch_decision_counts_as_the_change_being_here(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _review(root, f"01-{KIND}.md")
    _decide(root, "worked on the shared branch", by="owner", branch="feat/shared",
            change=CHANGE)

    assert _from_workspace(root, branch="feat/shared")["step"] == "triage"


def test_a_clone_view_in_the_workspace_sends_the_change_to_its_clone(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    view = rounds.View(CHANGE, f"feat/{CHANGE}", "b" * 40, HEAD, clone="/the/clone",
                       returns_to="dev")

    # The workspace has the branch checked out to show the round: the change is
    # still worked in its clone.
    result = _from_workspace(root, branch=f"feat/{CHANGE}", view=view)

    assert (result["step"], result["clone"]) == ("in-clone", "/the/clone")


def test_another_changes_view_in_place_still_holds_a_change_with_no_clone(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _review(root, f"01-{KIND}.md")
    view = rounds.View("other-change", "feat/other-change", "b" * 40, HEAD)

    result = _from_workspace(root, branch="feat/other-change", view=view)

    assert (result["step"], result["round_view"]) == ("owner", "other-change")


def test_a_clone_of_another_change_computes_nothing_for_this_one(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")

    result = nxt.compute(root, CHANGE, head=lambda _: HEAD, view=lambda _: None,
                         uncommitted=lambda *_: False, branch=lambda _: "feat/other",
                         workspace=lambda _: WORKSPACE, clone=lambda *_: None,
                         bootstrap=lambda _: _bootstrap("succeeded"))

    assert result["step"] == "owner" and str(WORKSPACE) in result["reason"]


@pytest.mark.parametrize("state,phase,expected", [
    ("running", "in design", "triage"),
    ("running", "in planning", "plan"),
    ("running", "in implementation", "wait"),
    ("failed", "in design", "owner"),
    ("failed", "in implementation", "owner"),
    ("absent", "in implementation", "clone"),
    ("succeeded", "in implementation", "implement"),
])
def test_the_bootstrap_holds_implementation_and_validation(tmp_path: Path, state: str,
                                                           phase: str, expected: str) -> None:
    root = _repository(tmp_path, phase)
    if phase == "in design":
        _review(root, f"01-{KIND}.md")
    elif phase == "in planning":
        _review(root, f"01-{KIND}.md")
        _triage(root, f"01-{KIND}.md", to=_to("plan"))
    elif phase == "in implementation":
        _round(root, [[2]])

    result = _in_clone(root, bootstrap=state)

    assert result["step"] == expected
    if state == "failed":
        assert "/clone/.git/log" in result["reason"] and "make change-clone" in result["reason"]
        assert result["environmental"] is True
    if expected == "wait":
        assert "bootstrap" in result["reason"] and result["waits"]["step"] == "implement"


def test_a_running_bootstrap_holds_validation_and_closeout(tmp_path: Path) -> None:
    validating = _repository(tmp_path / "validating", "in implementation")
    _committed_round(validating)
    closing = _repository(tmp_path / "closing", "ready for closeout", tasks=ALL_WORK_DONE)
    _to_closeout(closing)

    held = [_in_clone(root, bootstrap="running") for root in (validating, closing)]

    assert [(r["step"], r["waits"]["step"]) for r in held] == [
        ("wait", "validate-and-review"), ("wait", "closeout")]


def test_a_running_bootstrap_does_not_hold_a_design_step_after_a_return(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    returned = _log(root, "implement", _returned(_to("design")), sections=[2])
    _direct(root, "design", "return to design confirmed", resolves=returned["seq"])

    assert _in_clone(root, bootstrap="running")["step"] == "design"


def _clone_view(root: Path) -> "rounds.View":
    return rounds.View(CHANGE, f"feat/{CHANGE}", "b" * 40, HEAD, clone=str(root))


def test_a_round_in_a_clone_starts_validation_and_review_beside_the_reading(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root)

    result = _in_clone(root)

    assert (result["step"], result["kind"], result["reading"]) == (
        "validate-and-review", "implementation", True)
    assert result["workspace"] == str(WORKSPACE)


def test_the_rounds_triage_waits_for_its_join(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root, "02-validation.md")
    _log(root, "validate", _done(ROUND_TRIAGE))

    reading = _in_clone(root, view=_clone_view(root))
    unread = _in_clone(root)

    # Its review and the owner's reading are still to come: no triage.
    assert (reading["step"], reading["kind"]) == ("review", "implementation")
    assert "reading" not in reading
    assert (unread["step"], unread["reading"]) == ("review", True)


def test_triage_waits_for_the_owners_reading(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root, "02-validation.md")
    _review(root, "03-implementation.md")

    reading = _in_clone(root, view=_clone_view(root))
    unread = _in_clone(root)

    assert reading["step"] == "owner" and "round-done" in reading["reason"]
    assert reading["round_view"] == CHANGE
    assert (unread["step"], unread["workspace"]) == ("round-view", str(WORKSPACE))


def test_a_view_left_open_after_the_owners_answer_names_round_done_alone(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root, "02-validation.md", "04-implementation-owner.md")
    _review(root, "03-implementation.md")

    result = _in_clone(root, view=_clone_view(root))

    assert result["step"] == "owner" and "is saved" in result["reason"]
    assert "NN-implementation-owner.md" not in result["reason"]


def test_an_earlier_rounds_view_is_closed_before_this_round_is_read(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    note_round(log_path(root, CHANGE), [[2]], "owner", commit="c" * 40)
    _check(root, SECOND_DONE)
    earlier = rounds.View(CHANGE, f"feat/{CHANGE}", "b" * 40, HEAD, clone=str(root))
    this_round = rounds.View(CHANGE, f"feat/{CHANGE}", "c" * 40, HEAD, clone=str(root))

    stale = _in_clone(root, view=earlier)
    current = _in_clone(root, view=this_round)

    assert stale["step"] == "owner" and "earlier round" in stale["reason"]
    assert (current["step"], "reading" in current) == ("validate-and-review", False)


def test_triage_starts_once_the_owner_record_review_and_validation_exist(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root, "02-validation.md", "04-implementation-owner.md")
    _review(root, "03-implementation.md")

    assert _in_clone(root)["step"] == "triage"


def test_an_open_view_holds_triage_and_nothing_else(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root, "02-implementation-owner.md", "03-validation.md")
    _review(root, "04-implementation.md")
    _triage(root, "02-implementation-owner.md", "03-validation.md", "04-implementation.md",
            to=_to("round"))

    result = _in_clone(root, view=_clone_view(root))

    assert (result["step"], result["round"]) == ("owner", ["3"])


def test_a_change_in_the_workspace_keeps_the_reading_first(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root)

    assert _from_workspace(root, branch=f"feat/{CHANGE}")["step"] == "round-view"


# A repeat pass in a clone, read beside its validation and review.

def test_a_repeat_pass_in_a_clone_is_read_beside_its_validation_and_review(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root)
    _first_pass(root, "01-validation.md", "02-implementation-owner.md")

    validating = _in_clone(root)
    _record(root, "04-validation.md", text=_validation(HEAD))
    _log(root, "validate", _done(_to("review", "implementation")))
    _review(root, "05-implementation.md", reviewed=HEAD)
    unread = _in_clone(root)
    first_pass_view = _in_clone(root, view=_clone_view(root))
    _record(root, "06-implementation-owner.md")
    read = _in_clone(root)

    assert (validating["step"], validating["reading"], validating["base"]) == (
        "validate", True, "e" * 40)
    assert validating["workspace"] == str(WORKSPACE)
    assert (unread["step"], unread["base"], unread["workspace"]) == (
        "round-view", "e" * 40, str(WORKSPACE))
    # A view over the round's own base is an earlier pass's, not this one's.
    assert first_pass_view["step"] == "owner" and "earlier round" in first_pass_view["reason"]
    assert read["step"] == "triage"


def test_a_repeat_pass_with_no_fix_has_nothing_to_read(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root)
    _first_pass(root, "01-validation.md", "02-implementation-owner.md", reviewed=HEAD)

    result = _in_clone(root)
    _review(root, "04-implementation.md", reviewed=HEAD)

    assert (result["step"], "reading" in result) == ("review", False)
    assert _in_clone(root)["step"] == "triage"


def test_a_first_pass_read_beside_its_review_does_not_answer_for_the_fix(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root)
    # In a clone the owner's answer on the first pass may land after its review.
    _record(root, "02-validation.md", text=_validation("e" * 40))
    _review(root, "03-implementation.md", reviewed="e" * 40)
    _record(root, "04-implementation-owner.md")
    _triage(root, "02-validation.md", "03-implementation.md", "04-implementation-owner.md",
            to=_to("review", "implementation"))
    _saved_earlier(root, "02-validation.md", "03-implementation.md",
                   "04-implementation-owner.md", "03-implementation.triage.md")

    result = _in_clone(root)

    assert (result["step"], result["reading"], result["base"]) == ("validate", True, "e" * 40)


def test_a_view_over_an_abbreviated_base_is_the_passs_own(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root)
    _first_pass(root, "01-validation.md", "02-implementation-owner.md", reviewed="e" * 12)
    _record(root, "04-validation.md", text=_validation(HEAD))
    _review(root, "05-implementation.md", reviewed=HEAD)
    view = rounds.View(CHANGE, f"feat/{CHANGE}", "e" * 40, HEAD, clone=str(root))

    result = _in_clone(root, view=view)

    assert result["step"] == "owner" and "save their answer" in result["reason"]


def test_a_repeat_pass_that_advances_moves_on(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root)
    _first_pass(root, "01-validation.md", "02-implementation-owner.md")
    _record(root, "04-implementation-owner.md")
    _record(root, "05-validation.md", text=_validation(HEAD))
    _review(root, "06-implementation.md", reviewed=HEAD)
    _triage(root, "04-implementation-owner.md", "05-validation.md", "06-implementation.md",
            to=_to("round"))

    result = _in_clone(root)

    # The next round, which no plan maps here, so the owner agrees it.
    assert (result["step"], result["round"]) == ("owner", ["3"])


def test_a_third_pass_is_read_over_the_second_passs_review(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root)
    _first_pass(root, "01-validation.md", "02-implementation-owner.md")
    _first_pass(root, "04-implementation-owner.md", "05-validation.md",
                reviewed="f" * 40, review="06-implementation.md")

    result = _in_clone(root)

    assert (result["step"], result["base"]) == ("validate", "f" * 40)


def test_a_failed_fix_validation_before_the_repeat_review_goes_to_the_owner(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _committed_round(root)
    _first_pass(root, "01-validation.md", "02-implementation-owner.md")
    _record(root, "04-validation.md", text=_validation(HEAD, "failed"))

    result = _in_clone(root)

    # A triage names a review among what it triaged, so the failed validation alone
    # is not triaged: the guard it failed names the owner.
    assert (result["step"], result["validation"], result["target"]) == (
        "owner", "failed", {"step": "review", "kind": "implementation"})


# The clone found by `clone_of` and the workspace's view read through the clone's
# `workspace` remote, in real Git repositories.

def test_a_clone_and_the_workspaces_view_are_read_from_git(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.invalid")
    work = _repository(tmp_path / "work", "in implementation")
    shutil.rmtree(_reviews(work))
    (work / ".gitignore").write_text("reviews/\n.claude/settings.local.json\n", "utf-8")
    _git(tmp_path, "init", "-q", "--bare", "-b", "dev", str(tmp_path / "origin.git"))
    _git(work, "init", "-q", "-b", "dev")
    _commit_all(work, "the change's proposal and plan")
    _git(work, "remote", "add", "origin", str(tmp_path / "origin.git"))
    _git(work, "push", "-q", "origin", "dev")

    def spawned(command, cwd: Path, log: Path, status: Path) -> int:
        status.write_text("0\n", "utf-8")
        return os.getpid()

    clone = clones.create(work, CHANGE, spawn=spawned).clone
    base = _git(clone, "rev-parse", "HEAD")
    note_round(log_path(clone, CHANGE), [[2]], "owner", commit=base)
    _check(clone, SECOND_DONE)
    _commit_all(clone, "section 2")

    from_workspace = nxt.compute(work, CHANGE)
    committed = nxt.compute(clone, CHANGE)
    _record(clone, "01-validation.md", text=_validation(_git(clone, "rev-parse", "HEAD")))
    _record(clone, "02-implementation.md")
    unread = nxt.compute(clone, CHANGE)
    rounds.start(work, CHANGE, runs=lambda _: [])
    reading = nxt.compute(clone, CHANGE)

    assert (from_workspace["step"], from_workspace["clone"]) == ("in-clone", str(clone))
    assert (committed["step"], committed["reading"], committed["workspace"]) == (
        "validate-and-review", True, str(work.resolve()))
    assert unread["step"] == "round-view"
    assert (reading["step"], reading["round_view"]) == ("owner", CHANGE)
