"""The engine's actions and the repository's hooks around a step's session: the inputs
directory, the gathering and the hooks before a session, the hooks after one that
finished, and `run before|after` for a step held interactively.

Library integration, but for the unit tests of a pure step: the wrapper or the
command driven in process, each hook a real `sh` command, the gathering on a real
temporary Git repository. The harness is doubled by a fake that replays a session's
events, and the wrapper's other readings — of the checkout's `HEAD` and landing,
the next-step computation, the conversation, the runs in progress — by the
fixtures' `make_wrapper`."""

from __future__ import annotations

import json
import subprocess
from dataclasses import fields, replace
from pathlib import Path

import pytest

from change_workflow import around, config
from change_workflow.cli import main
from change_workflow.common import SESSION_ID, UNATTENDED_RUN, StepError
from change_workflow.log import log_path, read_log
from change_workflow.next_step import TASKS_FILE
from change_workflow.wrapper import Wrapper
from change_workflow_fixtures import (AT, CHANGE, MODELS, SESSION, VALID, FakeClaude, clock,
                                      configured, evidence_kind, event_lines, make_wrapper,
                                      option, prompted)

RUN = f"{AT.strftime('%Y%m%dT%H%M%SZ')}"
REQUIRED = '[repository]\nprotected-branches = ["main", "dev"]\n\n'


def _hooks(*lines: str) -> str:
    return REQUIRED + "[hooks]\npre-commit-functional = []\n" + "".join(
        f"{line}\n" for line in lines) + "\n" + evidence_kind("local", run="true") + MODELS


def _reviews(root: Path) -> Path:
    return root / "openspec/changes" / CHANGE / "reviews"


def _inputs(root: Path, step: str, when: str = "before") -> Path:
    return _reviews(root) / "runs" / f"{RUN}-{step}" / when


def _wrapper(root: Path, text: str, claude: FakeClaude):
    """The wrapper of `root` configured with `text`, keeping invocations where a Git
    checkout would, since `root` is none."""
    configured(root, text)
    return replace(make_wrapper(root, claude), invocations=lambda _: root / "kept")


class Acting(FakeClaude):
    """A session that does something, `action(index)`, as each of its runs starts."""

    def __init__(self, action, *runs) -> None:
        super().__init__(*runs)
        self.action = action

    def __call__(self, command, cwd, feed, step) -> int:
        self.action(len(self.commands))
        return super().__call__(command, cwd, feed, step)


# The inputs directory.

def test_two_runs_started_in_one_second_never_share_a_directory(tmp_path: Path) -> None:
    first = around.claim_inputs(tmp_path, "implement", clock)
    second = around.claim_inputs(tmp_path, "implement", clock)

    assert (first.name, second.name) == (f"{RUN}-implement", f"{RUN}-implement-2")


def test_a_runs_inputs_are_named_on_its_line_and_hold_what_each_hook_printed(
        tmp_path: Path) -> None:
    """CW-i9np: the directory is on the line and in the prompt; `status.md` holds the
    hook's closing line, exit status, and log, and the log what it printed."""
    claude = FakeClaude((event_lines(VALID["finished"]), 0))
    hook = "before-implement = 'echo printed; echo Read me. > {inputs}/message.md'"

    line = _wrapper(tmp_path, _hooks(hook), claude).run("implement", CHANGE)

    inputs = _inputs(tmp_path, "implement")
    assert line["inputs"] == f"runs/{RUN}-implement"
    assert claude.commands[0][2] == prompted(f"/change-implement {CHANGE}", "implement")
    status = (inputs / "status.md").read_text("utf-8")
    assert "## before-implement\n\n- Exit status: 0\n- Log: `before-implement.log`" in status
    assert "[change-workflow] before-implement at no commit: passed, exit 0" in status
    assert "printed" in (inputs / "before-implement.log").read_text("utf-8")
    assert (inputs / "message.md").read_text("utf-8") == "Read me.\n"
    (invoked,) = line["invoked"]
    assert (invoked["hook"], invoked["exit_status"]) == ("before-implement", 0)


