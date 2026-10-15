"""The next step of a change is computed from its files and its workflow log."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

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
step = sys.modules["run_change_step"]
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
    return step.change_directory(root, CHANGE) / "reviews"


def _record(root: Path, name: str, *, triage: str | None = None, text: str = "x") -> None:
    (_reviews(root) / name).write_text(text, "utf-8")
    if triage is not None:
        (_reviews(root) / name.replace(".md", ".triage.md")).write_text(
            f"# Triage\n\n### F1 — x\n\n## Gate\n\n{triage}\n", "utf-8")


def _validation(commit: str = HEAD, result: str = "passed") -> str:
    return f"# Validation\n\n- **Commit:** {commit} on feat/x\n- **Result:** {result}\n"


def _log(root: Path, step_name: str, outcome: dict, **extra) -> None:
    step.record_outcome(step.log_path(root, CHANGE), step_name, outcome, session="s",
                        commit=HEAD, extra=extra or None)


def _round(root: Path, sections) -> None:
    step.note_round(step.log_path(root, CHANGE), sections, "owner")


def _next(root: Path, *, uncommitted: bool = False) -> dict:
    return nxt.compute(root, CHANGE, head=lambda _: HEAD, view=lambda _: None,
                       uncommitted=lambda *_: uncommitted)


def _check(root: Path, tasks: str) -> None:
    (step.change_directory(root, CHANGE) / nxt.TASKS_FILE).write_text(tasks, "utf-8")


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
    _log(root, "design", QUESTION)

    result = _next(root)

    assert (result["step"], result["resume"], result["awaiting"]) == ("owner", "design",
                                                                      "a choice")
    assert "Which option?" in result["reason"]


def test_a_design_gate_not_passed_returns_to_design(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in design")
    _log(root, "design", FINISHED)
    _record(root, f"01-{KIND}.md", triage="Not passed: F1 needs another round.")
    _log(root, "triage", FINISHED)

    assert _next(root)["step"] == "design"


def test_ready_for_planning_runs_planning(tmp_path: Path) -> None:
    assert _next(_repository(tmp_path, "ready for planning"))["step"] == "plan"


def test_a_written_plan_waits_for_the_owners_acceptance(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in planning")
    _log(root, "plan", FINISHED)

    result = _next(root)

    assert (result["step"], result["resume"]) == ("owner", "plan")
    assert "accepts it" in result["reason"]


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


def test_a_pre_closeout_gate_not_passed_waits_for_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2, 3]])
    _check(root, ALL_WORK_DONE)
    _record(root, "01-validation.md", text=_validation(), triage="Not a gate.")
    _record(root, "02-implementation.md", triage="Passed.")
    _record(root, "03-pre-closeout.md", triage="Not passed: F2 first.")

    result = _next(root)

    assert result["step"] == "owner" and "03-pre-closeout.md" in result["reason"]


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


def test_a_closeout_gate_not_passed_waits_for_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in closeout", archived=True)
    _record(root, "05-closeout.md", triage="Not passed.")

    assert _next(root)["step"] == "owner"


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
    step.record_outcome(step.log_path(root, CHANGE), "review", FINISHED, session="codex:x",
                        commit=HEAD, extra={"kind": "implementation"})

    result = _next(root)

    assert (result["step"], result["resume"], result["awaiting"]) == (
        "owner", "validate", "environmental remedy")


def test_a_stopped_run_waits_until_the_orchestrator_records_its_decision(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _implemented_round(root)
    _record(root, "02-implementation-owner.md")
    _record(root, "03-validation.md", text=_validation())
    step.record_outcome(step.log_path(root, CHANGE), "review", STOPPED, session=None,
                        commit=HEAD, extra={"kind": "implementation"})

    stopped = _next(root)
    step.note_orchestrator(step.log_path(root, CHANGE), "rerun the review",
                           "codex authentication renewed")
    decided = _next(root)

    assert (stopped["step"], stopped["denials"]) == ("owner", [{"tool_name": "Bash"}])
    assert (decided["step"], decided["kind"]) == ("review", "implementation")


def test_a_blocked_step_other_than_design_waits_for_the_owner(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    _round(root, [[2]])
    _log(root, "implement", {"outcome": "blocked", "message": "Needs another change.",
                             "blocked_on": "split-pools"}, sections=[2])

    assert (_next(root)["step"], _next(root)["blocked_on"]) == ("owner", "split-pools")


def test_a_design_reviews_stopped_run_does_not_hold_implementation(tmp_path: Path) -> None:
    root = _repository(tmp_path, "in implementation")
    step.record_outcome(step.log_path(root, CHANGE), "review", STOPPED, session=None,
                        commit=HEAD, extra={"kind": "design"})
    _round(root, [[2]])

    assert _next(root)["step"] == "implement"


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
