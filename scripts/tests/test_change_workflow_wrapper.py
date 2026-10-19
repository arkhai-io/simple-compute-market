"""A step runs unattended on its models, and a waiting run resumes with the owner's
answer: the wrapper's command and the outcome it logs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from change_workflow.common import StepError
from change_workflow.log import log_path, note_orchestrator, read_log, record_outcome
from change_workflow.outcome import harness_schema, load_schema, outcome_problems
from change_workflow.steps import Model, load_steps
from change_workflow.wrapper import Wrapper
from change_workflow_fixtures import (CHANGE, COMMIT, LIMIT, NETWORK, OPUS, SESSION, VALID,
                                      FakeClaude, clock, event_lines, failed_run, make_wrapper,
                                      option, option_rules)


def test_a_run_is_headless_held_to_its_rules_and_given_the_schema(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["finished"]), 0))

    make_wrapper(tmp_path, claude).run("design", CHANGE)

    command = claude.commands[0]
    rules = load_steps()["design"]
    assert command[:3] == ["claude", "-p", f"/change-design {CHANGE}"]
    assert option(command, "--permission-mode") == "dontAsk"
    assert (option(command, "--model"), option(command, "--effort")) == (
        "claude-opus-5-5", "high")
    assert option(command, "--setting-sources") == "project"
    assert option(command, "--output-format") == "stream-json"
    assert "--verbose" in command
    assert json.loads(option(command, "--json-schema")) == harness_schema(load_schema())
    assert option_rules(command, "--allowedTools") == list(rules.allow)
    assert option_rules(command, "--disallowedTools") == list(rules.deny)
    assert "--resume" not in command


@pytest.mark.parametrize("kind", sorted(VALID))
def test_each_outcome_is_logged_with_its_session_and_commit(tmp_path: Path, kind: str) -> None:
    claude = FakeClaude((event_lines(VALID[kind]), 0))

    line = make_wrapper(tmp_path, claude).run("triage", CHANGE)

    # Every line carries the run's own record of denials, the step's replaced.
    expected = {**VALID[kind], "denials": []}
    assert {key: line[key] for key in expected} == expected
    assert (line["step"], line["session"], line["commit"], line["exit_status"]) == (
        "triage", SESSION, COMMIT, 0)
    assert (line["harness"], line["model"], line["effort"]) == ("claude", "claude-opus-5-5",
                                                               "high")
    assert "unavailable" not in line
    assert read_log(log_path(tmp_path, CHANGE)) == [line]


def test_a_crash_is_logged_stopped_with_its_exit_status(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(result=False), 137))

    line = make_wrapper(tmp_path, claude).run("validate", CHANGE)

    assert (line["outcome"], line["reason"], line["exit_status"]) == ("stopped", "exit 137", 137)
    assert line["message"] == line["reason"]
    assert line["session"] == SESSION
    assert outcome_problems({k: line[k] for k in ("outcome", "message", "reason",
                                                  "denials")}) == []


def test_a_run_without_an_outcome_is_logged_stopped(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(None), 0))

    line = make_wrapper(tmp_path, claude).run("closeout", CHANGE)

    assert (line["outcome"], line["reason"]) == ("stopped", "the run ended without an outcome")


def test_a_run_that_ends_in_error_is_logged_stopped(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["finished"], is_error=True), 0))

    line = make_wrapper(tmp_path, claude).run("closeout", CHANGE)

    assert line["reason"] == "the run ended in error: error_during_execution"


def test_a_malformed_outcome_is_logged_stopped(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines({"outcome": "finished", "message": "Done."}), 0))

    line = make_wrapper(tmp_path, claude).run("implement", CHANGE)

    assert line["outcome"] == "stopped"
    assert line["reason"] == ("the run's outcome does not conform to the schema: "
                              "outcome has no next")


def test_denials_are_taken_from_the_stream_not_the_step(tmp_path: Path) -> None:
    recorded = [{"tool_name": "Bash", "tool_use_id": "t1", "tool_input": {"command": "make lock"}}]
    claimed = {**VALID["stopped"], "denials": [{"tool_name": "Edit"}]}
    claude = FakeClaude((event_lines(claimed, denials=recorded), 0),
                        (event_lines(result=False, denials=recorded), 1))
    wrapper = make_wrapper(tmp_path, claude)

    stopped = wrapper.run("validate", CHANGE)
    crashed = wrapper.run("validate", CHANGE)

    assert stopped["denials"] == recorded
    assert crashed["denials"] == []


def test_denials_of_a_crashed_run_with_a_result_are_kept(tmp_path: Path) -> None:
    recorded = [{"tool_name": "Bash", "tool_input": {"command": "make lock"}}]
    claude = FakeClaude((event_lines(None, denials=recorded), 1))

    line = make_wrapper(tmp_path, claude).run("validate", CHANGE)

    assert (line["reason"], line["denials"]) == ("exit 1: done", recorded)


def test_planning_resumes_the_design_session(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["question"], session="design-1"), 0),
                        (event_lines(VALID["finished"], session="design-1"), 0))
    wrapper = make_wrapper(tmp_path, claude)

    wrapper.run("design", CHANGE)
    line = wrapper.run("plan", CHANGE)

    assert option(claude.commands[1], "--resume") == "design-1"
    assert claude.commands[1][2] == f"/change-plan {CHANGE}"
    assert option_rules(claude.commands[1], "--allowedTools") == list(load_steps()["plan"].allow)
    assert (line["step"], line["session"]) == ("plan", "design-1")


def test_planning_without_a_design_session_starts_fresh(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["finished"]), 0))

    make_wrapper(tmp_path, claude).run("plan", CHANGE)

    assert "--resume" not in claude.commands[0]


def test_review_is_not_a_claude_step(tmp_path: Path) -> None:
    with pytest.raises(StepError, match="no unattended Claude Code run"):
        make_wrapper(tmp_path, FakeClaude()).run("review", CHANGE)


def test_a_question_is_answered_by_resuming_its_session_with_a_granted_rule(
        tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["question"], session="v-1"), 0),
                        (event_lines(VALID["finished"], session="v-1"), 0),
                        (event_lines(VALID["finished"], session="v-2"), 0))
    wrapper = make_wrapper(tmp_path, claude)
    asked = wrapper.run("validate", CHANGE)
    note_orchestrator(log_path(tmp_path, CHANGE), "asked the owner", "question")

    resumed = wrapper.resume(CHANGE, asked["seq"], "Delete the volume.",
                             ["Bash(kubectl delete pvc *)"])
    rerun = wrapper.run("validate", CHANGE)

    command = claude.commands[1]
    assert command[2] == "The owner's answer: Delete the volume."
    assert option(command, "--resume") == "v-1"
    assert option_rules(command, "--allowedTools")[-1] == "Bash(kubectl delete pvc *)"
    assert (resumed["step"], resumed["session"], resumed["granted"]) == (
        "validate", "v-1", ["Bash(kubectl delete pvc *)"])
    assert "Bash(kubectl delete pvc *)" not in claude.commands[2]
    assert "--resume" not in claude.commands[2]
    assert "granted" not in rerun


def test_a_resumed_implementation_keeps_its_sections(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["question"]), 0), (event_lines(VALID["finished"]), 0))
    wrapper = make_wrapper(tmp_path, claude)
    asked = wrapper.run("implement", CHANGE, arguments="section 2", sections=[2])

    line = wrapper.resume(CHANGE, asked["seq"], "Yes.")

    assert line["sections"] == [2]
    assert "granted" not in line


def test_a_resume_names_the_waiting_run_not_the_last(tmp_path: Path) -> None:
    # Validation and triage run side by side: the triage asks, then the
    # validation finishes above it, and the answer is the triage's.
    claude = FakeClaude((event_lines(VALID["question"], session="t-1"), 0),
                        (event_lines(VALID["finished"], session="v-1"), 0),
                        (event_lines(VALID["finished"], session="t-1"), 0))
    wrapper = make_wrapper(tmp_path, claude)
    asked = wrapper.run("triage", CHANGE)
    finished = wrapper.run("validate", CHANGE)

    line = wrapper.resume(CHANGE, asked["seq"], "Agreed.")

    assert option(claude.commands[2], "--resume") == "t-1"
    assert (line["step"], line["session"]) == ("triage", "t-1")
    with pytest.raises(StepError, match="ended finished"):
        wrapper.resume(CHANGE, finished["seq"], "Agreed.")


def test_a_stopped_run_is_read_then_resumed_with_a_grant_and_not_again(
        tmp_path: Path) -> None:
    # The orchestrating session's order: the stop's denial is read first, by a
    # line that resolves nothing, and the grant resumes the read run; a line
    # that resolved it would have made the resume refuse it.
    denied = [{"tool_name": "Bash", "tool_input": {"command": "make lock"}}]
    claude = FakeClaude((event_lines(VALID["stopped"], denials=denied, session="v-1"), 0),
                        (event_lines(VALID["finished"], session="v-1"), 0))
    wrapper = make_wrapper(tmp_path, claude)
    stopped = wrapper.run("validate", CHANGE)
    note_orchestrator(log_path(tmp_path, CHANGE),
                      "gap: proposed Bash(make lock) as a one-run grant", "r",
                      reads=stopped["seq"])

    line = wrapper.resume(CHANGE, stopped["seq"], "Go on.", ["Bash(make lock)"])

    assert option(claude.commands[1], "--resume") == "v-1"
    assert (line["step"], line["granted"]) == ("validate", ["Bash(make lock)"])
    assert line["seq"] != stopped["seq"]
    with pytest.raises(StepError, match="latest run"):
        wrapper.resume(CHANGE, stopped["seq"], "Go on.")


def test_a_run_that_is_not_waiting_is_refused(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["stopped"], session="d-1"), 0),
                        (event_lines(VALID["question"], session="v-1"), 0))
    wrapper = make_wrapper(tmp_path, claude)
    log = log_path(tmp_path, CHANGE)
    stopped = wrapper.run("design", CHANGE)
    resolved = note_orchestrator(log, "rerun it", "r", resolves=stopped["seq"])
    asked = wrapper.run("validate", CHANGE)
    note_orchestrator(log, "abandoned", "r", resolves=asked["seq"])
    review = record_outcome(log, "review", VALID["finished"], session="codex:x",
                            commit=COMMIT, extra={"kind": "design"})

    with pytest.raises(StepError, match="ended stopped and a decision line resolves it"):
        wrapper.resume(CHANGE, stopped["seq"], "Go on.")
    with pytest.raises(StepError, match="ended question and a decision line resolves"):
        wrapper.resume(CHANGE, asked["seq"], "Go on.")
    with pytest.raises(StepError, match="orchestrator line, not the run of a step"):
        wrapper.resume(CHANGE, resolved["seq"], "Go on.")
    with pytest.raises(StepError, match="review line, not the run of a step"):
        wrapper.resume(CHANGE, review["seq"], "Go on.")
    with pytest.raises(StepError, match="no seq 9"):
        wrapper.resume(CHANGE, 9, "Go on.")


def test_nothing_to_resume_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StepError, match="no seq 1"):
        make_wrapper(tmp_path, FakeClaude()).resume(CHANGE, 1, "Yes.")


def test_a_resume_needs_an_answer(tmp_path: Path) -> None:
    with pytest.raises(StepError, match="answer"):
        make_wrapper(tmp_path, FakeClaude()).resume(CHANGE, 1, "")


def test_a_run_that_cannot_start_is_logged_stopped(tmp_path: Path) -> None:
    def missing(command, cwd, feed) -> int:
        raise FileNotFoundError("claude")

    line = Wrapper(root=make_wrapper(tmp_path, FakeClaude()).root, runner=missing,
                   head=lambda _: COMMIT, clock=clock, echo=None).run("design", CHANGE)

    assert (line["outcome"], line["exit_status"]) == ("stopped", None)
    assert line["reason"] == ("no model of the step is available: claude-opus-5-5: claude is "
                              "not installed: claude")
    assert line["unavailable"] == [{**OPUS.entry(),
                                    "reason": "claude is not installed: claude"}]


@pytest.mark.parametrize("lines", [
    failed_run(LIMIT), failed_run("Not logged in · Please run /login"), ["Invalid API key\n"],
])
def test_a_steps_only_model_unavailable_stops_it_saying_why(tmp_path: Path, lines) -> None:
    claude = FakeClaude((lines, 1))

    line = make_wrapper(tmp_path, claude).run("triage", CHANGE)

    assert len(claude.commands) == 1
    assert line["outcome"] == "stopped"
    assert line["reason"].startswith("no model of the step is available: claude-opus-5-5: ")
    assert line["unavailable"][0]["model"] == "claude-opus-5-5"


def test_a_usage_limit_names_when_it_resets(tmp_path: Path) -> None:
    line = make_wrapper(tmp_path, FakeClaude((failed_run(LIMIT), 1))).run("validate", CHANGE)

    assert line["reason"] == f"no model of the step is available: claude-sonnet-5-5: {LIMIT}"
    assert (line["model"], line["effort"]) == ("claude-sonnet-5-5", "medium")


def test_a_network_error_is_retried_twice_on_the_same_model_then_stops(tmp_path: Path) -> None:
    claude = FakeClaude(*[(failed_run(NETWORK), 1)] * 3)

    line = make_wrapper(tmp_path, claude).run("design", CHANGE)

    assert len(claude.commands) == 3
    assert all(option(command, "--model") == "claude-opus-5-5" for command in claude.commands)
    assert line["outcome"] == "stopped"
    assert line["reason"] == f"claude-opus-5-5 could not be reached after 3 attempts: {NETWORK}"
    assert "unavailable" not in line


def test_a_network_error_then_a_run_logs_the_run(tmp_path: Path) -> None:
    claude = FakeClaude((failed_run(NETWORK), 1), (event_lines(VALID["finished"]), 0))

    line = make_wrapper(tmp_path, claude).run("design", CHANGE)

    assert claude.commands[0] == claude.commands[1]
    assert (line["outcome"], line["exit_status"]) == ("finished", 0)
    transcript = log_path(tmp_path, CHANGE).parent / line["transcript"]
    assert "EAI_AGAIN" in transcript.read_text("utf-8")


def test_an_ordinary_failure_is_not_read_as_an_unavailable_model(tmp_path: Path) -> None:
    claude = FakeClaude((failed_run("the hook refused the edit"), 1))

    line = make_wrapper(tmp_path, claude).run("implement", CHANGE)

    assert len(claude.commands) == 1
    assert line["reason"] == "exit 1: the hook refused the edit"
    assert "unavailable" not in line


def test_a_resume_runs_on_the_model_the_waiting_run_used(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["finished"], session="t-1"), 0))
    wrapper = make_wrapper(tmp_path, claude)
    log = log_path(tmp_path, CHANGE)
    asked = record_outcome(log, "triage", VALID["question"], session="t-1", commit=COMMIT,
                           extra={"harness": "claude", "model": "claude-sonnet-5-5",
                                  "effort": "low"})

    line = wrapper.resume(CHANGE, asked["seq"], "accept")

    assert (option(claude.commands[0], "--model"), option(claude.commands[0], "--effort")) == (
        "claude-sonnet-5-5", "low")
    assert (line["model"], line["effort"]) == ("claude-sonnet-5-5", "low")


def test_a_resume_whose_model_is_unavailable_stops_and_tries_no_other(tmp_path: Path) -> None:
    claude = FakeClaude((failed_run(LIMIT), 1))
    wrapper = make_wrapper(tmp_path, claude)
    asked = record_outcome(log_path(tmp_path, CHANGE), "triage", VALID["question"],
                           session="t-1", commit=COMMIT,
                           extra={"harness": "claude", "model": "claude-sonnet-5-5"})

    line = wrapper.resume(CHANGE, asked["seq"], "accept")

    # Neither the row's first model nor any other is tried in its place.
    assert [option(command, "--model") for command in claude.commands] == ["claude-sonnet-5-5"]
    assert (line["outcome"], line["model"]) == ("stopped", "claude-sonnet-5-5")
    assert LIMIT in line["reason"]


def test_an_unavailable_model_falls_to_the_next_in_order(tmp_path: Path) -> None:
    """The step loader allows one Claude model per row today, so the fallback between
    Claude entries is proven on the wrapper's turn with the models given directly."""
    claude = FakeClaude((failed_run(LIMIT), 1), (event_lines(VALID["finished"]), 0))
    wrapper = make_wrapper(tmp_path, claude)
    rules = load_steps()["triage"]
    second = Model("claude", "second-model", "low")

    line = wrapper._turn("triage", rules, log_path(tmp_path, CHANGE), "/change-triage x",
                         (OPUS, second), session=None)

    assert [option(command, "--model") for command in claude.commands] == [
        "claude-opus-5-5", "second-model"]
    assert (line["outcome"], line["model"], line["effort"]) == ("finished", "second-model", "low")
    assert line["unavailable"] == [{**OPUS.entry(), "reason": LIMIT}]


