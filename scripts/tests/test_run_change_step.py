"""An unattended step's outcome conforms to its schema and is kept in the workflow log."""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "run_change_step", Path(__file__).resolve().parents[1] / "run_change_step.py"
)
assert _SPEC and _SPEC.loader
step = importlib.util.module_from_spec(_SPEC)
# Registered before it runs: its dataclasses look their module up by name.
sys.modules[_SPEC.name] = step
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


# Running a step: the wrapper's command, its stream, and the outcome it logs.

SESSION = "9c07d1e2-0000-4000-8000-000000000000"


def _event_lines(outcome: dict | None = None, *, denials: list | None = None,
                 tools: tuple[tuple[str, dict], ...] = (), result: bool = True,
                 is_error: bool = False, session: str = SESSION) -> list[str]:
    events: list[dict] = [{"type": "system", "subtype": "init", "session_id": session}]
    for name, given in tools:
        events.append({"type": "assistant", "session_id": session,
                       "message": {"content": [{"type": "tool_use", "name": name,
                                                "input": given}]}})
    if result:
        final = {"type": "result", "subtype": "error_during_execution" if is_error else "success",
                 "is_error": is_error, "session_id": session,
                 "permission_denials": denials or [], "result": "done"}
        if outcome is not None:
            final["structured_output"] = outcome
        events.append(final)
    return [json.dumps(event) + "\n" for event in events]


class FakeClaude:
    """Stands in for `claude -p`: records each command and replays a stream."""

    def __init__(self, *runs: tuple[list[str], int]) -> None:
        self.runs = list(runs)
        self.commands: list[list[str]] = []

    def __call__(self, command, cwd: Path, feed) -> int:
        self.commands.append(list(command))
        lines, status = self.runs.pop(0)
        for line in lines:
            feed(line)
        return status


def _wrapper(tmp_path: Path, claude: FakeClaude) -> "step.Wrapper":
    (tmp_path / "openspec/changes" / CHANGE).mkdir(parents=True, exist_ok=True)
    return step.Wrapper(root=tmp_path, runner=claude, head=lambda _: COMMIT, clock=_clock,
                        echo=None)


def _option(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


def _rules(command: list[str], flag: str) -> list[str]:
    start = command.index(flag) + 1
    end = next((i for i in range(start, len(command)) if command[i].startswith("--")),
               len(command))
    return command[start:end]


def test_the_step_table_names_each_claude_step() -> None:
    steps = step.load_steps()

    assert set(steps) == set(step.STEPS) - {"review"}
    assert all(rules.skill == f"change-{name}" for name, rules in steps.items())
    assert steps["plan"].resume_from == "design"


def _allows(rules, command: str) -> bool:
    """Whether a Bash command matches an allow rule and no deny rule, by glob."""
    def matches(rule_list) -> bool:
        return any(rule.startswith("Bash(") and fnmatch.fnmatchcase(command, rule[5:-1])
                   for rule in rule_list)
    return matches(rules.allow) and not matches(rules.deny)


PUSHES = ["git push origin HEAD", "make push-branch", "uv run git push",
          "uv run bash -c 'git push'", "make run-e2e", "docker push registry/image",
          "helm push chart.tgz oci://registry"]


def test_no_step_may_push_except_validations_guarded_push() -> None:
    for name, rules in step.load_steps().items():
        assert "Bash(git push*)" in rules.deny
        allowed = [command for command in PUSHES if _allows(rules, command)]
        assert allowed == (["make push-branch", "make run-e2e"] if name == "validate"
                           else []), name


def test_every_step_may_check_that_no_round_view_is_open() -> None:
    for name, rules in step.load_steps().items():
        assert _allows(rules, "make round-view-closed"), name
        assert not _allows(rules, "make round-view CHANGE=x"), name
        assert not _allows(rules, "make round-done"), name


def test_a_step_row_without_a_skill_is_refused(tmp_path: Path) -> None:
    table = tmp_path / "steps.toml"
    table.write_text('[steps.design]\nallow = ["Read"]\n', "utf-8")

    with pytest.raises(step.StepError, match="needs a skill"):
        step.load_steps(table)


def test_validation_may_not_relock_or_commit() -> None:
    rules = step.load_steps()["validate"]

    assert {"Bash(make lock*)", "Bash(git commit*)", "Edit"} <= set(rules.deny)


def test_a_run_is_headless_held_to_its_rules_and_given_the_schema(tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(VALID["finished"]), 0))

    _wrapper(tmp_path, claude).run("design", CHANGE)

    command = claude.commands[0]
    rules = step.load_steps()["design"]
    assert command[:3] == ["claude", "-p", f"/change-design {CHANGE}"]
    assert _option(command, "--permission-mode") == "dontAsk"
    assert _option(command, "--setting-sources") == "project"
    assert _option(command, "--output-format") == "stream-json"
    assert "--verbose" in command
    assert json.loads(_option(command, "--json-schema")) == step.harness_schema(step.load_schema())
    assert _rules(command, "--allowedTools") == list(rules.allow)
    assert _rules(command, "--disallowedTools") == list(rules.deny)
    assert "--resume" not in command


