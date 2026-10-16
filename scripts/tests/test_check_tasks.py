"""Every numbered task of a change's task list sits under its own section's heading."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


check = _load("check_tasks")
nxt = sys.modules["change_next_step"]

CHANGE = "shape-bounds"
# Joined at run time: this file is scanned for task-number references like any
# other, and a problem written out whole would be a finding against the test.
STRAYED = "task " + "2.1 sits under `## 1. First`"
MISPLACED = "task " + "1.3 sits under `## 2A. Second again`"
WELL_FORMED = """## 1. First

- [x] 1.1 Done.
- [ ] 1.2 Open.

## 2. Second

- [ ] 2.1 Open.

## 2A. Second again

- [ ] 2A.1 Open.
  - [ ] 2A.2 Nested.
"""


def test_a_well_formed_list_has_no_problem() -> None:
    assert nxt.task_problems(WELL_FORMED) == []


def test_a_task_under_another_sections_heading_is_named_with_the_heading() -> None:
    problems = nxt.task_problems(WELL_FORMED.replace("## 2. Second\n\n", ""))

    assert problems == [f"line 6: {STRAYED}"]


def test_a_misplaced_task_is_named_wherever_it_sits() -> None:
    text = WELL_FORMED.replace("- [ ] 2A.1 Open.", "- [ ] 2A.1 Open.\n- [ ] 1.3 Strayed.")

    assert nxt.task_problems(text) == [f"line 13: {MISPLACED}"]


def test_unnumbered_tasks_and_tasks_before_any_heading_are_not_checked() -> None:
    text = "- [ ] 9.1 Before any heading.\n\n## 1. First\n\n- [ ] Do it.\n- [x] Done it.\n"

    assert nxt.task_problems(text) == []


def test_a_list_without_numbered_headings_is_not_checked() -> None:
    assert nxt.task_problems("## Tasks\n\n- [ ] 1.1 One.\n- [ ] 2.1 Two.\n") == []


def test_tasks_under_an_unnumbered_heading_after_a_section_are_not_checked() -> None:
    text = WELL_FORMED + "\n## Deferred, carried out of this change\n\n- [ ] 7.1 Later.\n"

    assert nxt.task_problems(text) == []


def test_a_section_id_is_matched_whatever_its_case() -> None:
    assert nxt.task_problems("## 5A. Fifth\n\n- [ ] 5a.1 Lower.\n- [ ] 5A.2 Upper.\n") == []


def _repository(tmp_path: Path, text: str | None) -> Path:
    directory = tmp_path / "openspec/changes" / CHANGE
    directory.mkdir(parents=True)
    if text is not None:
        (directory / nxt.TASKS_FILE).write_text(text, "utf-8")
    return tmp_path


def test_the_command_names_each_problem_and_fails(tmp_path: Path,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path, WELL_FORMED.replace("## 2. Second\n\n", ""))

    assert check.main([CHANGE], root=root) == 1

    out = capsys.readouterr().out
    assert out.startswith(f"openspec/changes/{CHANGE}/{nxt.TASKS_FILE}:line 6: {STRAYED}")
    assert "FAIL:" in out


def test_the_command_passes_a_well_formed_list(tmp_path: Path,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    assert check.main([CHANGE], root=_repository(tmp_path, WELL_FORMED)) == 0
    assert capsys.readouterr().out.startswith("OK:")


def test_the_command_passes_a_change_with_no_task_list_yet(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert check.main([CHANGE], root=_repository(tmp_path, None)) == 0
    assert "no task list yet" in capsys.readouterr().out


def test_the_command_refuses_an_unknown_change_and_a_missing_argument(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repository(tmp_path, WELL_FORMED)

    assert check.main(["missing"], root=root) == 2
    assert "missing" in capsys.readouterr().err
    assert check.main([], root=root) == 2
    assert "usage" in capsys.readouterr().err