def test_planning_resumes_design_on_the_model_design_ran_on(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["finished"], session="d-1"), 0))
    wrapper = make_wrapper(tmp_path, claude)
    record_outcome(log_path(tmp_path, CHANGE), "design", VALID["finished"],
                   session="d-1", commit=COMMIT,
                   extra={"harness": "claude", "model": "claude-opus-5-0", "effort": "max"})

    wrapper.run("plan", CHANGE)

    assert option(claude.commands[0], "--resume") == "d-1"
    assert option(claude.commands[0], "--model") == "claude-opus-5-0"


def test_a_session_from_before_models_were_recorded_resumes_on_the_steps_first(
        tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["finished"], session="d-1"), 0))
    wrapper = make_wrapper(tmp_path, claude)
    record_outcome(log_path(tmp_path, CHANGE), "design", VALID["question"],
                   session="d-1", commit=COMMIT)

    wrapper.run("plan", CHANGE)

    assert option(claude.commands[0], "--model") == "claude-opus-5-5"


def test_an_interrupted_run_is_logged_stopped_and_the_interrupt_kept(tmp_path: Path) -> None:
    def interrupted(command, cwd, feed) -> int:
        for line in event_lines(result=False):
            feed(line)
        raise KeyboardInterrupt

    wrapper = Wrapper(root=make_wrapper(tmp_path, FakeClaude()).root, runner=interrupted,
                      head=lambda _: COMMIT, clock=clock, echo=None)
    with pytest.raises(KeyboardInterrupt):
        wrapper.run("validate", CHANGE)

    line = read_log(log_path(tmp_path, CHANGE))[-1]
    assert (line["outcome"], line["session"]) == ("stopped", SESSION)
    assert line["reason"] == "the run did not finish: KeyboardInterrupt"


