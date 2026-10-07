"""The client carries the typed calls and nothing that serves them.

It depends only on the contracts it signs from, the identity kit it signs
with, and its HTTP library: never on the family kit, the deployed service, a
persistence or web framework, or a domain's package, at any import depth.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "compute_provisioning_client"

ALLOWED = {
    "httpx",
    "market_core",
    "market_identity",
    "compute_provisioning_contracts",
    "compute_provisioning_client",
}


def _imports(path: Path) -> set[str]:
    """Top-level names of every absolute import, at any depth; a relative
    import stays inside this package."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_imports_only_its_contracts_identity_and_http():
    violations = [
        f"{path.name}: {name}"
        for path in sorted(SRC.rglob("*.py"))
        for name in sorted(_imports(path))
        if name not in ALLOWED and name not in sys.stdlib_module_names
    ]
    assert violations == []
