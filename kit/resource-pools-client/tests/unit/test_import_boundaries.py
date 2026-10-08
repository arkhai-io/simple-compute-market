"""The client reaches its service only through the transport it is given.

It must not import the pool authority, SQLAlchemy, any compute provisioning
package, or an HTTP library, at any import depth.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "market_resource_pools_client"

ALLOWED = {"market_resource_pools_contracts", "market_resource_pools_client"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_imports_only_the_contracts():
    violations = [
        f"{path.name}: {name}"
        for path in sorted(SRC.rglob("*.py"))
        for name in sorted(_imports(path))
        if name not in ALLOWED and name not in sys.stdlib_module_names
    ]
    assert violations == []
