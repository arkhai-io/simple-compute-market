"""The component's boundary, which `make check-architecture` does not read.

The architecture check skips `tools/`, so these hold what it would: the component
depends on the standard library alone, SQLAlchemy only through its optional extra
and only in the module that extra serves; it declares no repository package; and it
names no concept of the system that uses it, so it can be lifted into its own
repository as it stands.
"""

from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
import tomllib
from pathlib import Path

import pytest

COMPONENT_DIR = Path(__file__).resolve().parents[2]
SOURCE = COMPONENT_DIR / "src" / "request_replay"
PUBLIC_INDEX = "https://pypi.org/simple"
SQLALCHEMY_MODULE = "sqlalchemy_store.py"

# Words naming the marketplace this component serves; a generic replay guard has
# no use for any of them. "Lease" is absent: here it is the dispatch lease an
# attempt holds on its request, the guard's own concept, not a compute lease.
MARKET_WORDS = re.compile(
    r"\b(market\w*|storefront\w*|buyer\w*|seller\w*|listing\w*|deal\w*|negotiat\w*|"
    r"provision\w*|registry|registries|credits?|escrow\w*|settlement\w*|arkhai|"
    r"hosts?|sites?)\b",
    re.IGNORECASE,
)


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
    """Each module importing anything but the standard library, the component, and,
    in the SQLAlchemy store alone, SQLAlchemy."""
    allowed = set(sys.stdlib_module_names) | {"__future__", "request_replay"}
    found = {}
    for path in sorted(source.rglob("*.py")):
        permitted = allowed | ({"sqlalchemy"} if path.name == SQLALCHEMY_MODULE else set())
        found[str(path.relative_to(source))] = sorted(imported_modules(path) - permitted)
    return {path: names for path, names in found.items() if names}


def market_words(source: Path) -> dict[str, list[str]]:
    """Each module whose names, strings or comments use a marketplace word."""
    found = {}
    for path in sorted(source.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        words = {
            match.group(0).lower()
            for token in tokenize.generate_tokens(io.StringIO(text).readline)
            for match in MARKET_WORDS.finditer(token.string)
        }
        if words:
            found[str(path.relative_to(source))] = sorted(words)
    return found


def test_the_source_imports_only_the_standard_library_itself_and_sqlalchemy_where_extra() -> None:
    assert sorted(SOURCE.rglob("*.py"))
    assert outside_the_boundary(SOURCE) == {}


@pytest.mark.parametrize(("module", "planted"), [
    ("planted.py", "import httpx\n"),
    ("planted.py", "from market_identity import wire\n"),
    ("planted.py", "def later():\n    import sqlalchemy\n"),
    (SQLALCHEMY_MODULE, "import starlette\n"),
])
def test_a_planted_import_outside_the_boundary_is_found(tmp_path: Path, module: str, planted: str) -> None:
    source = tmp_path / "request_replay"
    source.mkdir()
    (source / "clean.py").write_text("import json\nfrom request_replay.policy import Policy\n")
    (source / module).write_text(planted)

    assert list(outside_the_boundary(source)) == [module]


def test_the_source_names_no_marketplace_concept() -> None:
    assert market_words(SOURCE) == {}


def test_a_planted_marketplace_word_is_found(tmp_path: Path) -> None:
    source = tmp_path / "request_replay"
    source.mkdir()
    (source / "clean.py").write_text('"""A dispatch lease on an opaque request key."""\n')
    (source / "planted.py").write_text("# Answers the storefront's retry.\n")

    assert market_words(source) == {"planted.py": ["storefront"]}


def test_the_component_declares_only_sqlalchemy_and_only_as_an_extra() -> None:
    project = tomllib.loads((COMPONENT_DIR / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["dependencies"] == []
    assert project["optional-dependencies"] == {"sqlalchemy": ["sqlalchemy>=2.0,<3"]}


def test_the_lock_resolves_nothing_from_the_wheelhouse() -> None:
    lock = tomllib.loads((COMPONENT_DIR / "uv.lock").read_text(encoding="utf-8"))

    sources = {package["name"]: package["source"] for package in lock["package"]}

    assert sources.pop("arkhai-request-replay") == {"editable": "."}
    off_index = {name: source for name, source in sources.items() if source != {"registry": PUBLIC_INDEX}}
    assert off_index == {}
