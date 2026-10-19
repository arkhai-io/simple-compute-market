"""An unattended step's outcome conforms to its schema and is kept in the workflow log."""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

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
                          "outcome": "round", "sections": [[1, 2], [3]], "by": "owner",
                          "after": 0}
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


def test_a_decision_names_who_decided_the_run_it_resolves_and_the_next_step(
        tmp_path: Path) -> None:
    log = _log(tmp_path)
    run = step.record_outcome(log, "implement", VALID["returned"], session="s", commit=COMMIT)

    line = step.note_orchestrator(log, "return to design confirmed", "the owner's word",
                                  by="owner", resolves=run["seq"], next_step="design",
                                  clock=_clock)
    review = step.note_orchestrator(log, "review again", "the owner asked", by="owner",
                                    next_step="review", kind="pre-closeout", clock=_clock)

    assert line == {"seq": 2, "at": "2026-10-21T09:15:40Z", "step": "orchestrator",
                    "outcome": "orchestrator", "by": "owner",
                    "decision": "return to design confirmed", "reason": "the owner's word",
                    "resolves": 1, "next": "design"}
    assert (review["next"], review["kind"]) == ("review", "pre-closeout")
    assert step.note_orchestrator(log, "d", "r")["by"] == "orchestrator"


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
    log = _log(tmp_path)
    step.note_orchestrator(log, "an earlier decision", "r", clock=_clock)

    with pytest.raises(step.StepError, match=problem):
        step.note_orchestrator(log, "d", "r", **fields)

    assert len(step.read_log(log)) == 1


def test_a_decision_resolves_only_a_steps_run(tmp_path: Path) -> None:
    log = _log(tmp_path)
    note = step.note_orchestrator(log, "an earlier decision", "r", clock=_clock)

    with pytest.raises(step.StepError, match="a decision resolves a step's run"):
        step.note_orchestrator(log, "d", "r", resolves=note["seq"])


# A run denied a call can still end with a question or a return, so the reading
# of its denials is recorded apart from the decision that settles its outcome.

DENIALS = [{"tool_name": "Bash", "tool_input": {"command": "gh run view 1"}, "reason": "mode"}]


def test_a_decision_reads_a_run_with_denials_without_resolving_it(tmp_path: Path) -> None:
    log = _log(tmp_path)
    run = step.record_outcome(log, "validate", {**VALID["question"], "denials": DENIALS},
                              session="s", commit=COMMIT)

    line = step.note_orchestrator(log, "gap: gh run view", "the skill names it", reads=run["seq"],
                                  clock=_clock)
    both = step.note_orchestrator(log, "gap: gh run view; rerun", "r", reads=run["seq"],
                                  resolves=run["seq"], clock=_clock)

    assert (line["reads"], "resolves" in line) == (1, False)
    assert (both["reads"], both["resolves"]) == (1, 1)


def test_a_decision_may_not_read_a_run_that_recorded_no_denial(tmp_path: Path) -> None:
    log = _log(tmp_path)
    run = step.record_outcome(log, "validate", VALID["question"], session="s", commit=COMMIT)

    with pytest.raises(step.StepError, match="recorded no denial"):
        step.note_orchestrator(log, "d", "r", reads=run["seq"])

    assert len(step.read_log(log)) == 1


def test_an_outcome_may_not_set_what_the_wrapper_records(tmp_path: Path) -> None:
    with pytest.raises(step.StepError, match="does not conform"):
        step.record_outcome(_log(tmp_path), "plan", {**VALID["finished"], "commit": "x"},
                            session="s", commit=COMMIT)


def test_sections_parse_by_session(tmp_path: Path) -> None:
    assert step.parse_sections("1,2; 3 ;5B") == [[1, 2], [3], ["5B"]]


