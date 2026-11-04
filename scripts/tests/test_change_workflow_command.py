"""The engine is reached as one command, `scripts/change-workflow`: it runs as an
executable, acts on the repository containing its working directory, and is the only
way this repository's own scripts reach the engine.

The command's runs start it as a process from a working directory, since what is
proven is which repository it acts on; the import rule reads the scripts' source.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
COMMAND = SCRIPTS / "change-workflow"
PACKAGE = SCRIPTS / "change_workflow"
TESTS = SCRIPTS / "tests"
NOT_IN_REPOSITORY = "is not inside a Git repository"


def test_the_command_acts_on_its_working_directorys_repository(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    environ = {**os.environ, "GIT_CEILING_DIRECTORIES": str(tmp_path)}
    command = [sys.executable, str(COMMAND), "check", "skills"]

    inside = subprocess.run(command, cwd=SCRIPTS.parent, env=environ, capture_output=True,
                            text=True, check=False)
    assert (inside.returncode, inside.stdout) == (
        0, "OK: every agent skill is loaded from its one shared source.\n")
    refused = subprocess.run(command, cwd=outside, env=environ, capture_output=True,
                             text=True, check=False)
    assert (refused.returncode, refused.stdout) == (1, "")
    assert f"{outside} {NOT_IN_REPOSITORY}" in refused.stderr
    assert list(outside.iterdir()) == []


def test_the_command_runs_as_an_executable_from_a_subdirectory() -> None:
    # Started by its path, as the make fragment, the skills, and the hook start it.
    ran = subprocess.run([str(COMMAND), "find", "--json", "archive"], cwd=TESTS,
                         capture_output=True, text=True, check=False)
    assert (ran.returncode, ran.stdout) == (1, "")
    assert "'archive' is not a change name" in ran.stderr


def test_the_command_compares_this_checkouts_graph_diagram() -> None:
    ran = subprocess.run([str(COMMAND), "check", "graph"], cwd=SCRIPTS.parent,
                         capture_output=True, text=True, check=False)
    assert (ran.returncode, ran.stderr) == (0, "")
    assert ran.stdout.endswith("draws the table.\n")


def test_next_gives_an_unclassified_results_reason_on_standard_error() -> None:
    # The result stays on standard output, where a program reads it; exit 1 gives
    # its reason on standard error, as every subcommand's refusal does.
    command = [str(COMMAND), "next", "no-such-change"]
    ran = subprocess.run(command, cwd=SCRIPTS.parent, capture_output=True, text=True,
                         check=False)
    assert ran.returncode == 1
    result = json.loads(ran.stdout)
    assert result["step"] == "unclassified" and "no-such-change" in result["reason"]
    assert ran.stderr == f"ERROR: {result['reason']}\n"
    plain = subprocess.run([*command, "--plain"], cwd=SCRIPTS.parent, capture_output=True,
                           text=True, check=False)
    assert (plain.returncode, plain.stderr) == (1, ran.stderr)


def _post_compaction_hook() -> str:
    """The command the project's settings run for the post-compaction hook."""
    settings = json.loads((SCRIPTS.parent / ".claude/settings.json").read_text("utf-8"))
    [entry] = [entry for entry in settings["hooks"]["SessionStart"]
               if entry.get("matcher") == "compact"]
    [hook] = entry["hooks"]
    return hook["command"]


def test_the_post_compaction_hook_describes_the_project_from_any_directory(
        tmp_path: Path) -> None:
    # Claude Code runs the hook from the session's working directory, which may be
    # outside any repository or in another checkout, such as a change's clone; the
    # hook describes the project all the same.
    outside = tmp_path / "outside"
    outside.mkdir()
    other = tmp_path / "other"
    subprocess.run(["git", "init", "-q", "-b", "elsewhere", str(other)], check=True)
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=SCRIPTS.parent,
                            capture_output=True, text=True, check=True).stdout.strip()
    environ = {**os.environ, "CLAUDE_PROJECT_DIR": str(SCRIPTS.parent),
               "GIT_CEILING_DIRECTORIES": str(tmp_path)}
    for where in (outside, other):
        ran = subprocess.run(["sh", "-c", _post_compaction_hook()], cwd=where, env=environ,
                             capture_output=True, text=True, check=False)
        assert (ran.returncode, ran.stderr) == (0, "")
        assert f"Checked-out branch: {branch or '(detached HEAD)'}\n" in ran.stdout