def test_a_hooks_commands_run_as_the_steps_run_never_under_the_callers_session(
        tmp_path: Path) -> None:
    """What a hook's commands run through the engine is held to the step's hook
    table and kept for the run's line, not for an orchestrating session that
    started the wrapper."""
    claude = FakeClaude((event_lines(VALID["finished"]), 0))
    hook = ("before-implement = 'echo $CHANGE_WORKFLOW_UNATTENDED $CLAUDE_CODE_SESSION_ID "
            "> {inputs}/marked'")
    wrapper = replace(_wrapper(tmp_path, _hooks(hook), claude),
                      environ={"PATH": "/usr/bin:/bin", SESSION_ID: "the-orchestrators"})

    wrapper.run("implement", CHANGE)

    marker, session = (_inputs(tmp_path, "implement") / "marked").read_text("utf-8").split()
    assert marker == "implement"
    assert session.startswith("implement-before-implement-")


def test_a_hook_passes_a_large_artifact_beside_its_message(tmp_path: Path) -> None:
    """CW-i9np's large artifact, as its layout: the message and the data are files of
    the directory, and neither the prompt nor `status.md` carries the data."""
    claude = FakeClaude((event_lines(VALID["finished"]), 0))
    hook = ("before-implement = 'echo See diff-summary.json. > {inputs}/message.md; "
            "head -c 3000000 /dev/zero | tr \"\\\\0\" x > {inputs}/diff-summary.json'")

    _wrapper(tmp_path, _hooks(hook), claude).run("implement", CHANGE)

    inputs = _inputs(tmp_path, "implement")
    assert sorted(path.name for path in inputs.iterdir()) == [
        "before-implement.log", "diff-summary.json", "message.md", "status.md"]
    assert (inputs / "diff-summary.json").stat().st_size == 3_000_000
    assert "xxxx" not in claude.commands[0][2]
    assert "xxxx" not in (inputs / "status.md").read_text("utf-8")


# Before the session.

