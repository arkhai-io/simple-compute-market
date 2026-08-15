from __future__ import annotations

import ast
from pathlib import Path

_ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "collections",
    "dataclasses",
    "json",
    "market_contact_exchange",
    "market_core",
    "market_identity",
    "market_settlement_runtime",
    "pydantic",
    "re",
    "sqlite3",
    "typing",
}


def test_contact_kit_imports_only_lower_level_kits() -> None:
    source_root = Path(__file__).parents[2] / "src" / "market_contact_exchange"
    imported_roots: set[str] = set()
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(
                    alias.name.partition(".")[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported_roots.add(node.module.partition(".")[0])
    assert imported_roots <= _ALLOWED_IMPORT_ROOTS
    assert not imported_roots & {
        "fastapi",
        "hosted_settlement_client",
        "httpx",
        "market_alkahest",
        "requests",
        "stripe",
    }
