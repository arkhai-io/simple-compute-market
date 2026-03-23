from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
LOCAL_GATE = ROOT / "scripts/check_local_bootstrap_contract.py"
INSTALLED_GATE = ROOT / "scripts/check_installed_bundle_contract.py"


def _load_script_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_bootstrap_gate_exists_with_reviewable_matrix() -> None:
    module = _load_script_module(LOCAL_GATE, "check_local_bootstrap_contract")

    assert module.TEST_MATRIX == [
        (
            [
                "uv",
                "--no-config",
                "run",
                "pytest",
                "tests/unit/test_bootstrap_contract.py",
                "tests/unit/test_bootstrap_local_dev.py",
                "tests/unit/test_test_env_helper.py",
                "tests/unit/test_local_bootstrap_docs_contract.py",
                "tests/unit/test_compose_deprecation_contract.py",
                "-q",
            ],
            module.ROOT / "core",
        ),
        (
            ["uv", "--no-config", "run", "pytest", "tests/test_dev_cli.py", "-q"],
            module.ROOT / "cli",
        ),
    ]


def test_installed_bundle_gate_exists_with_reviewable_matrix() -> None:
    module = _load_script_module(INSTALLED_GATE, "check_installed_bundle_contract")

    assert module.TEST_MATRIX == [
        (
            [
                "uv",
                "--no-config",
                "run",
                "pytest",
                "tests/unit/test_installed_bundle_contract.py",
                "tests/unit/test_package_manifest.py",
                "-q",
            ],
            module.ROOT / "core",
        ),
    ]