@pytest.mark.parametrize("kind", sorted(VALID))
def test_each_outcome_is_logged_with_its_session_and_commit(tmp_path: Path, kind: str) -> None:
    claude = FakeClaude((_event_lines(VALID[kind]), 0))

    line = _wrapper(tmp_path, claude).run("triage", CHANGE)

    expected = dict(VALID[kind])
    if kind == "stopped":
        expected["denials"] = []
    assert {key: line[key] for key in expected} == expected
    assert (line["step"], line["session"], line["commit"], line["exit_status"]) == (
        "triage", SESSION, COMMIT, 0)
    assert step.read_log(step.log_path(tmp_path, CHANGE)) == [line]


def test_a_crash_is_logged_stopped_with_its_exit_status(tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(result=False), 137))

    line = _wrapper(tmp_path, claude).run("validate", CHANGE)

    assert (line["outcome"], line["reason"], line["exit_status"]) == ("stopped", "exit 137", 137)
    assert line["message"] == line["reason"]
    assert line["session"] == SESSION
    assert step.outcome_problems({k: line[k] for k in ("outcome", "message", "reason",
                                                         "denials")}) == []


def test_a_run_without_an_outcome_is_logged_stopped(tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(None), 0))

    line = _wrapper(tmp_path, claude).run("closeout", CHANGE)

    assert (line["outcome"], line["reason"]) == ("stopped", "the run ended without an outcome")


def test_a_run_that_ends_in_error_is_logged_stopped(tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(VALID["finished"], is_error=True), 0))

    line = _wrapper(tmp_path, claude).run("closeout", CHANGE)

    assert line["reason"] == "the run ended in error: error_during_execution"


def test_a_malformed_outcome_is_logged_stopped(tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines({"outcome": "finished", "message": "Done."}), 0))

    line = _wrapper(tmp_path, claude).run("implement", CHANGE)

    assert line["outcome"] == "stopped"
    assert line["reason"] == ("the run's outcome does not conform to the schema: "
                              "outcome has no next")


def test_denials_are_taken_from_the_stream_not_the_step(tmp_path: Path) -> None:
    recorded = [{"tool_name": "Bash", "tool_use_id": "t1", "tool_input": {"command": "make lock"}}]
    claimed = {**VALID["stopped"], "denials": [{"tool_name": "Edit"}]}
    claude = FakeClaude((_event_lines(claimed, denials=recorded), 0),
                        (_event_lines(result=False, denials=recorded), 1))
    wrapper = _wrapper(tmp_path, claude)

    stopped = wrapper.run("validate", CHANGE)
    crashed = wrapper.run("validate", CHANGE)

    assert stopped["denials"] == recorded
    assert crashed["denials"] == []