def test_the_command_line_notes_a_round_and_prints_the_log(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = _log(tmp_path)
    step.record_outcome(log, "validate", {**VALID["question"], "denials": DENIALS},
                        session="s", commit=COMMIT)

    assert step.main(["note", CHANGE, "round", "--sections", "1;2,3", "--after", "4"],
                     root=tmp_path) == 0
    assert step.main(["note", CHANGE, "orchestrator", "--decision", "d", "--reason", "r",
                      "--by", "owner", "--next", "review", "--kind", "closeout"],
                     root=tmp_path) == 0
    assert step.main(["note", CHANGE, "orchestrator", "--decision", "gap", "--reason", "r",
                      "--reads", "1"], root=tmp_path) == 0
    capsys.readouterr()
    assert step.main(["log", CHANGE, "--last", "1"], root=tmp_path) == 0

    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    entries = step.read_log(log)[1:]
    assert [entry["outcome"] for entry in entries] == ["round", "orchestrator", "orchestrator"]
    assert (entries[0]["sections"], entries[0]["after"]) == ([[1], [2, 3]], 4)
    assert (entries[1]["by"], entries[1]["next"], entries[1]["kind"]) == (
        "owner", "review", "closeout")
    assert entries[2]["reads"] == 1
    assert [entry["seq"] for entry in printed] == [4]


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


def test_the_step_table_names_each_step() -> None:
    steps = step.load_steps()

    assert set(steps) == set(step.STEPS)
    assert all(rules.skill == f"change-{name}" for name, rules in steps.items())
    assert steps["plan"].resume_from == "design"


OPUS = step.Model("claude", "claude-opus-5-5", "high")
SONNET = step.Model("claude", "claude-sonnet-5-5", "medium")


def test_each_step_runs_on_the_models_its_work_needs() -> None:
    """Design, triage, implementation, and closeout on Opus at high effort; validation
    and archive cleanup on Sonnet at medium; the review on Codex, then Claude."""
    models = {name: rules.models for name, rules in step.load_steps().items()}

    assert models == {"design": (OPUS,), "plan": (OPUS,), "triage": (OPUS,),
                      "implement": (OPUS,), "closeout": (OPUS,), "validate": (SONNET,),
                      "archive-cleanup": (SONNET,),
                      "review": (step.Model("codex", "gpt-6-sol", "high"), OPUS)}


def test_a_review_on_claude_only_reads() -> None:
    rules = step.load_steps()["review"]
    record = f"openspec/changes/{CHANGE}/reviews/09-implementation.md"

    assert _allows(rules, "git diff dev...HEAD") and _allows(rules, "cat AGENTS.md")
    assert not any(_allows_edit(rules, tool, record) for tool in ("Edit", "Write"))
    assert not _allows(rules, "git commit -m x") and not _allows(rules, "make lock")


MODELS = 'models = [{ harness = "claude", model = "claude-opus-5-5", effort = "high" }]\n'


@pytest.mark.parametrize("models,problem", [
    ("", "needs a skill and models"),
    ("models = []\n", "a list of one or more models"),
    ('models = [{ harness = "claude", model = "claude-fable-5-1" }]\n', "never runs on"),
    ('models = [{ harness = "claude", model = "astra-2" }]\n', "never runs on"),
    ('models = [{ harness = "claude", model = "claude-opus-5-5" }, '
     '{ harness = "claude", model = "claude-sonnet-5-5" }]\n', "two models of one vendor"),
    ('models = [{ harness = "claude", effort = "high" }]\n', "without a model"),
    ('models = [{ harness = "codex", model = "gpt-6-sol" }]\n', "Codex runs only the review"),
    ('models = [{ harness = "gemini", model = "g" }]\n', "harness 'gemini'"),
    ('models = [{ harness = "claude", model = "m", speed = "fast" }]\n', "a key other than"),
])
def test_a_row_naming_models_the_policy_forbids_is_refused(
        tmp_path: Path, models: str, problem: str) -> None:
    table = tmp_path / "steps.toml"
    table.write_text(f'[steps.triage]\nskill = "change-triage"\n{models}', "utf-8")

    with pytest.raises(step.StepError, match=problem) as refused:
        step.load_steps(table)

    assert "triage row" in str(refused.value)


def _allows(rules, command: str) -> bool:
    """Whether a Bash command matches an allow rule and no deny rule, by glob."""
    def matches(rule_list) -> bool:
        return any(rule.startswith("Bash(") and fnmatch.fnmatchcase(command, rule[5:-1])
                   for rule in rule_list)
    return matches(rules.allow) and not matches(rules.deny)


def _allows_chain(rules, command: str) -> bool:
    """A chained command runs only when every command in it is allowed."""
    parts = [part.strip() for part in re.split(r"\s*(?:;|&&|\|\||\|)\s*", command)]
    return all(_allows(rules, part) for part in parts if part)


def _allows_edit(rules, tool: str, path: str) -> bool:
    """Whether editing `path` with `tool` matches an allow rule and no deny rule.

    As the harness's rules do: an `Edit` rule, bare or with a pattern, applies to
    every tool that edits a file, `Write` among them; a bare tool name applies to
    that tool; a `Write(pattern)` rule is not honoured, so it matches nothing here
    and no row may rely on one.
    """
    def matches(rule_list) -> bool:
        for rule in rule_list:
            name, _, rest = rule.partition("(")
            if name == "Edit" and fnmatch.fnmatchcase(path, rest[:-1] if rest else "*"):
                return True
            if name == tool and not rest:
                return True
        return False
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
        assert _allows(rules, "make round-view-closed CHANGE=x"), name
        assert not _allows(rules, "make round-view CHANGE=x"), name
        assert not _allows(rules, "make round-done"), name


READ_ONLY = ["ls -la .agents", "cat AGENTS.md", "head -5 x.log", "tail -n 20 x.log",
             "wc -l x.log", "grep -n seq workflow.jsonl", "echo rc=$?", "diff a b",
             "find . -name '*.md'"]
WRITING_FINDS = ["find . -name '*.pyc' -delete", "find . -name x -exec rm {} \\;",
                 "find . -execdir rm {} \\;", "find . -ok rm {} \\;", "find . -fprint out",
                 "find . -fprintf out %p", "find . -fls out"]


def test_every_step_may_run_the_read_only_utilities_but_not_a_find_that_writes() -> None:
    for name, rules in step.load_steps().items():
        assert all(_allows(rules, command) for command in READ_ONLY), name
        assert not any(_allows(rules, command) for command in WRITING_FINDS), name


def test_validation_may_run_its_skills_commands_one_per_call_or_chained() -> None:
    rules = step.load_steps()["validate"]
    chained = ("make round-view-closed; echo rc=$?; git status --porcelain "
               "--untracked-files=all; git rev-parse HEAD; git branch --show-current; "
               f"python3 scripts/find_change.py {CHANGE}; gh auth status 2>&1 | head -5")

    assert _allows_chain(rules, chained)
    assert _allows(rules, "gh run view 38723279321 --json headSha,conclusion,jobs")
    assert not _allows_chain(rules, "git status; make lock")


def test_a_step_row_without_a_skill_is_refused(tmp_path: Path) -> None:
    table = tmp_path / "steps.toml"
    table.write_text('[steps.design]\nallow = ["Read"]\n', "utf-8")

    with pytest.raises(step.StepError, match="needs a skill"):
        step.load_steps(table)


def test_validation_may_not_relock_or_commit() -> None:
    rules = step.load_steps()["validate"]

    assert {"Bash(make lock*)", "Bash(git commit*)", "Bash(git add*)"} <= set(rules.deny)


def test_validation_may_write_only_its_own_record() -> None:
    """The record is admitted by an `Edit(path)` rule, which covers every editing
    tool, since a `Write(path)` rule is not honoured. A bare `Edit` deny would
    cover the record too, so the row relies on no allow rule naming anything
    else instead."""
    rules = step.load_steps()["validate"]
    record = "openspec/changes/shape-bounds/reviews/07-validation.md"

    assert _allows_edit(rules, "Write", record)
    assert _allows_edit(rules, "Edit", record)
    assert not _allows_edit(rules, "Write", "openspec/changes/shape-bounds/reviews/08-closeout.md")
    assert not _allows_edit(rules, "Write", "scripts/run_change_step.py")
    assert not _allows_edit(rules, "Edit", "scripts/run_change_step.py")
    assert "Edit" not in rules.deny
    assert not any(rule.startswith("Write(") for rule in rules.allow)


def test_archive_cleanup_may_write_only_the_index_and_its_pull_request_draft() -> None:
    rules = step.load_steps()["archive-cleanup"]
    archived = f"openspec/changes/archive/2026-10-20-{CHANGE}"

    assert _allows_edit(rules, "Write", f"{archived}/reviews/pull-request.md")
    assert _allows_edit(rules, "Edit", f"{archived}/reviews/pull-request.md")
    assert _allows_edit(rules, "Edit", "openspec/changes/README.md")
    assert not _allows_edit(rules, "Write", f"{archived}/specs/pools/spec.md")
    assert not any(rule.startswith("Write(") for rule in rules.allow)


def test_every_step_may_compute_the_next_step_and_read_the_log() -> None:
    for name, rules in step.load_steps().items():
        assert _allows(rules, f"python3 scripts/change_next_step.py {CHANGE}"), name
        assert _allows(rules, f"python3 scripts/run_change_step.py log {CHANGE} --last 3"), name


def test_a_run_is_headless_held_to_its_rules_and_given_the_schema(tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(VALID["finished"]), 0))

    _wrapper(tmp_path, claude).run("design", CHANGE)

    command = claude.commands[0]
    rules = step.load_steps()["design"]
    assert command[:3] == ["claude", "-p", f"/change-design {CHANGE}"]
    assert _option(command, "--permission-mode") == "dontAsk"
    assert (_option(command, "--model"), _option(command, "--effort")) == (
        "claude-opus-5-5", "high")
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

    # Every line carries the run's own record of denials, the step's replaced.
    expected = {**VALID[kind], "denials": []}
    assert {key: line[key] for key in expected} == expected
    assert (line["step"], line["session"], line["commit"], line["exit_status"]) == (
        "triage", SESSION, COMMIT, 0)
    assert (line["harness"], line["model"], line["effort"]) == ("claude", "claude-opus-5-5",
                                                               "high")
    assert "unavailable" not in line
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
    asked = wrapper.run("validate", CHANGE)
    step.note_orchestrator(step.log_path(tmp_path, CHANGE), "asked the owner", "question")

    resumed = wrapper.resume(CHANGE, asked["seq"], "Delete the volume.",
                             ["Bash(kubectl delete pvc *)"])
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
    asked = wrapper.run("implement", CHANGE, arguments="section 2", sections=[2])

    line = wrapper.resume(CHANGE, asked["seq"], "Yes.")

    assert line["sections"] == [2]
    assert "granted" not in line


def test_a_resume_names_the_waiting_run_not_the_last(tmp_path: Path) -> None:
    # Validation and triage run side by side: the triage asks, then the
    # validation finishes above it, and the answer is the triage's.
    claude = FakeClaude((_event_lines(VALID["question"], session="t-1"), 0),
                        (_event_lines(VALID["finished"], session="v-1"), 0),
                        (_event_lines(VALID["finished"], session="t-1"), 0))
    wrapper = _wrapper(tmp_path, claude)
    asked = wrapper.run("triage", CHANGE)
    finished = wrapper.run("validate", CHANGE)

    line = wrapper.resume(CHANGE, asked["seq"], "Agreed.")

    assert _option(claude.commands[2], "--resume") == "t-1"
    assert (line["step"], line["session"]) == ("triage", "t-1")
    with pytest.raises(step.StepError, match="ended finished"):
        wrapper.resume(CHANGE, finished["seq"], "Agreed.")


def test_a_stopped_run_is_read_then_resumed_with_a_grant_and_not_again(
        tmp_path: Path) -> None:
    # The orchestrating session's order: the stop's denial is read first, by a
    # line that resolves nothing, and the grant resumes the read run; a line
    # that resolved it would have made the resume refuse it.
    denied = [{"tool_name": "Bash", "tool_input": {"command": "make lock"}}]
    claude = FakeClaude((_event_lines(VALID["stopped"], denials=denied, session="v-1"), 0),
                        (_event_lines(VALID["finished"], session="v-1"), 0))
    wrapper = _wrapper(tmp_path, claude)
    stopped = wrapper.run("validate", CHANGE)
    step.note_orchestrator(step.log_path(tmp_path, CHANGE),
                           "gap: proposed Bash(make lock) as a one-run grant", "r",
                           reads=stopped["seq"])

    line = wrapper.resume(CHANGE, stopped["seq"], "Go on.", ["Bash(make lock)"])

    assert _option(claude.commands[1], "--resume") == "v-1"
    assert (line["step"], line["granted"]) == ("validate", ["Bash(make lock)"])
    assert line["seq"] != stopped["seq"]
    with pytest.raises(step.StepError, match="latest run"):
        wrapper.resume(CHANGE, stopped["seq"], "Go on.")


