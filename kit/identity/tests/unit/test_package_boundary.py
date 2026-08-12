from __future__ import annotations

import ast
from pathlib import Path

_ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "base64",
    "binascii",
    "collections",
    "cryptography",
    "enum",
    "eth_account",
    "hashlib",
    "hmac",
    "market_identity",
    "pydantic",
    "re",
    "rfc8785",
    "typing",
}


def test_identity_kit_imports_only_foundation_and_crypto_dependencies() -> None:
    source_root = Path(__file__).parents[2] / "src" / "market_identity"
    imported_roots: set[str] = set()
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.partition(".")[0])
    assert imported_roots <= _ALLOWED_IMPORT_ROOTS
    assert not imported_roots & {
        "core_buyer",
        "core_storefront",
        "fastapi",
        "hosted_settlement_client",
        "httpx",
        "market_hosted_settlement",
        "market_settlement",
        "requests",
        "stripe",
        "web3",
    }
