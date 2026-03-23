from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PACKAGE_MANIFEST_PATH = ROOT / "scripts/package_manifest.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_package_manifest_exists_and_declares_installed_layout() -> None:
    module = _load_module(PACKAGE_MANIFEST_PATH, "package_manifest")

    assert module.MANIFEST_VERSION == "2026-03-23"
    assert module.INSTALLED_LAYOUT == {
        "repo_root": "~/.market",
        "market_binary": "~/.local/bin/market",
        "runtime_venv": "core/.venv",
    }
    assert module.SUPPORTED_INSTALLED_ENTRYPOINTS == [
        "~/.local/bin/market",
    ]


def test_package_manifest_includes_scripts_and_excludes_broken_compose_artifacts() -> None:
    module = _load_module(PACKAGE_MANIFEST_PATH, "package_manifest_scripts")

    assert "scripts" in module.INCLUDED_TOP_LEVEL_PATHS
    assert "docs" in module.INCLUDED_TOP_LEVEL_PATHS
    assert "docker-compose.yml" not in module.INCLUDED_TOP_LEVEL_PATHS
    assert "scripts" not in module.TAR_EXCLUDE_PATTERNS
    assert "docker-compose*.yml" in module.TAR_EXCLUDE_PATTERNS


def test_package_manifest_snapshot_is_machine_readable() -> None:
    module = _load_module(PACKAGE_MANIFEST_PATH, "package_manifest_snapshot")

    snapshot = module.manifest_snapshot()

    assert snapshot["version"] == "2026-03-23"
    assert snapshot["installed_layout"]["runtime_venv"] == "core/.venv"
    assert snapshot["supported_installed_entrypoints"] == ["~/.local/bin/market"]
