"""The contracts package carries the wire contract and nothing that serves it.

The family kit, the service, its adapters, and its clients all depend on this
package, so it must not reach persistence, a web framework, an HTTP library, or
any other compute provisioning package, at any import depth.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "compute_provisioning_contracts"

ALLOWED = {"pydantic", "market_core", "market_identity", "compute_provisioning_contracts"}


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
