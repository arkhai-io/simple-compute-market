"""The kit imports only the standard library and the shape vocabulary, so
storefronts, buyers, and pool administration can all install it."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "market_capability_admissibility"
_ALLOWED = {"market_capability_admissibility", "market_capability_shape"}


def test_imports_only_the_standard_library_and_the_shape_kit():
    # ast.walk visits every node, so an import inside a function, under
    # TYPE_CHECKING, or behind try counts as a dependency like any other.
    violations = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            elif isinstance(node, ast.Call) and getattr(node.func, "id", None) == "__import__":
                violations.append(f"{path.name}: imports dynamically")
            for name in names:
                if name not in sys.stdlib_module_names and name not in _ALLOWED:
                    violations.append(f"{path.name}: imports {name}")
    assert not violations, violations