def test_the_command_has_no_python_suffix_so_nothing_imports_it() -> None:
    assert COMMAND.is_file()
    assert not (SCRIPTS / "change-workflow.py").exists()
    mode = subprocess.run(["git", "ls-files", "-s", "change-workflow"], cwd=SCRIPTS,
                          capture_output=True, text=True, check=True).stdout.split()[0]
    assert mode == "100755"


def _imports(source: str) -> list[tuple[int, str]]:
    """Each absolute import in `source`, with its line, wherever it sits: at module
    level, in a function, under `TYPE_CHECKING`, or in a `try`."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            found.append((node.lineno, node.module or ""))
    return found


def engine_imports(source: str) -> list[int]:
    """The lines of `source` that import the engine's package."""
    return [line for line, name in _imports(source)
            if name == "change_workflow" or name.startswith("change_workflow.")]


def is_a_repository_scripts_test(source: str, scripts: set[str]) -> bool:
    """Whether a test loads one of this repository's own scripts, `scripts` naming
    their modules — by importing it, or by naming its file, as a test loading it from
    its path does: such a test is the repository's, not the engine's."""
    named = {Path(node.value).name for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Constant) and isinstance(node.value, str)
             and node.value.endswith(".py")}
    return (any(name.split(".")[0] in scripts for _, name in _imports(source))
            or any(Path(name).stem in scripts for name in named))


def test_no_script_but_the_engines_own_imports_the_engine() -> None:
    """A repository reaches the engine only as the command. The package's modules
    and the engine's tests are the engine's own; a test of one of this repository's
    scripts is the repository's, so it reaches the engine as the command too."""
    scripts = {path.stem for path in SCRIPTS.glob("*.py")}
    importing = []
    for path in sorted(SCRIPTS.rglob("*.py")):
        if path.is_relative_to(PACKAGE):
            continue
        source = path.read_text("utf-8")
        if path.is_relative_to(TESTS) and not is_a_repository_scripts_test(source, scripts):
            continue
        importing += [f"{path.relative_to(SCRIPTS)}:{line}" for line in engine_imports(source)]
    assert importing == []


def test_a_test_of_a_repository_script_is_the_repositorys() -> None:
    scripts = {"validate_parallel", "check_change"}
    assert is_a_repository_scripts_test("import validate_parallel as check\n", scripts)
    assert is_a_repository_scripts_test("from check_change import main\n", scripts)
    assert is_a_repository_scripts_test(
        'spec_from_file_location("c", ROOT / "check_change.py")\n', scripts)
    assert not is_a_repository_scripts_test("from change_workflow import cli\n", scripts)
    assert not is_a_repository_scripts_test('PATH = "scripts/change_workflow/log.py"\n',
                                            scripts)


@pytest.mark.parametrize("source,lines", [
    ("import change_workflow\n", [1]),
    ("from change_workflow.find import change_directory\n", [1]),
    ("def f():\n    from change_workflow import clone\n", [2]),
    ("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import change_workflow.log\n",
     [3]),
    ("try:\n    import change_workflow as w\nexcept ImportError:\n    w = None\n", [2]),
    ("import change_workflow_notes\nfrom . import change_workflow\n", []),
])
def test_an_import_of_the_engine_is_found_wherever_it_sits(source: str,
                                                           lines: list[int]) -> None:
    assert engine_imports(source) == lines
