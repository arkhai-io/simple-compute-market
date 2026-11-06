"""This repository's scripts reach the engine by running its command and reading its
structured output, with its reason when it refuses.

The command is a process, so each case runs a real one: the workflow's own command
where a real repository answers, and a stand-in executable where an answer the
command never gives — no reason, no JSON — is what is proven.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from workflow_command import WorkflowRefused, clone_where, found_change


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    root = tmp_path / "checkout"
    (root / "openspec/changes/shape-bounds").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def _stand_in(tmp_path: Path, script: str) -> Path:
    command = tmp_path / "change-workflow"
    command.write_text(f"#!/bin/sh\n{script}\n", "utf-8")
    command.chmod(command.stat().st_mode | stat.S_IXUSR)
    return command


def test_a_change_is_found_with_the_fields_a_program_reads(checkout: Path) -> None:
    assert found_change(checkout, "shape-bounds") == {
        "name": "shape-bounds", "directory": "openspec/changes/shape-bounds",
        "archived": False, "records": None, "format": 2, "base": None}


def test_a_refusal_carries_the_commands_reason(checkout: Path) -> None:
    with pytest.raises(WorkflowRefused, match=r"^no change 'other' under"):
        found_change(checkout, "other")
    with pytest.raises(WorkflowRefused, match=r"^no change 'other' under"):
        clone_where(checkout, "other")


def test_no_clone_directory_is_a_change_worked_in_place(checkout: Path) -> None:
    assert clone_where(checkout, "shape-bounds") is None


def test_outside_a_repository_the_directory_is_named(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    with pytest.raises(WorkflowRefused, match=str(tmp_path)):
        found_change(tmp_path, "shape-bounds")


def test_a_refusal_without_a_reason_names_the_command_and_its_status(tmp_path: Path) -> None:
    command = _stand_in(tmp_path, "exit 3")
    with pytest.raises(WorkflowRefused, match=r"^change-workflow find --json x exited 3$"):
        found_change(tmp_path, "x", command)


@pytest.mark.parametrize("printed", ["not json", "[1, 2]"])
def test_output_that_is_no_json_object_is_refused(tmp_path: Path, printed: str) -> None:
    command = _stand_in(tmp_path, f"echo '{printed}'")
    with pytest.raises(WorkflowRefused, match="printed no JSON object"):
        found_change(tmp_path, "x", command)


def test_a_command_that_cannot_run_is_refused(tmp_path: Path) -> None:
    missing = tmp_path / "absent"
    with pytest.raises(WorkflowRefused, match=f"cannot run {missing}"):
        found_change(tmp_path, "x", missing)
    assert not os.path.exists(missing)
