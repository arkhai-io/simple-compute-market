"""A step's outcome and the orchestrating session's notes are kept in the workflow log."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from change_workflow.cli import main
from change_workflow.common import StepError
from change_workflow.log import (LogError, append_entry, branch_decisions, last_entries,
                                 note_orchestrator, note_round, read_log, record_outcome)
from change_workflow_fixtures import CHANGE, COMMIT, DENIALS, VALID, clock, log_file


def test_the_owners_branch_decision_is_recorded_and_found(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = log_file(tmp_path)
    note_orchestrator(log, "runs here", "its own evidence", by="owner",
                      branch="feat/x", change=CHANGE, clock=clock)
    note_orchestrator(log, "rerun", "renewed", clock=clock)

    assert main(["log", CHANGE, "--branch", "feat/x"], root=tmp_path) == 0
    shown = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(entry["seq"], entry["change"]) for entry in shown] == [(1, CHANGE)]
    assert branch_decisions(read_log(log), "feat/x", "another-change") == []
    assert branch_decisions(read_log(log), "feat/y") == []


@pytest.mark.parametrize("fields,problem", [
    ({"branch": "feat/x"}, "both the branch and the change"),
    ({"change": CHANGE}, "both the branch and the change"),
    ({"branch": "feat/x", "change": CHANGE, "by": "orchestrator"}, "the owner's"),
])
def test_a_branch_decision_names_both_and_is_the_owners(tmp_path: Path, fields: dict,
                                                        problem: str) -> None:
    fields = {"by": "owner", **fields}

    with pytest.raises(StepError, match=problem):
        note_orchestrator(log_file(tmp_path), "runs here", "pilot", **fields)


def test_an_outcome_is_logged_with_its_run(tmp_path: Path) -> None:
    log = log_file(tmp_path)

    line = record_outcome(log, "validate", VALID["question"], session="51aa",
                          commit=COMMIT, clock=clock)

    assert line == {"seq": 1, "at": "2026-10-21T09:15:40Z", "step": "validate",
                    "session": "51aa", "commit": COMMIT, **VALID["question"]}
    assert [json.loads(text) for text in log.read_text("utf-8").splitlines()] == [line]


def test_an_outcome_that_does_not_conform_is_not_logged(tmp_path: Path) -> None:
    log = log_file(tmp_path)

    with pytest.raises(StepError, match="has no next"):
        record_outcome(log, "implement", {"outcome": "finished", "message": "Done."},
                       session="s", commit=COMMIT)

    assert not log.exists()


def test_an_unknown_step_is_not_logged(tmp_path: Path) -> None:
    with pytest.raises(StepError, match="unknown step 'deploy'"):
        record_outcome(log_file(tmp_path), "deploy", VALID["finished"], session="s",
                       commit=COMMIT)


def test_seq_increases_across_outcomes_and_notes(tmp_path: Path) -> None:
    log = log_file(tmp_path)

    note_round(log, [[1, 2], [3]], "owner", clock=clock)
    record_outcome(log, "implement", VALID["finished"], session="s", commit=COMMIT,
                   extra={"sections": [1, 2]}, clock=clock)
    note_orchestrator(log, "rerun validate", "it died before an outcome", clock=clock)

    entries = read_log(log)
    assert [entry["seq"] for entry in entries] == [1, 2, 3]
    assert entries[0] == {"seq": 1, "at": "2026-10-21T09:15:40Z", "step": "orchestrator",
                          "outcome": "round", "sections": [[1, 2], [3]], "by": "owner",
                          "after": 0}
    assert entries[1]["sections"] == [1, 2]
    assert entries[2]["decision"] == "rerun validate"


def test_seq_follows_the_highest_in_the_log(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    log.parent.mkdir()
    log.write_text('{"seq": 7, "step": "orchestrator"}\n', "utf-8")

    line = note_orchestrator(log, "d", "r", clock=clock)

    assert line["seq"] == 8


def test_a_malformed_line_is_reported_with_its_number(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    log.parent.mkdir()
    log.write_text('{"seq": 1}\n\nnot json\n', "utf-8")

    with pytest.raises(LogError, match=r"workflow\.jsonl:3: not a JSON line"):
        read_log(log)
    with pytest.raises(LogError, match=r":3:"):
        note_orchestrator(log, "d", "r")
    assert log.read_text("utf-8") == '{"seq": 1}\n\nnot json\n'


def test_a_line_without_seq_is_reported(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    log.parent.mkdir()
    log.write_text('{"seq": 1}\n["seq"]\n', "utf-8")

    with pytest.raises(LogError, match=r":2: not a JSON object"):
        read_log(log)


def test_an_absent_log_reads_empty(tmp_path: Path) -> None:
    assert read_log(log_file(tmp_path)) == []


def test_the_last_lines_are_read(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    for index in range(4):
        note_orchestrator(log, f"d{index}", "r", clock=clock)

    assert [entry["decision"] for entry in last_entries(log, 2)] == ["d2", "d3"]
    assert last_entries(log, 0) == []


@pytest.mark.parametrize("sections", [[], [[]], [1], [[0.5]], [[""]], [[True]]])
def test_a_round_without_sessions_of_sections_is_refused(tmp_path: Path, sections) -> None:
    log = log_file(tmp_path)

    with pytest.raises(StepError, match="a round names"):
        note_round(log, sections, "owner")

    assert not log.exists()


def test_a_round_without_who_agreed_it_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StepError, match="who agreed"):
        note_round(log_file(tmp_path), [[1]], "")


@pytest.mark.parametrize("decision,reason", [("", "r"), ("d", "")])
def test_an_orchestrator_line_without_its_decision_or_reason_is_refused(
        tmp_path: Path, decision: str, reason: str) -> None:
    with pytest.raises(StepError, match="decision and its reason"):
        note_orchestrator(log_file(tmp_path), decision, reason)


def test_a_decision_names_who_decided_the_run_it_resolves_and_the_next_step(
        tmp_path: Path) -> None:
    log = log_file(tmp_path)
    run = record_outcome(log, "implement", VALID["returned"], session="s", commit=COMMIT)

    line = note_orchestrator(log, "return to design confirmed", "the owner's word",
                             by="owner", resolves=run["seq"], next_step="design",
                             clock=clock)
    review = note_orchestrator(log, "review again", "the owner asked", by="owner",
                               next_step="review", kind="pre-closeout", clock=clock)

    assert line == {"seq": 2, "at": "2026-10-21T09:15:40Z", "step": "orchestrator",
                    "outcome": "orchestrator", "by": "owner",
                    "decision": "return to design confirmed", "reason": "the owner's word",
                    "resolves": 1, "next": "design"}
    assert (review["next"], review["kind"]) == ("review", "pre-closeout")
    assert note_orchestrator(log, "d", "r")["by"] == "orchestrator"


def test_the_owner_may_direct_archive_cleanup_past_its_validation(tmp_path: Path) -> None:
    log = log_file(tmp_path)

    waiver = note_orchestrator(log, "waive archive cleanup's validation", "the paths judged",
                               by="owner", next_step="archive-cleanup")

    assert waiver["next"] == "archive-cleanup" and "resolves" not in waiver
    with pytest.raises(StepError, match="is the owner's waiver"):
        note_orchestrator(log, "d", "r", next_step="archive-cleanup")


@pytest.mark.parametrize("next_step", ["design", "plan"])
def test_only_the_owner_confirms_a_return(tmp_path: Path, next_step: str) -> None:
    log = log_file(tmp_path)
    run = record_outcome(log, "triage", VALID["returned"], session="s", commit=COMMIT)

    with pytest.raises(StepError, match="which is the owner's"):
        note_orchestrator(log, "return confirmed", "r", resolves=run["seq"],
                          next_step=next_step)

    assert len(read_log(log)) == 1


@pytest.mark.parametrize("fields,problem", [
    ({"resolves": 9}, "no run has seq 9"),
    ({"reads": 9}, "no run has seq 9"),
    ({"next_step": "deploy"}, "unknown step 'deploy'"),
    ({"kind": "design"}, "a kind goes with next = review"),
    ({"next_step": "review", "kind": "triage"}, "unknown review kind 'triage'"),
    ({"next_step": "review"}, "a decision directing a review names its kind"),
    ({"next_step": "design"}, "directing design is a confirmed return and names the run"),
    ({"by": ""}, "names who decided"),
])
def test_a_decision_naming_what_the_log_lacks_is_refused(tmp_path: Path, fields: dict,
                                                         problem: str) -> None:
    log = log_file(tmp_path)
    note_orchestrator(log, "an earlier decision", "r", clock=clock)

    with pytest.raises(StepError, match=problem):
        note_orchestrator(log, "d", "r", **fields)

    assert len(read_log(log)) == 1


def test_a_decision_resolves_only_a_steps_run(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    note = note_orchestrator(log, "an earlier decision", "r", clock=clock)

    with pytest.raises(StepError, match="a decision resolves a step's run"):
        note_orchestrator(log, "d", "r", resolves=note["seq"])


def test_a_decision_reads_a_run_with_denials_without_resolving_it(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    run = record_outcome(log, "validate", {**VALID["question"], "denials": DENIALS},
                         session="s", commit=COMMIT)

    line = note_orchestrator(log, "gap: gh run view", "the skill names it", reads=run["seq"],
                             clock=clock)
    both = note_orchestrator(log, "gap: gh run view; rerun", "r", reads=run["seq"],
                             resolves=run["seq"], clock=clock)

    assert (line["reads"], "resolves" in line) == (1, False)
    assert (both["reads"], both["resolves"]) == (1, 1)


def test_a_decision_may_not_read_a_run_that_recorded_no_denial(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    run = record_outcome(log, "validate", VALID["question"], session="s", commit=COMMIT)

    with pytest.raises(StepError, match="recorded no denial"):
        note_orchestrator(log, "d", "r", reads=run["seq"])

    assert len(read_log(log)) == 1


def test_an_outcome_may_not_set_what_the_wrapper_records(tmp_path: Path) -> None:
    with pytest.raises(StepError, match="does not conform"):
        record_outcome(log_file(tmp_path), "plan", {**VALID["finished"], "commit": "x"},
                       session="s", commit=COMMIT)


@pytest.mark.parametrize("extra", [{"commit": "other"}, {"step": "plan"}, {"message": "m"},
                                   {"seq": 9}])
def test_run_fields_are_recorded_once(tmp_path: Path, extra: dict) -> None:
    log = log_file(tmp_path)

    with pytest.raises(StepError, match="recorded twice|the log assigns"):
        record_outcome(log, "implement", VALID["finished"], session="s", commit=COMMIT,
                       extra=extra)

    assert not log.exists()


def test_a_last_line_without_its_newline_is_not_joined(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    log.parent.mkdir()
    log.write_text('{"seq": 1}', "utf-8")

    note_orchestrator(log, "d", "r", clock=clock)

    assert [entry["seq"] for entry in read_log(log)] == [1, 2]


def test_a_round_records_the_last_record_before_it(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    (log.parent / "transcripts").mkdir(parents=True)
    (log.parent / "transcripts" / "04-review.log").write_text("x", "utf-8")

    assert note_round(log, [[2]], "owner", clock=clock)["after"] == 4


def test_a_round_recorded_after_the_fact_is_given_its_last_record_before_it(
        tmp_path: Path) -> None:
    log = log_file(tmp_path)
    (log.parent / "transcripts").mkdir(parents=True)
    (log.parent / "transcripts" / "09-triage.jsonl").write_text("x", "utf-8")

    assert note_round(log, [[1, 2, 3]], "owner", after=1, clock=clock)["after"] == 1
    with pytest.raises(StepError, match="a record number"):
        note_round(log, [[1]], "owner", after=-1)


# The owner's waiver of another design review after a return.

def _returned_and_redesigned(log: Path, *, design: dict | None = None) -> None:
    run = record_outcome(log, "plan", VALID["returned"], session="s", commit=COMMIT)
    note_orchestrator(log, "return to design confirmed", "the owner's word", by="owner",
                      resolves=run["seq"], next_step="design", clock=clock)
    record_outcome(log, "design", design or VALID["finished"], session="s", commit=COMMIT)


def test_the_owner_may_waive_another_design_review_after_a_return(tmp_path: Path) -> None:
    log = log_file(tmp_path)
    _returned_and_redesigned(log)

    waiver = note_orchestrator(log, "waive another design review", "the decision is small",
                               by="owner", next_step="plan", status="in design")

    assert waiver["next"] == "plan" and "resolves" not in waiver


@pytest.mark.parametrize("case", ["by the orchestrator", "not in design", "no return",
                                  "design not finished", "design before the return",
                                  "return not the owner's"])
def test_a_waiver_is_refused_unless_it_follows_a_finished_redesign(tmp_path: Path,
                                                                   case: str) -> None:
    log = log_file(tmp_path)
    by, status = "owner", "in design"
    if case == "by the orchestrator":
        _returned_and_redesigned(log)
        by = "orchestrator"
    elif case == "not in design":
        _returned_and_redesigned(log)
        status = "in planning"
    elif case == "no return":
        record_outcome(log, "design", VALID["finished"], session="s", commit=COMMIT)
    elif case == "design not finished":
        _returned_and_redesigned(log, design=VALID["question"])
    elif case == "return not the owner's":
        run = record_outcome(log, "plan", VALID["returned"], session="s", commit=COMMIT)
        # Appended past the writer, which refuses this line, to stand for a log holding one.
        append_entry(log, {"step": "orchestrator", "outcome": "orchestrator",
                           "by": "orchestrator", "decision": "return to design confirmed",
                           "reason": "r", "resolves": run["seq"], "next": "design"})
        record_outcome(log, "design", VALID["finished"], session="s", commit=COMMIT)
    else:
        record_outcome(log, "design", VALID["finished"], session="s", commit=COMMIT)
        run = record_outcome(log, "plan", VALID["returned"], session="s", commit=COMMIT)
        note_orchestrator(log, "return to design confirmed", "r", by="owner",
                          resolves=run["seq"], next_step="design", clock=clock)
    count = len(read_log(log))

    with pytest.raises(StepError, match="directing plan names the run it resolves"):
        note_orchestrator(log, "waive", "r", by=by, next_step="plan", status=status)
    assert len(read_log(log)) == count


def test_the_command_line_reads_the_changes_status_for_a_waiver(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = log_file(tmp_path)
    _returned_and_redesigned(log)
    note = ["note", CHANGE, "orchestrator", "--decision", "waive another design review",
            "--reason", "the decision is small", "--by", "owner", "--next", "plan"]
    (tmp_path / "openspec/changes/README.md").write_text(
        "| Change | Status | Depends on | Notes | Acceptance boundary |\n|---|---|---|---|---|\n"
        f"| [`{CHANGE}`]({CHANGE}/) | in planning | — | x | x |\n", "utf-8")

    assert main(note, root=tmp_path) == 1
    assert "directing plan" in capsys.readouterr().err

    (tmp_path / "openspec/changes/README.md").write_text(
        (tmp_path / "openspec/changes/README.md").read_text("utf-8").replace(
            "in planning", "in design"), "utf-8")
    assert main(note, root=tmp_path) == 0
    assert read_log(log)[-1]["next"] == "plan"
