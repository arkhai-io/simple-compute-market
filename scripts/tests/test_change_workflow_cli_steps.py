"""The workflow's command line, `change_workflow.cli`, and the `make` targets that
run it."""

from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from change_workflow.cli import expand_sections, main, parse_sections, split_rules
from change_workflow.common import StepError
from change_workflow.log import log_path, read_log, record_outcome
from change_workflow.running import live_runs, recorded_run, select_run, signal_run, stop
from change_workflow_fixtures import (CHANGE, COMMIT, DENIALS, VALID, FakeClaude, configured,
                                      event_lines, log_file, make_wrapper, option, option_rules,
                                      repository, review_text)


def _checkout(path: Path) -> Path:
    """`path` as a Git checkout with its workflow configuration: a step that reads
    `HEAD` is started only once the checkout shows no round view open, and one that
    commits or validates only once the fields it needs are declared."""
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return configured(path)


def test_the_command_line_records_a_branch_decision(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log_file(tmp_path)

    # The change defaults to the one whose log holds the line, where steps look.
    assert main(["note", CHANGE, "orchestrator", "--by", "owner", "--branch", "feat/x",
                 "--decision", "runs here", "--reason", "pilot"],
                root=tmp_path) == 0
    capsys.readouterr()
    assert main(["log", CHANGE, "--branch", "feat/x"], root=tmp_path) == 0
    shown = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert [(entry["branch"], entry["change"]) for entry in shown] == [("feat/x", CHANGE)]


# `record`: a step the owner runs interactively records its own outcome.

def _committed(root: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """`root` made a Git repository with one commit, whose id is returned."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for command in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@example.invalid",
                                     "commit", "-q", "--allow-empty", "-m", "start"]):
        subprocess.run(["git", *command], cwd=root, check=True, capture_output=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()


def _triaged(log: Path, *names: str) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    for name in names:
        (log.parent / name).with_suffix(".md").write_text("A record.\n", "utf-8")
        (log.parent / name).with_suffix(".triage.md").write_text("Its triage.\n", "utf-8")


TRIAGED = {"outcome": "finished", "message": "Advance to planning.",
           "triaged": ["13-design"], "next": {"step": "plan"}}
INTERACTIVE = {"CLAUDE_CODE_SESSION_ID": "5e55-1011"}


def test_an_interactive_triage_records_its_outcome(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    head = _committed(tmp_path, monkeypatch)
    log = log_file(tmp_path)
    _triaged(log, "13-design")

    assert main(["record", CHANGE, "triage", "--outcome", json.dumps(TRIAGED)], root=tmp_path,
                environ=INTERACTIVE) == 0

    (line,) = read_log(log)
    assert {key: line[key] for key in TRIAGED} == TRIAGED
    assert (line["step"], line["session"], line["commit"], line["interactive"],
            line["format"]) == ("triage", "5e55-1011", head, True, 2)
    assert json.loads(capsys.readouterr().out) == line


DESIGNED = {**VALID["finished"], "next": {"step": "review", "kind": "design"}}


def _record(tmp_path: Path, step: str, outcome: dict | str, environ: dict, *more: str,
            head: str | None = COMMIT) -> int:
    """`record` run with `HEAD` given, through the wrapper's seam."""
    wrapper = make_wrapper(tmp_path, FakeClaude())
    wrapper.head = lambda _: head
    text = outcome if isinstance(outcome, str) else json.dumps(outcome)
    return main(["record", CHANGE, step, "--outcome", text, *more], root=tmp_path,
                wrapper=wrapper, environ=environ)


@pytest.mark.parametrize("environ", [{}, INTERACTIVE])
def test_a_session_given_is_recorded_whatever_the_harness_exports(
        tmp_path: Path, environ: dict) -> None:
    log = log_file(tmp_path)

    assert _record(tmp_path, "design", DESIGNED, environ, "--session", "given") == 0

    assert read_log(log)[-1]["session"] == "given"


@pytest.mark.parametrize("step,outcome,environ,more,named", [
    ("design", DESIGNED, {}, (), "CLAUDE_CODE_SESSION_ID is not set"),
    ("design", DESIGNED, {**INTERACTIVE, "CHANGE_WORKFLOW_UNATTENDED": "1"}, (),
     "the wrapper records its outcome"),
    # A session given does not make a wrapper's run interactive.
    ("design", DESIGNED, {"CHANGE_WORKFLOW_UNATTENDED": "1"}, ("--session", "given"),
     "the wrapper records its outcome"),
    ("deploy", DESIGNED, INTERACTIVE, (), "unknown step 'deploy'"),
    ("design", {"outcome": "finished", "message": "Done."}, INTERACTIVE, (),
     "outcome has no next"),
    ("design", {**VALID["finished"], "next": {"step": "review"}}, INTERACTIVE, (),
     "names no node"),
    ("triage", {**TRIAGED, "triaged": ["31-design"]}, INTERACTIVE, (),
     "31-design is no record in reviews/"),
    ("triage", {**TRIAGED, "triaged": []}, INTERACTIVE, (), "not a non-empty list"),
    ("design", "finished", INTERACTIVE, (), "--outcome is not JSON"),
])
def test_a_record_refused_writes_nothing_and_says_why(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], step: str, outcome,
        environ: dict, more: tuple, named: str) -> None:
    log = log_file(tmp_path)
    _triaged(log, "13-design")

    assert _record(tmp_path, step, outcome, environ, *more) == 1

    assert named in capsys.readouterr().err
    assert not log.exists()


def test_a_record_without_head_is_refused(tmp_path: Path,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    log = log_file(tmp_path)

    assert _record(tmp_path, "design", DESIGNED, INTERACTIVE, head=None) == 1

    assert "the commit at HEAD" in capsys.readouterr().err
    assert not log.exists()


@pytest.mark.parametrize("flags,target", [
    (["--next", "validate", "--target", "implement", "--sections", "5;6"],
     {"step": "validate", "target": {"step": "implement", "sections": [[5], [6]]}}),
    (["--next", "validate", "--target", "review", "--kind", "implementation"],
     {"step": "validate", "target": {"step": "review", "kind": "implementation"}}),
    (["--next", "implement", "--sections", "5"], {"step": "implement", "sections": [[5]]}),
])
def test_the_command_line_builds_the_owners_direction(tmp_path: Path, flags: list[str],
                                                       target: dict) -> None:
    log = log_file(tmp_path)

    assert main(["note", CHANGE, "orchestrator", "--decision", "d", "--reason", "r",
                 "--by", "owner", *flags], root=tmp_path) == 0

    assert read_log(log)[-1]["next"] == target


def test_the_command_line_refuses_a_direction_naming_no_node(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = log_file(tmp_path)

    assert main(["note", CHANGE, "orchestrator", "--decision", "d", "--reason", "r",
                 "--by", "owner", "--next", "validate"], root=tmp_path) == 1

    assert ("validate's entry guard (it carries a target that is a node) is not met"
            in capsys.readouterr().err)
    assert not log.exists()


def test_sections_parse_by_session(tmp_path: Path) -> None:
    assert parse_sections("1,2; 3 ;5B") == [[1, 2], [3], ["5B"]]


def test_the_command_line_notes_a_round_and_prints_the_log(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = log_file(tmp_path)
    record_outcome(log, "validate", {**VALID["question"], "denials": DENIALS},
                   session="s", commit=COMMIT)

    assert main(["note", CHANGE, "round", "--sections", "1;2,3", "--after", "4"],
                root=tmp_path) == 0
    assert main(["note", CHANGE, "orchestrator", "--decision", "d", "--reason", "r",
                 "--by", "owner", "--next", "review", "--kind", "pre-closeout"],
                root=tmp_path) == 0
    assert main(["note", CHANGE, "orchestrator", "--decision", "gap", "--reason", "r",
                 "--reads", "1"], root=tmp_path) == 0
    capsys.readouterr()
    assert main(["log", CHANGE, "--last", "1"], root=tmp_path) == 0

    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    entries = read_log(log)[1:]
    assert [entry["outcome"] for entry in entries] == ["round", "orchestrator", "orchestrator"]
    assert (entries[0]["sections"], entries[0]["after"]) == ([[1], [2, 3]], 4)
    # A round recorded after the fact started at a commit that is no longer HEAD.
    assert "commit" not in entries[0]
    assert (entries[1]["by"], entries[1]["next"]) == (
        "owner", {"step": "review", "kind": "pre-closeout"})
    assert entries[2]["reads"] == 1
    assert [entry["seq"] for entry in printed] == [4]


def test_a_round_noted_as_it_starts_records_head(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    log = log_file(tmp_path)
    head = _committed(tmp_path, monkeypatch)

    assert main(["note", CHANGE, "round", "--sections", "2", "--by", "plan"],
                root=tmp_path) == 0

    assert read_log(log)[-1]["commit"] == head


def test_the_command_line_names_a_change_it_cannot_find(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["log", "missing"], root=tmp_path) == 1
    assert "no change 'missing'" in capsys.readouterr().err


def test_an_archived_changes_log_is_found_by_its_name(tmp_path: Path) -> None:
    archived = tmp_path / "openspec/changes/archive" / f"2026-10-20-{CHANGE}"
    archived.mkdir(parents=True)

    assert main(["note", CHANGE, "orchestrator", "--decision", "d", "--reason", "r"],
                root=tmp_path) == 0

    assert read_log(archived / "reviews" / "workflow.jsonl")[0]["decision"] == "d"


def test_a_cleaned_up_changes_log_is_printed_from_its_archived_records(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    archived = tmp_path / "openspec/changes/archive" / f"2026-10-20-{CHANGE}"
    (archived / "reviews").mkdir(parents=True)
    record_outcome(archived / "reviews" / "workflow.jsonl", "validate", VALID["finished"],
                   session="s", commit=COMMIT)
    # The workspace's branch carries the change's active directory, without records.
    (tmp_path / "openspec/changes" / CHANGE).mkdir()

    assert main(["log", CHANGE], root=tmp_path) == 0

    assert [json.loads(line)["step"] for line in capsys.readouterr().out.splitlines()] == [
        "validate"]


def test_a_non_ascii_digit_is_a_section_name() -> None:
    assert parse_sections("²") == [["²"]]


def test_implementation_is_given_its_sections(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["finished"]), 0))
    _checkout(tmp_path)

    assert main(["start", "implement", CHANGE, "--sections", "1-3", "--unattended"],
                root=tmp_path, wrapper=make_wrapper(tmp_path, claude)) == 0

    assert claude.commands[0][2] == f"/change-implement {CHANGE} sections 1-3"
    assert read_log(log_path(tmp_path, CHANGE))[-1]["sections"] == [1, 2, 3]


def test_the_command_continues_a_named_implementation_session(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    claude = FakeClaude((event_lines(VALID["finished"], session="i-1"), 0),
                        (event_lines(VALID["finished"], session="i-1"), 0))
    wrapper = make_wrapper(_checkout(tmp_path), claude)
    assert main(["start", "implement", CHANGE, "--sections", "8A", "--unattended"],
                root=tmp_path, wrapper=wrapper) == 0

    assert main(["start", "implement", CHANGE, "--sections", "8B", "--session", "i-1",
                 "--unattended"], root=tmp_path, wrapper=wrapper) == 0
    assert main(["start", "implement", CHANGE, "--session", "other", "--unattended"],
                root=tmp_path, wrapper=wrapper) == 1

    assert claude.commands[1][2] == f"/change-implement {CHANGE} section 8B"
    assert option(claude.commands[1], "--resume") == "i-1"
    first, continued = [entry for entry in read_log(log_path(tmp_path, CHANGE))
                        if entry["step"] == "implement"]
    assert continued["continues"] == first["seq"]
    assert "no implementation run of session other" in capsys.readouterr().err


def test_the_command_resumes_by_seq(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["question"], session="d-1"), 0),
                        (event_lines(VALID["finished"], session="d-1"), 0))
    wrapper = make_wrapper(tmp_path, claude)
    wrapper.run("design", CHANGE)

    assert main(["resume", CHANGE, "--seq", "1", "--answer", "Yes."], root=tmp_path,
                wrapper=wrapper) == 0

    assert option(claude.commands[1], "--resume") == "d-1"
    assert claude.commands[1][2] == "The owner's answer: Yes."


def test_the_owners_revisit_resumes_the_finished_triage_with_their_words(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    triaged = {**VALID["finished"], "triaged": ["04-implementation"]}
    claude = FakeClaude((event_lines(triaged, session="t-1"), 0))
    wrapper = make_wrapper(tmp_path, claude)
    log = log_path(tmp_path, CHANGE)
    _triaged(log, "04-implementation")
    triage = record_outcome(log, "triage", triaged, session="t-1", commit=COMMIT)

    assert main(["note", CHANGE, "orchestrator", "--by", "owner", "--resumes",
                 str(triage["seq"]), "--decision", "revisits 04 F5",
                 "--reason", "cite the stable row"], root=tmp_path) == 0
    assert main(["resume", CHANGE, "--seq", str(triage["seq"]), "--answer",
                 "Cite the stable row."], root=tmp_path, wrapper=wrapper) == 0

    assert option(claude.commands[0], "--resume") == "t-1"
    assert claude.commands[0][2] == "The owner's answer: Cite the stable row."
    assert (read_log(log)[-1]["outcome"], read_log(log)[-1]["resumes"]) == (
        "finished", triage["seq"])


def test_a_revisit_direction_from_the_orchestrator_is_refused(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = log_file(tmp_path)
    _triaged(log, "04-implementation")
    triage = record_outcome(log, "triage", {**VALID["finished"],
                                            "triaged": ["04-implementation"]},
                            session="t-1", commit=COMMIT)

    assert main(["note", CHANGE, "orchestrator", "--resumes", str(triage["seq"]),
                 "--decision", "revisits", "--reason", "r"], root=tmp_path) == 1

    assert "a direction to revisit a triage is the owner's" in capsys.readouterr().err
    assert read_log(log) == [triage]


@pytest.mark.parametrize("later,refused", [
    ({**VALID["finished"], "triaged": ["04-implementation"]}, "triaging 04-implementation again"),
    (None, "not a finished triage"),
])
def test_the_command_line_refuses_a_revisit_the_log_refuses(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], later: dict | None,
        refused: str) -> None:
    """A later triage has run; or the run named is not a finished triage."""
    log = log_file(tmp_path)
    _triaged(log, "04-implementation")
    first = record_outcome(log, "triage", later or VALID["question"], session="t-1",
                           commit=COMMIT)
    if later is not None:
        record_outcome(log, "triage", later, session="t-2", commit=COMMIT)

    assert main(["note", CHANGE, "orchestrator", "--by", "owner", "--resumes",
                 str(first["seq"]), "--decision", "revisits", "--reason", "r"],
                root=tmp_path) == 1

    assert refused in capsys.readouterr().err


def test_a_fresh_run_is_granted_each_rule_its_allow_values_hold(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["finished"]), 0))
    _checkout(tmp_path)

    assert main(["start", "validate", CHANGE, "--unattended",
                 "--allow", "Bash(gh run download *);Bash(make lock)",
                 "--allow", "Bash(helm version)"], root=tmp_path,
                wrapper=make_wrapper(tmp_path, claude)) == 0

    rules = ["Bash(gh run download *)", "Bash(make lock)", "Bash(helm version)"]
    assert option_rules(claude.commands[0], "--allowedTools")[-3:] == rules
    assert read_log(log_path(tmp_path, CHANGE))[-1]["granted"] == rules


def test_a_resumed_run_splits_its_allow_values_too(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["question"], session="d-1"), 0),
                        (event_lines(VALID["finished"], session="d-1"), 0))
    wrapper = make_wrapper(tmp_path, claude)
    wrapper.run("design", CHANGE)

    assert main(["resume", CHANGE, "--seq", "1", "--answer", "Yes.",
                 "--allow", "Bash(helm version);; Bash(make lock) ;"], root=tmp_path,
                wrapper=wrapper) == 0

    rules = ["Bash(helm version)", "Bash(make lock)"]
    assert option_rules(claude.commands[1], "--allowedTools")[-2:] == rules
    assert read_log(log_path(tmp_path, CHANGE))[-1]["granted"] == rules


