"""market-core stays a pure wire-carrier wheel.

The wheel survives the core/kit/domain extraction as the protocol
carrier package both roles share (buyer and storefront must derive
identical negotiation/settlement shapes from the same message history).
The price of surviving: it imports nothing but the standard library and
pydantic — no role packages, no kit, no domains — so that any role can
ship it without dragging in the rest of the graph, and no domain
vocabulary can sneak back in through a dependency.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "market_core"

# Everything market_core may import from, by top-level module name.
ALLOWED_TOP_LEVEL = {"pydantic", "typing", "market_core"}

FORBIDDEN_PREFIXES = (
    "market_",   # kit + carrier siblings (market_identity, market_policy, …)
    "core_",     # role shells
    "domains",   # domain packages
    "registry_client",
    "storefront_client",
)


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_market_core_imports_only_stdlib_and_pydantic():
    violations: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        for name in sorted(_top_level_imports(path)):
            if name in ALLOWED_TOP_LEVEL or name in sys.stdlib_module_names:
                continue
            violations.append(f"{path.relative_to(SRC)}: imports {name!r}")
    assert not violations, (
        "market-core must stay a pure carrier wheel (stdlib + pydantic only):\n"
        + "\n".join(violations)
    )


def test_market_core_imports_no_role_kit_or_domain_code():
    # Redundant with the allowlist above, but states the architectural
    # rule directly so a future allowlist edit can't quietly open it.
    violations: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        for name in sorted(_top_level_imports(path)):
            if name != "market_core" and name.startswith(FORBIDDEN_PREFIXES):
                violations.append(f"{path.relative_to(SRC)}: imports {name!r}")
    assert not violations, "\n".join(violations)