def test_a_last_run_without_a_session_is_not_resumed_past(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["question"], session="v-1"), 0),
                        (["Error: refused\n"], 1))
    wrapper = make_wrapper(tmp_path, claude)
    asked = wrapper.run("validate", CHANGE)
    crashed = wrapper.run("validate", CHANGE)

    with pytest.raises(StepError, match="recorded no session"):
        wrapper.resume(CHANGE, crashed["seq"], "Yes.")
    with pytest.raises(StepError, match="not validate's latest run"):
        wrapper.resume(CHANGE, asked["seq"], "Yes.")


def test_planning_resumes_its_own_latest_session_and_may_start_fresh(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["question"], session="design-1"), 0),
                        (event_lines(VALID["question"], session="plan-2"), 0),
                        (event_lines(VALID["finished"], session="plan-2"), 0),
                        (event_lines(VALID["finished"], session="plan-3"), 0))
    wrapper = make_wrapper(tmp_path, claude)
    wrapper.run("design", CHANGE)
    wrapper.run("plan", CHANGE)

    wrapper.run("plan", CHANGE)
    wrapper.run("plan", CHANGE, fresh=True)

    assert option(claude.commands[2], "--resume") == "plan-2"
    assert "--resume" not in claude.commands[3]


def test_only_implementation_takes_sections(tmp_path: Path) -> None:
    with pytest.raises(StepError, match="only implementation"):
        make_wrapper(tmp_path, FakeClaude()).run("validate", CHANGE, sections=[1])


def test_planning_after_a_design_run_without_a_session_is_refused(tmp_path: Path) -> None:
    claude = FakeClaude((["Error: refused\n"], 1), (event_lines(VALID["finished"]), 0))
    wrapper = make_wrapper(tmp_path, claude)
    wrapper.run("design", CHANGE)

    with pytest.raises(StepError, match="--fresh"):
        wrapper.run("plan", CHANGE)
    wrapper.run("plan", CHANGE, fresh=True)

    assert "--resume" not in claude.commands[1]


@pytest.mark.parametrize("kind", ["finished", "question"])
def test_a_run_that_went_on_past_a_denial_is_logged_as_it_ended_with_the_denial(
        tmp_path: Path, kind: str) -> None:
    recorded = [{"tool_name": "Bash", "tool_input": {"command": "cat x"}}]
    claude = FakeClaude((event_lines(VALID[kind], denials=recorded), 0))

    line = make_wrapper(tmp_path, claude).run("design", CHANGE)

    assert (line["outcome"], line["message"], line["denials"]) == (
        kind, VALID[kind]["message"], recorded)
