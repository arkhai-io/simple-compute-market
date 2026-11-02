"""The tool's dependency boundary, which `make check-architecture` does not read.

The architecture check skips `tools/`, so these hold what it would: the tool depends
on no internal package and nothing but `cryptography`, PyJWT, and the standard
library, so it can be lifted into its own repository as it stands.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

import pytest

from tests.floor import PYPROJECT, runtime_floors, same_release

TOOL_DIR = PYPROJECT.parent
SOURCE = TOOL_DIR / "src" / "frp_grant_admission"
ALLOWED_IMPORTS = set(sys.stdlib_module_names) | {"jwt", "cryptography", "frp_grant_admission"}
PUBLIC_INDEX = "https://pypi.org/simple"


def test_the_lock_resolves_nothing_from_the_wheelhouse() -> None:
    lock = tomllib.loads((TOOL_DIR / "uv.lock").read_text(encoding="utf-8"))

    sources = {package["name"]: package["source"] for package in lock["package"]}

    assert sources.pop("frp-grant-admission") == {"editable": "."}
    assert sources, "the lock resolves no third-party package"
    off_index = {name: source for name, source in sources.items()
                 if source != {"registry": PUBLIC_INDEX}}
    assert off_index == {}


def test_only_cryptography_and_pyjwt_are_runtime_dependencies_each_with_only_a_floor() -> None:
    # runtime_floors refuses any requirement but `<name>>=<release>`, so an upper
    # bound, a marker, or an exact pin fails here.
    floors = runtime_floors()
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]

    assert {name.lower() for name in floors} == {"cryptography", "pyjwt"}
    assert "optional-dependencies" not in project


@pytest.mark.parametrize(
    "requirement", ["PyJWT>=2.8.0,<3", "PyJWT==2.8.0", "PyJWT", "PyJWT>=2.8.0; python_version>'3'"]
)
def test_a_requirement_other_than_a_bare_floor_is_refused(tmp_path: Path, requirement: str) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(f'[project]\ndependencies = ["{requirement}"]\n')

    with pytest.raises(ValueError, match="is not declared as"):
        runtime_floors(pyproject)


def test_releases_compare_as_releases() -> None:
    assert same_release("42.0.0", "42")
    assert same_release("2.8.0", "2.8.0")
    assert not same_release("2.8.1", "2.8.0")
    assert not same_release("50.0.2", "42")


def imported_modules(path: Path) -> set[str]:
    """The top-level names a module imports absolutely, wherever the import is."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_the_source_imports_only_the_standard_library_jwt_cryptography_and_itself() -> None:
    modules = sorted(SOURCE.rglob("*.py"))
    assert modules

    outside = {
        str(path.relative_to(TOOL_DIR)): sorted(imported_modules(path) - ALLOWED_IMPORTS)
        for path in modules
    }

    assert {path: names for path, names in outside.items() if names} == {}
