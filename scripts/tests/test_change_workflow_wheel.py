"""The workflow's wheel, built from this tree and installed as a tool, carries every
document it names: the installed `change-workflow` prints its version, refuses
until `change-workflow install` has written its skills, and then, in a repository
holding no copy of the workflow, names each document by role inside the installed
distribution, and prints the installed fragment's path, which a Makefile includes.
The paths the handbook's procedure for the move lifts are what the wheel packages,
its project, the command that runs the engine from the tree, and the workflow's own
tests and fixtures.

The tests of the wheel build it with `uv build` and install it with `uv tool
install` into temporary tool directories, so they need `uv`, and are skipped, saying
so, where there is none."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

from change_workflow import documents
from test_change_workflow_citations import document_set, links_leaving

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "scripts/change-workflow-wheel"
UV = shutil.which("uv")

TESTS = ROOT / "scripts/tests"
# The command that runs the engine from the tree, which no wheel packages.
LAUNCHER = "scripts/change-workflow"
MOVE_HEADING = "## Moving the workflow to its own repository"


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if UV is None:
        pytest.skip("uv is not installed, so the wheel cannot be built or installed")
    out = tmp_path_factory.mktemp("wheel")
    subprocess.run([UV, "build", "--wheel", "--out-dir", str(out), str(PROJECT)], check=True,
                   capture_output=True)
    (built,) = out.glob("arkhai_change_workflow-*.whl")
    return built


@pytest.fixture(scope="module")
def installed(wheel: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The installed command, in a tool directory of its own."""
    tools = tmp_path_factory.mktemp("tools")
    environment = {**os.environ, "UV_TOOL_DIR": str(tools / "tools"),
                   "UV_TOOL_BIN_DIR": str(tools / "bin")}
    subprocess.run([UV, "tool", "install", str(wheel)], check=True, capture_output=True,
                   env=environment)
    return tools / "bin" / "change-workflow"


def test_the_wheel_ships_the_engine_and_every_document_of_the_tree(wheel: Path) -> None:
    names = set(zipfile.ZipFile(wheel).namelist())
    tree = documents.RUNNING
    expected = {f"change_workflow/{path.relative_to(tree.package).as_posix()}"
                for path in tree.package.glob("*") if path.suffix in (".py", ".mk")}
    # The handbook, guidance, and specification at their tree paths under `data/`,
    # so their relative links resolve installed; the schema at its top.
    shipped = {"change_workflow/data/change-outcome.schema.json": tree.path(documents.SCHEMA)}
    for role in (documents.SPECIFICATION, documents.INDEX, documents.COMPANION,
                 documents.DIAGRAMS, documents.GUIDANCE, documents.HANDBOOK):
        source = tree.path(role)
        for path in [source] if source.is_file() else source.rglob("*"):
            if path.is_file():
                shipped[f"change_workflow/data/{path.relative_to(tree.tree).as_posix()}"] = path
    for name, source in tree.skills().items():
        for path in source.rglob("*"):
            if path.is_file():
                shipped[f"change_workflow/data/skills/{name}/"
                        f"{path.relative_to(source).as_posix()}"] = path

    packaged = {name for name in names if name.startswith("change_workflow/")}
    assert packaged == expected | set(shipped)
    for name, source in shipped.items():
        assert zipfile.ZipFile(wheel).read(name) == source.read_bytes(), name


def test_every_relative_link_of_the_wheels_documents_resolves_installed(
        wheel: Path, tmp_path: Path) -> None:
    """The distribution's documents, unpacked from the wheel as an installation lays
    them out, link only within their set: each relative link the tree's test proves
    resolves the same way in the installed copy."""
    zipfile.ZipFile(wheel).extractall(tmp_path)
    unpacked = documents.Distribution(tmp_path / "change_workflow")

    assert unpacked.installed
    assert document_set(unpacked), "the wheel ships no document"
    assert links_leaving(unpacked) == []


def test_the_installed_command_prints_its_version(installed: Path, tmp_path: Path) -> None:
    # Under a home directory holding no installed skill, which every other
    # subcommand refuses.
    (tmp_path / "home").mkdir()
    printed = subprocess.run([str(installed), "--version"], cwd=tmp_path, capture_output=True,
                             text=True, env={**os.environ, "HOME": str(tmp_path / "home")})

    assert (printed.returncode, printed.stdout) == (0, f"{documents.version()}\n")


