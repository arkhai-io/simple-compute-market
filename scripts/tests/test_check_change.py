"""This repository's own closing checks of a change run as one command that fails
when any one fails and says so in one line when all pass."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Sequence

import pytest

from check_change import checks, main, run_checks

CHANGE = "shape-bounds"
# The workflow's default checks — the change index, the task list, the agent skills,
# and the OpenSpec validation — are the `pre-commit` hook's, run before this
# repository's command, so none is here.
NAMES = ["comment hygiene", "documentation citations", "specification index",
         "decision destinations", "history wording", "version bumps", "local imports",
         "capability index"]


def _checkout(tmp_path: Path) -> Path:
    """A Git repository, where the workflow's command finds a change."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def _change(tmp_path: Path, lands_on: str | None = "dev") -> Path:
    """A change in a checkout that is its clone, the clone's marker recording the
    branch it lands on, or none."""
    (tmp_path / "openspec/changes" / CHANGE).mkdir(parents=True)
    root = _checkout(tmp_path)
    if lands_on is not None:
        (root / ".git/change-clone.json").write_text(
            json.dumps({"change": CHANGE, "base": lands_on}), "utf-8")
    return root


class FakeChecks:
    """Stands in for the checks: records each command, and fails the one named."""

    def __init__(self, failing: str | None = None) -> None:
        self.failing = failing
        self.commands: list[list[str]] = []

    def __call__(self, command: Sequence[str], cwd: Path) -> tuple[int, str]:
        self.commands.append(list(command))
        name = NAMES[len(self.commands) - 1]
        return (1, f"{name} said why\n") if name == self.failing else (0, f"{name} chatter\n")


def test_every_check_passing_prints_one_line(tmp_path: Path) -> None:
    shown: list[str] = []
    runner = FakeChecks()

    status = run_checks(CHANGE, root=_change(tmp_path), runner=runner, echo=shown.append)

    assert status == 0
    assert shown == [f"OK: every check of {CHANGE} passed: " + ", ".join(NAMES)]
    assert runner.commands == [
        ["make", "--no-print-directory", "check-comment-hygiene"],
        ["make", "--no-print-directory", "check-doc-citations", f"CHANGE={CHANGE}"],
        # The change named, so its deltas count as the archive will leave them.
        ["make", "--no-print-directory", "check-spec-index", f"CHANGE={CHANGE}"],
        ["make", "--no-print-directory", "check-decision-destinations", f"CHANGE={CHANGE}"],
        ["make", "--no-print-directory", "check-history-wording", "CHANGE_BASE=dev"],
        ["make", "--no-print-directory", "check-version-bumps", "CHANGE_BASE=dev"],
        ["make", "--no-print-directory", "check-local-imports", "CHANGE_BASE=dev"],
        ["make", "--no-print-directory", "check-capability-index"],
    ]


def test_the_diff_checks_read_the_branch_the_clone_recorded(tmp_path: Path) -> None:
    """With no `--base`, the base is `find --json`'s, the landing branch the change's
    clone recorded."""
    runner = FakeChecks()

    run_checks(CHANGE, root=_change(tmp_path, lands_on="release"), runner=runner,
               echo=lambda _: None)

    assert [command[-1] for command in runner.commands[4:7]] == ["CHANGE_BASE=release"] * 3


def test_a_base_given_overrides_the_recorded_one(tmp_path: Path) -> None:
    runner = FakeChecks()

    run_checks(CHANGE, root=_change(tmp_path, lands_on="dev"), runner=runner,
               echo=lambda _: None, base="main")

    assert [command[-1] for command in runner.commands[4:7]] == ["CHANGE_BASE=main"] * 3


def test_a_change_with_no_base_recorded_or_given_is_refused(tmp_path: Path) -> None:
    shown: list[str] = []
    runner = FakeChecks()

    assert run_checks(CHANGE, root=_change(tmp_path, lands_on=None), runner=runner,
                      echo=shown.append) == 1

    assert runner.commands == []
    assert shown[0].startswith("ERROR: ") and "--base" in shown[0] and "CHANGE_BASE" in shown[0]


def test_the_command_takes_the_branch_the_change_lands_on(
        monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, str | None]] = []
    monkeypatch.setattr("check_change.run_checks",
                        lambda change, base: seen.append((change, base)) or 0)

    assert main([CHANGE, "--base", "release"]) == 0
    assert main([CHANGE]) == 0
    assert seen == [(CHANGE, "release"), (CHANGE, None)]


@pytest.mark.parametrize("failing", NAMES)
def test_any_one_check_failing_fails_and_shows_only_its_output(
        tmp_path: Path, failing: str) -> None:
    shown: list[str] = []
    runner = FakeChecks(failing)

    status = run_checks(CHANGE, root=_change(tmp_path), runner=runner, echo=shown.append)

    assert status == 1
    # Every check runs whatever the others report.
    assert len(runner.commands) == len(NAMES)
    assert shown[0].startswith(f"FAILED: {failing} (")
    assert shown[1] == f"{failing} said why"
    assert shown[-1] == f"FAILED: 1 of {len(NAMES)} checks of {CHANGE}: {failing}"
    assert not any("chatter" in line or line.startswith("OK:") for line in shown)


def test_exactly_the_repositorys_checks_run() -> None:
    assert [name for name, _ in checks(CHANGE, "dev")] == NAMES


def test_an_unknown_change_is_refused_before_any_check_runs(tmp_path: Path) -> None:
    shown: list[str] = []
    runner = FakeChecks()

    assert run_checks("missing", root=_checkout(tmp_path), runner=runner,
                      echo=shown.append, base="dev") == 1

    assert runner.commands == []
    assert shown[0].startswith("ERROR: no change 'missing'")


def test_a_directory_outside_any_repository_is_refused_naming_it(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    shown: list[str] = []
    runner = FakeChecks()

    assert run_checks(CHANGE, root=tmp_path, runner=runner, echo=shown.append,
                      base="dev") == 1

    assert runner.commands == []
    assert shown[0].startswith("ERROR: ") and str(tmp_path) in shown[0]


def test_the_command_needs_one_change(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([""]) == 2
    assert main([]) == 2
    assert main([CHANGE, "--base"]) == 2
    assert main([CHANGE, "--base", ""]) == 2
    assert "usage" in capsys.readouterr().err
