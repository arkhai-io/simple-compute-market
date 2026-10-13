"""Module-level import boundaries inside ``market_fulfillment``.

`make check-architecture` holds the package-level rules: this kit depends only
downward, on ``kit/site``, ``kit/resource-pools`` and its contracts, and the
core carrier package, and never on the compute family kit, a domain, or a
storefront (``openspec/specs/fulfillment/spec.md#dependency-boundary``). What it
cannot express is which module of the package may reach which of those, so the
carrier modules stay free of the scheduling and persistence dependencies.
"""

import ast
from pathlib import Path


def _imported_module_names(source_path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(source_path.read_text(), filename=str(source_path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            # Relative imports (``from .settlement_types import X``) carry
            # their dots in ``node.level``, not in ``node.module`` -- fold
            # them back in so callers can recognize "starts with a dot" as
            # "local sibling module" regardless of depth.
            prefix = "." * node.level
            found.append((node.lineno, f"{prefix}{node.module or ''}"))
    return found


def test_only_scheduler_and_ids_modules_import_the_two_allowed_kit_dependencies():
    """Keep each fulfillment module within its declared dependency boundary.

    Most modules are plain data, policy, or persistence contracts. The
    scheduling and fulfillment persistence use cases may reach their specific
    upstream kits, while orchestration remains composed entirely from local
    fulfillment abstractions.
    """
    package_root = Path(__file__).parents[2] / "src" / "market_fulfillment"
    allowed_external_by_module = {
        "__init__.py": set(),  # only imports its own siblings
        "ids.py": {"uuid6"},
        "settlement_types.py": {"pydantic"},
        "scheduling.py": set(),
        "round_robin_policy.py": set(),
        "results.py": {"market_core", "pydantic", "typing"},
        "scheduler.py": {"market_resource_pools", "market_resource_pools_contracts", "market_site"},
        "scheduling_persistence.py": {"market_resource_pools", "market_site", "sqlalchemy"},
        "provider.py": {"market_core"},
        "fulfillment.py": {"market_core", "market_resource_pools", "market_resource_pools_contracts"},
        "fulfillment_persistence.py": {"market_core", "market_resource_pools", "sqlalchemy"},
        "transitions.py": set(),
        "db.py": {"sqlalchemy"},
        "settlement_repository.py": {"market_core", "sqlalchemy"},
        "backoff.py": set(),
        "backfill.py": set(),
        "recovery_diagnostics.py": set(),
    }
    violations = []
    for source_path in package_root.glob("*.py"):
        allowed = allowed_external_by_module.get(source_path.name)
        if allowed is None:
            violations.append(
                f"{source_path.name}: module is missing from the external-import allowlist"
            )
            continue
        for _, module_name in _imported_module_names(source_path):
            top_level = module_name.split(".")[0]
            is_local = module_name.startswith(".") or top_level == "market_fulfillment"
            is_stdlib_or_typing = top_level in {
                "__future__", "abc", "contextlib", "dataclasses", "datetime", "decimal", "enum", "logging", "random", "threading", "typing", "uuid",
            }
            if is_local or is_stdlib_or_typing:
                continue
            if top_level not in allowed:
                violations.append(f"{source_path.name}: unexpected external import {module_name!r}")

    assert violations == []
