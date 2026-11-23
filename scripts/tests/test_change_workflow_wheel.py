"""The workflow's wheel, built from this tree and installed as a tool, carries every
document it names: the installed `change-workflow` prints its version, refuses
until `change-workflow install` has written its skills, and then, in a repository
holding no copy of the workflow, names each document by role inside the installed
distribution, and prints the installed fragment's path, which a Makefile includes.

The test builds the wheel with `uv build` and installs it with `uv tool install`
into temporary tool directories, so it needs `uv`, and is skipped, saying so, where
there is none."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from change_workflow import documents

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "scripts/change-workflow-wheel"
UV = shutil.which("uv")

pytestmark = pytest.mark.skipif(UV is None, reason="uv is not installed, so the wheel "
                                                   "cannot be built or installed")


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
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
    shipped = {
        "change_workflow/data/specification/spec.md": tree.path(documents.SPECIFICATION),
        "change_workflow/data/specification/index.md": tree.path(documents.INDEX),
        "change_workflow/data/specification/README.md": tree.path(documents.COMPANION),
        "change_workflow/data/change-workflow-handbook.md": tree.path(documents.HANDBOOK),
        "change_workflow/data/change-outcome.schema.json": tree.path(documents.SCHEMA),
    }
    for directory, source in (("data/specification/diagrams", documents.DIAGRAMS),
                              ("data/guidance", documents.GUIDANCE)):
        for path in tree.path(source).rglob("*"):
            if path.is_file():
                shipped[f"change_workflow/{directory}/"
                        f"{path.relative_to(tree.path(source)).as_posix()}"] = path
    for name, source in tree.skills().items():
        for path in source.rglob("*"):
            if path.is_file():
                shipped[f"change_workflow/data/skills/{name}/"
                        f"{path.relative_to(source).as_posix()}"] = path

    packaged = {name for name in names if name.startswith("change_workflow/")}
    assert packaged == expected | set(shipped)
    for name, source in shipped.items():
        assert zipfile.ZipFile(wheel).read(name) == source.read_bytes(), name


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
