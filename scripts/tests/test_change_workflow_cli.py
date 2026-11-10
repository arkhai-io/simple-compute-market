"""The engine's command, `scripts/change-workflow`: each subcommand reaches its module,
every exit status is one of three, `start` holds the make targets' entry logic, and
the make fragment's targets call the command.

The repository, a change's directory, its clone, and an open round view are Git's
and the filesystem's own state, so real repositories in a temporary directory are
the lowest level that proves them; an interactive session's launch and an
unattended run's harness are injected.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Sequence

import pytest

from change_workflow import (clone, cli, config, cost_report, diagram, find, history, hook, index,
                             next_step, push, round_view, skills, tasks)
from change_workflow.common import FORMAT, StepError
from change_workflow.log import log_path, read_log, record_outcome
from change_workflow.review import check_review
from change_workflow_fixtures import (CHANGE, CONFIGURED, LANDED, VALID, FakeClaude,
                                      configured, event_lines, make_wrapper, option_rules)

REPO = Path(__file__).resolve().parents[2]
FRAGMENT = REPO / "scripts" / "change_workflow" / "workflow.mk"
ARCHIVED = "openspec/changes/archive/2026-10-01-" + CHANGE


@pytest.fixture(autouse=True)
def _git_isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.invalid")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def _repository(path: Path, *changes: str) -> Path:
    """A checkout with a commit, its workflow configuration, and an active directory
    for each of `changes`."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    configured(path)
    for change in changes:
        (path / "openspec/changes" / change).mkdir(parents=True, exist_ok=True)
        (path / "openspec/changes" / change / "README").write_text("x\n", "utf-8")
    (path / "README.md").write_text("x\n", "utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "start")
    return path


def _archive(root: Path) -> Path:
    archived = root / ARCHIVED
    archived.mkdir(parents=True)
    return archived


class Launched:
    """Stands in for an interactive session: records each command it is given."""

    def __init__(self, status: int = 0) -> None:
        self.status = status
        self.commands: list[list[str]] = []

    def __call__(self, command: Sequence[str], root: Path) -> int:
        self.commands.append(list(command))
        return self.status


def _printed(capsys: pytest.CaptureFixture[str], run: Callable[[], int]) -> tuple[int, str, str]:
    status = run()
    captured = capsys.readouterr()
    return status, captured.out, captured.err


# Each subcommand reaches its module with the arguments it hands the module's own
# command line: what it prints, and its status, are the module's.

@pytest.mark.parametrize("subcommand,module", [
    (["next", CHANGE], lambda root: next_step.main([CHANGE], root=root)),
    (["next", CHANGE, "--plain"], lambda root: next_step.main([CHANGE, "--plain"], root=root)),
    (["find", CHANGE], lambda root: find.main([CHANGE], root=root)),
    (["find", "--active", CHANGE], lambda root: find.main(["--active", CHANGE], root=root)),
    (["find", "--archived", CHANGE], lambda root: find.main(["--archived", CHANGE], root=root)),
    (["find", "--records", CHANGE], lambda root: find.main(["--records", CHANGE], root=root)),
    (["clone", CHANGE], lambda root: clone.main(["create", CHANGE], root=root)),
    (["clone", CHANGE, "--branch", "b", "--from", "main"],
     lambda root: clone.main(["create", CHANGE, "--branch", "b", "--from", "main"], root=root)),
    (["clone-remove", CHANGE], lambda root: clone.main(["remove", CHANGE], root=root)),
    (["round-view", CHANGE], lambda root: round_view.main(["start", CHANGE], root=root)),
    (["round-done"], lambda root: round_view.main(["done"], root=root)),
    (["history", CHANGE], lambda root: history.main(["sync", CHANGE], root=root)),
    (["cost", CHANGE], lambda root: cost_report.main([CHANGE], root=root)),
    (["push"], lambda root: push.main(["push"], root=root)),
    (["check", "index"], lambda root: index.main(root)),
    (["check", "tasks", CHANGE], lambda root: tasks.main([CHANGE], root=root)),
    (["check", "push"], lambda root: push.main(["check"], root=root)),
    (["check", "skills"], lambda root: skills.main(root)),
    (["check", "round-view"], lambda root: round_view.main(["check"], root=root)),
    (["hook", "post-compaction"], lambda root: hook.main(root)),
])
def test_a_subcommand_does_what_its_modules_command_line_does(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], subcommand: list[str],
        module: Callable[[Path], int]) -> None:
    # A workspace whose change's clone directory is a file, a dirty worktree, and no
    # round view: every subcommand here reads it or refuses, and none changes it.
    root = _repository(tmp_path / "workspace", CHANGE)
    (root / "openspec/changes/README.md").write_text("", "utf-8")
    (tmp_path / "workspace.changes").mkdir()
    (tmp_path / "workspace.changes" / CHANGE).write_text("not a clone\n", "utf-8")

    expected = _printed(capsys, lambda: module(root))
    assert _printed(capsys, lambda: cli.main(subcommand, root=root)) == expected
    assert expected[0] in (0, 1)


