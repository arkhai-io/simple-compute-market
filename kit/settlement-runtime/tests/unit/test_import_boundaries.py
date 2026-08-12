from __future__ import annotations

import ast
import sys
from pathlib import Path


PACKAGE = Path(__file__).parents[2] / "src" / "market_settlement_runtime"


def test_runtime_imports_only_stdlib_pydantic_identity_and_its_own_modules() -> None:
    forbidden: list[tuple[Path, int, str]] = []
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            for name in names:
                root = name.split(".", 1)[0]
                if root not in sys.stdlib_module_names and root not in {
                    "market_identity",
                    "pydantic",
                }:
                    forbidden.append((path, node.lineno, name))
    assert forbidden == []


def test_no_upward_or_concrete_imports_are_hidden_in_source() -> None:
    forbidden_roots = (
        "core_storefront",
        "domains.",
        "eth_account",
        "fastapi",
        "hosted_settlement_client",
        "httpx",
        "market_alkahest",
        "stripe",
        "web3",
    )
    matches: list[tuple[str, str]] = []
    for path in PACKAGE.glob("*.py"):
        source = path.read_text()
        for root in forbidden_roots:
            if root in source:
                matches.append((path.name, root))
    assert matches == []
