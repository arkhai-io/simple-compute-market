"""The component's boundary, which `make check-architecture` does not read.

The architecture check skips `tools/`, so these hold what it would: the component
depends on the standard library, SQLAlchemy, pydantic and sqlglot alone — no
repository package — and names no concept of the marketplace it serves, so it can be
lifted into its own repository as it stands.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

import pytest

COMPONENT_DIR = Path(__file__).resolve().parents[2]
SOURCE = COMPONENT_DIR / "src" / "eventing"
PUBLIC_INDEX = "https://pypi.org/simple"

THIRD_PARTY = {"pydantic", "sqlalchemy", "sqlglot"}
ALLOWED_IMPORTS = set(sys.stdlib_module_names) | {"__future__", "eventing"} | THIRD_PARTY

MARKET_TERMS = (
    "arkhai", "market", "marketplace", "lease", "leases", "site", "sites", "storefront",
    "provisioning", "buyer", "seller", "escrow", "deal", "deals", "reservation",
    "capacity", "host", "hosts", "listing", "settlement", "teardown", "reclaim",
    "bare_metal", "bare-metal", "vm", "vms",
)
"""Words naming the marketplace's concepts, none of which a generic component uses."""

_TERM = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(map(re.escape, MARKET_TERMS)) + r")(?![A-Za-z0-9])",
                   re.IGNORECASE)


def imported_modules(path: Path) -> set[str]:
    """The top-level names a module imports absolutely, wherever the import is."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def outside_the_boundary(source: Path) -> dict[str, list[str]]:
    """Each module under `source` importing anything but the standard library, the
    three declared distributions, or the component itself, with what it imports."""
    found = {
        str(path.relative_to(source)): sorted(imported_modules(path) - ALLOWED_IMPORTS)
        for path in sorted(source.rglob("*.py"))
    }
    return {path: names for path, names in found.items() if names}


def market_terms(source: Path) -> dict[str, list[str]]:
    """Each module under `source` naming a market term, with the terms it names."""
    found = {
        str(path.relative_to(source)): sorted({m.lower() for m in _TERM.findall(path.read_text())})
        for path in sorted(source.rglob("*.py"))
    }
    return {path: terms for path, terms in found.items() if terms}


def test_the_source_imports_only_its_declared_distributions_and_itself() -> None:
    assert sorted(SOURCE.rglob("*.py"))
    assert outside_the_boundary(SOURCE) == {}


@pytest.mark.parametrize("planted", [
    "from market_site import ledger\n",
    "import injected_time\n",
    "def later():\n    from market_delivery import sinks\n",
    "import httpx\n",
])
def test_a_planted_import_of_a_repository_package_or_another_distribution_is_found(
        tmp_path: Path, planted: str) -> None:
    source = tmp_path / "eventing"
    source.mkdir()
    (source / "clean.py").write_text("import json\nimport sqlglot\nfrom eventing.envelope import Envelope\n")
    (source / "planted.py").write_text(planted)

    assert list(outside_the_boundary(source)) == ["planted.py"]


def test_the_source_names_no_market_concept() -> None:
    assert market_terms(SOURCE) == {}


@pytest.mark.parametrize("planted", [
    "# A lease ends here.\n",
    'KIND = "site.capacity_released"\n',
    "def record_storefront_event(): ...\n",
])
def test_a_planted_market_term_is_found(tmp_path: Path, planted: str) -> None:
    source = tmp_path / "eventing"
    source.mkdir()
    (source / "clean.py").write_text("# Events are delivered to each destination; a website is not a term.\n")
    (source / "planted.py").write_text(planted)

    assert list(market_terms(source)) == ["planted.py"]


def test_the_runtime_dependencies_are_the_three_distributions_each_with_a_floor() -> None:
    project = tomllib.loads((COMPONENT_DIR / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    requirements = {
        re.split(r"[<>=!~;\[ ]", requirement, maxsplit=1)[0].lower(): requirement
        for requirement in project["dependencies"]
    }

    assert set(requirements) == THIRD_PARTY
    assert all(re.fullmatch(r"[A-Za-z0-9_.-]+>=[0-9.]+", r) for r in requirements.values())
    assert "optional-dependencies" not in project


def test_the_lock_resolves_nothing_from_the_wheelhouse() -> None:
    lock = tomllib.loads((COMPONENT_DIR / "uv.lock").read_text(encoding="utf-8"))

    sources = {package["name"]: package["source"] for package in lock["package"]}

    assert sources.pop("arkhai-eventing") == {"editable": "."}
    off_index = {name: source for name, source in sources.items()
                 if source != {"registry": PUBLIC_INDEX}}
    assert off_index == {}
