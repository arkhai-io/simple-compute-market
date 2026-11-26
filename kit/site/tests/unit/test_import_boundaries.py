"""``market_site`` imports nothing from the pool capability.

The site authority and the pool authority are kits of empty scope side by side,
so `make check-architecture` permits an edge between them in either direction
and sees a cycle only once both exist. The site reads every pool fact through
the port its composition fills (``market_site.pool_facts``), so no module of
the package may import the pool authority or its contracts, by any import form:
at module level, inside a function, under ``TYPE_CHECKING``, or behind
``try``. See openspec/specs/site-capacity/architecture.md, "Declared capacity
and connection identity".
"""

import ast
from pathlib import Path

FORBIDDEN = {"market_resource_pools", "market_resource_pools_contracts"}


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


def test_no_module_imports_the_pool_authority_or_its_contracts():
    package_root = Path(__file__).parents[2] / "src" / "market_site"
    sources = sorted(package_root.rglob("*.py"))
    assert sources
    violations = [
        f"{source_path.relative_to(package_root)}:{line}: imports {module_name!r}"
        for source_path in sources
        for line, module_name in _imported_module_names(source_path)
        if module_name.split(".")[0] in FORBIDDEN
    ]

    assert violations == []
