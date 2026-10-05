from __future__ import annotations

import ast
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[2]
SERVICE_PACKAGE = SERVICE_ROOT / "src" / "compute_provisioning_service"
REPOSITORY = SERVICE_ROOT.parents[2]
ADAPTER_PACKAGES = (
    REPOSITORY
    / "domains/vms/provisioning/adapter/src/vm_provisioning_adapter",
    REPOSITORY
    / "domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter",
)
DOMAIN_MODULES = (
    "vm_provisioning_adapter",
    "bare_metal_provisioning_adapter",
    "vm_provisioning_operator",
    "arkhai_bare_metal",
)
# Every place the generic service may name a domain, as (service file, module)
# pairs. The composition root builds the adapters' runtimes and mounts their
# routers. The service's database holds VM's tables, so schema creation creates
# VM's metadata, and the migration history, which created and evolved those
# tables, reads VM's models and its legacy lease conversion.
ALLOWED_DOMAIN_IMPORTS = {
    ("container.py", "vm_provisioning_adapter.runtime"),
    ("container.py", "bare_metal_provisioning_adapter.runtime"),
    ("main.py", "vm_provisioning_adapter.routers"),
    ("main.py", "bare_metal_provisioning_adapter.routers"),
    ("db/database.py", "vm_provisioning_adapter.db"),
    ("db/migrations.py", "vm_provisioning_adapter.db"),
    ("db/migrations.py", "vm_provisioning_adapter.legacy_backfill"),
}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_the_generic_service_names_a_domain_only_where_allowed():
    violations: list[str] = []
    for path in SERVICE_PACKAGE.rglob("*.py"):
        relative = path.relative_to(SERVICE_PACKAGE).as_posix()
        for module in imported_modules(path):
            if module.startswith(DOMAIN_MODULES) and (
                relative,
                module,
            ) not in ALLOWED_DOMAIN_IMPORTS:
                violations.append(f"{relative}: {module}")

    assert violations == []


def imported_targets(path: Path) -> set[str]:
    """Every imported module, and each name imported from one as ``module.name``,
    so ``from package import module`` is seen as the module it imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            targets.add(node.module)
            targets.update(f"{node.module}.{alias.name}" for alias in node.names)
    return targets


SERVICE_COMPOSITION = (
    "compute_provisioning_service.container",
    "compute_provisioning_service.main",
    "compute_provisioning_service.app_runtime",
)


def test_no_adapter_module_reaches_into_the_service_composition():
    """Adapters bind their routes through accessors the service passes, so no
    adapter module imports the service's composition module or its entry
    point."""
    violations: list[str] = []
    for package in ADAPTER_PACKAGES:
        assert package.is_dir(), package
        for path in package.rglob("*.py"):
            for target in imported_targets(path):
                if target.startswith(SERVICE_COMPOSITION):
                    violations.append(f"{path.relative_to(REPOSITORY)}: {target}")

    assert violations == []
