"""This repository's scripts reach the engine by running its command and reading its
structured output, with its reason when it refuses.

The command is a process, so each case runs a real one: a stand-in executable
answering as the installed command's structured output is documented to, since
this repository's suites run without the workflow installed. The default command
is found on the path, where a case puts its stand-in.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from workflow_command import (WorkflowRefused, clone_where, created_specifications, found_change,
                              installed_guidance)


def _stand_in(directory: Path, script: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    command = directory / "change-workflow"
    command.write_text(f"#!/bin/sh\n{script}\n", "utf-8")
    command.chmod(command.stat().st_mode | stat.S_IXUSR)
    return command


@pytest.fixture
def on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Puts a stand-in answering with `script` first on the path, where the default
    command is looked for."""
    def put(script: str) -> None:
        directory = tmp_path / "bin"
        _stand_in(directory, script)
        monkeypatch.setenv("PATH", f"{directory}{os.pathsep}{os.environ['PATH']}")
    return put


def test_the_default_command_is_the_one_on_the_path(tmp_path: Path, on_path) -> None:
    on_path("""[ "$*" = "find --json shape-bounds" ] || exit 9
echo '{"name": "shape-bounds", "directory": "openspec/changes/shape-bounds",'\\
' "archived": false, "records": null}'""")

    assert found_change(tmp_path, "shape-bounds") == {
        "name": "shape-bounds", "directory": "openspec/changes/shape-bounds",
        "archived": False, "records": None}


def test_a_refusal_carries_the_commands_reason(tmp_path: Path) -> None:
    command = _stand_in(tmp_path, "echo \"ERROR: no change 'other' under x\" >&2; exit 1")
    with pytest.raises(WorkflowRefused, match=r"^no change 'other' under x$"):
        found_change(tmp_path, "other", command)
    with pytest.raises(WorkflowRefused, match=r"^no change 'other' under x$"):
        clone_where(tmp_path, "other", command)
    with pytest.raises(WorkflowRefused, match=r"^no change 'other' under x$"):
        created_specifications(tmp_path, "other", command)


def test_the_specifications_a_change_creates_are_read_whatever_the_index_check_found(
        tmp_path: Path) -> None:
    """`check spec-index --json` exits 1 when the index check fails, and still names
    what the deltas create; the caller reads only that."""
    command = _stand_in(tmp_path, """echo '{"result": "failed",'\\
' "created": ["openspec/specs/new-flow/spec.md"]}'; exit 1""")

    assert created_specifications(tmp_path, "shape-bounds", command) == {
        "openspec/specs/new-flow/spec.md"}


def test_a_report_with_no_created_list_is_refused(tmp_path: Path) -> None:
    command = _stand_in(tmp_path, """echo '{"result": "passed"}'""")
    with pytest.raises(WorkflowRefused, match="printed no `created` list"):
        created_specifications(tmp_path, "x", command)


def test_no_clone_directory_is_a_change_worked_in_place(tmp_path: Path) -> None:
    command = _stand_in(tmp_path, "exit 0")
    assert clone_where(tmp_path, "shape-bounds", command) is None


def test_a_clone_is_the_path_printed(tmp_path: Path) -> None:
    command = _stand_in(tmp_path, f"echo '{tmp_path}/work.changes/shape-bounds'")
    assert clone_where(tmp_path, "shape-bounds", command) == (
        tmp_path / "work.changes/shape-bounds")


def test_the_installed_guidance_is_the_directory_config_names(tmp_path: Path) -> None:
    command = _stand_in(tmp_path, """[ "$*" = "config --json" ] || exit 9
echo '{"version": 1, "workflow": {"version": "0.1.0", "guidance": "/opt/w/guidance/"}}'""")

    assert installed_guidance(tmp_path, command) == Path("/opt/w/guidance")


@pytest.mark.parametrize("printed", ['{"workflow": {}}', '{"workflow": "x"}', "[]"])
def test_a_configuration_naming_no_guidance_is_refused(tmp_path: Path, printed: str) -> None:
    command = _stand_in(tmp_path, f"echo '{printed}'")
    with pytest.raises(WorkflowRefused, match="printed no `workflow.guidance` path"):
        installed_guidance(tmp_path, command)


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


def test_without_the_command_on_the_path_it_cannot_run(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(WorkflowRefused, match="^cannot run change-workflow"):
        found_change(tmp_path, "x")
