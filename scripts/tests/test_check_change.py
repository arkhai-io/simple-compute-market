"""A change's closing checks run as one command that fails when any one fails and
says so in one line when all pass."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest

from check_change import OPENSPEC, checks, main, openspec_command, run_checks

CHANGE = "shape-bounds"
NAMES = ["comment hygiene", "agent skills", "documentation citations", "task list",
         "change index", "openspec validate"]


def _change(tmp_path: Path, archived: bool = False) -> Path:
    directory = (tmp_path / "openspec/changes/archive" / f"2026-10-20-{CHANGE}" if archived
                 else tmp_path / "openspec/changes" / CHANGE)
    directory.mkdir(parents=True)
    return tmp_path


class FakeChecks:
    """Stands in for the checks: records each command, and fails the one named."""

    def __init__(self, failing: str | None = None) -> None:
        self.failing = failing
        self.commands: list[list[str]] = []

    def __call__(self, command: Sequence[str], cwd: Path) -> tuple[int, str]:
        self.commands.append(list(command))
        name = NAMES[len(self.commands) - 1]
        return (1, f"{name} said why\n") if name == self.failing else (0, f"{name} chatter\n")


def _bunx(name: str) -> str | None:
    return "/usr/bin/bunx" if name == "bunx" else None


def test_every_check_passing_prints_one_line(tmp_path: Path) -> None:
    shown: list[str] = []
    runner = FakeChecks()

    status = run_checks(CHANGE, root=_change(tmp_path), runner=runner, which=_bunx,
                        echo=shown.append)

    assert status == 0
    assert shown == [f"OK: every check of {CHANGE} passed: " + ", ".join(NAMES)]
    assert runner.commands == [
        ["make", "--no-print-directory", "check-comment-hygiene"],
        ["make", "--no-print-directory", "check-agent-skills"],
        ["make", "--no-print-directory", "check-doc-citations", f"CHANGE={CHANGE}"],
        ["make", "--no-print-directory", "check-tasks", f"CHANGE={CHANGE}"],
        ["make", "--no-print-directory", "check-change-index"],
        ["bunx", OPENSPEC, "validate", CHANGE, "--strict"],
    ]


@pytest.mark.parametrize("failing", NAMES)
def test_any_one_check_failing_fails_and_shows_only_its_output(
        tmp_path: Path, failing: str) -> None:
    shown: list[str] = []
    runner = FakeChecks(failing)

    status = run_checks(CHANGE, root=_change(tmp_path), runner=runner, which=_bunx,
                        echo=shown.append)

    assert status == 1
    # Every check runs whatever the others report.
    assert len(runner.commands) == len(NAMES)
    assert shown[0].startswith(f"FAILED: {failing} (")
    assert shown[1] == f"{failing} said why"
    assert shown[-1] == f"FAILED: 1 of {len(NAMES)} checks of {CHANGE}: {failing}"
    assert not any("chatter" in line or line.startswith("OK:") for line in shown)


def test_the_validator_runs_through_npx_without_bunx() -> None:
    assert openspec_command(lambda _: None) == ["npx", "--yes", OPENSPEC]
    assert openspec_command(_bunx) == ["bunx", OPENSPEC]


def test_an_archived_change_validates_the_permanent_specifications(tmp_path: Path) -> None:
    runner = FakeChecks()

    assert run_checks(CHANGE, root=_change(tmp_path, archived=True), runner=runner,
                      which=_bunx, echo=lambda _: None) == 0

    assert runner.commands[-1] == ["bunx", OPENSPEC, "validate", "--specs", "--strict"]
    assert checks(CHANGE, archived=False, which=_bunx)[-1][1][-2:] == [CHANGE, "--strict"]


def test_an_unknown_change_is_refused_before_any_check_runs(tmp_path: Path) -> None:
    shown: list[str] = []
    runner = FakeChecks()

    assert run_checks("missing", root=tmp_path, runner=runner, echo=shown.append) == 1

    assert runner.commands == []
    assert "no change 'missing'" in shown[0]


def test_the_command_needs_one_change(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([""]) == 2
    assert main([]) == 2
    assert "usage" in capsys.readouterr().err