def test_a_run_that_is_not_waiting_is_refused(tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(VALID["stopped"], session="d-1"), 0),
                        (_event_lines(VALID["question"], session="v-1"), 0))
    wrapper = _wrapper(tmp_path, claude)
    log = step.log_path(tmp_path, CHANGE)
    stopped = wrapper.run("design", CHANGE)
    resolved = step.note_orchestrator(log, "rerun it", "r", resolves=stopped["seq"])
    asked = wrapper.run("validate", CHANGE)
    step.note_orchestrator(log, "abandoned", "r", resolves=asked["seq"])
    review = step.record_outcome(log, "review", VALID["finished"], session="codex:x",
                                 commit=COMMIT, extra={"kind": "design"})

    with pytest.raises(step.StepError, match="ended stopped and a decision line resolves it"):
        wrapper.resume(CHANGE, stopped["seq"], "Go on.")
    with pytest.raises(step.StepError, match="ended question and a decision line resolves"):
        wrapper.resume(CHANGE, asked["seq"], "Go on.")
    with pytest.raises(step.StepError, match="orchestrator line, not the run of a step"):
        wrapper.resume(CHANGE, resolved["seq"], "Go on.")
    with pytest.raises(step.StepError, match="review line, not the run of a step"):
        wrapper.resume(CHANGE, review["seq"], "Go on.")
    with pytest.raises(step.StepError, match="no seq 9"):
        wrapper.resume(CHANGE, 9, "Go on.")


def test_nothing_to_resume_is_refused(tmp_path: Path) -> None:
    with pytest.raises(step.StepError, match="no seq 1"):
        _wrapper(tmp_path, FakeClaude()).resume(CHANGE, 1, "Yes.")


def test_a_resume_needs_an_answer(tmp_path: Path) -> None:
    with pytest.raises(step.StepError, match="answer"):
        _wrapper(tmp_path, FakeClaude()).resume(CHANGE, 1, "")


def test_the_command_resumes_by_seq(tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(VALID["question"], session="d-1"), 0),
                        (_event_lines(VALID["finished"], session="d-1"), 0))
    wrapper = _wrapper(tmp_path, claude)
    wrapper.run("design", CHANGE)

    assert step.main(["resume", CHANGE, "--seq", "1", "--answer", "Yes."], root=tmp_path,
                     wrapper=wrapper) == 0

    assert _option(claude.commands[1], "--resume") == "d-1"
    assert claude.commands[1][2] == "The owner's answer: Yes."


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
    second = wrapper.resume(CHANGE, first["seq"], "Option A.")

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
    assert line["reason"] == ("no model of the step is available: claude-opus-5-5: claude is "
                              "not installed: claude")
    assert line["unavailable"] == [{**OPUS.entry(),
                                    "reason": "claude is not installed: claude"}]


LIMIT = "You've hit your session limit · resets 11:20pm (Europe/Paris)"
NETWORK = "API Error: Can't reach the API server — check your internet or DNS (EAI_AGAIN)"


def _failed(said: str) -> list[str]:
    """A run Claude Code ended with an error result saying `said`."""
    return [json.dumps({"type": "system", "subtype": "init", "session_id": SESSION}) + "\n",
            json.dumps({"type": "result", "subtype": "success", "is_error": True,
                        "session_id": SESSION, "result": said,
                        "permission_denials": []}) + "\n"]


@pytest.mark.parametrize("lines", [
    _failed(LIMIT), _failed("Not logged in · Please run /login"), ["Invalid API key\n"],
])
def test_a_steps_only_model_unavailable_stops_it_saying_why(tmp_path: Path, lines) -> None:
    claude = FakeClaude((lines, 1))

    line = _wrapper(tmp_path, claude).run("triage", CHANGE)

    assert len(claude.commands) == 1
    assert line["outcome"] == "stopped"
    assert line["reason"].startswith("no model of the step is available: claude-opus-5-5: ")
    assert line["unavailable"][0]["model"] == "claude-opus-5-5"


def test_a_usage_limit_names_when_it_resets(tmp_path: Path) -> None:
    line = _wrapper(tmp_path, FakeClaude((_failed(LIMIT), 1))).run("validate", CHANGE)

    assert line["reason"] == f"no model of the step is available: claude-sonnet-5-5: {LIMIT}"
    assert (line["model"], line["effort"]) == ("claude-sonnet-5-5", "medium")


def test_a_network_error_is_retried_twice_on_the_same_model_then_stops(tmp_path: Path) -> None:
    claude = FakeClaude(*[(_failed(NETWORK), 1)] * 3)

    line = _wrapper(tmp_path, claude).run("design", CHANGE)

    assert len(claude.commands) == 3
    assert all(_option(command, "--model") == "claude-opus-5-5" for command in claude.commands)
    assert line["outcome"] == "stopped"
    assert line["reason"] == f"claude-opus-5-5 could not be reached after 3 attempts: {NETWORK}"
    assert "unavailable" not in line


def test_a_network_error_then_a_run_logs_the_run(tmp_path: Path) -> None:
    claude = FakeClaude((_failed(NETWORK), 1), (_event_lines(VALID["finished"]), 0))

    line = _wrapper(tmp_path, claude).run("design", CHANGE)

    assert claude.commands[0] == claude.commands[1]
    assert (line["outcome"], line["exit_status"]) == ("finished", 0)
    transcript = step.log_path(tmp_path, CHANGE).parent / line["transcript"]
    assert "EAI_AGAIN" in transcript.read_text("utf-8")


def test_an_ordinary_failure_is_not_read_as_an_unavailable_model(tmp_path: Path) -> None:
    claude = FakeClaude((_failed("the hook refused the edit"), 1))

    line = _wrapper(tmp_path, claude).run("implement", CHANGE)

    assert len(claude.commands) == 1
    assert line["reason"] == "exit 1: the hook refused the edit"
    assert "unavailable" not in line


def test_a_resume_runs_on_the_model_the_waiting_run_used(tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(VALID["finished"], session="t-1"), 0))
    wrapper = _wrapper(tmp_path, claude)
    log = step.log_path(tmp_path, CHANGE)
    asked = step.record_outcome(log, "triage", VALID["question"], session="t-1", commit=COMMIT,
                                extra={"harness": "claude", "model": "claude-sonnet-5-5",
                                       "effort": "low"})

    line = wrapper.resume(CHANGE, asked["seq"], "accept")

    assert (_option(claude.commands[0], "--model"), _option(claude.commands[0], "--effort")) == (
        "claude-sonnet-5-5", "low")
    assert (line["model"], line["effort"]) == ("claude-sonnet-5-5", "low")


def test_a_resume_whose_model_is_unavailable_stops_and_tries_no_other(tmp_path: Path) -> None:
    claude = FakeClaude((_failed(LIMIT), 1))
    wrapper = _wrapper(tmp_path, claude)
    asked = step.record_outcome(step.log_path(tmp_path, CHANGE), "triage", VALID["question"],
                                session="t-1", commit=COMMIT,
                                extra={"harness": "claude", "model": "claude-sonnet-5-5"})

    line = wrapper.resume(CHANGE, asked["seq"], "accept")

    # Neither the row's first model nor any other is tried in its place.
    assert [_option(command, "--model") for command in claude.commands] == ["claude-sonnet-5-5"]
    assert (line["outcome"], line["model"]) == ("stopped", "claude-sonnet-5-5")
    assert LIMIT in line["reason"]


def test_an_unavailable_model_falls_to_the_next_in_order(tmp_path: Path) -> None:
    """The step loader allows one Claude model per row today, so the fallback between
    Claude entries is proven on the wrapper's turn with the models given directly."""
    claude = FakeClaude((_failed(LIMIT), 1), (_event_lines(VALID["finished"]), 0))
    wrapper = _wrapper(tmp_path, claude)
    rules = step.load_steps()["triage"]
    second = step.Model("claude", "second-model", "low")

    line = wrapper._turn("triage", rules, step.log_path(tmp_path, CHANGE), "/change-triage x",
                         (OPUS, second), session=None)

    assert [_option(command, "--model") for command in claude.commands] == [
        "claude-opus-5-5", "second-model"]
    assert (line["outcome"], line["model"], line["effort"]) == ("finished", "second-model", "low")
    assert line["unavailable"] == [{**OPUS.entry(), "reason": LIMIT}]


def test_planning_resumes_design_on_the_model_design_ran_on(tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(VALID["finished"], session="d-1"), 0))
    wrapper = _wrapper(tmp_path, claude)
    step.record_outcome(step.log_path(tmp_path, CHANGE), "design", VALID["finished"],
                        session="d-1", commit=COMMIT,
                        extra={"harness": "claude", "model": "claude-opus-5-0", "effort": "max"})

    wrapper.run("plan", CHANGE)

    assert _option(claude.commands[0], "--resume") == "d-1"
    assert _option(claude.commands[0], "--model") == "claude-opus-5-0"