@pytest.mark.parametrize("text,status", [
    ("# Design review — c\n\n## Summary\n\nWhat.\n\n## Assessment\n\nSound.\n\n"
     "## Questions\n\nNone.\n\n## Findings\n\nNone.\n\n## Readiness\n\nReady.\n", 0),
    ("Not a review.\n", 1),
])
def test_check_review_reads_the_review_on_standard_input(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
        text: str, status: int) -> None:
    expected = _printed(capsys, lambda: check_review(text, "design", "c"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))

    assert _printed(capsys, lambda: cli.main(["check", "review", "design", "c"],
                                             root=tmp_path)) == expected
    assert expected[0] == status


def test_check_review_refuses_an_unknown_kind(tmp_path: Path) -> None:
    assert cli.main(["check", "review", "kindly", "c"], root=tmp_path) == 2


@pytest.mark.parametrize("subcommand,module,arguments", [
    (["next", "c", "--plain"], next_step.main, ["c", "--plain"]),
    (["find", "--archived", "--json", "c"], find.main, ["--archived", "--json", "c"]),
    (["clone", "c", "--branch", "b", "--from", "main"], clone.main,
     ["create", "c", "--branch", "b", "--from", "main"]),
    (["clone-remove", "c"], clone.main, ["remove", "c"]),
    (["round-view", "c", "--base", "abc"], round_view.main, ["start", "c", "--base", "abc"]),
    (["round-done"], round_view.main, ["done"]),
    (["history", "c"], history.main, ["sync", "c"]),
    (["cost", "c"], cost_report.main, ["c"]),
    (["push"], push.main, ["push"]),
    (["check", "index"], index.main, None),
    (["check", "tasks", "c"], tasks.main, ["c"]),
    (["check", "push"], push.main, ["check"]),
    (["check", "skills"], skills.main, None),
    (["check", "round-view"], round_view.main, ["check"]),
    (["hook", "post-compaction"], hook.main, None),
])
def test_a_subcommand_hands_its_module_every_argument(
        subcommand: list[str], module: Callable[..., int], arguments: list[str] | None) -> None:
    assert cli.delegated(cli._parser().parse_args(subcommand)) == (module, arguments)


def test_check_graph_compares_the_repositorys_own_diagram(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    subcommand = cli._parser().parse_args(["check", "graph"])
    assert cli.delegated(subcommand) == (cli._graph, None)
    # This checkout's diagram draws the table, so the command says so as the module
    # does; a repository with no diagram is refused, naming the file.
    expected = _printed(capsys, lambda: diagram.main(root=REPO))
    assert expected[0] == 0
    assert _printed(capsys, lambda: cli.main(["check", "graph"], root=REPO)) == expected
    status, out, err = _printed(capsys, lambda: cli.main(
        ["check", "graph"], root=_repository(tmp_path / "bare")))
    assert (status, out) == (1, "")
    assert f"cannot read the graph's diagram {diagram.SOURCE}" in err


def test_the_subcommands_this_module_runs_reach_no_other() -> None:
    for subcommand in (["start", "design", "c"], ["clone", "where", "c"], ["log", "c"],
                       ["record", "c", "plan", "--outcome", "{}"], ["watch", "c"]):
        assert cli.delegated(cli._parser().parse_args(subcommand)) is None


# Every exit status is one of three.

@pytest.mark.parametrize("arguments", [
    [], ["deploy"], ["start"], ["start", "review", CHANGE], ["start", "design"],
    ["find"], ["find", "--records", "--json", CHANGE], ["find", "--active", "--archived", CHANGE],
    ["clone", "where"], ["clone", "a", "b"], ["clone", "where", CHANGE, "--from", "dev"],
    ["check"], ["check", "lint"], ["hook", "pre-compaction"], ["next"], ["review", CHANGE],
])
def test_a_usage_error_exits_2(tmp_path: Path, arguments: list[str]) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)

    assert cli.main(arguments, root=root) == 2


def test_the_engine_loads_with_only_its_package_on_the_path(tmp_path: Path) -> None:
    # A repository runs the engine without its own scripts beside the package, so
    # the package imports nothing from beside itself.
    shutil.copytree(FRAGMENT.parent, tmp_path / "change_workflow",
                    ignore=shutil.ignore_patterns("__pycache__"))
    loaded = subprocess.run(
        [sys.executable, "-I", "-c",
         f"import sys; sys.path.insert(0, {str(tmp_path)!r}); import change_workflow.cli"],
        cwd=tmp_path, capture_output=True, text=True)
    assert loaded.returncode == 0, loaded.stderr


def test_success_exits_0_and_a_refusal_exits_1_with_its_reason_on_standard_error(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)

    assert _printed(capsys, lambda: cli.main(["find", CHANGE], root=root))[:2] == (
        0, f"openspec/changes/{CHANGE}\n")
    status, out, err = _printed(capsys, lambda: cli.main(["find", "missing"], root=root))
    assert (status, out) == (1, "")
    assert "'missing'" in err


