"""Dependency-direction guardrail for the core/kit/domain split.

The target graph (docs/development/ARCHITECTURE.md, "Package and dependency
layers") permits shared kits to consume lower-layer core contracts, including
``core_storefront``. Kits must not reverse the dependency direction by
importing domain packages, composition roots, or role executables. VM domain
concept modules implement core hook shapes from below without importing core
packages. Only composition roots (the VM buyer/storefront executables and the
provisioning service) may import every layer.

This test walks the actual import statements so the rule is enforced,
not just documented.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (
            (parent / "docs").is_dir()
            and (parent / "kit").is_dir()
            and (parent / "domains").is_dir()
        ):
            return parent
    raise AssertionError("repo root not found above test file")


REPO = _repo_root()

# Lower-layer core contracts. These remain forbidden to VM concept modules,
# but are valid dependencies of shared kits.
CORE_PREFIXES = (
    "core_buyer",
    "core_storefront",
    "market_core",
    "registry_client",
    "storefront_client",
)

# Executable role/composition imports point upward from a kit and are forbidden.
# ``core_buyer`` is included because that distribution owns the ``market``
# executable; ``core_storefront`` is a contract package with no executable.
ROLE_EXECUTABLE_PREFIXES = (
    "core_buyer",
    "market_buyer",
    "market_storefront",
)

# Both repository namespaces and installed domain package names are guarded.
# A kit must receive domain behavior through injected hooks instead.
DOMAIN_PREFIXES = (
    "domains",
    "apicredits_storefront",
    "arkhai_bare_metal",
    "arkhai_bare_metal_storefront",
    "arkhai_vms",
    "bare_metal_provisioning_adapter",
    "vm_provisioning_adapter",
    "vm_provisioning_operator",
)

KIT_ROOTS = sorted(REPO.glob("kit/*/src"))

# Concept modules: from-below hook/implementation homes. Storefront-owned VM
# provisioning orchestration is now under the storefront composition root, and
# ``domains/vms/provisioning`` is the provisioning-service client/executable
# namespace rather than a concept-module home.
CONCEPT_ROOTS = [
    REPO / "domains/vms/listings",
    REPO / "domains/vms/negotiation",
    REPO / "domains/vms/settlement",
]
CONCEPT_EXCLUDES: tuple[str, ...] = ()

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


def _matches_prefix(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(
        module == prefix or module.startswith(prefix + ".")
        for prefix in prefixes
    )


def _violations(roots, forbidden_prefixes):
    out = []
    for root in roots:
        assert root.is_dir(), f"expected directory missing: {root}"
        for path in _py_files(root):
            for lineno, module in _absolute_imports(path):
                if _matches_prefix(module, forbidden_prefixes):
                    out.append(f"{path.relative_to(REPO)}:{lineno}: imports {module}")
    return out


def test_kit_imports_no_domain_or_upward_role_packages():
    assert KIT_ROOTS, "no kit packages found"
    violations = _violations(
        KIT_ROOTS,
        ROLE_EXECUTABLE_PREFIXES + DOMAIN_PREFIXES,
    )
    assert not violations, "kit must stay domain- and upward-role-free:\n" + "\n".join(
        violations
    )


def test_kit_boundary_classifier_rejects_domain_and_upward_imports() -> None:
    forbidden = ROLE_EXECUTABLE_PREFIXES + DOMAIN_PREFIXES
    assert _matches_prefix("domains.vms.settlement", forbidden)
    assert _matches_prefix("market_storefront.server", forbidden)
    assert not _matches_prefix("core_storefront.domain_registry", forbidden)


def test_domain_concept_modules_import_no_core_packages():
    violations = _violations(
        CONCEPT_ROOTS,
        CORE_PREFIXES + ROLE_EXECUTABLE_PREFIXES,
    )
    assert not violations, (
        "domain concept modules must not import core/composition packages "
        "(only composition roots like domains/vms/{buyer,storefront} and the "
        "provisioning service may):\n" + "\n".join(violations)
    )


def test_vm_storefront_constructs_contract_only_in_domain_contribution() -> None:
    storefront_root = (
        REPO / "domains" / "vms" / "storefront" / "src" / "market_storefront"
    )
    construction_calls: list[str] = []
    stale_accessors: list[str] = []
    for path in _py_files(storefront_root):
        source = path.read_text(encoding="utf-8")
        if "get_market_domain_contract" in source:
            stale_accessors.append(str(path.relative_to(REPO)))
        tree = ast.parse(source, filename=str(path))
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "build_vm_storefront_domain"
            for node in ast.walk(tree)
        ):
            construction_calls.append(str(path.relative_to(REPO)))

    assert stale_accessors == []
    assert construction_calls == [
        "domains/vms/storefront/src/market_storefront/domain_runtime.py"
    ]


def test_vm_storefront_imports_no_bare_metal_composition() -> None:
    storefront_root = (
        REPO / "domains" / "vms" / "storefront" / "src" / "market_storefront"
    )
    violations = _violations(
        [storefront_root],
        ("domains.bare_metal", "arkhai_bare_metal_storefront"),
    )
    assert not violations, "VM storefront must not import bare-metal roots:\n" + "\n".join(
        violations
    )


def test_core_storefront_imports_no_domain_composition() -> None:
    core_root = REPO / "core" / "storefront" / "src" / "core_storefront"
    violations = _violations(
        [core_root],
        ("domains.vms", "domains.bare_metal", "market_storefront", "arkhai_bare_metal_storefront"),
    )
    assert not violations, "core storefront must stay domain-free:\n" + "\n".join(
        violations
    )


def test_vm_storefront_wheel_declares_lower_layer_contract_package() -> None:
    metadata = tomllib.loads(
        (
            REPO / "domains" / "vms" / "storefront" / "pyproject.toml"
        ).read_text(encoding="utf-8")
    )
    dependencies = metadata["project"]["dependencies"]
    assert any(dependency.startswith("arkhai-core>=") for dependency in dependencies)