def test_denials_of_a_crashed_run_with_a_result_are_kept(tmp_path: Path) -> None:
    recorded = [{"tool_name": "Bash", "tool_input": {"command": "make lock"}}]
    claude = FakeClaude((_event_lines(None, denials=recorded), 1))

    line = _wrapper(tmp_path, claude).run("validate", CHANGE)

    assert (line["reason"], line["denials"]) == ("exit 1: done", recorded)


def test_implementation_is_given_its_sections(tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(VALID["finished"]), 0))

    assert step.main(["run", "implement", CHANGE, "--sections", "1-3"], root=tmp_path,
                     wrapper=_wrapper(tmp_path, claude)) == 0

    assert claude.commands[0][2] == f"/change-implement {CHANGE} sections 1-3"
    assert step.read_log(step.log_path(tmp_path, CHANGE))[0]["sections"] == [1, 2, 3]


def test_planning_resumes_the_design_session(tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(VALID["question"], session="design-1"), 0),
                        (_event_lines(VALID["finished"], session="design-1"), 0))
    wrapper = _wrapper(tmp_path, claude)

    wrapper.run("design", CHANGE)
    line = wrapper.run("plan", CHANGE)

    assert _option(claude.commands[1], "--resume") == "design-1"
    assert claude.commands[1][2] == f"/change-plan {CHANGE}"
    assert _rules(claude.commands[1], "--allowedTools") == list(step.load_steps()["plan"].allow)
    assert (line["step"], line["session"]) == ("plan", "design-1")


def test_planning_without_a_design_session_starts_fresh(tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(VALID["finished"]), 0))

    _wrapper(tmp_path, claude).run("plan", CHANGE)

    assert "--resume" not in claude.commands[0]


def test_review_is_not_a_claude_step(tmp_path: Path) -> None:
    with pytest.raises(step.StepError, match="no unattended Claude Code run"):
        _wrapper(tmp_path, FakeClaude()).run("review", CHANGE)


def test_a_question_is_answered_by_resuming_its_session_with_a_granted_rule(
        tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(VALID["question"], session="v-1"), 0),
                        (_event_lines(VALID["finished"], session="v-1"), 0),
                        (_event_lines(VALID["finished"], session="v-2"), 0))
    wrapper = _wrapper(tmp_path, claude)
    wrapper.run("validate", CHANGE)
    step.note_orchestrator(step.log_path(tmp_path, CHANGE), "asked the owner", "question")

    resumed = wrapper.resume(CHANGE, "Delete the volume.", ["Bash(kubectl delete pvc *)"])
    rerun = wrapper.run("validate", CHANGE)

    command = claude.commands[1]
    assert command[2] == "The owner's answer: Delete the volume."
    assert _option(command, "--resume") == "v-1"
    assert _rules(command, "--allowedTools")[-1] == "Bash(kubectl delete pvc *)"
    assert (resumed["step"], resumed["session"], resumed["granted"]) == (
        "validate", "v-1", ["Bash(kubectl delete pvc *)"])
    assert "Bash(kubectl delete pvc *)" not in claude.commands[2]
    assert "--resume" not in claude.commands[2]
    assert "granted" not in rerun


def test_a_resumed_implementation_keeps_its_sections(tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(VALID["question"]), 0), (_event_lines(VALID["finished"]), 0))
    wrapper = _wrapper(tmp_path, claude)
    wrapper.run("implement", CHANGE, arguments="section 2", sections=[2])

    line = wrapper.resume(CHANGE, "Yes.")

    assert line["sections"] == [2]
    assert "granted" not in line


def test_nothing_to_resume_is_refused(tmp_path: Path) -> None:
    with pytest.raises(step.StepError, match="no step session"):
        _wrapper(tmp_path, FakeClaude()).resume(CHANGE, "Yes.")


def test_a_resume_needs_an_answer(tmp_path: Path) -> None:
    with pytest.raises(step.StepError, match="answer"):
        _wrapper(tmp_path, FakeClaude()).resume(CHANGE, "")


