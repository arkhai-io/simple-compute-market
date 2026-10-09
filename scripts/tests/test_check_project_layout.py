"""Every distribution is one import package under src/ and installs editable."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_project_layout", Path(__file__).resolve().parents[1] / "check_project_layout.py"
)
assert _SPEC and _SPEC.loader
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)

HATCH = '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'


def _project(root: Path, path: str, body: str, package: str | None = "pkg") -> Path:
    project = root / path
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        f'[project]\nname = "{path.replace("/", "-")}"\nversion = "0.1.0"\n\n' + body, "utf-8"
    )
    if package:
        (project / "src" / package).mkdir(parents=True)
        (project / "src" / package / "__init__.py").write_text("", "utf-8")
    return project


CONFORMING = HATCH + '\n[tool.hatch.build.targets.wheel]\npackages = ["src/pkg"]\n'


def test_a_conforming_project_passes(tmp_path):
    _project(tmp_path, "kit/a", CONFORMING)

    assert checker.problems(tmp_path) == []


def test_a_directory_mapped_package_is_refused(tmp_path):
    _project(tmp_path, "domains/buyer", HATCH + '\n[tool.hatch.build.targets.wheel]\ninclude = ["/*.py"]\n\n'
             '[tool.hatch.build.targets.wheel.sources]\n"" = "domains/buyer/"\n', package=None)

    assert checker.problems(tmp_path) == [
        'domains/buyer: the wheel target must be exactly packages = ["src/<package>"] (also sets include, sources)'
    ]


def test_several_packages_or_another_backend_are_refused(tmp_path):
    _project(tmp_path, "a", HATCH + '\n[tool.hatch.build.targets.wheel]\npackages = ["src/pkg", "src/other"]\n')
    _project(tmp_path, "b", '[build-system]\nrequires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n')

    assert checker.problems(tmp_path) == [
        'a: the wheel target must be exactly packages = ["src/<package>"]',
        "b: builds with setuptools.build_meta; use hatchling",
    ]


def test_a_named_package_must_exist(tmp_path):
    _project(tmp_path, "a", CONFORMING, package="elsewhere")

    assert checker.problems(tmp_path) == ["a: src/pkg is not a package"]


def test_force_include_is_refused(tmp_path):
    _project(tmp_path, "a", CONFORMING + 'force-include = { "src/pkg/py.typed" = "pkg/py.typed" }\n')

    assert checker.problems(tmp_path) == [
        'a: the wheel target must be exactly packages = ["src/<package>"] (also sets force-include)'
    ]


def test_uv_settings_that_restate_the_layout_are_refused(tmp_path):
    _project(tmp_path, "a", CONFORMING + '\n[tool.uv]\nfind-links = ["../.dist"]\ncache-keys = [{ file = "*.py" }]\n'
             '\n[tool.uv.sources]\nsibling = { path = "../sibling", editable = true }\ntorch = { index = "cpu" }\n')

    assert checker.problems(tmp_path) == [
        "a: declares [tool.uv] find-links",
        "a: declares [tool.uv] cache-keys",
        "a: resolves sibling from the path ../sibling; use the wheelhouse",
    ]


def test_a_virtual_project_is_outside_the_wheel_rule(tmp_path):
    _project(tmp_path, "iac", "[tool.uv]\npackage = false\n", package=None)

    assert checker.problems(tmp_path) == []


def test_disabling_editable_installs_is_refused(tmp_path):
    _project(tmp_path, "kit/a", CONFORMING)
    (tmp_path / "kit/a/Makefile").write_text("export UV_NO_EDITABLE := 1\n# UV_NO_EDITABLE in a comment\n", "utf-8")
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / ".github/workflows/tests.yml").write_text("matrix: { no_editable: true }\n", "utf-8")

    assert checker.problems(tmp_path) == [
        "kit/a/Makefile:1: disables editable installs",
        ".github/workflows/tests.yml:1: disables editable installs",
    ]


def test_the_current_tree_passes():
    assert checker.problems() == []
