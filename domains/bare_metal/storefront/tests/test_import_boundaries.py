"""Dependency-direction guardrails for the bare-metal storefront composition."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "AGENTS.md").is_file() and (parent / "domains").is_dir():
            return parent
    raise AssertionError("repository root not found above test file")


REPO = _repo_root()
SKIP_PARTS = {".venv", "__pycache__", "build", "dist", "tests"}
BARE_METAL_STOREFRONT = ("arkhai_bare_metal_storefront",)
VM_IMPLEMENTATIONS = (
    "arkhai_vms",
    "domains.vms",
    "market_storefront",
    "vm_provisioning_adapter",
)


def _python_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        assert root.is_dir(), f"expected source directory missing: {root}"
        for path in sorted(root.rglob("*.py")):
            if not any(part in SKIP_PARTS for part in path.parts):
                yield path


def _absolute_imports(path: Path) -> Iterable[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module


def _violations(
    roots: Iterable[Path],
    forbidden: tuple[str, ...],
) -> list[str]:
    violations: list[str] = []
    for path in _python_files(roots):
        for lineno, module in _absolute_imports(path):
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in forbidden
            ):
                violations.append(
                    f"{path.relative_to(REPO)}:{lineno}: imports {module}",
                )
    return violations


def test_core_and_kit_do_not_import_bare_metal_storefront() -> None:
    roots = [REPO / "core/src"]
    roots += sorted(REPO.glob("core/*/src"))
    roots += sorted(REPO.glob("kit/*/src"))
    assert roots, "no core or kit source roots found"

    violations = _violations(roots, BARE_METAL_STOREFRONT)

    assert not violations, (
        "core and kit packages must not import a composition root:\n"
        + "\n".join(violations)
    )


def test_bare_metal_storefront_does_not_import_vm_implementations() -> None:
    roots = [REPO / "domains/bare_metal/storefront/src"]

    violations = _violations(roots, VM_IMPLEMENTATIONS)

    assert not violations, (
        "the bare-metal composition must not reuse VM implementations:\n"
        + "\n".join(violations)
    )