def test_a_failed_check_exits_1_with_its_reason_on_standard_error(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)
    # A task numbered for the first section under the second's heading.
    (root / "openspec/changes" / CHANGE / next_step.TASKS_FILE).write_text(
        "## 1. First\n\n- [ ] 1.1 One.\n\n## 2. Second\n\n- [ ] 1.2 Strayed.\n", "utf-8")
    # A shared skill with no SKILL.md, and no harness link to it.
    (root / ".agents/skills/lone").mkdir(parents=True)

    for arguments, reason in ((["check", "tasks", CHANGE], "sits under `## 2. Second`"),
                              (["check", "skills"], "shared skill has no SKILL.md")):
        status, out, err = _printed(capsys, lambda: cli.main(arguments, root=root))
        assert (status, out) == (1, "")
        assert reason in err


def test_a_failed_push_exits_1_whatever_git_returned(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)
    # The repository provides no pre-push check, so `git push` itself is what fails.
    _git(root, "remote", "add", "origin", str(tmp_path / "no-such-remote"))
    _git(root, "checkout", "-q", "-b", "feat/x")

    status, out, err = _printed(capsys, lambda: cli.main(["push", "--remote", "origin"],
                                                         root=root))
    assert status == 1
    assert out.startswith("+ git push")
    assert "ERROR: git push exited with status" in err


# `start`: the make targets' entry logic.

@pytest.mark.parametrize("step", ["design", "plan", "implement"])
def test_start_refuses_an_archived_change_for_a_step_taking_an_active_one(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], step: str) -> None:
    root = _repository(tmp_path / "workspace")
    _archive(root)
    launched = Launched()

    status, _, err = _printed(capsys, lambda: cli.main(["start", step, CHANGE], root=root,
                                                       launch=launched))
    assert status == 1
    assert ARCHIVED in err
    assert launched.commands == []


@pytest.mark.parametrize("step", ["triage", "closeout", "validate", "orchestrate"])
def test_start_takes_an_archived_change_for_a_step_that_may_follow_the_archive(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str) -> None:
    root = _repository(tmp_path / "workspace")
    _archive(root)
    (root / ".claude").mkdir()
    (root / ".claude/change-steps.toml").write_text(
        (REPO / ".claude/change-steps.toml").read_text("utf-8"), "utf-8")
    monkeypatch.chdir(root)
    launched = Launched()

    assert cli.main(["start", step, CHANGE], root=root, launch=launched) == 0
    assert launched.commands[0][-1] == f"/change-{step} {CHANGE}"


def test_start_takes_an_archived_change_for_the_merge_after_the_archive(
        tmp_path: Path) -> None:
    """One node of the merge step, the merge after the archive, enters an archived
    change, so `start` takes it; the merge's route check refuses a run the
    computation does not name."""
    root = _repository(tmp_path / "workspace")
    _archive(root)
    launched = Launched()

    assert cli.main(["start", "merge", CHANGE, "--arguments", "from dev"], root=root,
                    launch=launched) == 0
    assert launched.commands[0][-1] == f"/change-merge {CHANGE} from dev"


def test_start_takes_only_an_archived_change_for_archive_cleanup(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)
    launched = Launched()

    status, _, err = _printed(capsys, lambda: cli.main(["start", "archive-cleanup", CHANGE],
                                                       root=root, launch=launched))
    assert status == 1
    assert "not archived" in err
    assert launched.commands == []


def test_start_refuses_an_unknown_change(tmp_path: Path,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path / "workspace")

    status, _, err = _printed(capsys, lambda: cli.main(["start", "design", "missing"],
                                                       root=root, launch=Launched()))
    assert status == 1
    assert "'missing'" in err


def _open_round_view(root: Path) -> None:
    state = Path(_git(root, "rev-parse", "--git-path", round_view.STATE))
    view = round_view.View(change=CHANGE, branch="feat/x", base="a" * 40, head="b" * 40)
    (state if state.is_absolute() else root / state).write_text(json.dumps(asdict(view)),
                                                                "utf-8")


@pytest.mark.parametrize("step", sorted(cli.ROUND_VIEW_CLOSED))
def test_start_refuses_while_a_round_view_is_open_for_a_step_reading_head(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], step: str) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)
    if step == "archive-cleanup":
        (root / "openspec/changes" / CHANGE / "README").unlink()
        (root / "openspec/changes" / CHANGE).rmdir()
        _archive(root)
    _open_round_view(root)
    launched = Launched()

    status, _, err = _printed(capsys, lambda: cli.main(["start", step, CHANGE], root=root,
                                                       launch=launched))
    assert status == 1
    assert "round view" in err
    assert launched.commands == []