def test_the_installed_command_names_each_document_inside_the_distribution(
        installed: Path, tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    environment = {**os.environ, "HOME": str(tmp_path / "home")}
    (tmp_path / "home").mkdir()

    def run(*arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(installed), *arguments], cwd=repository,
                              capture_output=True, text=True, env=environment)

    before = run("config", "--json")
    installing = run("install")
    printed = run("config", "--json")
    fragment = run("fragment")

    assert before.returncode == 1
    assert "run `change-workflow install`" in before.stderr
    assert installing.returncode == 0, installing.stderr
    skills = sorted(path.name for path in (tmp_path / "home/.claude/skills").iterdir()
                    if path.is_dir())
    assert skills == sorted(documents.RUNNING.skills())
    assert printed.returncode == 0, printed.stderr
    workflow = json.loads(printed.stdout)["workflow"]
    assert workflow["version"] == documents.version()
    assert list(workflow) == ["version", *documents.ROLES]
    tools = installed.parent.parent
    for role in documents.ROLES:
        path = Path(workflow[role])
        assert path.exists(), role
        assert path.is_relative_to(tools), role
        assert not path.is_relative_to(ROOT), role
    assert (fragment.returncode, fragment.stdout) == (0, f"{workflow['fragment']}\n")
    # CW-dvz5's "A Makefile includes the fragment": make reads the installed fragment
    # at the path the command prints, and its targets call `change-workflow`.
    (repository / "Makefile").write_text(f"include $(shell {installed} fragment)\n", "utf-8")
    made = subprocess.run(["make", "-n", "--no-print-directory", "design", "CHANGE=X"],
                          cwd=repository, capture_output=True, text=True,
                          env={key: value for key, value in environment.items()
                               if key not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL",
                                              "CHANGE_WORKFLOW", "UNATTENDED")})
    assert (made.returncode, made.stdout) == (0, 'change-workflow start design "X"\n')


# The paths the move lifts.

def lifted(handbook: str) -> list[str]:
    """The paths the handbook's procedure for the move lists: the first fenced block
    under its heading, one path a line, a directory ending in `/`."""
    section = handbook.split(f"\n{MOVE_HEADING}\n", 1)[1]
    block = re.search(r"^```[a-z]*\n(.*?)^```", section, re.S | re.M)
    assert block, "the procedure for the move lists no paths"
    return [line.strip() for line in block[1].splitlines() if line.strip()]


def packaged() -> set[str]:
    """Each source the wheel's project gathers, as a path from the tree's root."""
    project = tomllib.loads((PROJECT / "pyproject.toml").read_text("utf-8"))
    sources = project["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    return {(PROJECT / source).resolve().relative_to(ROOT).as_posix() for source in sources}


def _modules(source: str) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_the_move_lifts_what_the_wheel_packages_and_the_workflows_tests() -> None:
    """The list is exactly the wheel's sources, its project, the tree's command, and
    the test files of the workflow's: each test or fixture importing the engine's
    package or the workflow's fixtures is listed, and no listed one loads a script
    of the repository's own, as only a repository's test does."""
    listed = lifted(documents.path(documents.HANDBOOK).read_text("utf-8"))
    paths = [path.rstrip("/") for path in listed]
    tests = {path for path in paths if path.startswith("scripts/tests/")}
    scripts = {path.stem for path in (ROOT / "scripts").glob("*.py")}
    engine = {"change_workflow", "change_workflow_fixtures"}
    importing = {path.relative_to(ROOT).as_posix() for path in TESTS.glob("*.py")
                 if _modules(path.read_text("utf-8")) & engine}

    assert len(paths) == len(set(paths))
    assert [path for path in paths if not (ROOT / path).exists()] == []
    assert set(paths) - tests == packaged() | {PROJECT.relative_to(ROOT).as_posix(), LAUNCHER}
    assert importing - tests == set()
    assert [test for test in sorted(tests)
            if _modules((ROOT / test).read_text("utf-8")) & scripts] == []
    assert [path for path in listed if (ROOT / path.rstrip("/")).is_dir()
            and not path.endswith("/")] == []
