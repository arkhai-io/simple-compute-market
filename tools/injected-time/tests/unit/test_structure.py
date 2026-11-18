"""The component's dependency boundary, which `make check-architecture` does not read.

The architecture check skips `tools/`, so these hold what it would: the component
depends on the standard library alone — no repository package and no third-party
distribution — so it can be lifted into its own repository as it stands, and
every package can depend on it without depending on anything else.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

import pytest

COMPONENT_DIR = Path(__file__).resolve().parents[2]
SOURCE = COMPONENT_DIR / "src" / "injected_time"
PUBLIC_INDEX = "https://pypi.org/simple"


def imported_modules(path: Path) -> set[str]:
    """The top-level names a module imports absolutely, wherever the import is."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def outside_the_standard_library(source: Path) -> dict[str, list[str]]:
    """Each module under `source` importing anything but the standard library or
    the component itself, with what it imports."""
    allowed = set(sys.stdlib_module_names) | {"__future__", "injected_time"}
    found = {
        str(path.relative_to(source)): sorted(imported_modules(path) - allowed)
        for path in sorted(source.rglob("*.py"))
    }
    return {path: names for path, names in found.items() if names}


def test_the_source_imports_only_the_standard_library_and_itself() -> None:
    assert sorted(SOURCE.rglob("*.py"))
    assert outside_the_standard_library(SOURCE) == {}


@pytest.mark.parametrize("planted", [
    "import httpx\n",
    "from market_identity import verification\n",
    "def later():\n    import httpx\n",
])
def test_a_planted_import_of_a_package_or_a_distribution_is_found(
        tmp_path: Path, planted: str) -> None:
    source = tmp_path / "injected_time"
    source.mkdir()
    (source / "clean.py").write_text("import json\nfrom injected_time.value import parse_time\n")
    (source / "planted.py").write_text(planted)

    assert list(outside_the_standard_library(source)) == ["planted.py"]


def test_the_component_declares_no_runtime_dependency() -> None:
    project = tomllib.loads((COMPONENT_DIR / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["dependencies"] == []
    assert "optional-dependencies" not in project


def test_the_lock_resolves_nothing_from_the_wheelhouse() -> None:
    lock = tomllib.loads((COMPONENT_DIR / "uv.lock").read_text(encoding="utf-8"))

    sources = {package["name"]: package["source"] for package in lock["package"]}

    assert sources.pop("arkhai-injected-time") == {"editable": "."}
    off_index = {name: source for name, source in sources.items()
                 if source != {"registry": PUBLIC_INDEX}}
    assert off_index == {}
