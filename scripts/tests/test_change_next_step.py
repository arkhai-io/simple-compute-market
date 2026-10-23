"""The next step of a change is computed from its files and its workflow log."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from change_workflow.log import log_path, note_orchestrator, note_round, record_outcome
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
# The review kind the records below are named for.
KIND = "design"
HEAD = "0123456789abcdef0123456789abcdef01234567"
TASKS = """## 1. First

- [x] 1.1 Done.

## 2. Second

- [ ] 2.1 Open.

## 3. Third

- [ ] 3.1 Open.

## 4. Closeout

- [ ] 4.1 Archive.
"""
FINISHED = {"outcome": "finished", "message": "Done.", "next": "next"}
QUESTION = {"outcome": "question", "message": "Which option?", "awaiting": "a choice"}


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


def _record(root: Path, name: str, *, triage: str | None = None, text: str = "x",
            reviewed: str | None = None) -> None:
    if reviewed is not None:
        text = f"{text}\n<!-- reviewed-commit: {reviewed} -->\n"
    (_reviews(root) / name).write_text(text, "utf-8")
    if triage is not None:
        (_reviews(root) / name.replace(".md", ".triage.md")).write_text(
            f"# Triage\n\n### F1 — x\n\n## Gate\n\n{triage}\n", "utf-8")


def _validation(commit: str = HEAD, result: str = "passed") -> str:
    return f"# Validation\n\n- **Commit:** {commit} on feat/x\n- **Result:** {result}\n"


def _log(root: Path, step_name: str, outcome: dict, **extra) -> dict:
    return record_outcome(log_path(root, CHANGE), step_name, outcome, session="s",
                          commit=HEAD, extra=extra or None)


def _decide(root: Path, decision: str = "decided", **fields) -> dict:
    return note_orchestrator(log_path(root, CHANGE), decision, "a reason", **fields)


def _round(root: Path, sections, after: int | None = None) -> None:
    note_round(log_path(root, CHANGE), sections, "owner", after)


# What HEAD changed since a reviewed commit: a fix in code, unless a test says otherwise.
FIX = ["scripts/change_next_step.py"]
RECORDS_ONLY = [f"openspec/changes/{CHANGE}/interventions.jsonl"]


def _next(root: Path, *, uncommitted: bool = False, changed: list[str] | None = FIX) -> dict:
    return nxt.compute(root, CHANGE, head=lambda _: HEAD, view=lambda _: None,
                       uncommitted=lambda *_: uncommitted, changed_since=lambda *_: changed)


def _check(root: Path, tasks: str) -> None:
    (change_directory(root, CHANGE) / nxt.TASKS_FILE).write_text(tasks, "utf-8")


ALL_WORK_DONE = TASKS.replace("- [ ] 2.1", "- [x] 2.1").replace("- [ ] 3.1", "- [x] 3.1")


# Design and planning.

def test_ready_for_design_runs_design(tmp_path: Path) -> None:
    assert _next(_repository(tmp_path, "ready for design"))["step"] == "design"


def test_an_untriaged_design_review_is_triaged(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _record(root, f"01-{KIND}.md")

    assert _next(root) == {"step": "triage", "reason": f"01-{KIND}.md has no triage"}


def test_a_finished_design_discussion_goes_to_its_review(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _log(root, "design", FINISHED)

    assert (_next(root)["step"], _next(root)["kind"]) == ("review", "design")


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
    root = _repository(tmp_path, "in implementation",
                       tasks=TASKS.replace("## 3. Third\n\n", ""))

    result = _next(root)

    assert result["step"] == "unclassified"
    assert "3.1 sits under `## 2. Second`" in result["reason"]


def test_a_legacy_design_gate_not_passed_goes_to_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _log(root, "design", FINISHED)
    _record(root, f"01-{KIND}.md", triage="Not passed: F1 needs another round.")
    _log(root, "triage", FINISHED)

    assert _next(root)["step"] == "owner"


def test_ready_for_planning_runs_planning(tmp_path: Path) -> None:
    assert _next(_repository(tmp_path, "ready for planning"))["step"] == "plan"


def test_a_plan_that_finished_without_setting_its_status_goes_to_the_owner(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in planning")
    _log(root, "plan", FINISHED)

    result = _next(root)

    assert result["step"] == "owner" and "left the change in planning" in result["reason"]
    assert "resume" not in result


def test_planning_in_progress_continues(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in planning")
    _log(root, "design", FINISHED)

    assert _next(root)["step"] == "plan"


# Implementation rounds.

def test_implementation_waits_for_the_owner_to_agree_a_round(tmp_path: Path) -> None:
    result = _next(_repository(tmp_path, "ready for implementation"))

    assert (result["step"], result["round"]) == ("owner", ["2", "3"])


def test_the_agreed_rounds_next_session_is_implemented(tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for implementation")
    _round(root, [[1], [2, 3]])

    result = _next(root)

    assert (result["step"], result["sections"]) == ("implement", [2, 3])


def test_an_implementation_returning_to_design_waits_for_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    _log(root, "implement", {"outcome": "returned", "message": "Needs a decision.",
                             "return_to": "design", "evidence": "the notes"}, sections=[2])

    result = _next(root)

    assert (result["step"], result["return_to"]) == ("owner", "design")


def test_a_committed_round_is_read_by_the_owner_first(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _record(root, f"01-{KIND}.md", triage="Passed.")
    _round(root, [[2]])
    _check(root, TASKS.replace("- [ ] 2.1", "- [x] 2.1"))

    assert _next(root)["step"] == "round-view"


@pytest.mark.parametrize("records,expected", [
    (["02-implementation-owner.md"], ("validate-and-review", "implementation")),
    (["02-implementation-owner.md", "03-validation.md"], ("review", "implementation")),
    (["02-implementation-owner.md", "03-implementation.md"], ("validate", None)),
])
def test_after_the_round_view_validation_and_review_run(
        tmp_path: Path, records: list[str], expected: tuple) -> None:
    root = _repository(tmp_path, "in implementation")
    _record(root, f"01-{KIND}.md", triage="Passed.")
    _round(root, [[2]])
    _check(root, TASKS.replace("- [ ] 2.1", "- [x] 2.1"))
    for name in records:
        _record(root, name)

    result = _next(root)

    assert (result["step"], result.get("kind")) == expected


def test_reviews_and_validation_await_triage(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    _check(root, TASKS.replace("- [ ] 2.1", "- [x] 2.1"))
    _record(root, "01-validation.md", text=_validation())
    _record(root, "02-implementation.md")

    result = _next(root)

    assert result == {"step": "triage",
                      "reason": "01-validation.md, 02-implementation.md have no triage"}


def test_a_triaged_round_with_fixes_since_its_validation_is_validated_again(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    _check(root, TASKS.replace("- [ ] 2.1", "- [x] 2.1"))
    _record(root, "01-validation.md", text=_validation("f" * 40), triage="Not a gate.")
    _record(root, "02-implementation.md", triage="Passed.")

    result = _next(root)

    assert result["step"] == "validate" and "not HEAD" in result["reason"]


def test_a_triaged_round_with_sections_left_waits_for_the_next_round(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    _check(root, TASKS.replace("- [ ] 2.1", "- [x] 2.1"))
    _record(root, "01-validation.md", text=_validation(), triage="Not a gate.")
    _record(root, "02-implementation.md", triage="Passed.")

    result = _next(root)

    assert (result["step"], result["round"]) == ("owner", ["3"])


def test_the_last_round_triaged_goes_to_the_pre_closeout_review(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2, 3]])
    _check(root, ALL_WORK_DONE)
    _record(root, "01-validation.md", text=_validation(), triage="Not a gate.")
    _record(root, "02-implementation.md", triage="Passed.")

    assert (_next(root)["step"], _next(root)["kind"]) == ("review", "pre-closeout")


def test_an_untriaged_pre_closeout_review_is_triaged(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2, 3]])
    _check(root, ALL_WORK_DONE)
    _record(root, "01-validation.md", text=_validation(), triage="Not a gate.")
    _record(root, "02-implementation.md", triage="Passed.")
    _record(root, "03-pre-closeout.md")

    assert _next(root)["step"] == "triage"


def _failed_pre_closeout(tmp_path: Path, *, reviewed: str, validated: str = HEAD) -> Path:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2, 3]])
    _check(root, ALL_WORK_DONE)
    _record(root, "01-validation.md", text=_validation(validated), triage="Not a gate.")
    _record(root, "02-implementation.md", triage="Passed.")
    _record(root, "03-pre-closeout.md", triage="Not passed: F2 first.", reviewed=reviewed)
    return root


def test_a_legacy_pre_closeout_gate_not_passed_goes_to_the_owner(tmp_path: Path) -> None:
    root = _failed_pre_closeout(tmp_path, reviewed=HEAD)

    result = _next(root)

    assert result["step"] == "owner" and "03-pre-closeout" in result["reason"]


def _next_section(token: str) -> str:
    return f"# Triage\n\n### F1 — x\n\n## Next\n\n{token}\n"


def _triaged(root: Path, name: str, next_words: str, reviewed: str | None = None) -> None:
    """A review record whose triage file ends with `## Next`."""
    _record(root, name, reviewed=reviewed)
    (_reviews(root) / name.replace(".md", ".triage.md")).write_text(
        _next_section(next_words), "utf-8")


# Another round runs the review of the same kind again: for pre-closeout, once
# the fix commit is validated; with no fix, on the same commit.

def test_another_pre_closeout_round_is_validated_then_reviewed_again(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2, 3]])
    _check(root, ALL_WORK_DONE)
    _record(root, "01-validation.md", text=_validation("e" * 40), triage="Not a gate.")
    _triaged(root, "02-implementation.md", "Advance")
    _triaged(root, "03-pre-closeout.md", "Another round — F2 changes the interface.",
             reviewed="e" * 40)

    unvalidated = _next(root)
    _record(root, "04-validation.md", text=_validation(HEAD))
    validated = _next(root)

    assert unvalidated["step"] == "validate" and "not HEAD" in unvalidated["reason"]
    assert (validated["step"], validated["kind"]) == ("review", "pre-closeout")
    assert "another round" in validated["reason"]


def test_another_round_with_no_fix_reviews_the_same_commit_again(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2, 3]])
    _check(root, ALL_WORK_DONE)
    _record(root, "01-validation.md", text=_validation(), triage="Not a gate.")
    _triaged(root, "02-implementation.md", "Another round", reviewed=HEAD)

    assert (_next(root)["step"], _next(root)["kind"]) == ("review", "implementation")


def test_another_closeout_round_is_reviewed_again(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _triaged(root, "05-closeout.md", "Another round", reviewed="e" * 40)

    assert (_next(root)["step"], _next(root)["kind"]) == ("review", "closeout")


def test_a_legacy_closeout_gate_not_passed_goes_to_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _record(root, "05-closeout.md", triage="Not passed.", reviewed="e" * 40)

    assert _next(root)["step"] == "owner"


# `## Next`: the token alone routes; a triage file without it is in progress.

@pytest.mark.parametrize("status,name", [("in design", f"01-{KIND}.md"),
                                         ("in closeout", "05-closeout.md")])
def test_a_triage_without_next_is_in_progress(tmp_path: Path, status: str, name: str) -> None:
    root = _repository(tmp_path, status, archived=status == "in closeout")
    _record(root, name)
    (_reviews(root) / name.replace(".md", ".triage.md")).write_text(
        "# Triage\n\n### F1 — x\n\n- **Owner disposition:** accepted\n", "utf-8")

    result = _next(root)

    assert result["step"] == "triage" and "in progress" in result["reason"]


@pytest.mark.parametrize("words,step_name", [
    ("Advance — the owner: \"advance.\"", "plan"),
    ("Another round — D3 changed.", "review"),
    ("Passed, I think", "owner"),
])
def test_a_design_triage_routes_on_its_next_token(tmp_path: Path, words: str,
                                                   step_name: str) -> None:
    root = _repository(tmp_path, "in design")
    _log(root, "design", FINISHED)
    record_outcome(log_path(root, CHANGE), "review", FINISHED, session="codex:x",
                   commit=HEAD, extra={"kind": "design", "record": f"01-{KIND}.md"})
    _triaged(root, f"01-{KIND}.md", words)
    _log(root, "triage", FINISHED)

    assert _next(root)["step"] == step_name


def test_a_next_token_on_the_heading_line_is_read(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _record(root, f"01-{KIND}.md")
    (_reviews(root) / f"01-{KIND}.triage.md").write_text("# Triage\n\n## Next: Advance\n",
                                                          "utf-8")

    assert _next(root)["step"] == "plan"


def test_a_legacy_passed_gate_reads_as_advance(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _record(root, f"01-{KIND}.md", triage="Passed — Advance. The owner: \"advance.\"")

    assert _next(root)["step"] == "plan"


# An implementation round advances on a passing validation of its fix commit.

PLAN = {"outcome": "finished", "message": "Planned.", "next": "implementation",
        "rounds": [[[2]], [[3]]]}


def _advanced_round(root: Path, validated: str = HEAD, result: str = "passed") -> None:
    _log(root, "plan", PLAN)
    _round(root, [[2]])
    _check(root, TASKS.replace("- [ ] 2.1", "- [x] 2.1"))
    _record(root, "01-validation.md", text=_validation("e" * 40), triage="Evidence.")
    _triaged(root, "02-implementation.md", "Advance", reviewed="e" * 40)
    if validated:
        _record(root, "03-validation.md", text=_validation(validated, result))


def test_an_advancing_round_validates_its_fix_commit_then_starts_the_next_planned_round(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _advanced_round(root, validated="")

    unvalidated = _next(root)
    _record(root, "03-validation.md", text=_validation(HEAD))
    validated = _next(root)

    assert unvalidated["step"] == "validate"
    assert validated == {"step": "round", "sections": [[3]], "by": "plan",
                         "reason": validated["reason"]}


def test_an_inconclusive_validation_of_the_fix_commit_goes_to_the_owner(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _advanced_round(root, result="inconclusive")

    result = _next(root)

    assert (result["step"], result["validation"]) == ("owner", "inconclusive")


def test_the_last_planned_round_advancing_goes_to_the_pre_closeout_review(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _advanced_round(root)
    _check(root, ALL_WORK_DONE)

    assert (_next(root)["step"], _next(root)["kind"]) == ("review", "pre-closeout")


def test_a_pre_closeout_triage_that_advances_goes_to_closeout_once_head_is_validated(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation", tasks=ALL_WORK_DONE)
    _triaged(root, "03-pre-closeout.md", "Advance", reviewed=HEAD)

    unvalidated = _next(root)
    _record(root, "04-validation.md", text=_validation(HEAD))
    validated = _next(root)

    assert unvalidated["step"] == "validate"
    assert validated["step"] == "closeout"


# A closeout triage that advances: archive cleanup, after a validation when a
# correction changed more than documentation.

def test_a_closeout_correction_awaits_validation(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _triaged(root, "05-closeout.md", "Advance", reviewed="e" * 40)

    unvalidated = _next(root, changed=[".agents/skills/change-triage/SKILL.md"])
    _record(root, "06-validation.md", text=_validation(HEAD))
    validated = _next(root, changed=FIX)

    assert unvalidated["step"] == "validate" and ".agents/" in unvalidated["reason"]
    assert validated["step"] == "archive-cleanup"


def test_a_documentation_correction_at_closeout_needs_no_validation(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _triaged(root, "05-closeout.md", "Advance", reviewed="e" * 40)

    result = _next(root, changed=["docs/agents/change-workflow.md",
                                  "openspec/specs/change-workflow/spec.md"])

    assert result["step"] == "archive-cleanup"


def test_the_owners_waiver_directs_archive_cleanup_past_a_missing_validation(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _triaged(root, "05-closeout.md", "Advance", reviewed="e" * 40)

    _decide(root, "waive archive cleanup's validation", by="owner",
            next_step="archive-cleanup")
    directed = _next(root, changed=FIX)
    _log(root, "archive-cleanup", QUESTION)
    asked = _next(root, changed=FIX)
    _log(root, "archive-cleanup", FINISHED)
    ran = _next(root, changed=FIX)

    assert directed["step"] == "archive-cleanup" and "waive" in directed["reason"]
    # Archive cleanup's own check asks, naming the paths, and records the waiver.
    assert asked["step"] == "owner"
    # Run once, the direction is spent; validation is the default again.
    assert ran["step"] == "validate"


# The plan's mapping of rounds.

def test_a_two_round_plan_names_the_second_round_only_after_the_first_advanced(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for implementation")
    _log(root, "plan", PLAN)

    first = _next(root)
    _round(root, [[2]])
    implementing = _next(root)
    _check(root, TASKS.replace("- [ ] 2.1", "- [x] 2.1"))
    viewing = _next(root)

    assert (first["step"], first["sections"], first["by"]) == ("round", [[2]], "plan")
    assert (implementing["step"], implementing["sections"]) == ("implement", [2])
    assert viewing["step"] == "round-view"


def test_an_amended_plan_governs_the_rounds_it_maps(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _log(root, "plan", PLAN)
    _log(root, "plan", {**PLAN, "rounds": [[[2], [3]]]})

    result = _next(root)

    assert (result["step"], result["sections"]) == ("round", [[2], [3]])


@pytest.mark.parametrize("plan", [FINISHED, {**PLAN, "rounds": [[[3]]]}])
def test_a_first_open_section_no_planned_round_names_goes_to_the_owner(
        tmp_path: Path, plan: dict) -> None:
    root = _repository(tmp_path, "ready for implementation")
    _log(root, "plan", plan)

    result = _next(root)

    assert (result["step"], result["round"]) == ("owner", ["2", "3"])
    assert "agree the next implementation round" in result["reason"]


def test_a_later_unmapped_section_does_not_hold_the_next_planned_round(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for implementation")
    _log(root, "plan", {**PLAN, "rounds": [[[2]]]})

    assert (_next(root)["step"], _next(root)["sections"]) == ("round", [[2]])


def test_a_closeout_section_a_plan_maps_is_left_out_of_its_round(tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for implementation")
    _log(root, "plan", {**PLAN, "rounds": [[[2], [3, 4]]]})

    planned = _next(root)
    _round(root, [[2], [3, 4]])
    _check(root, ALL_WORK_DONE)
    recorded = _next(root)

    assert planned["sections"] == [[2], [3]]
    # A round recorded with the closeout section is not held open by it.
    assert recorded["step"] == "round-view"


def test_a_planned_round_naming_a_section_the_task_list_lacks_goes_to_the_owner(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for implementation")
    _log(root, "plan", {**PLAN, "rounds": [[[2, 9]], [[3]]]})

    result = _next(root)

    assert (result["step"], result["round"]) == ("owner", ["2", "3"])
    assert "task list lacks: 9" in result["reason"] and "sections" not in result


def test_a_complete_section_a_plan_maps_is_left_out_of_its_round(tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for implementation")
    _log(root, "plan", {**PLAN, "rounds": [[[1], [1, 2], [3]]]})

    assert _next(root)["sections"] == [[2], [3]]


# `## Next` belongs to the bare heading, and to the review triaged with the round's.

def test_a_next_round_heading_is_not_next(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _record(root, f"01-{KIND}.md")
    (_reviews(root) / f"01-{KIND}.triage.md").write_text(
        "# Triage\n\n## Next round\n\nRe-review D3.\n\n## Gate\n\nPassed.\n", "utf-8")

    assert _next(root)["step"] == "plan"


def test_two_reviews_triaged_together_follow_the_one_with_next(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _log(root, "plan", PLAN)
    _round(root, [[2]])
    _check(root, TASKS.replace("- [ ] 2.1", "- [x] 2.1"))
    _record(root, "01-validation.md", text=_validation(), triage="Evidence.")
    _record(root, "02-implementation.md")
    _record(root, "03-implementation-external.md")
    # Triaged together, after both were published: the token is in one file only.
    (_reviews(root) / "03-implementation-external.triage.md").write_text(
        "# Triage\n\nEvidence for the round triaged in 02.\n", "utf-8")
    (_reviews(root) / "02-implementation.triage.md").write_text(_next_section("Advance"),
                                                                 "utf-8")

    assert _next(root)["step"] == "round"


def test_an_earlier_rounds_token_does_not_decide_a_triage_in_progress(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    _check(root, TASKS.replace("- [ ] 2.1", "- [x] 2.1"))
    _record(root, "01-validation.md", text=_validation(), triage="Evidence.")
    _triaged(root, "02-implementation.md", "Another round", reviewed=HEAD)
    _record(root, "03-implementation.md", reviewed=HEAD)
    (_reviews(root) / "03-implementation.triage.md").write_text("# Triage\n", "utf-8")
    # The earlier round was triaged before the latest review was published. Two
    # files written back to back often share a modification time, which reads as
    # triaged together, so the order is stated rather than left to the clock.
    published = (_reviews(root) / "03-implementation.md").stat().st_mtime_ns
    earlier = published - 1_000_000_000
    os.utime(_reviews(root) / "02-implementation.triage.md", ns=(earlier, earlier))

    result = _next(root)

    assert result["step"] == "triage" and "in progress" in result["reason"]


# Another round runs the review again, validating only a fix committed since.

def test_another_implementation_round_with_a_fix_is_validated_first(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    _check(root, TASKS.replace("- [ ] 2.1", "- [x] 2.1"))
    _record(root, "01-validation.md", text=_validation("e" * 40), triage="Evidence.")
    _triaged(root, "02-implementation.md", "Another round", reviewed="e" * 40)

    unvalidated = _next(root)
    _record(root, "03-validation.md", text=_validation(HEAD))
    validated = _next(root)

    assert unvalidated["step"] == "validate"
    assert (validated["step"], validated["kind"]) == ("review", "implementation")


def test_another_round_with_no_fix_runs_whatever_the_validation_said(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    _check(root, TASKS.replace("- [ ] 2.1", "- [x] 2.1"))
    _record(root, "01-validation.md", text=_validation(HEAD, "inconclusive"),
            triage="Evidence.")
    _triaged(root, "02-implementation.md", "Another round", reviewed=HEAD)

    assert (_next(root)["step"], _next(root)["kind"]) == ("review", "implementation")


def test_a_code_fix_from_an_earlier_closeout_round_is_validated_before_cleanup(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _triaged(root, "05-closeout.md", "Another round", reviewed="a" * 40)
    # The latest review read the fix commit, HEAD: only the archive commit shows it.
    _triaged(root, "07-closeout.md", "Advance", reviewed=HEAD)

    assert _next(root)["step"] == "validate"


def test_with_no_round_an_inconclusive_validation_goes_to_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _check(root, ALL_WORK_DONE)
    _record(root, "01-validation.md", text=_validation(HEAD, "inconclusive"))

    result = _next(root)

    assert (result["step"], result["validation"]) == ("owner", "inconclusive")


def test_the_owner_may_direct_a_repeat_review_with_no_fix(tmp_path: Path) -> None:
    root = _failed_pre_closeout(tmp_path, reviewed=HEAD)
    _decide(root, "review again", by="owner", next_step="review", kind="pre-closeout")

    directed = _next(root)
    record_outcome(log_path(root, CHANGE), "review", FINISHED, session="codex:x",
                   commit=HEAD, extra={"kind": "pre-closeout", "record": "04-pre-closeout.md"})
    _record(root, "04-pre-closeout.md", reviewed=HEAD)
    after = _next(root)

    assert (directed["step"], directed["kind"]) == ("review", "pre-closeout")
    assert "review again" in directed["reason"]
    assert after["step"] == "triage"


# Closeout.

def test_ready_for_closeout_runs_closeout(tmp_path: Path) -> None:
    assert _next(_repository(tmp_path, "ready for closeout"))["step"] == "closeout"


def test_closeout_not_yet_archived_continues(tmp_path: Path) -> None:
    assert _next(_repository(tmp_path, "in closeout"))["step"] == "closeout"


def test_an_archived_change_has_its_closeout_review(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)

    assert (_next(root)["step"], _next(root)["kind"]) == ("review", "closeout")


def test_an_untriaged_closeout_review_is_triaged(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _record(root, "05-closeout.md")

    assert _next(root)["step"] == "triage"


def test_a_passed_closeout_gate_goes_to_archive_cleanup(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _record(root, "05-closeout.md", triage="Passed (\"Yes, pass it.\").")

    assert _next(root)["step"] == "archive-cleanup"


def test_an_archived_change_is_done(tmp_path: Path) -> None:
    root = _repository(tmp_path, "archived", archived=True)

    assert _next(root)["step"] == "done"


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


# What the files say over the log, and what cannot be classified.

def test_a_status_set_back_by_hand_is_followed_and_reported(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _log(root, "plan", FINISHED)

    result = _next(root)

    assert result["step"] == "design"
    assert "the files decide" in result["disagreement"]


def test_an_open_round_view_waits_for_the_owner_before_anything_else(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    view = rounds.View(CHANGE, "feat/x", "a" * 40, HEAD)

    result = nxt.compute(root, CHANGE, head=lambda _: HEAD, view=lambda _: view,
                         uncommitted=lambda *_: False)

    assert (result["step"], result["round_view"]) == ("owner", CHANGE)
    assert "make round-done" in result["reason"]


@pytest.mark.parametrize("setup,reason", [
    (lambda root: (root / "openspec/changes/README.md").write_text("", "utf-8"), "has no row"),
    (lambda root: _check(root, "No sections.\n"), "has no sections"),
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
                       uncommitted=lambda *_: False)["step"] == "unclassified"


def test_a_malformed_log_is_unclassified(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    (_reviews(root) / "workflow.jsonl").write_text("not json\n", "utf-8")

    result = _next(root)

    assert result["step"] == "unclassified" and "workflow.jsonl:1" in result["reason"]


def test_the_command_prints_the_result(tmp_path: Path,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path, "ready for design")

    assert nxt.main([CHANGE], root=root) == 0
    assert json.loads(capsys.readouterr().out)["step"] == "design"
    assert nxt.main(["missing"], root=root) == 1


def test_plain_prints_the_result_as_lines(tmp_path: Path,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path, "in design")
    run = _log(root, "design", {**QUESTION, "denials": [{"tool_name": "Bash"}]})

    assert nxt.main([CHANGE, "--plain"], root=root) == 0

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
    _git(root, "init", "-q", "-b", "feat/x")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    base = _git(root, "rev-parse", "HEAD")
    _check(root, TASKS.replace("- [ ] 2.1", "- [x] 2.1"))
    _git(root, "commit", "-qam", "section 2")

    rounds.start(root, CHANGE, base=base, e2e=False)
    during = nxt.compute(root, CHANGE)
    rounds.done(root)
    after = nxt.compute(root, CHANGE)

    assert (during["step"], during["round_view"]) == ("owner", CHANGE)
    assert after["step"] == "round-view"


# A step whose latest run waits on the owner is never run afresh.

STOPPED = {"outcome": "stopped", "message": "Denied.", "reason": "denied",
           "denials": [{"tool_name": "Bash"}]}
# A run that ended without an outcome, as the wrapper logs it: no denial to read.
CRASHED = {"outcome": "stopped", "message": "exit 1", "reason": "exit 1", "denials": []}


def _implemented_round(root: Path) -> None:
    _round(root, [[2]])
    _check(root, TASKS.replace("- [ ] 2.1", "- [x] 2.1"))


def test_a_triage_question_waits_for_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _implemented_round(root)
    _record(root, "01-validation.md", text=_validation())
    _record(root, "02-implementation.md")
    _log(root, "triage", QUESTION)

    result = _next(root)

    assert (result["step"], result["resume"]) == ("owner", "triage")


def test_a_validation_question_waits_beside_a_finished_review(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _implemented_round(root)
    _record(root, "02-implementation-owner.md")
    _log(root, "validate", {**QUESTION, "awaiting": "environmental remedy"})
    record_outcome(log_path(root, CHANGE), "review", FINISHED, session="codex:x",
                   commit=HEAD, extra={"kind": "implementation"})

    result = _next(root)

    assert (result["step"], result["resume"], result["awaiting"]) == (
        "owner", "validate", "environmental remedy")


def test_a_stopped_run_waits_until_a_decision_resolves_it(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _implemented_round(root)
    _record(root, "02-implementation-owner.md")
    _record(root, "03-validation.md", text=_validation())
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
    _implemented_round(root)
    _record(root, "02-implementation-owner.md")
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
    run = _log(root, "implement", {**FINISHED, "denials": [{"tool_name": "Bash"}]},
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
    run = _log(root, "implement", {**FINISHED, "denials": [{"tool_name": "Bash"}]},
               sections=[2])
    _decide(root, "gap: proposed Bash(cat *)", resolves=run["seq"])

    assert _next(root)["step"] == "implement"


# A run can be denied a call and still ask or propose a return: its denials are
# read first, and its question or return waits after the reading as it would
# without the denial.

def test_a_question_with_denials_waits_for_its_reading_then_its_answer(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _implemented_round(root)
    _record(root, "02-implementation-owner.md")
    run = _log(root, "validate", {**QUESTION, "awaiting": "environmental remedy",
                                  "denials": [{"tool_name": "Bash"}]})

    unread = _next(root)
    _decide(root, "gap: proposed Bash(gh run view *)", reads=run["seq"])
    read = _next(root)
    _log(root, "validate", FINISHED)
    _record(root, "03-validation.md", text=_validation())
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
    run = _log(root, "implement", {"outcome": "returned", "message": "Needs a decision.",
                                   "return_to": "design", "evidence": "the notes",
                                   "denials": [{"tool_name": "Bash"}]}, sections=[2])

    unread = _next(root)
    _decide(root, "workaround: none", reads=run["seq"])
    read = _next(root)
    _decide(root, "return to design confirmed", by="owner", resolves=run["seq"],
            next_step="design")
    confirmed = _next(root)

    assert unread["step"] == "owner" and unread["denials"] == [{"tool_name": "Bash"}]
    assert "return_to" not in unread
    assert (read["step"], read["return_to"]) == ("owner", "design")
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
    _implemented_round(root)
    _record(root, "02-implementation-owner.md")
    _record(root, "03-validation.md", text=_validation())
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
    _implemented_round(root)
    _record(root, "02-implementation-owner.md")
    run = _log(root, "validate", STOPPED)

    _decide(root, "gap: proposed Bash(make lock) as a one-run grant", reads=run["seq"])
    read = _next(root)
    _log(root, "validate", FINISHED, granted=["Bash(make lock)"])
    resumed = _next(root)

    assert (read["step"], read["seq"]) == ("owner", run["seq"]) and "stopped" in read["reason"]
    assert resumed["step"] != "owner"


def test_a_decision_that_resolves_a_question_ends_its_wait(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _implemented_round(root)
    _record(root, "02-implementation-owner.md")
    run = _log(root, "validate", {**QUESTION, "denials": [{"tool_name": "Bash"}]})
    _decide(root, "validate afresh", by="owner", resolves=run["seq"])

    assert _next(root)["step"] == "validate-and-review"


def test_a_confirmed_return_routes_to_the_step_returned_to(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    run = _log(root, "implement", {"outcome": "returned", "message": "Needs a decision.",
                                   "return_to": "design", "evidence": "the notes"},
               sections=[2])

    unconfirmed = _next(root)
    _decide(root, "return to design confirmed", by="owner", resolves=run["seq"],
            next_step="design")
    confirmed = _next(root)

    assert (unconfirmed["step"], unconfirmed["return_to"]) == ("owner", "design")
    assert confirmed["step"] == "design" and "confirmed" in confirmed["reason"]


def test_a_directed_step_that_has_run_is_no_longer_directed(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    run = _log(root, "implement", {"outcome": "returned", "message": "Needs a decision.",
                                   "return_to": "design", "evidence": "the notes"})
    _decide(root, "return to design confirmed", by="owner", resolves=run["seq"],
            next_step="design")
    _log(root, "design", FINISHED)

    assert (_next(root)["step"], _next(root)["kind"]) == ("review", "design")


def test_a_round_recorded_after_the_fact_owns_the_records_above_its_after(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _check(root, TASKS.replace("- [ ] 2.1", "- [x] 2.1"))
    _record(root, f"01-{KIND}.md", triage="Passed.")
    _record(root, "02-implementation-owner.md")
    _record(root, "03-validation.md", text=_validation())
    _record(root, "04-implementation.md")

    unrecorded = _next(root)
    _round(root, [[2]], after=1)
    recorded = _next(root)

    assert (unrecorded["step"], unrecorded["round"]) == ("owner", ["3"])
    assert recorded == {"step": "triage",
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
    record_outcome(log_path(root, CHANGE), "review", FINISHED, session="codex:x",
                   commit=HEAD, extra={"kind": "design"})
    _log(root, "triage", CRASHED)
    _round(root, [[2]])

    assert _next(root)["step"] == "implement"


# Unread denials wait whatever the phase: the run that recorded them may be the
# one that moved the change on, and the reading is owed before any step runs.

def test_a_design_triages_denials_are_read_before_planning_starts(tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for planning")
    record_outcome(log_path(root, CHANGE), "review", FINISHED, session="codex:x",
                   commit=HEAD, extra={"kind": "design"})
    run = _log(root, "triage", {**FINISHED, "denials": [{"tool_name": "Bash"}]})

    unread = _next(root)
    _decide(root, "gap: proposed Bash(cat *)", reads=run["seq"])
    read = _next(root)

    assert (unread["step"], unread["seq"], unread["denials"]) == (
        "owner", run["seq"], [{"tool_name": "Bash"}])
    assert "denied 1 tool call" in unread["reason"]
    assert read["step"] == "plan"


def test_a_pre_closeout_triages_denials_are_read_before_closeout_starts(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for closeout")
    record_outcome(log_path(root, CHANGE), "review", FINISHED, session="codex:x",
                   commit=HEAD, extra={"kind": "pre-closeout"})
    run = _log(root, "triage", {**FINISHED, "denials": [{"tool_name": "Bash"}]})

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
    run = _log(root, "plan", {**FINISHED, "denials": [{"tool_name": "Bash"}]})

    unread = _next(root)
    _decide(root, "gap: proposed Bash(cat *)", reads=run["seq"])
    read = _next(root)

    assert (unread["step"], unread["seq"]) == ("owner", run["seq"])
    assert "denied 1 tool call" in unread["reason"]
    assert read["step"] == "owner" and "agree the next implementation round" in read["reason"]


def test_an_earlier_phases_question_with_denials_waits_only_for_their_reading(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for planning")
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


def test_a_return_the_owner_confirmed_no_longer_waits(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _log(root, "implement", {"outcome": "returned", "message": "Needs a decision.",
                             "return_to": "design", "evidence": "the notes"})

    assert _next(root)["step"] == "design"


# The other paths.

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


def test_an_archived_change_whose_row_was_pruned_is_done(tmp_path: Path) -> None:
    root = _repository(tmp_path, "archived", archived=True)
    (root / "openspec/changes/README.md").write_text("", "utf-8")

    assert _next(root)["step"] == "done"


def test_a_round_agreed_after_triage_starts_with_its_own_view(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2, 3]])
    _check(root, ALL_WORK_DONE)
    _record(root, "01-validation.md", text=_validation("f" * 40), triage="Not a gate.")
    _record(root, "02-implementation.md", triage="Passed.")
    _round(root, [[3]])

    result = _next(root)

    assert result["step"] == "round-view"


def test_with_no_round_a_finished_plan_goes_to_pre_closeout_after_validation(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _check(root, ALL_WORK_DONE)
    _record(root, "01-validation.md", text=_validation("f" * 40))

    result = _next(root)

    assert result["step"] == "validate" and "pre-closeout" in result["reason"]


def test_ready_for_implementation_with_an_implemented_round_goes_to_its_view(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "ready for implementation")
    _implemented_round(root)

    assert _next(root)["step"] == "round-view"


def test_an_uncommitted_archive_resumes_closeout(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)

    assert _next(root, uncommitted=True)["step"] == "closeout"


def test_a_closeout_question_waits_for_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _log(root, "closeout", QUESTION)

    assert (_next(root)["step"], _next(root)["resume"]) == ("owner", "closeout")


def test_an_archive_cleanup_that_stopped_waits_for_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _record(root, "05-closeout.md", triage="Passed.")
    _log(root, "archive-cleanup", STOPPED)

    assert _next(root)["step"] == "owner"


@pytest.mark.parametrize("title", ["Closeout", "Plan closeout", "Repository closeout",
                                   "Closeout after review follow-up"])
def test_a_closeout_section_is_known_by_its_title(tmp_path: Path, title: str) -> None:
    root = _repository(tmp_path, "ready for implementation",
                       tasks=ALL_WORK_DONE.replace("## 4. Closeout", f"## 4. {title}"))

    assert _next(root)["step"] in ("review", "validate")


def test_an_external_implementation_review_counts_for_the_round(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _implemented_round(root)
    _record(root, "01-validation.md", text=_validation())
    _record(root, "02-implementation-external.md")

    assert _next(root)["step"] == "triage"
