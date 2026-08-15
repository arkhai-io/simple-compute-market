from __future__ import annotations

import ast
from pathlib import Path

_ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "asyncio",
    "collections",
    "contextlib",
    "dataclasses",
    "datetime",
    "decimal",
    "enum",
    "fcntl",
    "hashlib",
    "hosted_settlement_client",
    "inspect",
    "json",
    "market_hosted_settlement",
    "market_identity",
    "market_settlement_runtime",
    "os",
    "pathlib",
    "pydantic",
    "re",
    "sqlite3",
    "stat",
    "tempfile",
    "typer",
    "typing",
    "urllib",
    "uuid",
}


def test_hosted_kit_imports_only_released_client_and_lower_level_kits() -> None:
    source_root = Path(__file__).parents[2] / "src" / "market_hosted_settlement"
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
        "core_buyer",
        "domains",
        "hosted_settlement_service",
        "httpx",
        "requests",
        "stripe",
    }


def test_core_and_domains_consume_hosted_contracts_through_the_kit() -> None:
    repository = Path(__file__).parents[4]
    violations: list[str] = []
    for package_root in (repository / "core", repository / "domains"):
        for path in package_root.rglob("*.py"):
            if any(part in {".venv", "__pycache__"} for part in path.parts):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = {alias.name.partition(".")[0] for alias in node.names}
                elif (
                    isinstance(node, ast.ImportFrom) and node.module and node.level == 0
                ):
                    roots = {node.module.partition(".")[0]}
                else:
                    continue
                if "hosted_settlement_client" in roots:
                    violations.append(str(path.relative_to(repository)))
    assert sorted(set(violations)) == []