def _committed(root: Path, text: str) -> Path:
    """A Git repository configured with `text`, its records ignored, all of it
    committed, so the gathering describes `HEAD`."""
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    configured(root, text)
    with (root / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
        exclude.write("/openspec/changes/*/reviews/\n")
    (root / "openspec/changes" / CHANGE).mkdir(parents=True, exist_ok=True)
    (root / "openspec/changes" / CHANGE / TASKS_FILE).write_text("# Tasks\n", "utf-8")
    for command in (["add", "--all"], ["-c", "user.name=t", "-c", "user.email=t@example.invalid",
                                       "commit", "-q", "-m", "configure"]):
        subprocess.run(["git", *command], cwd=root, check=True, capture_output=True)
    return root


def test_the_local_suite_fails_during_gathering(tmp_path: Path) -> None:
    """CW-g6th: the gathering's `local` kind fails, and the session starts with that
    failure in its inputs."""
    root = _committed(tmp_path, REQUIRED + "[hooks]\npre-commit-functional = []\n\n"
                      + evidence_kind("local", run="echo 3 failed; exit 1") + MODELS)
    claude = FakeClaude((event_lines(VALID["finished"]), 0))

    line = make_wrapper(root, claude).run("validate", CHANGE)

    inputs = _inputs(root, "validate")
    assert len(claude.commands) == 1
    assert claude.commands[0][2] == prompted(f"/change-validate {CHANGE}", "validate")
    status = (inputs / "status.md").read_text("utf-8")
    assert "## gather\n\n- Exit status: 1\n- Log: `gather.log`" in status
    assert "[change-workflow] gather local at tree " in status
    assert "failed, exit 1: echo 3 failed; exit 1 (exit 1); evidence none" in status
    assert "## before-validate\n\nNot declared; nothing ran." in status
    assert "3 failed" in (inputs / "gather.log").read_text("utf-8")
    (local,) = [entry for entry in line["invoked"] if entry.get("kind") == "local"]
    assert (local["hook"], local["phase"], local["exit_status"]) == ("gather", "run", 1)
    assert line["outcome"] == "finished"


def test_gathering_before_the_session_leaves_present_evidence_alone(tmp_path: Path) -> None:
    """CW-g6th: the gathering before validation says what it found present, and
    runs nothing for it."""
    root = _committed(tmp_path, REQUIRED + "[hooks]\npre-commit-functional = []\n\n"
                      + evidence_kind("local", run="touch ran") + MODELS)
    tree = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()
    present = root / f".snapshot/evidence/{tree}/local/20261117T100300Z/summary.json"
    present.parent.mkdir(parents=True)
    present.write_text("{}", "utf-8")

    make_wrapper(root, FakeClaude((event_lines(VALID["finished"]), 0))).run("validate", CHANGE)

    status = (_inputs(root, "validate") / "status.md").read_text("utf-8")
    assert f"gather local: skipped, present; evidence {present.relative_to(root)}" in status
    assert not (root / "ran").exists()


def test_an_environment_refresh_fails_before_implementation(tmp_path: Path) -> None:
    """CW-b7fl: a failing `before-implement` prevents nothing; its failure is in the
    session's inputs."""
    claude = FakeClaude((event_lines(VALID["finished"]), 0))

    line = _wrapper(tmp_path, _hooks("before-implement = 'echo stale lock; exit 3'"),
                    claude).run("implement", CHANGE)

    inputs = _inputs(tmp_path, "implement")
    assert len(claude.commands) == 1 and line["outcome"] == "finished"
    status = (inputs / "status.md").read_text("utf-8")
    assert "- Exit status: 1" in status
    assert "failed, exit 3: echo stale lock; exit 3 (exit 3)" in status
    assert "stale lock" in (inputs / "before-implement.log").read_text("utf-8")


def test_no_hook_is_declared_before_a_step(tmp_path: Path) -> None:
    """CW-h3ks: an absent hook runs nothing, and the run says so; an empty one too."""
    claude = FakeClaude((event_lines(VALID["finished"]), 0),
                        (event_lines(VALID["finished"]), 0))
    wrapper = _wrapper(tmp_path, _hooks("before-plan = []"), claude)

    design = wrapper.run("design", CHANGE)
    plan = wrapper.run("plan", CHANGE)

    assert "invoked" not in design and "invoked" not in plan
    assert "## before-design\n\nNot declared; nothing ran." in (
        _inputs(tmp_path, "design") / "status.md").read_text("utf-8")
    assert "## before-plan\n\nDeclared empty; nothing ran." in (
        _inputs(tmp_path, "plan") / "status.md").read_text("utf-8")
    assert sorted(path.name for path in _inputs(tmp_path, "design").iterdir()) == ["status.md"]


def test_a_hook_the_check_refuses_refuses_the_step(tmp_path: Path) -> None:
    claude = FakeClaude()

    with pytest.raises(StepError, match="before-implement.*remote"):
        _wrapper(tmp_path, _hooks("before-implement = 'echo {remote}'"), claude).run(
            "implement", CHANGE)

    assert claude.commands == []
    assert not log_path(tmp_path, CHANGE).exists()


def test_archive_cleanup_starts_after_every_kinds_cleanup(tmp_path: Path) -> None:
    """CW-ikmm: the engine runs the kinds' cleanup before archive cleanup's session,
    which reads what it did from its inputs."""
    text = (REQUIRED + "[hooks]\npre-commit-functional = []\n\n"
            + evidence_kind("helm", run="true", cleanup="echo removed; touch cleaned") + MODELS)
    claude = FakeClaude((event_lines(VALID["finished"]), 0))

    line = _wrapper(tmp_path, text, claude).run("archive-cleanup", CHANGE)

    inputs = _inputs(tmp_path, "archive-cleanup")
    assert (tmp_path / "cleaned").exists() and len(claude.commands) == 1
    status = (inputs / "status.md").read_text("utf-8")
    assert "## cleanup\n\n- Exit status: 0\n- Log: `cleanup.log`" in status
    assert "removed" in (inputs / "cleanup.log").read_text("utf-8")
    (cleanup,) = [entry for entry in line["invoked"] if entry["hook"] == "cleanup"]
    assert (cleanup["kind"], cleanup["phase"], cleanup["exit_status"]) == ("helm", "cleanup", 0)


def test_a_triages_hooks_are_given_the_kind_it_triages(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["finished"]), 0))
    wrapper = replace(_wrapper(tmp_path, _hooks("before-triage = 'echo {kind} > {inputs}/kind'"),
                               claude), kind=lambda *_: "design")

    wrapper.run("triage", CHANGE)

    assert (_inputs(tmp_path, "triage") / "kind").read_text("utf-8") == "design\n"


def test_a_resumed_run_runs_nothing_before_its_session(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["question"], session="i-1"), 0),
                        (event_lines(VALID["finished"], session="i-1"), 0))
    wrapper = _wrapper(tmp_path, _hooks("before-implement = 'echo ran >> ../../ran'"), claude)
    asked = wrapper.run("implement", CHANGE)

    line = wrapper.resume(CHANGE, asked["seq"], "Yes.")

    assert line["inputs"] == f"runs/{RUN}-implement-2"
    assert not (_reviews(tmp_path) / "runs" / f"{RUN}-implement-2" / "before").exists()
    assert claude.commands[1][2] == "The owner's answer: Yes."


