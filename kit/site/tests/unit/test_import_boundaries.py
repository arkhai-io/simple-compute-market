import ast
from pathlib import Path


FORBIDDEN_PREFIXES = (
    "compute_provisioning",
    "core_storefront",
    "services.async_job_queue",
    "services.job_service",
    "domains.vms",
    "domains.bare_metal",
    "arkhai_bare_metal",
)


def test_lower_site_modules_do_not_import_lifecycle_or_executor_implementations():
    site_root = Path(__file__).parents[2] / "src" / "market_site"
    violations = []

    for source_path in site_root.glob("*.py"):
        tree = ast.parse(source_path.read_text(), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            else:
                continue
            for module_name in imported:
                if module_name.startswith(FORBIDDEN_PREFIXES):
                    violations.append(f"{source_path.name}:{node.lineno}: {module_name}")

    assert violations == []
