from __future__ import annotations

import ast
import re
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


def resolved_imports(path: Path, package_root: Path, package: str) -> set[str]:
    """Every module ``path`` imports, at any depth, relative imports resolved.

    Walks every ``Import`` and ``ImportFrom`` in the syntax tree, so an import
    inside a function, under ``TYPE_CHECKING``, or behind ``try``/``except``
    counts as a top-level one does. ``from package import name`` also counts
    as ``package.name``, which may be a module.
    """
    relative = path.relative_to(package_root).with_suffix("").parts
    module_parts = [package, *relative]
    if module_parts[-1] == "__init__":
        module_parts = module_parts[:-1]
    else:
        module_parts = module_parts[:-1]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module_parts[: len(module_parts) - (node.level - 1)]
                module = ".".join([*base, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            modules.add(module)
            modules.update(f"{module}.{alias.name}" for alias in node.names)
    return modules


def _package_imports(package_root: Path, package: str) -> dict[str, set[str]]:
    return {
        path.relative_to(REPOSITORY).as_posix(): resolved_imports(path, package_root, package)
        for path in sorted(package_root.rglob("*.py"))
    }


def _violations(package_root: Path, package: str, forbidden: tuple[str, ...]) -> list[str]:
    return [
        f"{file}: {module}"
        for file, modules in _package_imports(package_root, package).items()
        for module in sorted(modules)
        if any(module == name or module.startswith(name + ".") for name in forbidden)
    ]


VM_ADAPTER, BARE_METAL_ADAPTER = ADAPTER_PACKAGES
FAMILY_KIT = REPOSITORY / "provisioning/compute/src/compute_provisioning"
NEUTRAL_PACKAGES = {
    "compute_provisioning": FAMILY_KIT,
    "compute_provisioning_ansible": REPOSITORY
    / "provisioning/compute/ansible/src/compute_provisioning_ansible",
    "compute_provisioning_contracts": REPOSITORY
    / "provisioning/compute/contracts/src/compute_provisioning_contracts",
    "compute_provisioning_client": REPOSITORY
    / "provisioning/compute/client/src/compute_provisioning_client",
    "compute_provisioning_service": SERVICE_PACKAGE,
}


def test_neither_adapter_imports_the_service_or_the_other_adapter():
    """Adapters receive their collaborators from composition; neither depends on
    the deployed service or on a sibling domain's adapter, at any depth."""
    violations = _violations(
        VM_ADAPTER,
        "vm_provisioning_adapter",
        ("compute_provisioning_service", "bare_metal_provisioning_adapter"),
    ) + _violations(
        BARE_METAL_ADAPTER,
        "bare_metal_provisioning_adapter",
        ("compute_provisioning_service", "vm_provisioning_adapter"),
    )

    assert violations == []


def test_no_neutral_provisioning_module_imports_a_domain_operator_client():
    """Compatibility flows from a domain's client to the neutral contract,
    never the other way."""
    violations = [
        violation
        for package, root in NEUTRAL_PACKAGES.items()
        for violation in _violations(root, package, ("vm_provisioning_operator",))
    ]

    assert violations == []


def test_the_job_and_host_authorities_name_no_execution_implementation():
    """Jobs and hosts are the family's: Ansible and SSH are one implementation
    of execution, which contributes its codec, executor, and probe."""
    implementations = (
        "compute_provisioning_ansible",
        "ansible",
        "ansible_runner",
        "paramiko",
        "asyncssh",
        "fabric",
    )
    violations = [
        violation
        for sub in ("jobs", "hosts")
        for violation in _violations(
            FAMILY_KIT / sub, f"compute_provisioning.{sub}", implementations
        )
    ]

    assert violations == []


# Deployment configuration is part of the boundary: a domain's compose files,
# profiles, inventory settings, and images name only its own tree, shared kits,
# and the compute family's vocabulary (``domains/compute``). Root-level compose
# files are compositions and may name any tree.
DOMAINS = ("vms", "bare_metal", "apicredits")
_CONFIG_SUFFIXES = {".yml", ".yaml", ".toml", ".ini", ".cfg", ".env", ".json", ".sh"}


def _deployment_files(domain_root: Path):
    for path in sorted(domain_root.rglob("*")):
        if not path.is_file() or ".venv" in path.parts or "node_modules" in path.parts:
            continue
        if path.name in {"uv.lock", "package-lock.json"}:
            continue
        if path.suffix in _CONFIG_SUFFIXES or path.name.startswith(("Dockerfile", "Makefile")):
            yield path


def test_no_domain_s_deployment_configuration_names_another_domain_s_tree():
    violations = []
    for domain in DOMAINS:
        root = REPOSITORY / "domains" / domain
        others = [other for other in DOMAINS if other != domain]
        pattern = re.compile(
            r"(?:domains/|(?<![\w.])\.\./)(" + "|".join(map(re.escape, others)) + r")\b"
        )
        for path in _deployment_files(root):
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if pattern.search(line):
                    violations.append(f"{path.relative_to(REPOSITORY)}:{number}: {line.strip()}")

    assert violations == []


def test_the_ansible_distribution_names_no_domain_s_inventory_group_or_playbook():
    """The distribution runs whichever playbooks and inventory groups the
    domains' codecs and configuration name; it knows none of them."""
    from bare_metal_provisioning_adapter.codec import BareMetalAnsibleCodec
    from vm_provisioning_adapter.codec import VmAnsibleCodec

    names = {VmAnsibleCodec.inventory_group, BareMetalAnsibleCodec.inventory_group}
    names.update(
        path.name
        for domain in DOMAINS
        for path in (REPOSITORY / "domains" / domain).rglob("playbooks/**/*")
        if path.suffix in {".yml", ".yaml"}
    )
    distribution = NEUTRAL_PACKAGES["compute_provisioning_ansible"]
    violations = [
        f"{path.relative_to(REPOSITORY)}: {name}"
        for path in sorted(distribution.rglob("*"))
        if path.is_file() and path.suffix in {".py", ".cfg", ".yml", ".yaml"}
        for name in sorted(names)
        if name in path.read_text(encoding="utf-8")
    ]

    assert names
    assert violations == []