# After the session.

def test_a_hook_after_implementation_finds_a_lint_failure(tmp_path: Path) -> None:
    """CW-a4fl: the session resumes with the failure, fixes it, ends finished again,
    and the hook passes; one outcome is logged, the first kept as earlier."""
    fixed = {**VALID["finished"], "message": "Fixed the lint."}
    claude = Acting(lambda index: (tmp_path / "linted").touch() if index == 1 else None,
                    (event_lines(VALID["finished"], session="i-1"), 0),
                    (event_lines(fixed, session="i-1"), 0))

    line = _wrapper(tmp_path, _hooks("after-implement = 'test -e linted'"), claude).run(
        "implement", CHANGE)

    inputs = _inputs(tmp_path, "implement", "after")
    assert option(claude.commands[1], "--resume") == "i-1"
    assert option(claude.commands[1], "--model") == option(claude.commands[0], "--model")
    assert claude.commands[1][2].startswith(
        "The engine ran what follows a finished implement, and it failed: after-implement: "
        "failed, exit 1.")
    assert f"reviews/runs/{RUN}-implement/after/status.md" in claude.commands[1][2]
    assert (line["outcome"], line["message"]) == ("finished", "Fixed the lint.")
    assert line["earlier"] == [{key: VALID["finished"][key]
                                for key in ("outcome", "message", "next")}]
    assert read_log(log_path(tmp_path, CHANGE)) == [line]
    status = (inputs / "status.md").read_text("utf-8")
    assert "- Log: `after-implement.log`" in status
    assert "- Log: `after-implement-2.log`" in status
    assert [entry["exit_status"] for entry in line["invoked"]] == [1, 0]


def test_a_hook_that_fails_again_ends_the_run_as_a_question(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["finished"], session="i-1"), 0),
                        (event_lines(VALID["finished"], session="i-1"), 0))

    line = _wrapper(tmp_path, _hooks("after-implement = 'exit 4'"), claude).run(
        "implement", CHANGE)

    assert len(claude.commands) == 2
    assert line["outcome"] == "question"
    assert line["message"].startswith(
        "after-implement failed again after the implement session was resumed with its "
        "failure: after-implement: failed, exit 1.")
    assert line["awaiting"] == "the owner's decision on the failing after-implement"
    assert read_log(log_path(tmp_path, CHANGE)) == [line]


def test_a_resumed_turn_that_asks_is_logged_as_it_asked(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["finished"], session="i-1"), 0),
                        (event_lines(VALID["question"], session="i-1"), 0))

    line = _wrapper(tmp_path, _hooks("after-implement = 'exit 4'"), claude).run(
        "implement", CHANGE)

    assert {key: line[key] for key in VALID["question"]} == VALID["question"]
    assert [entry["hook"] for entry in line["invoked"]] == ["after-implement"]


def test_what_the_engine_cannot_run_after_a_session_counts_as_a_failure(
        tmp_path: Path) -> None:
    class Unrunnable(around.Around):
        def after(self, directory: Path) -> list[around.Ran]:
            raise OSError("no space left on device")

    class Wrapping(Wrapper):
        def _around(self, step: str, change: str) -> around.Around:
            return Unrunnable(self.root, config.load(self.root), change, step)

    claude = FakeClaude((event_lines(VALID["finished"], session="i-1"), 0),
                        (event_lines(VALID["finished"], session="i-1"), 0))
    made = make_wrapper(tmp_path, claude)
    wrapper = Wrapping(**{entry.name: getattr(made, entry.name) for entry in fields(Wrapper)})

    line = wrapper.run("implement", CHANGE)

    assert line["outcome"] == "question" and len(claude.commands) == 2
    status = (_inputs(tmp_path, "implement", "after") / "status.md").read_text("utf-8")
    assert "ERROR: no space left on device" in status


def test_only_a_finished_session_runs_the_hooks_after_it(tmp_path: Path) -> None:
    claude = FakeClaude((event_lines(VALID["question"]), 0))

    line = _wrapper(tmp_path, _hooks("after-implement = 'exit 4'"), claude).run(
        "implement", CHANGE)

    assert line["outcome"] == "question" and len(claude.commands) == 1
    assert not _inputs(tmp_path, "implement", "after").exists()


