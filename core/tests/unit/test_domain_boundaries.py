"""Core must not branch on a concrete market domain's identity.

`make check-architecture` holds what core may import. This holds what it may
compare: no core module dispatches on a domain identity literal, including the
repository-wide roles, where the vocabulary rule only warns.
"""

from __future__ import annotations

import ast
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = (
    CORE / "src" / "market_core",
    CORE / "buyer" / "src" / "core_buyer",
    CORE / "storefront" / "src" / "core_storefront",
)
CONCRETE_IDENTITIES = {"compute.v1", "api_credits.v1", "bare_metal.v1"}


def _trees():
    for root in SOURCE_ROOTS:
        for path in root.rglob("*.py"):
            yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_core_has_no_concrete_identity_branches():
    violations = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.If, ast.Match, ast.Compare)):
                continue
            for descendant in ast.walk(node):
                if (
                    isinstance(descendant, ast.Constant)
                    and descendant.value in CONCRETE_IDENTITIES
                ):
                    violations.append(
                        f"{path.relative_to(CORE)}:{descendant.lineno}: "
                        f"branches on {descendant.value!r}"
                    )
    assert not violations, "\n".join(violations)
