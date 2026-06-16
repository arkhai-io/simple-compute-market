"""Dependency-direction guardrail for the core/kit/domain split.

The target graph (docs/development/ARCHITECTURE.md, "Organizing Principle"):
kit packages and the VM domain *concept* modules (listings, negotiation,
settlement, provisioning hooks) are composed from below — they implement
core hook shapes without importing core. Only composition roots (the VM
buyer/storefront executables and the provisioning service) may import
core packages. Kit additionally takes no domain dependencies.

This test walks the actual import statements so the rule is enforced,
not just documented.
"""

from __future__ import annotations

import ast
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "docs").is_dir() and (parent / "kit").is_dir() and (parent / "domains").is_dir():
            return parent
    raise AssertionError("repo root not found above test file")


REPO = _repo_root()

# Import-name prefixes that identify core packages (roles, carriers,
# protocol clients).
CORE_PREFIXES = (
    "core_buyer",
    "core_storefront",
    "market_core",
    "registry_client",
    "storefront_client",
)

# Composition-root / executable import names that from-below code must
# not depend on either.
COMPOSITION_PREFIXES = (
    "market_storefront",
    "market_buyer",
)

# Domain import-name prefixes, forbidden for kit ("no domain deps").
DOMAIN_PREFIXES = ("domains",)

KIT_ROOTS = sorted(REPO.glob("kit/*/src"))

# Concept modules: from-below hook/implementation homes. The provisioning
# *service* subtree is the VM fulfillment executable (a composition root)
# and is exempt; so are tests and the IaC tree.
CONCEPT_ROOTS = [
    REPO / "domains/vms/listings",
    REPO / "domains/vms/negotiation",
    REPO / "domains/vms/settlement",
    REPO / "domains/vms/provisioning",
]
CONCEPT_EXCLUDES = ("provisioning/service/", "provisioning/iac/")

SKIP_PARTS = {"__pycache__", "tests", "build", ".venv", "dist"}


def _py_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        if any(ex in rel for ex in CONCEPT_EXCLUDES):
            continue
        yield path


def _absolute_imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module


def _violations(roots, forbidden_prefixes):
    out = []
    for root in roots:
        assert root.is_dir(), f"expected directory missing: {root}"
        for path in _py_files(root):
            for lineno, module in _absolute_imports(path):
                if any(
                    module == p or module.startswith(p + ".")
                    for p in forbidden_prefixes
                ):
                    out.append(f"{path.relative_to(REPO)}:{lineno}: imports {module}")
    return out


def test_kit_imports_no_core_or_domain_packages():
    assert KIT_ROOTS, "no kit packages found"
    violations = _violations(
        KIT_ROOTS, CORE_PREFIXES + COMPOSITION_PREFIXES + DOMAIN_PREFIXES
    )
    assert not violations, "kit must stay core- and domain-free:\n" + "\n".join(violations)


def test_domain_concept_modules_import_no_core_packages():
    violations = _violations(CONCEPT_ROOTS, CORE_PREFIXES + COMPOSITION_PREFIXES)
    assert not violations, (
        "domain concept modules must not import core/composition packages "
        "(only composition roots like domains/vms/{buyer,storefront} and the "
        "provisioning service may):\n" + "\n".join(violations)
    )
