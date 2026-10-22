"""Code outside openspec/ names no change, task, or change document."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_comment_hygiene", Path(__file__).resolve().parents[1] / "check_comment_hygiene.py"
)
assert _SPEC and _SPEC.loader
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)

# The samples are joined at run time: this file is scanned like any other, and a
# sample written out would be a finding against the test of the check.
TASK_LIST = "tasks" + ".md"
DESIGN = "design" + ".md"
PROPOSAL = "proposal" + ".md"
TASK_LIST_CONSTANT = 'TASKS_FILE = "' + TASK_LIST + '"'
HISTORY_SAMPLES = [
    "# Moved here during " + "POOLS-" + "7 task 1" + ".8.",
    "# See " + "section 3" + ".2 of the plan.",
    "# " + "Section 4" + ": the rules.",
    "# " + "Task 2" + ".1 adds the field.",
    "# see " + TASK_LIST,
    "# as " + DESIGN + " records",
    "# " + PROPOSAL + " names it",
]


def _write(root: Path, path: str, text: str) -> None:
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(text, "utf-8")


def _tree(root: Path) -> Path:
    _write(root, "openspec/changes/shape-bounds/" + TASK_LIST, "- [ ] 1.1 A task.\n")
    _write(root, "openspec/changes/archive/2026-10-01-split-pools/" + TASK_LIST, "x\n")
    _write(root, "openspec/changes/archive/.gitkeep", "")
    _write(root, "scripts/change_next_step.py",
           '"""Reads a task list."""\n' + TASK_LIST_CONSTANT + "\n")
    _write(root, "kit/clean.py", "# The pool is keyed by provider.\n")
    return root


@pytest.mark.parametrize("line", HISTORY_SAMPLES)
def test_a_change_history_reference_in_python_is_caught(tmp_path: Path, line: str) -> None:
    root = _tree(tmp_path)
    _write(root, "kit/pools.py", f"x = 1\n{line}\n")

    assert checker.change_history_matches(root) == [f"./kit/pools.py:2:{line}"]


@pytest.mark.parametrize("path,caught", [
    ("domains/compose.yml", True), ("tools/ci.yaml", True), ("docs/a.yml", True),
    ("kit/config.toml", False), ("notes.txt", False), ("README.md", False),
    ("openspec/changes/x/notes.py", False), (".venv/lib/x.py", False),
    ("node_modules/x.py", False), ("build/x.py", False), (".dist/x.py", False),
    ("kit/__pycache__/x.py", False), (".git/hooks/x.py", False),
])
def test_the_history_scan_reads_python_and_yaml_outside_the_excluded_directories(
        tmp_path: Path, path: str, caught: bool) -> None:
    root = _tree(tmp_path)
    line = "# see " + TASK_LIST
    _write(root, path, line + "\n")

    assert (checker.change_history_matches(root) == [f"./{path}:1:{line}"]) is caught


def test_the_task_list_constant_is_exempt_but_no_other_mention_in_the_script(
        tmp_path: Path) -> None:
    root = _tree(tmp_path)

    assert checker.change_history_matches(root) == []

    mention = "# the sections of " + TASK_LIST
    _write(root, "scripts/change_next_step.py", TASK_LIST_CONSTANT + "\n" + mention + "\n")
    assert checker.change_history_matches(root) == [
        f"./scripts/change_next_step.py:2:{mention}"]

    _write(root, "scripts/other.py", TASK_LIST_CONSTANT + "\n")
    assert f"./scripts/other.py:1:{TASK_LIST_CONSTANT}" in checker.change_history_matches(root)


def test_change_names_are_the_active_and_archived_directories_without_dates(
        tmp_path: Path) -> None:
    root = _tree(tmp_path)
    _write(root, "openspec/changes/README.md", "index\n")
    (root / "openspec/changes/keep-archive-notes").mkdir()

    assert checker.change_names(root) == ["shape-bounds", "split-pools"]


@pytest.mark.parametrize("path,caught", [
    ("kit/pools.py", True), ("kit/config.toml", True), ("domains/compose.yml", True),
    ("tools/ci.yaml", True), ("docs/roadmap.py", False), (".claude/steps.toml", False),
    ("openspec/specs/x.py", False), ("notes.txt", False),
])
def test_a_change_name_in_code_is_caught_outside_docs_and_claude(
        tmp_path: Path, path: str, caught: bool) -> None:
    root = _tree(tmp_path)
    _write(root, path, "# until split-pools lands\n")

    assert (checker.change_name_matches(root) == [f"./{path}:1:# until split-pools lands"]) is caught


def test_no_change_directories_means_no_name_scan(tmp_path: Path) -> None:
    _write(tmp_path, "kit/pools.py", "# shape-bounds\n")

    assert checker.change_name_matches(tmp_path) == []


def test_the_command_reports_each_scan_and_fails_on_a_match(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _tree(tmp_path)

    assert checker.main(root) == 0
    clean = capsys.readouterr().out
    _write(root, "kit/pools.py", "# split-pools owns this\n")
    assert checker.main(root) == 1
    named = capsys.readouterr().out
    _write(root, "kit/pools.py", HISTORY_SAMPLES[1] + "\n")
    assert checker.main(root) == 1
    history = capsys.readouterr().out

    assert clean.splitlines() == [
        "Scanning for change-ID and task-number references outside openspec/...",
        "OK: no change-ID/task-number references found outside openspec/.",
        "Scanning for OpenSpec change directory names in code...",
        "OK: no OpenSpec change names found in code."]
    assert "./kit/pools.py:1:# split-pools owns this" in named
    assert "FAIL: code names an OpenSpec change." in named
    assert "FAIL: found change-history references outside openspec/." in history
    assert "Scanning for OpenSpec change directory names" not in history
