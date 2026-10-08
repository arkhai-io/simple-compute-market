"""The contracts package carries models and declarations, never an authority.

A pool client and a projection reader depend on this package alone, so it must
not reach the pool authority's persistence, the compute family, or a web
framework, at any import depth.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "market_resource_pools_contracts"

ALLOWED = {"pydantic", "market_capability_shape", "market_resource_pools_contracts"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_imports_only_its_declared_dependencies():
    violations = [
        f"{path.name}: {name}"
        for path in sorted(SRC.rglob("*.py"))
        for name in sorted(_imports(path))
        if name not in ALLOWED and name not in sys.stdlib_module_names
    ]
    assert violations == []