def test_the_stream_is_kept_as_a_numbered_transcript_with_progress(tmp_path: Path) -> None:
    reviews = tmp_path / "openspec/changes" / CHANGE / "reviews"
    (reviews / "transcripts").mkdir(parents=True)
    (reviews / "02-implementation.md").write_text("x", "utf-8")
    (reviews / "transcripts" / "03-design.log").write_text("x", "utf-8")
    lines = _event_lines(VALID["finished"], tools=(
        ("Read", {"file_path": "AGENTS.md"}), ("Bash", {"command": "make   test\n -q"})))
    claude = FakeClaude((lines, 0))

    line = _wrapper(tmp_path, claude).run("implement", CHANGE)

    transcript = reviews / "transcripts" / "04-implement.jsonl"
    assert line["transcript"] == "transcripts/04-implement.jsonl"
    assert transcript.read_text("utf-8") == "".join(lines)
    assert (reviews / "transcripts" / "04-implement.progress").read_text("utf-8") == (
        "09:15:40Z Read AGENTS.md\n09:15:40Z Bash make test -q\n")


def test_each_run_claims_its_own_transcript(tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(VALID["question"]), 0), (_event_lines(VALID["finished"]), 0))
    wrapper = _wrapper(tmp_path, claude)

    first = wrapper.run("design", CHANGE)
    second = wrapper.resume(CHANGE, "Option A.")

    assert (first["transcript"], second["transcript"]) == (
        "transcripts/01-design.jsonl", "transcripts/02-design.jsonl")


def test_lines_that_are_not_events_are_kept_but_not_read(tmp_path: Path) -> None:
    claude = FakeClaude((["warning: slow start\n", *_event_lines(VALID["finished"])], 0))

    line = _wrapper(tmp_path, claude).run("design", CHANGE)

    assert line["outcome"] == "finished"
    transcript = tmp_path / "openspec/changes" / CHANGE / "reviews" / line["transcript"]
    assert transcript.read_text("utf-8").startswith("warning: slow start\n")


def test_a_stopped_run_exits_non_zero(tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(result=False), 2))

    assert step.main(["run", "design", CHANGE], root=tmp_path,
                     wrapper=_wrapper(tmp_path, claude)) == 1


@pytest.mark.parametrize("text,sections", [("2", [2]), ("1-3", [1, 2, 3]), ("1,3", [1, 3]),
                                           ("5B", ["5B"]), ("", [])])
def test_implementation_sections_expand(text: str, sections: list) -> None:
    assert step.expand_sections(text) == sections


def test_claude_code_is_given_no_top_level_combinator() -> None:
    schema = step.load_schema()
    given = step.harness_schema(schema)

    assert not {"allOf", "anyOf", "oneOf"} & given.keys()
    assert given == {key: value for key, value in schema.items() if key != "allOf"}


def test_a_run_that_cannot_start_is_logged_stopped(tmp_path: Path) -> None:
    def missing(command, cwd, feed) -> int:
        raise FileNotFoundError("claude")

    line = step.Wrapper(root=_wrapper(tmp_path, FakeClaude()).root, runner=missing,
                        head=lambda _: COMMIT, clock=_clock, echo=None).run("design", CHANGE)

    assert (line["outcome"], line["exit_status"]) == ("stopped", None)
    assert line["reason"] == "the run did not finish: FileNotFoundError: claude"


def test_an_interrupted_run_is_logged_stopped_and_the_interrupt_kept(tmp_path: Path) -> None:
    def interrupted(command, cwd, feed) -> int:
        for line in _event_lines(result=False):
            feed(line)
        raise KeyboardInterrupt

    wrapper = step.Wrapper(root=_wrapper(tmp_path, FakeClaude()).root, runner=interrupted,
                           head=lambda _: COMMIT, clock=_clock, echo=None)
    with pytest.raises(KeyboardInterrupt):
        wrapper.run("validate", CHANGE)

    line = step.read_log(step.log_path(tmp_path, CHANGE))[-1]
    assert (line["outcome"], line["session"]) == ("stopped", SESSION)
    assert line["reason"] == "the run did not finish: KeyboardInterrupt"


