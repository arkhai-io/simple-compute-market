"""Package-boundary tests proving dependency direction and carrier purity.

the kit dependency contract. Mirrors the AST-scan pattern used by ``kit/site/tests/unit/
test_import_boundaries.py`` and ``provisioning/compute/service/tests/
unit/test_import_boundaries.py``.

Dependency direction (``openspec/specs/fulfillment/spec.md#dependency-boundary``): ``kit/fulfillment`` depends on ``kit/site``
(``market_site``) and ``kit/resource-pools`` (``market_resource_pools``).
Nothing here may depend on ``compute_provisioning``, the extracted
compute provisioning service, any VM/bare-metal domain package, or the
storefront -- those depend on this package, not the reverse. In
particular, this package must never import ``compute_provisioning`` or
``compute_provisioning_service``: that would recreate exactly the
reverse dependency that the permanent fulfillment boundary prohibits.
"""

import ast
from pathlib import Path


FORBIDDEN_PREFIXES = (
    "compute_provisioning",
    "compute_provisioning_service",
    "core_storefront",
    "market_storefront",
    "domains.vms",
    "domains.bare_metal",
    "domains.apicredits",
    "arkhai_bare_metal",
    "vm_provisioning_adapter",
    "bare_metal_provisioning_adapter",
)


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


def test_fulfillment_modules_do_not_import_downstream_packages():
    package_root = Path(__file__).parents[2] / "src" / "market_fulfillment"
    violations = []

    for source_path in package_root.glob("*.py"):
        for lineno, module_name in _imported_module_names(source_path):
            if module_name.startswith(FORBIDDEN_PREFIXES):
                violations.append(f"{source_path.name}:{lineno}: {module_name}")

    assert violations == []


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
        "envelopes.py": {"pydantic", "typing"},
        "scheduler.py": {"market_resource_pools", "market_site"},
        "scheduling_persistence.py": {"market_resource_pools", "market_site", "sqlalchemy"},
        "provider.py": set(),
        "fulfillment.py": set(),
        "fulfillment_persistence.py": {"market_resource_pools", "sqlalchemy"},
        "transitions.py": set(),
        "db.py": {"sqlalchemy"},
        "repository.py": {"sqlalchemy"},
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
                "__future__", "abc", "contextlib", "dataclasses", "datetime", "decimal", "enum", "threading", "typing",
            }
            if is_local or is_stdlib_or_typing:
                continue
            if top_level not in allowed:
                violations.append(f"{source_path.name}: unexpected external import {module_name!r}")

    assert violations == []
