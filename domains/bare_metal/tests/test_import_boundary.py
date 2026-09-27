"""The bare-metal domain binds the compute family's vocabulary, never VM's.

The compute-family capability schema is owned by ``arkhai_compute`` so both
compute domains bind one schema without importing each other. A VM import here
would make bare metal's vocabulary depend on VM's implementation instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "arkhai_bare_metal"
FORBIDDEN = ("arkhai_vms", "domains.vms", "market_storefront", "vm_provisioning_adapter")


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module


def test_the_domain_imports_no_vm_package():
    violations = [
        f"{path.relative_to(SRC)}: imports {module}"
        for path in sorted(SRC.rglob("*.py"))
        for module in _imports(path)
        if any(module == prefix or module.startswith(prefix + ".") for prefix in FORBIDDEN)
    ]

    assert not violations, violations

