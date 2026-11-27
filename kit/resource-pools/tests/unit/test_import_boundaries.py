"""``market_resource_pools`` imports nothing from the site authority.

The pool authority answers the site authority's pool-facts port structurally,
the values it returns included, so it needs nothing of the site's to do so; the
composition root that wires the two imports both. The two are kits of empty
scope side by side, so `make check-architecture` permits an edge between them
in either direction and sees a cycle only once both exist: this test is what
keeps an edge from the pool authority into the site from appearing, by any
import form — at module level, inside a function, under ``TYPE_CHECKING``, or
behind ``try``.
"""

import ast
from pathlib import Path

FORBIDDEN = {"market_site"}


def _imported_module_names(source_path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(source_path.read_text(), filename=str(source_path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            found.append((node.lineno, node.module or ""))
    return found


def test_no_module_imports_the_site_authority():
    package_root = Path(__file__).parents[2] / "src" / "market_resource_pools"
    sources = sorted(package_root.rglob("*.py"))
    assert sources
    violations = [
        f"{source_path.relative_to(package_root)}:{line}: imports {module_name!r}"
        for source_path in sources
        for line, module_name in _imported_module_names(source_path)
        if module_name.split(".")[0] in FORBIDDEN
    ]

    assert violations == []