def test_a_last_run_without_a_session_is_not_resumed_past(tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(VALID["question"], session="v-1"), 0),
                        (["Error: refused\n"], 1))
    wrapper = _wrapper(tmp_path, claude)
    wrapper.run("validate", CHANGE)
    wrapper.run("validate", CHANGE)

    with pytest.raises(step.StepError, match="recorded no session"):
        wrapper.resume(CHANGE, "Yes.")


def test_planning_resumes_its_own_latest_session_and_may_start_fresh(tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(VALID["question"], session="design-1"), 0),
                        (_event_lines(VALID["question"], session="plan-2"), 0),
                        (_event_lines(VALID["finished"], session="plan-2"), 0),
                        (_event_lines(VALID["finished"], session="plan-3"), 0))
    wrapper = _wrapper(tmp_path, claude)
    wrapper.run("design", CHANGE)
    wrapper.run("plan", CHANGE)

    wrapper.run("plan", CHANGE)
    wrapper.run("plan", CHANGE, fresh=True)

    assert _option(claude.commands[2], "--resume") == "plan-2"
    assert "--resume" not in claude.commands[3]


def test_only_implementation_takes_sections(tmp_path: Path) -> None:
    with pytest.raises(step.StepError, match="only implementation"):
        _wrapper(tmp_path, FakeClaude()).run("validate", CHANGE, sections=[1])


def test_no_step_may_edit_its_own_permissions() -> None:
    for name, rules in step.load_steps().items():
        assert {"Edit(scripts/change_steps.toml)", "Write(scripts/change_steps.toml)",
                "Edit(.claude/**)", "Write(.claude/**)"} <= set(rules.deny), name


@pytest.mark.parametrize("table,problem", [
    ('[steps.design]\nskill = "change-design"\ndeny = "Bash(git push*)"\n', "list of rules"),
    ('[steps.design]\nskill = "change-design"\nallowed = []\n', "takes only"),
    ('[steps.deploy]\nskill = "change-deploy"\n', "unknown step"),
    ('[commons]\nallow = []\n', "unknown tables"),
    ('[common]\nskill = "x"\n', "common row takes only"),
    ('[steps.plan]\nskill = "change-plan"\nresume_from = "design"\n', "has no row"),
])
def test_a_malformed_step_table_is_refused(tmp_path: Path, table: str, problem: str) -> None:
    path = tmp_path / "steps.toml"
    path.write_text(table, "utf-8")

    with pytest.raises(step.StepError, match=problem):
        step.load_steps(path)


def test_planning_after_a_design_run_without_a_session_is_refused(tmp_path: Path) -> None:
    claude = FakeClaude((["Error: refused\n"], 1), (_event_lines(VALID["finished"]), 0))
    wrapper = _wrapper(tmp_path, claude)
    wrapper.run("design", CHANGE)

    with pytest.raises(step.StepError, match="--fresh"):
        wrapper.run("plan", CHANGE)
    wrapper.run("plan", CHANGE, fresh=True)

    assert "--resume" not in claude.commands[1]


@pytest.mark.parametrize("kind", ["finished", "question"])
def test_a_run_denied_a_tool_ends_stopped_whatever_it_answered(tmp_path: Path, kind: str) -> None:
    recorded = [{"tool_name": "Bash", "tool_input": {"command": "cat x"}}]
    claude = FakeClaude((_event_lines(VALID[kind], denials=recorded), 0))

    line = _wrapper(tmp_path, claude).run("design", CHANGE)

    assert (line["outcome"], line["message"], line["denials"]) == (
        "stopped", VALID[kind]["message"], recorded)
    assert line["reason"] == f"the run was denied 1 tool call(s) but ended {kind}"


def test_a_backwards_section_range_is_refused(tmp_path: Path,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    assert step.main(["run", "implement", CHANGE, "--sections", "3-1"], root=tmp_path,
                     wrapper=_wrapper(tmp_path, FakeClaude())) == 1
    assert "runs backwards" in capsys.readouterr().err
