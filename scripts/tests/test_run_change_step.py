"""An unattended step's outcome conforms to its schema and is kept in the workflow log."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "run_change_step", Path(__file__).resolve().parents[1] / "run_change_step.py"
)
assert _SPEC and _SPEC.loader
step = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(step)

CHANGE = "shape-bounds"
COMMIT = "7f3c6e90"
AT = datetime(2026, 10, 21, 9, 15, 40, tzinfo=timezone.utc)

# Step outcomes as a workflow log carries them, without the fields the wrapper adds
# around them.
EXAMPLE_OUTCOMES = [
    {"outcome": "returned", "return_to": "design",
     "message": "The patch has no provider field; refusing it needs a decision the "
                "design does not make.",
     "evidence": "the section's notes"},
    {"outcome": "question",
     "message": "Helm part failed: a retained volume carries resource-policy keep. Remedy: "
                "delete it.",
     "awaiting": "environmental remedy"},
]
VALID = {
    "finished": {"outcome": "finished", "message": "The sections are committed.", "next": "triage"},
    "question": {"outcome": "question", "message": "Delete the volume?", "awaiting": "remedy"},
    "returned": {"outcome": "returned", "message": "Needs a decision.", "return_to": "design",
                 "evidence": "the section's notes"},
    "blocked": {"outcome": "blocked", "message": "Waits on its prerequisite.",
                "blocked_on": "split-pools"},
    "stopped": {"outcome": "stopped", "message": "Denied make lock.", "reason": "denied",
                "denials": [{"tool_name": "Bash", "tool_input": {"command": "make lock"}}]},
}
REQUIRED = {"finished": ["next"], "question": ["awaiting"],
            "returned": ["return_to", "evidence"], "blocked": ["blocked_on"],
            "stopped": ["reason", "denials"]}


def _log(tmp_path: Path) -> Path:
    directory = tmp_path / "openspec/changes" / CHANGE
    directory.mkdir(parents=True)
    return directory / "reviews" / "workflow.jsonl"


def _clock() -> datetime:
    return AT


@pytest.mark.parametrize("outcome", EXAMPLE_OUTCOMES, ids=lambda o: o["outcome"])
def test_the_designs_example_outcomes_conform(outcome: dict) -> None:
    assert step.outcome_problems(outcome) == []


@pytest.mark.parametrize("kind", sorted(VALID))
def test_each_outcome_conforms_with_its_own_fields(kind: str) -> None:
    assert step.outcome_problems(VALID[kind]) == []


@pytest.mark.parametrize("kind,field", [(kind, field) for kind, fields in REQUIRED.items()
                                        for field in fields + ["message"]])
def test_each_outcome_requires_its_fields(kind: str, field: str) -> None:
    outcome = {key: value for key, value in VALID[kind].items() if key != field}

    assert step.outcome_problems(outcome) == [f"outcome has no {field}"]


def test_an_unknown_outcome_is_rejected() -> None:
    problems = step.outcome_problems({"outcome": "done", "message": "All done."})

    assert problems == ["outcome.outcome is 'done', not one of finished, question, returned, "
                        "blocked, stopped"]


def test_a_field_the_schema_does_not_define_is_rejected() -> None:
    outcome = {**VALID["finished"], "verdict": "fine"}

    assert step.outcome_problems(outcome) == [
        "outcome has verdict, which the schema does not define"]


def test_a_return_to_a_phase_that_is_not_earlier_is_rejected() -> None:
    outcome = {**VALID["returned"], "return_to": "closeout"}

    assert step.outcome_problems(outcome) == [
        "outcome.return_to is 'closeout', not one of design, planning, implementation"]


def test_a_schema_keyword_the_check_cannot_enforce_fails_loudly() -> None:
    schema = {**step.load_schema(), "oneOf": []}

    with pytest.raises(step.StepError, match="oneOf"):
        step.outcome_problems(VALID["finished"], schema)


def test_an_outcome_is_logged_with_its_run(tmp_path: Path) -> None:
    log = _log(tmp_path)

    line = step.record_outcome(log, "validate", VALID["question"], session="51aa",
                               commit=COMMIT, clock=_clock)

    assert line == {"seq": 1, "at": "2026-10-21T09:15:40Z", "step": "validate",
                    "session": "51aa", "commit": COMMIT, **VALID["question"]}
    assert [json.loads(text) for text in log.read_text("utf-8").splitlines()] == [line]


def test_an_outcome_that_does_not_conform_is_not_logged(tmp_path: Path) -> None:
    log = _log(tmp_path)

    with pytest.raises(step.StepError, match="has no next"):
        step.record_outcome(log, "implement", {"outcome": "finished", "message": "Done."},
                            session="s", commit=COMMIT)

    assert not log.exists()


def test_an_unknown_step_is_not_logged(tmp_path: Path) -> None:
    with pytest.raises(step.StepError, match="unknown step 'deploy'"):
        step.record_outcome(_log(tmp_path), "deploy", VALID["finished"], session="s",
                            commit=COMMIT)


def test_seq_increases_across_outcomes_and_notes(tmp_path: Path) -> None:
    log = _log(tmp_path)

    step.note_round(log, [[1, 2], [3]], "owner", clock=_clock)
    step.record_outcome(log, "implement", VALID["finished"], session="s", commit=COMMIT,
                        extra={"sections": [1, 2]}, clock=_clock)
    step.note_orchestrator(log, "rerun validate", "it died before an outcome", clock=_clock)

    entries = step.read_log(log)
    assert [entry["seq"] for entry in entries] == [1, 2, 3]
    assert entries[0] == {"seq": 1, "at": "2026-10-21T09:15:40Z", "step": "orchestrator",
                          "outcome": "round", "sections": [[1, 2], [3]], "by": "owner"}
    assert entries[1]["sections"] == [1, 2]
    assert entries[2]["decision"] == "rerun validate"


def test_seq_follows_the_highest_in_the_log(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.parent.mkdir()
    log.write_text('{"seq": 7, "step": "orchestrator"}\n', "utf-8")

    line = step.note_orchestrator(log, "d", "r", clock=_clock)

    assert line["seq"] == 8


def test_a_malformed_line_is_reported_with_its_number(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.parent.mkdir()
    log.write_text('{"seq": 1}\n\nnot json\n', "utf-8")

    with pytest.raises(step.LogError, match=r"workflow\.jsonl:3: not a JSON line"):
        step.read_log(log)
    with pytest.raises(step.LogError, match=r":3:"):
        step.note_orchestrator(log, "d", "r")
    assert log.read_text("utf-8") == '{"seq": 1}\n\nnot json\n'


def test_a_line_without_seq_is_reported(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.parent.mkdir()
    log.write_text('{"seq": 1}\n["seq"]\n', "utf-8")

    with pytest.raises(step.LogError, match=r":2: not a JSON object"):
        step.read_log(log)


def test_an_absent_log_reads_empty(tmp_path: Path) -> None:
    assert step.read_log(_log(tmp_path)) == []


def test_the_last_lines_are_read(tmp_path: Path) -> None:
    log = _log(tmp_path)
    for index in range(4):
        step.note_orchestrator(log, f"d{index}", "r", clock=_clock)

    assert [entry["decision"] for entry in step.last_entries(log, 2)] == ["d2", "d3"]
    assert step.last_entries(log, 0) == []


@pytest.mark.parametrize("sections", [[], [[]], [1], [[0.5]], [[""]], [[True]]])
def test_a_round_without_sessions_of_sections_is_refused(tmp_path: Path, sections) -> None:
    log = _log(tmp_path)

    with pytest.raises(step.StepError, match="a round names"):
        step.note_round(log, sections, "owner")

    assert not log.exists()


def test_a_round_without_who_agreed_it_is_refused(tmp_path: Path) -> None:
    with pytest.raises(step.StepError, match="who agreed"):
        step.note_round(_log(tmp_path), [[1]], "")


@pytest.mark.parametrize("decision,reason", [("", "r"), ("d", "")])
def test_an_orchestrator_line_without_its_decision_or_reason_is_refused(
        tmp_path: Path, decision: str, reason: str) -> None:
    with pytest.raises(step.StepError, match="decision and its reason"):
        step.note_orchestrator(_log(tmp_path), decision, reason)


def test_an_outcome_may_not_set_what_the_wrapper_records(tmp_path: Path) -> None:
    with pytest.raises(step.StepError, match="does not conform"):
        step.record_outcome(_log(tmp_path), "plan", {**VALID["finished"], "commit": "x"},
                            session="s", commit=COMMIT)


def test_sections_parse_by_session(tmp_path: Path) -> None:
    assert step.parse_sections("1,2; 3 ;5B") == [[1, 2], [3], ["5B"]]


def test_the_command_line_notes_a_round_and_prints_the_log(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = _log(tmp_path)

    assert step.main(["note", CHANGE, "round", "--sections", "1;2,3"], root=tmp_path) == 0
    assert step.main(["note", CHANGE, "orchestrator", "--decision", "d", "--reason", "r"],
                     root=tmp_path) == 0
    capsys.readouterr()
    assert step.main(["log", CHANGE, "--last", "1"], root=tmp_path) == 0

    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [entry["outcome"] for entry in step.read_log(log)] == ["round", "orchestrator"]
    assert step.read_log(log)[0]["sections"] == [[1], [2, 3]]
    assert [entry["seq"] for entry in printed] == [2]


def test_the_command_line_names_a_change_it_cannot_find(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert step.main(["log", "missing"], root=tmp_path) == 1
    assert "no change 'missing'" in capsys.readouterr().err


def test_an_archived_changes_log_is_found_by_its_name(tmp_path: Path) -> None:
    archived = tmp_path / "openspec/changes/archive" / f"2026-10-20-{CHANGE}"
    archived.mkdir(parents=True)

    assert step.main(["note", CHANGE, "orchestrator", "--decision", "d", "--reason", "r"],
                     root=tmp_path) == 0

    assert step.read_log(archived / "reviews" / "workflow.jsonl")[0]["decision"] == "d"


@pytest.mark.parametrize("type_", ["number", ["string", "null"]])
def test_a_schema_type_the_check_cannot_enforce_fails_loudly(type_) -> None:
    schema = {**step.load_schema(), "properties": {"message": {"type": type_}}}

    with pytest.raises(step.StepError, match="does not enforce"):
        step.outcome_problems({"message": "m"}, schema)


@pytest.mark.parametrize("extra", [{"commit": "other"}, {"step": "plan"}, {"message": "m"},
                                   {"seq": 9}])
def test_run_fields_are_recorded_once(tmp_path: Path, extra: dict) -> None:
    log = _log(tmp_path)

    with pytest.raises(step.StepError, match="recorded twice|the log assigns"):
        step.record_outcome(log, "implement", VALID["finished"], session="s", commit=COMMIT,
                            extra=extra)

    assert not log.exists()


def test_a_last_line_without_its_newline_is_not_joined(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.parent.mkdir()
    log.write_text('{"seq": 1}', "utf-8")

    step.note_orchestrator(log, "d", "r", clock=_clock)

    assert [entry["seq"] for entry in step.read_log(log)] == [1, 2]


def test_a_non_ascii_digit_is_a_section_name() -> None:
    assert step.parse_sections("²") == [["²"]]