def test_review_and_push_refuse_while_a_round_view_is_open(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)
    _open_round_view(root)

    for arguments in (["review", CHANGE, "--kind", "design"], ["push"]):
        status, out, err = _printed(capsys, lambda: cli.main(arguments, root=root))
        assert (status, out) == (1, "")
        assert "round view" in err


def test_design_and_planning_start_while_a_round_view_is_open(tmp_path: Path) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)
    _open_round_view(root)
    launched = Launched()

    assert cli.main(["start", "design", CHANGE], root=root, launch=launched) == 0
    assert cli.main(["start", "plan", CHANGE], root=root, launch=launched) == 0
    assert [command[-1] for command in launched.commands] == [
        f"/change-design {CHANGE}", f"/change-plan {CHANGE}"]


@pytest.mark.parametrize("arguments,prompt", [
    (["design"], f"/change-design {CHANGE}"),
    (["implement", "--sections", "2"], f"/change-implement {CHANGE} section 2"),
    (["implement", "--sections", "1-3"], f"/change-implement {CHANGE} sections 1-3"),
    (["merge", "--arguments", "from dev"], f"/change-merge {CHANGE} from dev"),
    (["validate", "--arguments", "with HELM_ALL_SCENARIOS=1"],
     f"/change-validate {CHANGE} with HELM_ALL_SCENARIOS=1"),
])
def test_an_interactive_start_opens_the_steps_skill(tmp_path: Path, arguments: list[str],
                                                    prompt: str) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)
    launched = Launched()

    assert cli.main(["start", arguments[0], CHANGE, *arguments[1:]], root=root,
                    launch=launched) == 0
    assert launched.commands == [["claude", prompt]]