def test_a_session_from_before_models_were_recorded_resumes_on_the_steps_first(
        tmp_path: Path) -> None:
    claude = FakeClaude((_event_lines(VALID["finished"], session="d-1"), 0))
    wrapper = _wrapper(tmp_path, claude)
    step.record_outcome(step.log_path(tmp_path, CHANGE), "design", VALID["question"],
                        session="d-1", commit=COMMIT)

    wrapper.run("plan", CHANGE)

    assert _option(claude.commands[0], "--model") == "claude-opus-5-5"


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
    asked = wrapper.run("validate", CHANGE)
    crashed = wrapper.run("validate", CHANGE)

    with pytest.raises(step.StepError, match="recorded no session"):
        wrapper.resume(CHANGE, crashed["seq"], "Yes.")
    with pytest.raises(step.StepError, match="not validate's latest run"):
        wrapper.resume(CHANGE, asked["seq"], "Yes.")


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
        assert {"Edit(.claude/**)", "Write(.claude/**)"} <= set(rules.deny), name
        assert not _allows_edit(rules, "Edit", step.STEP_TABLE.relative_to(step.ROOT).as_posix()), name
        assert not _allows_edit(rules, "Write", ".claude/settings.json"), name


@pytest.mark.parametrize("table,problem", [
    (f'[steps.design]\nskill = "change-design"\n{MODELS}deny = "Bash(git push*)"\n',
     "list of rules"),
    (f'[steps.design]\nskill = "change-design"\n{MODELS}allowed = []\n', "takes only"),
    (f'[steps.deploy]\nskill = "change-deploy"\n{MODELS}', "unknown step"),
    ('[commons]\nallow = []\n', "unknown tables"),
    ('[common]\nskill = "x"\n', "common row takes only"),
    (f'[steps.plan]\nskill = "change-plan"\n{MODELS}resume_from = "design"\n', "has no row"),
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
def test_a_run_that_went_on_past_a_denial_is_logged_as_it_ended_with_the_denial(
        tmp_path: Path, kind: str) -> None:
    recorded = [{"tool_name": "Bash", "tool_input": {"command": "cat x"}}]
    claude = FakeClaude((_event_lines(VALID[kind], denials=recorded), 0))

    line = _wrapper(tmp_path, claude).run("design", CHANGE)

    assert (line["outcome"], line["message"], line["denials"]) == (
        kind, VALID[kind]["message"], recorded)


# The run id is a fixture value, not a pipeline run.
DENIED = {"tool_name": "Bash", "tool_use_id": "t1",
          "tool_input": {"command": "gh run view 123456 --json headSha"}}


def _two_turn_lines(first: dict, second: dict) -> list[str]:
    """A run denied a call in its first turn, woken for a second by a background
    task finishing: two result events, only the first listing the denial."""
    def assistant(id_: str, name: str, given: dict) -> dict:
        return {"type": "assistant", "session_id": SESSION,
                "message": {"content": [{"type": "tool_use", "id": id_, "name": name,
                                         "input": given}]}}

    def result(outcome: dict, denials: list) -> dict:
        return {"type": "result", "subtype": "success", "is_error": False,
                "session_id": SESSION, "permission_denials": denials, "result": "done",
                "structured_output": outcome}

    events = [
        {"type": "system", "subtype": "init", "session_id": SESSION},
        assistant("t1", "Bash", DENIED["tool_input"]),
        {"type": "system", "subtype": "permission_denied", "session_id": SESSION,
         "tool_use_id": "t1", "decision_reason_type": "mode"},
        result(first, [DENIED]),
        {"type": "system", "subtype": "task_notification", "session_id": SESSION},
        assistant("t2", "Bash", {"command": "tail -n 20 local/1/test.log"}),
        result(second, []),
    ]
    return [json.dumps(event) + "\n" for event in events]


def test_denials_are_gathered_over_every_turn_with_the_harness_reason(tmp_path: Path) -> None:
    claude = FakeClaude((_two_turn_lines(VALID["stopped"], VALID["finished"]), 0))

    line = _wrapper(tmp_path, claude).run("validate", CHANGE)

    assert line["outcome"] == "finished"
    assert line["denials"] == [{**DENIED, "reason": "mode"}]


def test_a_runs_denials_are_listed_with_the_calls_after_each(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    claude = FakeClaude((_two_turn_lines(VALID["stopped"], VALID["finished"]), 0))
    _wrapper(tmp_path, claude).run("validate", CHANGE)

    assert step.main(["denials", CHANGE, "1"], root=tmp_path) == 0

    assert capsys.readouterr().out.splitlines() == [
        "denied: Bash gh run view 123456 --json headSha (mode)",
        "  calls after it:",
        "    Bash tail -n 20 local/1/test.log",
    ]


def test_a_run_without_denials_or_without_a_transcript_says_so(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    claude = FakeClaude((_event_lines(VALID["finished"]), 0))
    _wrapper(tmp_path, claude).run("design", CHANGE)
    log = step.log_path(tmp_path, CHANGE)
    # A review's line has no transcript to read: Codex's session is its own log.
    step.record_outcome(log, "review", {**VALID["stopped"], "denials": []}, session=None,
                        commit=COMMIT, extra={"kind": "design"})
    step.record_outcome(log, "review", VALID["stopped"], session=None, commit=COMMIT,
                        extra={"kind": "design"})

    assert step.main(["denials", CHANGE, "1"], root=tmp_path) == 0
    assert capsys.readouterr().out == "seq 1: the design run recorded no denial\n"
    assert step.main(["denials", CHANGE, "2"], root=tmp_path) == 0
    assert capsys.readouterr().out == "seq 2: the review run recorded no denial\n"
    assert step.main(["denials", CHANGE, "3"], root=tmp_path) == 1
    assert "no transcript" in capsys.readouterr().err
    assert step.main(["denials", CHANGE, "9"], root=tmp_path) == 1
    assert "no seq 9" in capsys.readouterr().err


def test_a_backwards_section_range_is_refused(tmp_path: Path,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    assert step.main(["run", "implement", CHANGE, "--sections", "3-1"], root=tmp_path,
                     wrapper=_wrapper(tmp_path, FakeClaude())) == 1
    assert "runs backwards" in capsys.readouterr().err


# Reviews: run read-only in Codex, published only when they are reviews.

# The commit each review is told it reviews; HEAD is injected, never read from Git.
HEAD = "0123456789abcdef0123456789abcdef01234567"
FINDING = """### F1 — The override has no carrier

- **Lens:** architecture
- **Basis:** evidence
- **Severity:** blocking
- **Evidence:** `kit/pool-overrides/records.py:43`

The record has no field for it.

**Suggested action:** Choose one.
"""


def _review(kind: str = "design", findings: str = FINDING) -> str:
    return (f"# {kind.capitalize()} review — {CHANGE}\n\n## Summary\n\nWhat it does.\n\n"
            "## Assessment\n\nSound.\n\n## Questions\n\n### consistency — Is it consistent?\n\n"
            f"Yes.\n\n## Findings\n\n{findings}\n## Readiness\n\nNot yet.\n")


def _repository(tmp_path: Path, *records: str) -> Path:
    reviews = tmp_path / "openspec/changes" / CHANGE / "reviews"
    reviews.mkdir(parents=True)
    for name in records:
        (reviews / name).parent.mkdir(parents=True, exist_ok=True)
        (reviews / name).write_text("x", "utf-8")
    return tmp_path


def _writing(text: str, status: int = 0, calls: list[list[str]] | None = None,
             session: str = "s-1"):
    def runner(command: Sequence[str], log: Path) -> int:
        if calls is not None:
            calls.append(list(command))
        log.write_text(f"--------\nsession id: {session}\n--------\nsession output\n", "utf-8")
        Path(command[command.index("--output-last-message") + 1]).write_text(text, "utf-8")
        return status
    return runner


def _reviews(root: Path) -> Path:
    return root / "openspec/changes" / CHANGE / "reviews"


def test_a_review_is_published_and_its_transcript_kept_apart(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    kind = "design"

    path = step.run_review(CHANGE, kind, root=root, runner=_writing(_review()), head=lambda _: HEAD)

    assert path == _reviews(root) / f"01-{kind}.md"
    assert path.read_text("utf-8") == (_review().rstrip("\n") + "\n\n"
                                       "<!-- reviewer-session: codex:s-1 -->\n"
                                       "<!-- reviewer: codex gpt-6-sol high -->\n"
                                       f"<!-- reviewed-commit: {HEAD} -->\n")
    assert (_reviews(root) / "transcripts" / "01-design.log").is_file()
    assert sorted(p.name for p in _reviews(root).iterdir()) == [path.name, "transcripts"]


def test_numbering_follows_records_and_transcripts(tmp_path: Path) -> None:
    root = _repository(tmp_path, "01-design.log", "02-validation.log", "transcripts/03-implementation.log")

    path = step.run_review(CHANGE, "implementation", root=root,
                               runner=_writing(_review("implementation")), head=lambda _: HEAD)

    assert path.name == "04-implementation.md"


def test_reviewer_runs_read_only_with_the_skill(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    calls: list[list[str]] = []

    step.run_review(CHANGE, "pre-closeout", base="main", model="m1", effort="high", root=root,
                        unvalidated=True, runner=_writing(_review("pre-closeout"), calls=calls), head=lambda _: HEAD)

    command = calls[0]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--model") + 1] == "m1"
    assert command[command.index("--config") + 1] == 'model_reasoning_effort="high"'
    assert command[-1] == ("Use the change-review skill. Review kind: pre-closeout. "
                           f"Change: {CHANGE}. Base: main.")


def test_design_review_names_no_base(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    calls: list[list[str]] = []

    step.run_review(CHANGE, "design", root=root, runner=_writing(_review(), calls=calls), head=lambda _: HEAD)

    assert "Base:" not in calls[0][-1]


def test_a_review_runs_on_the_review_rows_codex_entry(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    calls: list[list[str]] = []

    step.run_review(CHANGE, "design", root=root, runner=_writing(_review(), calls=calls),
                    head=lambda _: HEAD)

    assert calls[0][calls[0].index("--model") + 1] == "gpt-6-sol"
    assert calls[0][calls[0].index("--config") + 1] == 'model_reasoning_effort="high"'


def test_a_given_model_overrides_only_the_codex_entry() -> None:
    rules = step.load_steps()["review"]

    assert step.review_models(rules, "gpt-6.1-sol") == (
        step.Model("codex", "gpt-6.1-sol", "high"), OPUS)
    assert step.review_models(rules, effort="low") == (step.Model("codex", "gpt-6-sol", "low"),
                                                       OPUS)
    assert step.review_models(rules) == rules.models


def test_a_review_with_no_findings_is_accepted(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    path = step.run_review(CHANGE, "design", root=root,
                               runner=_writing(_review(findings="None: the change needs none.\n")), head=lambda _: HEAD)

    assert path.is_file()


@pytest.mark.parametrize("text,status,reason", [
    ("", 0, "empty"),
    (_review(), 1, "exited 1"),
    ("ERROR: the model is not supported\n", 0, "title"),
    (_review().replace("## Questions", "## Notes"), 0, "missing section '## Questions'"),
    (_review().replace("- **Basis:** evidence\n", ""), 0, "F1 has no Basis"),
    (_review().replace("blocking", "urgent"), 0, "F1 has Severity 'urgent'"),
    (_review("implementation"), 0, "title"),
])
def test_output_that_is_not_a_review_publishes_nothing(
    tmp_path: Path, text: str, status: int, reason: str
) -> None:
    root = _repository(tmp_path)

    with pytest.raises(step.ReviewError, match=reason):
        step.run_review(CHANGE, "design", root=root, runner=_writing(text, status), head=lambda _: HEAD)

    assert [p.name for p in _reviews(root).iterdir()] == ["transcripts"]
    assert (_reviews(root) / "transcripts" / "01-design.log").is_file()


def test_rejected_output_is_kept_with_its_transcript(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    with pytest.raises(step.ReviewError):
        step.run_review(CHANGE, "design", root=root, runner=_writing("ERROR: refused\n"), head=lambda _: HEAD)

    rejected = _reviews(root) / "transcripts" / "01-design.rejected.md"
    assert rejected.read_text("utf-8") == "ERROR: refused\n"


@pytest.mark.parametrize("change,kind", [("missing", "design"), ("archive", "design"), ("../x", "design"),
                                         (CHANGE, "triage")])
def test_unknown_change_or_kind_is_refused(tmp_path: Path, change: str, kind: str) -> None:
    root = _repository(tmp_path)

    with pytest.raises(step.ReviewError):
        step.run_review(change, kind, root=root, runner=_writing(_review()), head=lambda _: HEAD)


def test_a_closeout_review_of_an_archived_change_is_recorded_in_the_archive(tmp_path: Path) -> None:
    archived = tmp_path / "openspec/changes/archive" / f"2026-10-14-{CHANGE}"
    archived.mkdir(parents=True)

    path = step.run_review(CHANGE, "closeout", root=tmp_path,
                               runner=_writing(_review("closeout")), head=lambda _: HEAD)

    assert path == archived / "reviews" / "01-closeout.md"


def test_a_closeout_review_of_an_active_change_is_refused(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    calls: list[list[str]] = []

    with pytest.raises(step.ReviewError, match="not archived"):
        step.run_review(CHANGE, "closeout", root=root, head=lambda _: HEAD,
                            runner=_writing(_review("closeout"), calls=calls))

    assert calls == []
    assert not (_reviews(root) / "transcripts").exists()


def test_a_later_review_continues_the_last_reviewer_read_only(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    step.run_review(CHANGE, "design", root=root, runner=_writing(_review(), session="first"), head=lambda _: HEAD)
    calls: list[list[str]] = []

    path = step.run_review(CHANGE, "design", root=root,
                               runner=_writing(_review(), calls=calls, session="first"), head=lambda _: HEAD)

    command = calls[0]
    assert command[:4] == ["codex", "exec", "resume", "first"]
    assert command[command.index("--config") + 1] == 'sandbox_mode="read-only"'
    assert "01-design" in command[-1] and "triage records" in command[-1]
    assert path.stem == "02-design"
    assert path.read_text("utf-8").count("<!-- reviewer-session: codex:first -->\n") == 1


def test_an_untagged_reviewer_session_is_continued_in_codex(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    kind = "design"
    (_reviews(root) / f"01-{kind}.md").write_text(
        _review() + "\n<!-- reviewer-session: old -->\n", "utf-8")
    calls: list[list[str]] = []

    step.run_review(CHANGE, "design", root=root, runner=_writing(_review(), calls=calls),
                    head=lambda _: HEAD)

    assert calls[0][:4] == ["codex", "exec", "resume", "old"]


def test_fresh_starts_a_new_reviewer(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    step.run_review(CHANGE, "design", root=root, runner=_writing(_review(), session="first"), head=lambda _: HEAD)
    calls: list[list[str]] = []

    step.run_review(CHANGE, "design", fresh=True, root=root,
                        runner=_writing(_review(), calls=calls, session="second"), head=lambda _: HEAD)

    assert calls[0][:3] == ["codex", "exec", "--sandbox"]


def test_a_review_of_another_kind_does_not_continue(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    step.run_review(CHANGE, "design", root=root, runner=_writing(_review(), session="first"), head=lambda _: HEAD)
    calls: list[list[str]] = []

    step.run_review(CHANGE, "implementation", root=root,
                        runner=_writing(_review("implementation"), calls=calls), head=lambda _: HEAD)

    assert "resume" not in calls[0]


def test_an_external_review_is_never_continued(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (_reviews(root) / "01-design-external.md").write_text(_review(), "utf-8")
    calls: list[list[str]] = []

    step.run_review(CHANGE, "design", root=root, runner=_writing(_review(), calls=calls), head=lambda _: HEAD)

    assert "resume" not in calls[0]


CODEX_SESSION = """Reading additional input from stdin...
OpenAI Codex v0.157.0
--------
workdir: /repo
model: gpt-6-sol
sandbox: read-only
session id: abc
--------
user
Use the change-review skill.
codex
I'll load the guidance first.
exec
/bin/bash -lc 'cat AGENTS.md' in /repo
 succeeded in 0ms:
# Repository Engineering Guidance
exec
/bin/bash -lc 'rg missing' in /repo
 exited 1 in 4ms:
codex
# Design review — shape-bounds
one
two
three
four
five
tokens used
83,133
# Design review — shape-bounds
"""


def _shown(text: str) -> list[str]:
    progress = step.Progress()
    shown = [out for line in text.splitlines(keepends=True) for out in progress.feed(line)]
    return shown + progress.close()


def test_progress_shows_commands_and_messages_not_file_contents() -> None:
    shown = _shown(CODEX_SESSION)

    assert shown[:3] == ["model: gpt-6-sol", "sandbox: read-only", "session id: abc"]
    assert "» I'll load the guidance first." in shown
    assert "$ cat AGENTS.md" in shown
    assert "  ✗ exited 1 in 4ms:" in shown
    assert not any("Repository Engineering Guidance" in line for line in shown)
    assert not any("Use the change-review skill" in line for line in shown)
    assert shown[-1] == "tokens used: 83,133"


def test_progress_cuts_long_messages_short() -> None:
    shown = _shown(CODEX_SESSION)

    review = [line for line in shown if line.startswith("» ") and "load the guidance" not in line]
    assert review[0] == "» # Design review — shape-bounds"
    assert review[-1] == "» … (2 more lines in the transcript)"
    assert len(review) == step.Progress.MESSAGE_LINES + 1


def test_progress_always_shows_errors() -> None:
    assert _shown("model: m\nERROR: the model is not supported\n") == [
        "model: m", "ERROR: the model is not supported"]


def test_a_record_written_during_the_run_takes_the_earlier_number(tmp_path: Path) -> None:
    root = _repository(tmp_path, "01-design.log")
    inner = _writing(_review("implementation"))

    def runner(command: Sequence[str], log: Path) -> int:
        # A validation started beside the review publishes its record meanwhile.
        (_reviews(root) / "02-validation.md").write_text("x", "utf-8")
        return inner(command, log)

    path = step.run_review(CHANGE, "implementation", root=root, runner=runner, head=lambda _: HEAD)

    assert path.name == "03-implementation.md"
    assert (_reviews(root) / "transcripts" / "03-implementation.log").is_file()
    assert not list((_reviews(root) / "transcripts").glob("pending-*"))



def _validation(commit: str, result: str) -> str:
    return (f"# Validation — {CHANGE} — {commit[:12]}\n\n- **Commit:** {commit} on feat/x\n"
            f"- **Result:** {result} — why\n")


@pytest.mark.parametrize("records, reason", [
    ({}, "no validation record"),
    ({"03-validation.md": _validation("f" * 40, "passed")}, "not HEAD"),
    ({"03-validation.md": _validation(HEAD, "inconclusive")}, "inconclusive, not passed"),
    ({"03-validation.md": _validation(HEAD, "passed"),
      "05-validation.md": _validation(HEAD, "failed")}, "05-validation.md's result is failed"),
])
def test_a_pre_closeout_review_needs_a_passing_validation_of_head(
    tmp_path: Path, records: dict[str, str], reason: str
) -> None:
    root = _repository(tmp_path)
    for name, text in records.items():
        (_reviews(root) / name).write_text(text, "utf-8")
    calls: list[list[str]] = []

    with pytest.raises(step.ReviewError, match=reason):
        step.run_review(CHANGE, "pre-closeout", root=root, head=lambda _: HEAD,
                            runner=_writing(_review("pre-closeout"), calls=calls))

    assert calls == []


def test_a_passing_validation_of_head_admits_a_pre_closeout_review(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (_reviews(root) / "03-validation.md").write_text(_validation(HEAD, "passed"), "utf-8")

    path = step.run_review(CHANGE, "pre-closeout", root=root, head=lambda _: HEAD,
                               runner=_writing(_review("pre-closeout")))

    assert path.name == "04-pre-closeout.md"


VALIDATED = "f" * 40
RECORDS = f"openspec/changes/{CHANGE}"


@pytest.mark.parametrize("changed, reason", [
    ([f"{RECORDS}/interventions.jsonl", f"{RECORDS}/reviews/05-validation.triage.md"], None),
    ([], None),
    ([f"{RECORDS}/interventions.jsonl", f"{RECORDS}/notes.txt"], f"also changes {RECORDS}/notes.txt"),
    (["openspec/changes/other/interventions.jsonl", "openspec/changes/other/reviews/01-review.txt"],
     None),
    (["openspec/changes/other/notes.jsonl"], "also changes openspec/changes/other/notes.jsonl"),
    (["openspec/changes/interventions.jsonl"], "also changes openspec/changes/interventions.jsonl"),
    (["openspec/changes/archive/interventions.jsonl"], "also changes openspec/changes/archive/"),
    (["openspec/changes/archive/reviews/01-closeout.md"], "also changes openspec/changes/archive/"),
    ([f"openspec/changes/archive/2026-10-20-{CHANGE}/interventions.jsonl",
      f"openspec/changes/archive/2026-10-20-{CHANGE}/reviews/09-closeout.triage.md"], None),
    (None, "not HEAD"),
])
def test_a_validation_of_an_ancestor_clears_head_when_only_records_changed(
    tmp_path: Path, changed: list[str] | None, reason: str | None
) -> None:
    root = _repository(tmp_path)
    (_reviews(root) / "03-validation.md").write_text(_validation(VALIDATED, "passed"), "utf-8")
    compared: list[tuple[str, str]] = []

    def changed_since(_: Path, commit: str, head: str) -> list[str] | None:
        compared.append((commit, head))
        return changed

    problem = step.validation_problem(_reviews(root), HEAD, root, changed_since)

    assert compared == [(VALIDATED, HEAD)]
    if reason is None:
        assert problem is None
    else:
        assert problem is not None and reason in problem


def test_a_ledger_commit_after_validation_admits_a_pre_closeout_review(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (_reviews(root) / "03-validation.md").write_text(_validation(VALIDATED, "passed"), "utf-8")

    path = step.run_review(
        CHANGE, "pre-closeout", root=root, head=lambda _: HEAD,
        changed_since=lambda *_: [f"{RECORDS}/interventions.jsonl"],
        runner=_writing(_review("pre-closeout")))

    assert path.name == "04-pre-closeout.md"


def test_the_paths_changed_since_are_read_from_git(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True,
                              check=True).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (tmp_path / "ledger.jsonl").write_text("1\n", "utf-8")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (tmp_path / "ledger.jsonl").write_text("1\n2\n", "utf-8")
    (tmp_path / "név.md").write_text("x", "utf-8")
    git("add", ".")
    git("commit", "-qm", "records")
    head = git("rev-parse", "HEAD")

    assert sorted(step._changed_since(tmp_path, base, head)) == ["ledger.jsonl", "név.md"]
    git("mv", "ledger.jsonl", "moved.jsonl")
    git("commit", "-qm", "rename")

    assert sorted(step._changed_since(tmp_path, head, git("rev-parse", "HEAD"))) == [
        "ledger.jsonl", "moved.jsonl"]
    assert step._changed_since(tmp_path, head, base) is None
    assert step._changed_since(tmp_path, "e" * 40, head) is None


def test_the_owner_may_run_a_pre_closeout_review_unvalidated(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    path = step.run_review(CHANGE, "pre-closeout", root=root, unvalidated=True,
                               head=lambda _: HEAD, runner=_writing(_review("pre-closeout")))

    assert path.name == "01-pre-closeout.md"


def test_an_implementation_review_never_waits_for_validation(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    path = step.run_review(CHANGE, "implementation", root=root, head=lambda _: HEAD,
                               runner=_writing(_review("implementation")))

    assert path.name == "01-implementation.md"


def test_make_review_passes_the_override() -> None:
    command = "\n".join(_make_n("review", f"CHANGE={CHANGE}", "KIND=pre-closeout",
                                "UNVALIDATED=1"))

    assert "scripts/run_change_step.py review" in command and "--unvalidated" in command


def test_make_closeout_opens_the_closeout_skill() -> None:
    command = "\n".join(_make_n("closeout", f"CHANGE={CHANGE}", keep_checks=True))

    assert "scripts/find_change.py" in command and "--active" not in command
    assert f"\"/change-closeout {CHANGE}\"" in command


def test_make_archive_cleanup_takes_only_an_archived_change() -> None:
    command = "\n".join(_make_n("archive-cleanup", f"CHANGE={CHANGE}", keep_checks=True))

    assert "scripts/find_change.py --archived" in command
    assert f"\"/change-archive-cleanup {CHANGE}\"" in command


def test_an_interrupted_run_still_numbers_its_transcript(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    def runner(command: Sequence[str], log: Path) -> int:
        log.write_text("partial\n", "utf-8")
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        step.run_review(CHANGE, "design", root=root, runner=runner, head=lambda _: HEAD)

    transcripts = _reviews(root) / "transcripts"
    assert [p.name for p in transcripts.iterdir()] == ["01-design.log"]


@pytest.mark.parametrize("record, admitted", [
    (f"- **Commit:** {HEAD[:12]} on feat/x\n- **Result:** passed — why\n", True),
    (f"- **Commit:** `{HEAD}` on feat/x\n- **Result:** passed — why\n", False),
    (f"- **Commit:** {HEAD} on feat/x\n- **Result:** **passed**\n", False),
])
def test_the_validation_record_lines_are_read_exactly(
    tmp_path: Path, record: str, admitted: bool
) -> None:
    reviews = _reviews(_repository(tmp_path))
    (reviews / "02-validation.md").write_text(record, "utf-8")

    assert (step.validation_problem(reviews, HEAD) is None) is admitted


def test_a_claimed_name_is_never_overwritten(tmp_path: Path) -> None:
    reviews = _reviews(_repository(tmp_path))
    taken = reviews / "03-validation.md"
    taken.write_text("another writer's record", "utf-8")
    proposals = iter([taken, reviews / "04-validation.md"])

    claimed = step.claim_record(reviews, "validation", propose=lambda *_: next(proposals))

    assert claimed.name == "04-validation.md"
    assert taken.read_text("utf-8") == "another writer's record"


def test_an_interrupted_run_leaves_no_empty_record(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    def runner(command: Sequence[str], log: Path) -> int:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        step.run_review(CHANGE, "design", root=root, runner=runner, head=lambda _: HEAD)

    assert sorted(p.name for p in _reviews(root).iterdir()) == ["transcripts"]


def test_the_proposed_number_advances_past_a_record_written_meanwhile(tmp_path: Path) -> None:
    reviews = _reviews(_repository(tmp_path, "01-design.log"))
    (reviews / "02-validation.md").write_text("another writer's record", "utf-8")

    claimed = step.claim_record(reviews, "validation")

    assert claimed.name == "03-validation.md"
    assert (reviews / "02-validation.md").read_text("utf-8") == "another writer's record"


# The workflow targets, interactive and unattended.

def _make_n(*arguments: str, keep_checks: bool = False) -> list[str]:
    """`make -n` of a target, with no step variable inherited from the caller.

    A make that ran these tests passes its own command-line variables down through
    MAKEFLAGS, so those are dropped too.
    """
    env = {key: value for key, value in os.environ.items()
           if key not in ("UNATTENDED", "SECTION", "SECTIONS", "FRESH", "HELM_ALL_SCENARIOS",
                          "REVIEW_BASE", "REVIEW_MODEL", "REVIEW_EFFORT", "UNVALIDATED",
                          "MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "MAKELEVEL")}
    output = subprocess.run(["make", "-n", "--no-print-directory", *arguments],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True,
                            text=True, check=True, env=env).stdout
    return [line for line in output.splitlines() if keep_checks
            or ("find_change.py" not in line and "round_view.py" not in line)]


@pytest.mark.parametrize("target,interactive,unattended", [
    ("design", 'claude "/change-design X"', 'run design "X"'),
    ("plan", 'claude "/change-plan X"', 'run plan "X"'),
    ("triage", 'claude "/change-triage X"', 'run triage "X"'),
    ("validate", 'claude "/change-validate X"', 'run validate "X"'),
    ("closeout", 'claude "/change-closeout X"', 'run closeout "X"'),
    ("archive-cleanup", 'claude "/change-archive-cleanup X"', 'run archive-cleanup "X"'),
    ("implement", 'claude "/change-implement X"', 'run implement "X"'),
])
def test_a_step_target_is_interactive_unless_unattended(
        target: str, interactive: str, unattended: str) -> None:
    assert _make_n(target, "CHANGE=X") == [interactive]
    assert _make_n(target, "CHANGE=X", "UNATTENDED=1") == [
        f"python3 scripts/run_change_step.py {unattended}"]


@pytest.mark.parametrize("variable,interactive,unattended", [
    ("SECTION=2", "section 2", '--sections "2"'),
    ("SECTIONS=1-3", "sections 1-3", '--sections "1-3"'),
])
def test_implementation_targets_pass_their_sections(
        variable: str, interactive: str, unattended: str) -> None:
    assert _make_n("implement", "CHANGE=X", variable) == [
        f'claude "/change-implement X {interactive}"']
    assert _make_n("implement", "CHANGE=X", variable, "UNATTENDED=1") == [
        f'python3 scripts/run_change_step.py run implement "X" {unattended}']


def test_unattended_planning_may_start_fresh_and_validation_take_every_scenario() -> None:
    assert _make_n("plan", "CHANGE=X", "UNATTENDED=1", "FRESH=1") == [
        'python3 scripts/run_change_step.py run plan "X" --fresh']
    assert _make_n("validate", "CHANGE=X", "UNATTENDED=1", "HELM_ALL_SCENARIOS=1") == [
        'python3 scripts/run_change_step.py run validate "X" '
        '--arguments "with HELM_ALL_SCENARIOS=1"']


def test_make_review_runs_the_wrappers_review() -> None:
    assert _make_n("review", "CHANGE=X", "KIND=design") == [
        'python3 scripts/run_change_step.py review "X" --kind "design" --base "dev"    ']


def test_make_review_passes_a_codex_model_for_one_run() -> None:
    assert _make_n("review", "CHANGE=X", "KIND=design", "REVIEW_MODEL=gpt-6.1-sol",
                   "REVIEW_EFFORT=low") == [
        'python3 scripts/run_change_step.py review "X" --kind "design" --base "dev" '
        '--model "gpt-6.1-sol" --effort "low"  ']


def test_make_orchestrate_opens_the_session_on_opus_at_medium_effort() -> None:
    assert _make_n("orchestrate", "CHANGE=X") == [
        'claude --model claude-opus-5-5 --effort medium "/change-orchestrate X"']


# A review's outcome in the workflow log.

def test_a_published_review_is_logged_finished_naming_its_record_and_commit(
        tmp_path: Path) -> None:
    root = _repository(tmp_path)
    kind = "design"

    line = step.review_and_log(CHANGE, kind, root=root, clock=_clock,
                               runner=_writing(_review(), session="codex-1"),
                               head=lambda _: HEAD)

    assert line == {"seq": 1, "at": "2026-10-21T09:15:40Z", "step": "review",
                    "session": "codex:codex-1", "commit": HEAD, "kind": "design",
                    "record": f"01-{kind}.md", "harness": "codex", "model": "gpt-6-sol",
                    "effort": "high", "outcome": "finished", "next": "triage",
                    "message": f"01-{kind}.md written; triage is next"}


def _claude_review(text: str, session: str = "c-1", denials: list | None = None) -> FakeClaude:
    """Claude Code ending a review run with `text` as its final message."""
    events = [{"type": "system", "subtype": "init", "session_id": session},
              {"type": "result", "subtype": "success", "is_error": False, "session_id": session,
               "result": text, "permission_denials": denials or []}]
    return FakeClaude(([json.dumps(event) + "\n" for event in events], 0))


def _codex_saying(said: str, status: int = 1):
    def runner(command: Sequence[str], log: Path) -> int:
        with log.open("a", encoding="utf-8") as stream:
            stream.write(f"OpenAI Codex v0.157.0\n{said}\n")
        return status
    return runner


def _codex_missing(command: Sequence[str], log: Path) -> int:
    raise FileNotFoundError("codex")


@pytest.mark.parametrize("codex,why", [
    (_codex_missing, "codex is not installed: codex"),
    (_codex_saying("ERROR: Not logged in. Run codex login."), "ERROR: Not logged in. Run codex login."),
    (_codex_saying("ERROR: You've hit your usage limit. Try again at 3:05 PM."),
     "ERROR: You've hit your usage limit. Try again at 3:05 PM."),
])
def test_a_review_falls_back_to_claude_when_codex_is_unavailable(
        tmp_path: Path, codex, why: str) -> None:
    root = _repository(tmp_path)
    claude = _claude_review(_review("implementation"))

    line = step.review_and_log(CHANGE, "implementation", root=root, clock=_clock, runner=codex,
                               claude=claude, head=lambda _: HEAD, echo=None)

    command = claude.commands[0]
    assert command[:3] == ["claude", "-p", ("Use the change-review skill. Review kind: "
                                            f"implementation. Change: {CHANGE}. Base: dev.")]
    assert "--json-schema" not in command
    assert (_option(command, "--model"), _option(command, "--effort")) == ("claude-opus-5-5",
                                                                           "high")
    assert _rules(command, "--allowedTools") == list(step.load_steps()["review"].allow)
    assert "Edit" in _rules(command, "--disallowedTools")
    record = _reviews(root) / "01-implementation.md"
    text = record.read_text("utf-8")
    assert "<!-- reviewer-session: claude:c-1 -->" in text
    assert "<!-- reviewer: claude claude-opus-5-5 high -->" in text
    assert f"<!-- reviewer-unavailable: codex gpt-6-sol: {why} -->" in text
    assert (line["outcome"], line["record"], line["session"]) == (
        "finished", "01-implementation.md", "claude:c-1")
    assert (line["harness"], line["model"], line["effort"]) == ("claude", "claude-opus-5-5",
                                                               "high")
    assert line["unavailable"] == [{"harness": "codex", "model": "gpt-6-sol", "reason": why}]
    assert line["transcript"] == "transcripts/01-implementation.log"
    assert line["denials"] == []
    assert "codex gpt-6-sol being unavailable" in line["message"]


def test_a_claude_reviews_denials_are_recorded_from_its_transcript(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    denied = [{"tool_name": "Edit", "tool_use_id": "t1",
               "tool_input": {"file_path": "scripts/x.py"}}]
    claude = _claude_review(_review(), denials=denied)

    line = step.review_and_log(CHANGE, "design", root=root, clock=_clock, runner=_codex_missing,
                               claude=claude, head=lambda _: HEAD, echo=None)

    assert line["denials"] == denied


def test_a_claude_review_continues_only_a_claude_reviewer(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    step.run_review(CHANGE, "design", root=root, runner=_codex_missing,
                    claude=_claude_review(_review(), session="c-1"), head=lambda _: HEAD,
                    echo=None)
    again = _claude_review(_review(), session="c-1")

    step.run_review(CHANGE, "design", root=root, runner=_codex_missing, claude=again,
                    head=lambda _: HEAD, echo=None)
    calls: list[list[str]] = []
    step.run_review(CHANGE, "design", root=root, runner=_writing(_review(), calls=calls),
                    head=lambda _: HEAD)

    assert _option(again.commands[0], "--resume") == "c-1"
    assert "01-design" in again.commands[0][2]
    # Codex is available again, and starts fresh rather than resuming Claude's session.
    assert calls[0][:3] == ["codex", "exec", "--sandbox"]


def test_a_review_with_no_reviewer_available_publishes_nothing(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    def missing(command, cwd, feed) -> int:
        raise FileNotFoundError("claude")

    line = step.review_and_log(CHANGE, "design", root=root, clock=_clock, runner=_codex_missing,
                               claude=missing, head=lambda _: HEAD, echo=None)

    assert line["outcome"] == "stopped"
    assert line["reason"] == ("the reviewer produced no review: no reviewer is available: "
                              "codex gpt-6-sol: codex is not installed: codex; claude "
                              "claude-opus-5-5: claude is not installed: claude")
    assert [entry["model"] for entry in line["unavailable"]] == ["gpt-6-sol", "claude-opus-5-5"]
    assert not [p for p in _reviews(root).iterdir() if p.suffix == ".md"]


def test_a_failed_claude_reviews_denials_are_on_its_stopped_line(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    denied = [{"tool_name": "Edit", "tool_use_id": "t1", "tool_input": {}}]

    line = step.review_and_log(CHANGE, "design", root=root, clock=_clock, runner=_codex_missing,
                               claude=_claude_review("not a review", denials=denied),
                               head=lambda _: HEAD, echo=None)

    assert line["outcome"] == "stopped"
    assert (line["denials"], line["transcript"]) == (denied, "transcripts/01-design.log")
    assert line["unavailable"][0]["harness"] == "codex"


def test_a_reviewers_output_mentioning_a_limit_is_not_read_as_codex_unavailable(
        tmp_path: Path) -> None:
    root = _repository(tmp_path)
    claude = FakeClaude()

    line = step.review_and_log(CHANGE, "design", root=root, clock=_clock,
                               runner=_codex_saying("exec\ncat scripts/x.py\n"
                                                    "# a usage limit, a connection error"),
                               claude=claude, head=lambda _: HEAD, echo=None)

    assert claude.commands == []
    assert line["reason"].startswith("the reviewer produced no review: the reviewer exited 1")


def test_a_reviews_network_error_is_retried_and_never_falls_back(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    calls: list[list[str]] = []

    def unreachable(command: Sequence[str], log: Path) -> int:
        calls.append(list(command))
        return _codex_saying("ERROR: stream error: connection error; retrying")(command, log)

    line = step.review_and_log(CHANGE, "design", root=root, clock=_clock, runner=unreachable,
                               claude=FakeClaude(), head=lambda _: HEAD, echo=None)

    assert len(calls) == 3
    assert line["outcome"] == "stopped"
    assert "gpt-6-sol could not be reached after 3 attempts" in line["reason"]


def test_a_failed_review_beside_an_earlier_record_is_logged_stopped(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    kind = "design"
    (_reviews(root) / f"01-{kind}.md").write_text(_review(), "utf-8")

    line = step.review_and_log(CHANGE, "design", root=root, clock=_clock,
                               runner=_writing("ERROR: refused\n"), head=lambda _: HEAD)

    assert (line["outcome"], line["commit"], line["session"]) == ("stopped", HEAD, None)
    assert line["reason"].startswith("the reviewer produced no review")
    assert "record" not in line


def test_a_review_refused_before_it_runs_is_logged_stopped(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    line = step.review_and_log(CHANGE, "pre-closeout", root=root, clock=_clock,
                               runner=_writing(_review("pre-closeout")), head=lambda _: HEAD)

    assert line["outcome"] == "stopped"
    assert "no validation record" in line["reason"]


def test_an_interrupted_review_is_logged_stopped(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    def runner(command, log: Path) -> int:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        step.review_and_log(CHANGE, "design", root=root, clock=_clock, runner=runner,
                            head=lambda _: HEAD)

    line = step.read_log(step.log_path(root, CHANGE))[-1]
    assert (line["outcome"], line["reason"]) == (
        "stopped", "the review did not finish: KeyboardInterrupt")


def test_the_review_command_exits_non_zero_when_it_stops(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path)

    assert step.main(["review", CHANGE, "--kind", "closeout"], root=root) == 1

    captured = capsys.readouterr()
    assert "not archived" in captured.err
    assert json.loads(captured.out)["outcome"] == "stopped"


def test_a_review_quoting_an_earlier_records_markers_is_logged_with_its_own(
        tmp_path: Path) -> None:
    root = _repository(tmp_path)
    quoted = _review().replace("The record has no field for it.",
                               "The earlier record ends `<!-- reviewer-session: old -->` and "
                               f"`<!-- reviewed-commit: {'e' * 40} -->`.")

    line = step.review_and_log(CHANGE, "design", root=root, clock=_clock,
                               runner=_writing(quoted, session="new"), head=lambda _: HEAD)

    assert (line["session"], line["commit"]) == ("codex:new", HEAD)


def test_a_reviewer_that_cannot_start_is_logged_stopped_with_head(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    def broken(command, log: Path) -> int:
        raise PermissionError("codex")

    line = step.review_and_log(CHANGE, "design", root=root, clock=_clock, runner=broken,
                               head=lambda _: HEAD)

    assert (line["outcome"], line["commit"]) == ("stopped", HEAD)
    assert line["reason"] == "the review did not finish: PermissionError: codex"


def test_planning_starts_fresh_only_for_fresh_1() -> None:
    assert _make_n("plan", "CHANGE=X", "UNATTENDED=1", "FRESH=0") == [
        'python3 scripts/run_change_step.py run plan "X"']


def test_a_round_records_the_last_record_before_it(tmp_path: Path) -> None:
    log = _log(tmp_path)
    (log.parent / "transcripts").mkdir(parents=True)
    (log.parent / "transcripts" / "04-review.log").write_text("x", "utf-8")

    assert step.note_round(log, [[2]], "owner", clock=_clock)["after"] == 4


def test_a_round_recorded_after_the_fact_is_given_its_last_record_before_it(
        tmp_path: Path) -> None:
    log = _log(tmp_path)
    (log.parent / "transcripts").mkdir(parents=True)
    (log.parent / "transcripts" / "09-triage.jsonl").write_text("x", "utf-8")

    assert step.note_round(log, [[1, 2, 3]], "owner", after=1, clock=_clock)["after"] == 1
    with pytest.raises(step.StepError, match="a record number"):
        step.note_round(log, [[1]], "owner", after=-1)


def test_watch_follows_the_newest_progress_file(tmp_path: Path) -> None:
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    first = transcripts / "03-validate.progress"
    first.write_text("".join(f"line {n}\n" for n in range(12)), "utf-8")
    shown: list[str] = []
    polls = iter(range(10))

    def tick(_: float) -> None:
        n = next(polls)
        if n == 0:
            with first.open("a", encoding="utf-8") as stream:
                stream.write("line 12\n")
        elif n == 1:
            second = transcripts / "04-triage.progress"
            second.write_text("triage 0\n", "utf-8")
            os.utime(second, ns=(first.stat().st_mtime_ns + 1,) * 2)

    step.watch(tmp_path, echo=shown.append, sleep=tick, polls=3)
    assert shown == ["== 03-validate.progress", *(f"line {n}" for n in range(2, 12)),
                     "line 12", "== 04-triage.progress", "triage 0"]


def test_watch_waits_for_a_first_progress_file(tmp_path: Path) -> None:
    shown: list[str] = []
    step.watch(tmp_path, echo=shown.append, sleep=lambda _: None, polls=2)
    assert shown == []
