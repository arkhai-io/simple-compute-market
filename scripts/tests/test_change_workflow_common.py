"""The engine acts on the repository it runs in, and takes its steps and review
kinds from the graph alone.

The repository is Git's own answer for the working directory, so real repositories
in a temporary directory — one with a subdirectory, a clone of it, and a directory
no repository contains — are the lowest level that proves it.
"""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import pytest

from change_workflow import (cli, clone, cost_report, diagram, find, graph, history, hook, index,
                             next_step, push, round_view, skills, tasks)
from change_workflow.common import NotInRepository, repository_root

PACKAGE = Path(__file__).resolve().parents[1] / "change_workflow"


@pytest.fixture(autouse=True)
def _git_isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    # Git looks no higher than the test's directory, so a directory in it that no
    # repository contains is outside every repository, wherever the test runs.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))


def _repository(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def test_the_root_is_the_top_level_of_the_repository_holding_the_directory(
        tmp_path: Path) -> None:
    repo = _repository(tmp_path / "workspace")
    (repo / "scripts" / "deep").mkdir(parents=True)

    assert repository_root(repo / "scripts" / "deep") == repo.resolve()
    assert repository_root(repo) == repo.resolve()


def test_the_root_defaults_to_the_working_directory(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repository(tmp_path / "workspace")
    (repo / "docs").mkdir()
    monkeypatch.chdir(repo / "docs")

    assert repository_root() == repo.resolve()


def test_in_a_clone_the_root_is_the_clone_not_the_repository_it_was_cloned_from(
        tmp_path: Path) -> None:
    workspace = _repository(tmp_path / "workspace")
    clone = tmp_path / "workspace.changes" / "a-change"
    subprocess.run(["git", "clone", "-q", str(workspace), str(clone)], check=True,
                   capture_output=True)

    assert repository_root(clone) == clone.resolve()


def test_in_this_checkout_the_root_is_where_the_engine_sits(monkeypatch: pytest.MonkeyPatch,
                                                           ) -> None:
    monkeypatch.delenv("GIT_CEILING_DIRECTORIES")

    assert repository_root(PACKAGE) == PACKAGE.parents[1]


def test_outside_any_repository_the_root_is_refused_naming_the_directory(
        tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(NotInRepository, match=f"{outside} is not inside a Git repository"):
        repository_root(outside)


@pytest.mark.parametrize("command", [
    lambda: find.main(["a-change"]),
    lambda: next_step.main(["a-change"]),
    lambda: cli.main(["log", "a-change"]),
    lambda: clone.main(["create", "a-change"]),
    lambda: history.main(["sync", "a-change"]),
    lambda: round_view.main(["check"]),
    lambda: cost_report.main(["a-change"]),
    lambda: index.main(),
    lambda: tasks.main(["a-change"]),
    lambda: push.main(["check"]),
    lambda: skills.main(),
    lambda: hook.main(),
    lambda: diagram.main(),
])
def test_a_command_run_outside_any_repository_refuses_and_writes_nothing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
        command) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    assert command() == 1
    assert f"{outside} is not inside a Git repository" in capsys.readouterr().err
    assert list(outside.iterdir()) == []


def test_the_steps_and_kinds_are_those_the_graph_declares() -> None:
    assert graph.STEPS == tuple(dict.fromkeys(d.runs for d in graph.TABLE if d.runs))
    assert set(graph.STEPS) == {"design", "plan", "review", "triage", "implement", "validate",
                                "merge", "closeout", "archive-cleanup"}
    assert graph.KINDS == ("design", "implementation", "pre-closeout", "closeout")
    assert set(graph.KINDS) == {node.kind for node in graph.NODES if node.step == "review"}


def test_the_phase_a_step_is_compared_in_is_read_from_the_graph() -> None:
    assert next_step._STEP_PHASE == {
        "design": "design", "plan": "planning", "implement": "implementation",
        "validate": "implementation", "merge": "implementation", "triage": None,
        "review": None, "closeout": "closeout", "archive-cleanup": "closeout"}


def test_no_module_but_the_graph_keeps_a_list_of_steps_or_kinds() -> None:
    declaring = {}
    for module in sorted(PACKAGE.glob("*.py")):
        for node in ast.walk(ast.parse(module.read_text("utf-8"))):
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target] if isinstance(node, ast.AnnAssign) else [])
            for target in targets:
                if isinstance(target, ast.Name) and target.id in ("STEPS", "KINDS"):
                    declaring.setdefault(target.id, []).append(module.name)

    assert declaring == {"STEPS": ["graph.py"], "KINDS": ["graph.py"]}