def test_a_validations_finished_resume_keeps_its_target(tmp_path: Path) -> None:
    target = {"step": "closeout"}
    claude = Acting(lambda index: (tmp_path / "explained").touch() if index == 1 else None,
                    (event_lines(VALID["finished"], session="v-1"), 0),
                    (event_lines(VALID["finished"], session="v-1"), 0))
    wrapper = replace(_wrapper(tmp_path, _hooks("after-validate = 'test -e explained'"), claude),
                      target=lambda *_: target)

    line = wrapper.run("validate", CHANGE)

    assert (line["outcome"], line["next"]) == ("finished", target)


# Interactively.

def test_a_step_held_interactively_runs_its_hooks_and_records_its_inputs(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CW-h3ks: `run before|after` runs the hook into the session's inputs directory,
    and `record` names it and takes what ran."""
    configured(tmp_path, _hooks("before-implement = 'echo m > {inputs}/m.md'",
                                "after-implement = 'true'"))
    (tmp_path / "openspec/changes" / CHANGE).mkdir(parents=True, exist_ok=True)
    session = {SESSION_ID: "5e55-1011"}
    kept = tmp_path / "kept"
    wrapper = replace(make_wrapper(tmp_path, FakeClaude()), invocations=lambda _: kept)

    assert main(["run", "before", "implement", CHANGE], root=tmp_path, environ=session,
                wrapper=wrapper) == 0
    assert main(["run", "after", "implement", CHANGE], root=tmp_path, environ=session,
                wrapper=wrapper) == 0
    assert main(["record", CHANGE, "implement", "--outcome", json.dumps(VALID["finished"])],
                root=tmp_path, environ=session, wrapper=wrapper) == 0

    run = _reviews(tmp_path) / "runs/session-5e55-1011-implement"
    assert (run / "before/m.md").read_text("utf-8") == "m\n"
    assert (run / "after/status.md").is_file()
    out = capsys.readouterr().out
    assert f"[change-workflow] inputs: reviews/runs/session-5e55-1011-implement/before" in out
    line = json.loads(out.splitlines()[-1])
    assert line["inputs"] == "runs/session-5e55-1011-implement"
    assert [entry["hook"] for entry in line["invoked"]] == ["before-implement",
                                                            "after-implement"]


def test_a_steps_hooks_are_refused_to_another_steps_run(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    configured(tmp_path, _hooks("before-implement = 'touch ran'"))
    (tmp_path / "openspec/changes" / CHANGE).mkdir(parents=True, exist_ok=True)

    assert main(["run", "before", "implement", CHANGE], root=tmp_path,
                environ={UNATTENDED_RUN: "validate"}) == 1

    assert "this is the validate step's run" in capsys.readouterr().err
    assert not (tmp_path / "ran").exists()


@pytest.mark.parametrize("when", ["before", "after"])
def test_an_interactive_review_runs_no_hooks_and_says_so(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], when: str) -> None:
    """CW-h3ks: a review run interactively is no run."""
    configured(tmp_path, _hooks(f"{when}-review = 'touch ran'"))
    (tmp_path / "openspec/changes" / CHANGE).mkdir(parents=True, exist_ok=True)

    assert main(["run", when, "review", CHANGE], root=tmp_path,
                environ={SESSION_ID: SESSION}) == 0

    assert (f"[change-workflow] {when}-review: skipped, a review run interactively is no "
            "run, so it runs no hooks") in capsys.readouterr().out
    assert not (tmp_path / "ran").exists()
    assert not (_reviews(tmp_path) / "runs").exists()


@pytest.mark.parametrize("session", ["../elsewhere", "a/b", ".", ".."])
def test_a_session_id_that_would_name_another_directory_is_refused(
        tmp_path: Path, session: str) -> None:
    with pytest.raises(StepError, match="no session id a directory can be named for"):
        around.session_inputs(tmp_path, session, "implement")


@pytest.mark.parametrize("arguments", [["run", "before", CHANGE],
                                       ["run", "after", "deploy", CHANGE],
                                       ["run", "pre-archive", "implement", CHANGE]])
def test_run_before_and_after_take_a_step_and_a_change(tmp_path: Path,
                                                       arguments: list[str]) -> None:
    configured(tmp_path, _hooks())

    assert main(arguments, root=tmp_path, environ={}) == 2