@pytest.mark.parametrize("values,rules", [
    ([], []), (["a"], ["a"]), (["a;b"], ["a", "b"]), ([";a;;b;"], ["a", "b"]),
    (["a; b", "c"], ["a", "b", "c"]), ([" ; "], []),
])
def test_allow_values_split_on_semicolons(values: list[str], rules: list[str]) -> None:
    assert split_rules(values) == rules


def test_a_stopped_run_exits_non_zero(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(result=False), 2))

    assert main(["start", "design", CHANGE, "--unattended"], root=tmp_path,
                wrapper=make_wrapper(tmp_path, claude)) == 1


@pytest.mark.parametrize("text,sections", [("2", [2]), ("1-3", [1, 2, 3]), ("1,3", [1, 3]),
                                           ("5B", ["5B"]), ("", [])])
def test_implementation_sections_expand(text: str, sections: list) -> None:
    assert expand_sections(text) == sections


def test_a_backwards_section_range_is_refused(tmp_path: Path,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    # A malformed argument is a usage error.
    assert main(["start", "implement", CHANGE, "--sections", "3-1", "--unattended"],
                root=_checkout(tmp_path), wrapper=make_wrapper(tmp_path, FakeClaude())) == 2
    assert "runs backwards" in capsys.readouterr().err


def test_the_review_command_exits_non_zero_when_it_stops(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _checkout(repository(tmp_path))

    assert main(["review", CHANGE, "--kind", "closeout"], root=root) == 1

    captured = capsys.readouterr()
    assert "not archived" in captured.err
    assert json.loads(captured.out)["outcome"] == "stopped"


# `stop`: the owner interrupts a running step.

class Sent:
    """Stands in for `os.kill`, recording each signal sent."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def __call__(self, pid: int, signum: int) -> None:
        self.calls.append((pid, signum))


def _stop(tmp_path: Path, runs: Path, *flags: str, send: Sent) -> int:
    wrapper = make_wrapper(tmp_path, FakeClaude())
    wrapper.runs = lambda _: runs
    return main(["stop", CHANGE, *flags], root=tmp_path, wrapper=wrapper, send=send)


def test_stop_signals_the_one_run_in_progress(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runs, sent = tmp_path / "change-runs", Sent()

    with recorded_run(runs, "validate", CHANGE):
        assert _stop(tmp_path, runs, send=sent) == 0

    assert sent.calls == [(os.getpid(), signal.SIGTERM)]
    assert f"Sent SIGTERM to validate of {CHANGE}" in capsys.readouterr().out


def test_stop_with_nothing_running_refuses_and_signals_nothing(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Nothing is running."""
    runs, sent = tmp_path / "change-runs", Sent()

    with recorded_run(runs, "validate", "another-change"):
        assert _stop(tmp_path, runs, send=sent) == 1

    assert sent.calls == []
    assert f"no run of {CHANGE} is in progress" in capsys.readouterr().err


def test_stop_refuses_a_stale_record_naming_it(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A run record outlives its run: its process (this one) is alive, but nothing
    holds the record."""
    runs, sent = tmp_path / "change-runs", Sent()
    runs.mkdir()
    (runs / "1-stale.json").write_text(json.dumps(
        {"pid": os.getpid(), "step": "validate", "change": CHANGE,
         "started": "2026-10-21T09:15:40Z"}), "utf-8")

    assert _stop(tmp_path, runs, send=sent) == 1

    assert sent.calls == []
    err = capsys.readouterr().err
    assert "1-stale.json is stale" in err and "nothing was signalled" in err


def test_stop_with_two_runs_needs_the_step(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runs, sent = tmp_path / "change-runs", Sent()

    with recorded_run(runs, "validate", CHANGE), recorded_run(runs, "review", CHANGE):
        assert _stop(tmp_path, runs, send=sent) == 1
        assert sent.calls == []
        err = capsys.readouterr().err
        assert f"2 runs of {CHANGE} are in progress" in err and "--step" in err
        assert _stop(tmp_path, runs, "--step", "review", send=sent) == 0

    assert sent.calls == [(os.getpid(), signal.SIGTERM)]
    assert "Sent SIGTERM to review of" in capsys.readouterr().out


def test_a_run_that_ends_before_the_second_check_is_not_signalled(tmp_path: Path) -> None:
    """A run ends while it is being stopped."""
    runs, sent = tmp_path / "change-runs", Sent()
    with recorded_run(runs, "validate", CHANGE):
        selected = select_run(runs, CHANGE)

    with pytest.raises(StepError, match="ended before it could be stopped"):
        signal_run(selected, sent)
    assert sent.calls == []


def test_a_run_killed_between_the_checks_is_not_signalled(tmp_path: Path) -> None:
    """Its record stays, but the kernel has released its lock."""
    runs, sent = tmp_path / "change-runs", Sent()
    runs.mkdir()
    record = runs / "1-killed.json"
    record.write_text(json.dumps({"pid": os.getpid(), "step": "validate", "change": CHANGE,
                                  "started": "2026-10-21T09:15:40Z"}), "utf-8")
    with record.open("r") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        selected = select_run(runs, CHANGE)

    with pytest.raises(StepError, match="ended before it could be stopped"):
        signal_run(selected, sent)
    assert sent.calls == [] and record.is_file()


def test_a_run_gone_as_the_signal_is_sent_is_reported_ended(tmp_path: Path) -> None:
    runs = tmp_path / "change-runs"

    def gone(pid: int, signum: int) -> None:
        raise ProcessLookupError(pid)

    with recorded_run(runs, "validate", CHANGE):
        with pytest.raises(StepError, match="ended before it could be stopped"):
            stop(runs, CHANGE, send=gone)


# A stand-in for the agent or reviewer a run starts: it says it started, gives its
# process id, and runs until it is ended.
_STAND_IN = """
import os, sys, time
from pathlib import Path
print('{"type": "system", "subtype": "init", "session_id": "s-stop"}', flush=True)
Path(sys.argv[1] + ".partial").write_text(str(os.getpid()))
Path(sys.argv[1] + ".partial").replace(sys.argv[1])
time.sleep(120)
"""

# A step run through the real wrapper, which starts the stand-in through
# `run_claude`.
_STEP = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
root, runs, started = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
from change_workflow.harness import run_claude
from change_workflow.wrapper import Wrapper
def runner(command, cwd, feed, step):
    return run_claude([sys.executable, "-c", sys.argv[5], started], cwd, feed, step)
Wrapper(root=root, runner=runner, head=lambda _: "c0ffee", echo=None,
        conversation=lambda _, session: root / "conversations" / f"{session}.jsonl",
        runs=lambda _: runs).run("validate", sys.argv[6])
"""

# A review run through the real review runner, which starts the stand-in through
# `run_codex`; the reviewer's finished review is written as it starts, so only the
# stop keeps it from being published.
_REVIEW = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
root, runs, started = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
from change_workflow.harness import run_codex
from change_workflow.review import review_and_log
def runner(command, log):
    Path(command[command.index("--output-last-message") + 1]).write_text(sys.argv[7])
    return run_codex([sys.executable, "-c", sys.argv[5], started], log)
review_and_log(sys.argv[6], "design", root=root, runner=runner,
               head=lambda _: "c0ffee", runs=lambda _: runs)
"""

SCRIPTS = Path(__file__).resolve().parents[1]


def _started(kind: str, tmp_path: Path, runs: Path) -> tuple[subprocess.Popen, int]:
    """A real run of `kind` in a child process, once the process it started runs:
    the run, and that process's id."""
    started = tmp_path / f"{kind}.pid"
    run = subprocess.Popen([sys.executable, "-c", {"step": _STEP, "review": _REVIEW}[kind],
                            str(SCRIPTS), str(tmp_path), str(runs), str(started), _STAND_IN,
                            CHANGE, review_text()],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 30
    while not started.is_file():
        assert run.poll() is None and time.monotonic() < deadline, f"the {kind} never started"
        time.sleep(0.05)
    return run, int(started.read_text())


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_a_stopped_step_is_logged_stopped_and_its_agent_ended(tmp_path: Path) -> None:
    """Library integration: a real wrapper process and the process it started."""
    repository(tmp_path)
    runs = tmp_path / "change-runs"
    run, agent = _started("step", tmp_path, runs)
    try:
        wrapper = make_wrapper(tmp_path, FakeClaude())
        wrapper.runs = lambda _: runs
        assert main(["stop", CHANGE], root=tmp_path, wrapper=wrapper) == 0
        run.wait(timeout=30)
    finally:
        run.kill()

    line = read_log(log_path(tmp_path, CHANGE))[-1]
    assert (line["step"], line["outcome"]) == ("validate", "stopped")
    assert "received SIGTERM" in line["reason"]
    assert _gone(agent)
    assert list(runs.iterdir()) == []


def test_stopping_the_review_leaves_the_validation_running(tmp_path: Path) -> None:
    """Two runs are in progress. Library integration: a real review runner and its
    reviewer's process, beside a real wrapper's validation."""
    repository(tmp_path)
    runs = tmp_path / "change-runs"
    validation, agent = _started("step", tmp_path, runs)
    review, reviewer = _started("review", tmp_path, runs)
    try:
        wrapper = make_wrapper(tmp_path, FakeClaude())
        wrapper.runs = lambda _: runs
        assert main(["stop", CHANGE, "--step", "review"], root=tmp_path, wrapper=wrapper) == 0
        review.wait(timeout=30)

        line = read_log(log_path(tmp_path, CHANGE))[-1]
        assert (line["step"], line["outcome"]) == ("review", "stopped")
        assert "received SIGTERM" in line["reason"]
        assert _gone(reviewer)
        # The review published nothing, though its reviewer had written a review;
        # the output is kept beside the transcript.
        reviews = tmp_path / "openspec/changes" / CHANGE / "reviews"
        assert not [p for p in reviews.glob("[0-9]*.md") if not p.name.endswith(".rejected.md")]
        assert list((reviews / "transcripts").glob("*.rejected.md"))
        # The validation runs on, untouched.
        assert validation.poll() is None and not _gone(agent)
        assert [(r.step, r.pid) for r in live_runs(runs)] == [("validate", validation.pid)]
    finally:
        for process in (review, validation):
            process.kill()
            process.wait()
        if not _gone(agent):
            os.kill(agent, signal.SIGKILL)


# This repository's Makefile: the engine's fragment included, set to this
# repository's branches, beside the repository's own targets.

COMMAND = "scripts/change-workflow"


def _make_n(*arguments: str) -> list[str]:
    """`make -n` of a target of the root Makefile, with no step variable inherited
    from the caller.

    A make that ran these tests passes its own command-line variables down through
    MAKEFLAGS, so those are dropped too.
    """
    env = {key: value for key, value in os.environ.items()
           if key not in ("UNATTENDED", "SECTION", "SECTIONS", "FRESH", "HELM_ALL_SCENARIOS",
                          "ALLOW", "ARGUMENTS", "SESSION_ID", "FROM", "BASE", "BRANCH",
                          "REVIEW_BASE", "REVIEW_MODEL", "REVIEW_EFFORT", "UNVALIDATED",
                          "CHANGE_WORKFLOW", "CHANGE_BASE",
                          "MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "MAKELEVEL")}
    output = subprocess.run(["make", "-n", "--no-print-directory", *arguments],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True,
                            text=True, check=True, env=env).stdout
    return output.splitlines()


@pytest.mark.parametrize("target,variables,commands", [
    # CW-h8vm, "A repository includes the fragment": the merge brings in the branch
    # the change lands on, which the engine reads, unless FROM names another; the
    # repository sets no branch of its own.
    ("merge", [], [f'{COMMAND} start merge "X"']),
    ("merge", ["FROM=release/2.1", "UNATTENDED=1"],
     [f"{COMMAND} start merge \"X\" --arguments 'from release/2.1' --unattended"]),
    # A review reads the change against the branch it lands on, unless REVIEW_BASE
    # names another.
    ("review", ["KIND=design"], [f'{COMMAND} review "X" --kind "design"     ']),
    ("review", ["KIND=design", "REVIEW_BASE=main"],
     [f'{COMMAND} review "X" --kind "design" --base "main"    ']),
    ("design", ["UNATTENDED=1", "ALLOW=Bash(make lock)"],
     [f"{COMMAND} start design \"X\" --unattended --allow 'Bash(make lock)'"]),
    ("orchestrate", [], [f'{COMMAND} start orchestrate "X"']),
    ("change-next", [], [f'{COMMAND} find "X" >/dev/null', f'{COMMAND} next "X" --plain']),
    ("check-change-index", [], [f"{COMMAND} check index"]),
    ("check-agent-skills", [], [f"{COMMAND} check skills"]),
    ("check-push-ready", [], [f"{COMMAND} check round-view", f"{COMMAND} check push"]),
    ("push-branch", [], [f"{COMMAND} push"]),
    ("change-graph", [], [f"{COMMAND} check graph"]),
    # The owner's complete closing check is the workflow's whole pre-commit, whose
    # hook is this repository's check-repository; each reads the branch the change
    # lands on, which the clone recorded, unless CHANGE_BASE names another.
    ("check-change", [], [f'{COMMAND} run pre-commit "X"']),
    ("check-change", ["CHANGE_BASE=release"], [f'{COMMAND} run pre-commit "X" --base "release"']),
    ("check-repository", [], ['python3 scripts/check_change.py "X"']),
    ("check-repository", ["CHANGE_BASE=release"],
     ['python3 scripts/check_change.py "X" --base "release"']),
])
def test_the_root_makefile_runs_the_command_through_the_fragment(
        target: str, variables: list[str], commands: list[str]) -> None:
    assert _make_n(target, "CHANGE=X", *variables) == commands


@pytest.mark.parametrize("target,variables,commands", [
    ("run-e2e", [], [f"{COMMAND} check round-view", "python3 scripts/ci_evidence.py pipeline"]),
    ("run-ci", ["WORKFLOW=tests.yml"],
     [f"{COMMAND} check round-view", 'python3 scripts/ci_evidence.py dispatch "tests.yml"']),
    ("pre-push", ["REMOTE=origin"], []),
])
def test_validations_dispatches_and_the_pre_push_checks_run_the_repositorys_scripts(
        target: str, variables: list[str], commands: list[str]) -> None:
    printed = _make_n(target, *variables)

    if commands:
        assert printed == commands
    else:
        assert any("check_public_content.py --pre-push \"origin\"" in line for line in printed)
        assert any("check_secrets.py --pre-push \"origin\"" in line for line in printed)


@pytest.mark.parametrize("target", ["run-e2e", "validate-local", "run-ci"])
def test_a_repository_target_refuses_while_a_round_view_is_open(target: str) -> None:
    # The repository's own targets that read or publish HEAD keep the fragment's
    # round-view check as their first prerequisite.
    assert _make_n(target, "WORKFLOW=tests.yml")[0] == f"{COMMAND} check round-view"


def test_a_granted_rule_and_arguments_reach_the_command_as_written(tmp_path: Path) -> None:
    """The shell quoting `make` writes, run by a real shell: quotes, `*`, and
    backticks arrive untouched, and an empty part of `ALLOW` is dropped by the
    command."""
    rule, other = "Bash(git commit -m 'wip' *)", 'Bash(echo "`id`" *)'
    (command,) = _make_n("implement", "CHANGE=X", "UNATTENDED=1",
                         "ARGUMENTS=resolve `scripts/a.py`'s conflicts",
                         f"ALLOW={rule};;{other}")
    printed = subprocess.run(
        ["sh", "-c", command.replace(f"{COMMAND} start", "printf '%s\\n'")],
        cwd=tmp_path, capture_output=True, text=True, check=True).stdout.splitlines()

    assert printed == ["implement", "X", "--arguments", "resolve `scripts/a.py`'s conflicts",
                       "--unattended", "--allow", rule, "--allow", "", "--allow", other]
    assert split_rules([rule, "", other]) == [rule, other]
