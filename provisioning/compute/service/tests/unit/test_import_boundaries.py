from __future__ import annotations

import ast
from pathlib import Path


SERVICE_PACKAGE = (
    Path(__file__).resolve().parents[2] / "src" / "compute_provisioning_service"
)
ALLOWED_ADAPTER_ENTRYPOINTS = {
    "vm_provisioning_adapter.runtime",
    "vm_provisioning_adapter.routers",
    "vm_provisioning_adapter.legacy_backfill",
    "bare_metal_provisioning_adapter.runtime",
    "bare_metal_provisioning_adapter.routers",
}
FORBIDDEN_DOMAIN_MODULES = (
    "arkhai_bare_metal",
    "vm_provisioning_operator",
)
# Named exceptions, each a (service file, module) pair. The relay routes are
# VM's but still served here; their controller reads VM's relay wire models
# until relay administration is served by VM's adapter.
ALLOWED_DOMAIN_IMPORTS = {
    ("controllers/relays_controller.py", "vm_provisioning_operator.relays"),
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


def test_generic_service_imports_only_domain_adapter_entrypoints():
    violations: list[str] = []
    for path in SERVICE_PACKAGE.rglob("*.py"):
        relative = path.relative_to(SERVICE_PACKAGE).as_posix()
        for module in imported_modules(path):
            if (relative, module) in ALLOWED_DOMAIN_IMPORTS:
                continue
            if module.startswith(FORBIDDEN_DOMAIN_MODULES):
                violations.append(f"{path.relative_to(SERVICE_PACKAGE)}: {module}")
                continue
            if module.startswith(
                ("vm_provisioning_adapter", "bare_metal_provisioning_adapter")
            ) and module not in ALLOWED_ADAPTER_ENTRYPOINTS:
                violations.append(f"{path.relative_to(SERVICE_PACKAGE)}: {module}")

    assert violations == []