def test_a_change_worked_in_place_merges_with_no_base_given(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CW-s3ju: with no clone to have recorded the branch the change lands on, and
    none given, the merge refuses, naming the argument that gives it, and starts
    nothing."""
    root = _repository(tmp_path / "workspace", CHANGE)
    launched = Launched()

    status, _, err = _printed(capsys, lambda: cli.main(["start", "merge", CHANGE], root=root,
                                                       launch=launched))

    assert status == 1
    assert "FROM=<branch>" in err and "--arguments 'from <branch>'" in err
    assert launched.commands == []


def test_the_merge_brings_in_the_branch_the_clone_recorded(tmp_path: Path) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)
    clone_root = find.clone_directory(root, CHANGE)
    _git(tmp_path, "clone", "-q", "--origin", "workspace", str(root), str(clone_root))
    (clone_root / ".git" / find.CLONE_MARKER).write_text(
        json.dumps({"change": CHANGE, "branch": f"feat/{CHANGE}", "base": "release/2.1"}),
        "utf-8")
    launched = Launched()

    assert cli.main(["start", "merge", CHANGE], root=clone_root, launch=launched) == 0
    assert cli.main(["start", "merge", CHANGE, "--arguments", "from main"], root=clone_root,
                    launch=launched) == 0
    # Only a leading `from <branch>` names the branch; other words are the skill's.
    assert cli.main(["start", "merge", CHANGE, "--arguments", "keep notes from me"],
                    root=clone_root, launch=launched) == 0

    assert [command[-1] for command in launched.commands] == [
        f"/change-merge {CHANGE} from release/2.1", f"/change-merge {CHANGE} from main",
        f"/change-merge {CHANGE} from release/2.1 keep notes from me"]


def test_an_interactive_session_that_fails_exits_1_naming_its_status(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)

    status, _, err = _printed(capsys, lambda: cli.main(["start", "design", CHANGE], root=root,
                                                       launch=Launched(status=130)))
    assert status == 1
    assert "status 130" in err


def test_an_unattended_run_that_stops_exits_1_with_its_reason_on_standard_error(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)
    claude = FakeClaude((event_lines(VALID["stopped"]), 0))

    status, out, err = _printed(capsys, lambda: cli.main(
        ["start", "plan", CHANGE, "--unattended"], root=root,
        wrapper=make_wrapper(root, claude)))
    line = json.loads(out)
    assert (status, line["outcome"]) == (1, "stopped")
    assert f"ERROR: {line['reason']}" in err


@pytest.mark.parametrize("flag", [["--allow", "Bash(make lock)"], ["--session", "s-1"],
                                  ["--fresh"]])
def test_an_interactive_start_refuses_what_qualifies_an_unattended_run(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], flag: list[str]) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)
    launched = Launched()

    status, _, err = _printed(capsys, lambda: cli.main(["start", "implement", CHANGE, *flag],
                                                       root=root, launch=launched))
    assert status == 2
    assert "unattended" in err
    assert launched.commands == []


@pytest.mark.parametrize("arguments", [
    ["design", CHANGE, "--sections", "2"], ["implement", CHANGE, "--sections", "3-1"],
])
def test_start_refuses_sections_it_cannot_take_as_a_usage_error(
        tmp_path: Path, arguments: list[str]) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)

    assert cli.main(["start", *arguments], root=root, launch=Launched()) == 2


def test_a_session_that_cannot_be_started_is_a_refusal(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)

    def missing(command: Sequence[str], root: Path) -> int:
        return cli._launch(["no-such-harness-anywhere", *command[1:]], root)

    status, _, err = _printed(capsys, lambda: cli.main(["start", "design", CHANGE], root=root,
                                                       launch=missing))
    assert status == 1
    assert "cannot run no-such-harness-anywhere" in err


def test_an_unattended_start_runs_the_step_through_the_wrapper(tmp_path: Path) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)
    claude = FakeClaude((event_lines({**VALID["finished"], "landing": LANDED}), 0))
    launched = Launched()

    assert cli.main(["start", "merge", CHANGE, "--arguments", "from dev", "--unattended",
                     "--allow", "Bash(make lock)"], root=root, launch=launched,
                    wrapper=make_wrapper(root, claude)) == 0
    assert launched.commands == []
    assert claude.commands[0][2] == f"/change-merge {CHANGE} from dev"
    assert option_rules(claude.commands[0], "--allowedTools")[-1] == "Bash(make lock)"


class Recorded(Launched):
    """An interactive session that reads the change's log as it opens, as the step's
    first record would follow whatever the log already holds."""

    def __init__(self, log: Path) -> None:
        super().__init__()
        self.log = log
        self.seen: list[list[dict]] = []

    def __call__(self, command: Sequence[str], root: Path) -> int:
        self.seen.append(read_log(self.log))
        return super().__call__(command, root)


def _opening(line: dict, step: str, interactive: bool) -> bool:
    return (line["format"], line["step"], line["outcome"], line["starts"],
            line["interactive"]) == (FORMAT, "start", "opened", step, interactive)


def test_an_interactive_start_opens_the_log_before_the_session(tmp_path: Path) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)
    log = log_path(root, CHANGE)
    launched = Recorded(log)

    assert cli.main(["start", "design", CHANGE], root=root, launch=launched) == 0

    (opened,) = launched.seen[0]
    assert _opening(opened, "design", True)
    assert read_log(log) == [opened]


def test_an_unattended_start_opens_the_log_before_the_run(tmp_path: Path) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)
    claude = FakeClaude((event_lines(VALID["finished"]), 0))

    assert cli.main(["start", "plan", CHANGE, "--unattended"], root=root,
                    wrapper=make_wrapper(root, claude)) == 0

    opened, run = read_log(log_path(root, CHANGE))
    assert _opening(opened, "plan", False)
    assert (run["step"], run["seq"]) == ("plan", opened["seq"] + 1)


def test_the_next_step_routes_on_no_opening_line(tmp_path: Path) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)
    (root / "openspec/changes/README.md").write_text(
        "| Change | Status | Depends on | Notes | Acceptance boundary |\n|---|---|---|---|---|\n"
        f"| [`{CHANGE}`]({CHANGE}/) | in design | — | n | x |\n", "utf-8")
    seams = {"branch": lambda _: f"feat/{CHANGE}", "workspace": lambda _: None,
             "clone": lambda *_: None}
    before = next_step.compute(root, CHANGE, **seams)

    assert cli.main(["start", "design", CHANGE], root=root, launch=Launched()) == 0
    # A log holding the opening line alone reads as no log at all.
    opened = next_step.compute(root, CHANGE, **seams)
    record_outcome(log_path(root, CHANGE), "design",
                   {**VALID["finished"], "next": {"step": "review", "kind": "design"}},
                   session="s", commit="c")
    assert cli.main(["start", "triage", CHANGE], root=root, launch=Launched()) == 0

    assert before == opened == {"step": "design", "reason": "in design"}
    # The design's exit stands after the triage's opening line, which routes nothing.
    assert next_step.compute(root, CHANGE, **seams)["kind"] == "design"
    assert next_step.compute(root, CHANGE, **seams)["step"] == "review"


@pytest.mark.parametrize("prepare,named", [
    (lambda reviews: (reviews / "03-implementation.md").write_text("x", "utf-8"),
     "no workflow log"),
    (lambda reviews: (reviews / "workflow.jsonl").write_text('{"seq": 1}\n', "utf-8"),
     "an older format at seq 1"),
    (lambda reviews: (reviews / "workflow.jsonl").write_text(
        json.dumps({"seq": 1, "format": FORMAT + 1}) + "\n", "utf-8"),
     f"format {FORMAT + 1}"),
])
def test_start_refuses_records_of_another_format_and_starts_nothing(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], prepare, named: str) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)
    reviews = root / "openspec/changes" / CHANGE / "reviews"
    reviews.mkdir()
    prepare(reviews)
    before = {path.name: path.read_text("utf-8") for path in reviews.iterdir()}
    launched = Launched()

    status, _, err = _printed(capsys, lambda: cli.main(["start", "design", CHANGE], root=root,
                                                       launch=launched))

    assert status == 1 and named in err
    assert launched.commands == []
    assert {path.name: path.read_text("utf-8") for path in reviews.iterdir()} == before


def test_the_owner_starts_the_orchestrating_session(tmp_path: Path) -> None:
    """CW-w2ld: on the model and effort the configuration's `models.orchestrator`
    names."""
    root = _repository(tmp_path / "workspace", CHANGE)
    configured(root, CONFIGURED.replace(
        'orchestrator = { model = "claude-opus-5-5", effort = "medium" }',
        'orchestrator = { model = "claude-sonnet-5-5", effort = "low" }'))
    launched = Launched()

    assert cli.main(["start", "orchestrate", CHANGE], root=root, launch=launched) == 0
    assert launched.commands == [["claude", "--model", "claude-sonnet-5-5", "--effort", "low",
                                  f"/change-orchestrate {CHANGE}"]]


@pytest.mark.parametrize("flags", [["--unattended"], ["--arguments", "now"]])
def test_start_orchestrate_takes_the_change_alone(tmp_path: Path, flags: list[str]) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)

    assert cli.main(["start", "orchestrate", CHANGE, *flags], root=root,
                    launch=Launched()) == 2


def test_start_orchestrate_refuses_a_configuration_without_its_model(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path / "workspace", CHANGE)
    configured(root, CONFIGURED.replace(
        'orchestrator = { model = "claude-opus-5-5", effort = "medium" }\n', ""))
    launched = Launched()

    status, _, err = _printed(capsys, lambda: cli.main(["start", "orchestrate", CHANGE],
                                                       root=root, launch=launched))
    assert status == 1
    assert "models.orchestrator" in err
    assert launched.commands == []


@pytest.mark.parametrize("entry,problem", [
    ('{ model = "claude-opus-5-5", allow = ["Bash(ls)"] }',
     "models.orchestrator.allow is no field"),
    ('{ model = "claude-opus-5-5", harness = "claude" }',
     "models.orchestrator.harness is no field"),
    ('{ effort = "medium" }', "models.orchestrator.model must be a non-empty string"),
    ('{ model = "claude-opus-5-5", effort = "" }', "models.orchestrator.effort must be"),
])
def test_the_orchestrators_model_is_a_model_and_effort_and_nothing_else(
        entry: str, problem: str) -> None:
    with pytest.raises(StepError, match=problem):
        config.check(f"[models]\norchestrator = {entry}\n", Path("workflow.toml"))


def test_this_repositorys_orchestrator_is_opus_at_medium_effort() -> None:
    # The orchestrating session relays and routes rather than judging: it needs a
    # large context for a change's relayed turns, not a high effort.
    model = config.load(REPO).orchestrator_model()
    assert (model.harness, model.model, model.effort) == ("claude", "claude-opus-5-5", "medium")


# `find --json`.

def test_find_json_prints_the_change_for_a_program(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path / "workspace", CHANGE, "other")
    (root / "openspec/changes" / CHANGE / "reviews").mkdir()

    assert _printed(capsys, lambda: cli.main(["find", "--json", CHANGE], root=root))[0] == 0
    # A change worked in place, with no clone, records no branch it lands on.
    assert _printed(capsys, lambda: cli.main(["find", "--json", CHANGE], root=root))[1] == (
        json.dumps({"name": CHANGE, "directory": f"openspec/changes/{CHANGE}",
                    "archived": False, "records": f"openspec/changes/{CHANGE}/reviews",
                    "format": FORMAT, "base": None}) + "\n")
    status, out, _ = _printed(capsys, lambda: cli.main(["find", "--json", "other"], root=root))
    assert status == 0
    assert json.loads(out)["records"] is None


def test_find_json_prints_the_branch_a_clone_recorded(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CW-s3ju: `base` is the branch the change's clone recorded, read from the
    workspace in the clone beside it, and in the clone itself."""
    root = _repository(tmp_path / "workspace", CHANGE)
    clone_root = find.clone_directory(root, CHANGE)
    _git(tmp_path, "clone", "-q", "--origin", "workspace", str(root), str(clone_root))
    marker = clone_root / ".git" / find.CLONE_MARKER
    marker.write_text(json.dumps({"change": CHANGE, "branch": f"feat/{CHANGE}",
                                  "base": "release/2.1"}), "utf-8")

    for checkout in (root, clone_root):
        status, out, _ = _printed(capsys, lambda: cli.main(["find", "--json", CHANGE],
                                                           root=checkout))
        assert status == 0 and json.loads(out)["base"] == "release/2.1"


def test_find_json_says_an_archived_change_is_archived(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path / "workspace")
    (_archive(root) / "reviews").mkdir()

    status, out, _ = _printed(capsys, lambda: cli.main(["find", "--json", CHANGE], root=root))
    assert status == 0
    assert json.loads(out) == {"name": CHANGE, "directory": ARCHIVED, "archived": True,
                               "records": f"{ARCHIVED}/reviews", "format": FORMAT,
                               "base": None}
    assert cli.main(["find", "--active", "--json", CHANGE], root=root) == 1


def test_find_json_refuses_an_unknown_change_naming_it(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path / "workspace")

    status, out, err = _printed(capsys, lambda: cli.main(["find", "--json", "missing"],
                                                         root=root))
    assert (status, out) == (1, "")
    assert "'missing'" in err


# `clone where`: four cases, against real clones.

def _clone_of(workspace: Path, change: str, *, branch: str | None = None,
              bootstrapped: bool = True) -> Path:
    """The change's clone beside `workspace`, as `clone` leaves it: its `workspace`
    remote naming the workspace, the change's branch checked out, and its bootstrap's
    exit status recorded."""
    target = clone.clone_directory(workspace, change)
    target.parent.mkdir(parents=True, exist_ok=True)
    _git(workspace.parent, "clone", "-q", "--origin", clone.WORKSPACE_REMOTE, str(workspace),
         str(target))
    _git(target, "checkout", "-q", "-b", branch or clone.default_branch(change))
    if bootstrapped:
        status = Path(_git(target, "rev-parse", "--git-path", clone.BOOTSTRAP_STATUS))
        (status if status.is_absolute() else target / status).write_text("0\n", "utf-8")
    return target


def test_clone_where_refuses_an_unknown_change_before_looking_for_a_clone(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace = _repository(tmp_path / "workspace", CHANGE)
    _clone_of(workspace, "missing")

    status, out, err = _printed(capsys, lambda: cli.main(["clone", "where", "missing"],
                                                         root=workspace))
    assert (status, out) == (1, "")
    assert "'missing'" in err


def test_clone_where_prints_a_usable_clones_path(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace = _repository(tmp_path / "workspace", CHANGE)
    target = _clone_of(workspace, CHANGE)

    assert _printed(capsys, lambda: cli.main(["clone", "where", CHANGE], root=workspace)) == (
        0, f"{target}\n", "")


def test_clone_where_prints_nothing_for_a_change_worked_in_place(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace = _repository(tmp_path / "workspace", CHANGE)

    assert _printed(capsys, lambda: cli.main(["clone", "where", CHANGE], root=workspace)) == (
        0, "", "")


@pytest.mark.parametrize("unusable,reason", [
    ("plain directory", "is not a clone of"),
    ("another branch", "does not have feat/"),
    ("no bootstrap", "bootstrap is absent"),
])
def test_clone_where_refuses_a_clone_directory_it_cannot_use_naming_why(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], unusable: str,
        reason: str) -> None:
    workspace = _repository(tmp_path / "workspace", CHANGE)
    if unusable == "plain directory":
        clone.clone_directory(workspace, CHANGE).mkdir(parents=True)
    else:
        _clone_of(workspace, CHANGE, branch="other" if unusable == "another branch" else None,
                  bootstrapped=unusable != "no bootstrap")

    status, out, err = _printed(capsys, lambda: cli.main(["clone", "where", CHANGE],
                                                         root=workspace))
    assert (status, out) == (1, "")
    assert reason in err


def test_clone_where_run_in_a_clone_looks_beside_its_workspace(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace = _repository(tmp_path / "workspace", CHANGE)
    target = _clone_of(workspace, CHANGE)

    assert _printed(capsys, lambda: cli.main(["clone", "where", CHANGE], root=target)) == (
        0, f"{target}\n", "")


# The make fragment.

def _fragment(tmp_path: Path, target: str, *variables: str) -> list[str]:
    """What `make -n` prints for `target` of a Makefile that includes the fragment,
    with no step variable inherited."""
    makefile = tmp_path / "Makefile"
    makefile.write_text(f"include {FRAGMENT}\n", "utf-8")
    env = {key: value for key, value in os.environ.items()
           if key not in ("UNATTENDED", "SECTION", "SECTIONS", "FRESH", "ALLOW", "ARGUMENTS",
                          "SESSION_ID", "REVIEW_BASE", "REVIEW_MODEL", "REVIEW_EFFORT",
                          "UNVALIDATED", "FROM", "BASE", "BRANCH", "KIND", "CHANGE",
                          "MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "MAKELEVEL")}
    output = subprocess.run(["make", "-n", "--no-print-directory", "-f", str(makefile), target,
                             *variables], cwd=tmp_path, capture_output=True, text=True,
                            check=True, env=env).stdout
    return output.splitlines()


COMMAND = "scripts/change-workflow"


@pytest.mark.parametrize("target,variables,commands", [
    ("design", [], [f'{COMMAND} start design "X"']),
    ("design", ["UNATTENDED=1", "ALLOW=Bash(make lock);Bash(gh run *)"],
     [f"{COMMAND} start design \"X\" --unattended --allow 'Bash(make lock)' "
      "--allow 'Bash(gh run *)'"]),
    ("design", ["ARGUMENTS=x"], [f'{COMMAND} start design "X"']),
    ("design", ["UNATTENDED=1", "ARGUMENTS=it's"],
     [f"{COMMAND} start design \"X\" --arguments 'it'\\''s' --unattended"]),
    ("plan", ["FRESH=1", "ARGUMENTS=x"], [f'{COMMAND} start plan "X"']),
    ("plan", ["UNATTENDED=1", "FRESH=1"], [f'{COMMAND} start plan "X" --fresh --unattended']),
    ("plan", ["UNATTENDED=1", "FRESH=1", "ARGUMENTS=go on"],
     [f"{COMMAND} start plan \"X\" --fresh --arguments 'go on' --unattended"]),
    ("implement", ["SECTIONS=1-2", "ARGUMENTS=x", "SESSION_ID=s"],
     [f'{COMMAND} start implement "X" --sections "1-2"']),
    ("implement", ["SECTION=3", "UNATTENDED=1", "ARGUMENTS=it's", "SESSION_ID=s-1"],
     [f"{COMMAND} start implement \"X\" --sections \"3\" --arguments 'it'\\''s' "
      "--session 's-1' --unattended"]),
    # No base given: the engine reads the branch the change lands on.
    ("review", ["KIND=design"],
     [f'{COMMAND} review "X" --kind "design"     ']),
    ("review", ["KIND=closeout", "REVIEW_BASE=main", "REVIEW_MODEL=m", "REVIEW_EFFORT=high",
                "FRESH=1", "UNVALIDATED=1"],
     [f'{COMMAND} review "X" --kind "closeout" --base "main" --model "m" --effort "high" '
      "--fresh --unvalidated"]),
    ("triage", ["UNATTENDED=1"], [f'{COMMAND} start triage "X" --unattended']),
    ("validate", ["ARGUMENTS=with HELM_ALL_SCENARIOS=1"],
     [f"{COMMAND} start validate \"X\" --arguments 'with HELM_ALL_SCENARIOS=1'"]),
    ("merge", [], [f'{COMMAND} start merge "X"']),
    ("merge", ["FROM=release", "UNATTENDED=1"],
     [f"{COMMAND} start merge \"X\" --arguments 'from release' --unattended"]),
    ("closeout", [], [f'{COMMAND} start closeout "X"']),
    ("archive-cleanup", ["UNATTENDED=1"], [f'{COMMAND} start archive-cleanup "X" --unattended']),
    ("orchestrate", [], [f'{COMMAND} start orchestrate "X"']),
    ("change-next", [], [f'{COMMAND} find "X" >/dev/null', f'{COMMAND} next "X" --plain']),
    ("change-clone", ["BRANCH=b", "FROM=main"],
     [f'{COMMAND} clone "X" --branch "b" --from "main"']),
    ("change-clone-remove", [], [f'{COMMAND} clone-remove "X"']),
    ("change-clone-remove", ["BASE=main"], [f'{COMMAND} clone-remove "X" --base "main"']),
    ("round-view", ["BASE=abc"], [f'{COMMAND} round-view "X" --base "abc"']),
    ("round-done", [], [f"{COMMAND} round-done"]),
    ("round-view-closed", [], [f"{COMMAND} check round-view"]),
    ("change-watch", [], [f'{COMMAND} watch "X"']),
    ("change-cost", [], [f'{COMMAND} find "X" >/dev/null', f'{COMMAND} cost "X"']),
    ("change-history", [], [f'{COMMAND} history "X"']),
    ("check-change-index", [], [f"{COMMAND} check index"]),
    ("check-tasks", [], [f'{COMMAND} check tasks "X"']),
    ("check-agent-skills", [], [f"{COMMAND} check skills"]),
    ("check-push-ready", [], [f"{COMMAND} check round-view", f"{COMMAND} check push"]),
    ("push-branch", [], [f"{COMMAND} push"]),
    ("change-graph", [], [f"{COMMAND} check graph"]),
])
def test_a_fragment_target_runs_the_command(tmp_path: Path, target: str,
                                            variables: list[str], commands: list[str]) -> None:
    assert _fragment(tmp_path, target, "CHANGE=X", *variables) == commands


def test_a_value_set_before_the_include_stands(tmp_path: Path) -> None:
    makefile = tmp_path / "Makefile"
    makefile.write_text("CHANGE_WORKFLOW := bin/cw\nREVIEW_BASE := trunk\n"
                        f"include {FRAGMENT}\n", "utf-8")
    output = subprocess.run(["make", "-n", "--no-print-directory", "-f", str(makefile), "review",
                             "CHANGE=X", "KIND=design"], cwd=tmp_path, capture_output=True,
                            text=True, check=True,
                            env={k: v for k, v in os.environ.items()
                                 if k not in ("MAKEFLAGS", "MFLAGS", "REVIEW_BASE",
                                              "CHANGE_WORKFLOW")}).stdout
    assert output.startswith('bin/cw review "X" --kind "design" --base "trunk"')


def test_the_fragment_says_its_targets_carry_no_compatibility_promise() -> None:
    head = FRAGMENT.read_text("utf-8").split("\n\n", 1)[0]
    assert "no compatibility promise" in head
