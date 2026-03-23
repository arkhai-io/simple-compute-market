from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP_CONTRACT_PATH = ROOT / "scripts/bootstrap_contract.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bootstrap_contract_exists_and_declares_surface_matrix() -> None:
    module = _load_module(BOOTSTRAP_CONTRACT_PATH, "bootstrap_contract")

    assert module.BOOTSTRAP_CONTRACT_VERSION == "2026-03-23"
    assert module.SURFACE_MATRIX == {
        "manual_local": {
            "status": "supported",
            "entrypoint": "README.md",
            "validation_tier": "bootstrap_acceptance",
        },
        "cli_local": {
            "status": "supported",
            "entrypoint": "market dev",
            "validation_tier": "fast_validation",
        },
        "installed_bundle": {
            "status": "supported",
            "entrypoint": "~/.local/bin/market",
            "validation_tier": "bootstrap_acceptance",
        },
        "compose_local": {
            "status": "deprecated",
            "entrypoint": "docker-compose.yml",
            "validation_tier": "none",
        },
        "internal_test_e2e": {
            "status": "supported",
            "entrypoint": "tests/e2e/test_local_dual_agent_stack.py",
            "validation_tier": "full_validation",
        },
    }


def test_bootstrap_contract_defines_canonical_local_bootstrap_and_runtime_rules() -> None:
    module = _load_module(BOOTSTRAP_CONTRACT_PATH, "bootstrap_contract_runtime")

    assert module.CANONICAL_SUBMODULE_INIT_COMMAND == [
        "git",
        "submodule",
        "update",
        "--init",
        "--recursive",
    ]
    assert module.CANONICAL_NODE_INSTALL_COMMAND == [
        "npm",
        "ci",
        "--legacy-peer-deps",
    ]
    assert module.CANONICAL_LOCAL_DEPLOY_WRAPPER == [
        "python",
        "scripts/deploy_local_contracts.py",
        "--rpc-url",
        "<rpc-url>",
    ]
    assert module.LOCAL_TEST_ENV_ENTRYPOINT == [
        "cd",
        "core/agent",
        "&&",
        "make",
        "test-env",
    ]
    assert module.LOCAL_RPC_URL_POLICY == "dynamic"
    assert (
        module.ALKAHEST_ADDRESS_CONFIG_PATH
        == "core/agent/app/data/alkahest_anvil_addresses.json"
    )
    assert module.CANONICAL_INSTALLED_RUNTIME == {
        "venv_path": "core/.venv",
        "market_binary": "~/.local/bin/market",
        "role_wrapper_support": "repo_checkout_only",
    }


def test_bootstrap_contract_snapshot_is_machine_readable() -> None:
    module = _load_module(BOOTSTRAP_CONTRACT_PATH, "bootstrap_contract_snapshot")

    snapshot = module.contract_snapshot()

    assert snapshot["version"] == "2026-03-23"
    assert snapshot["surfaces"]["compose_local"]["status"] == "deprecated"
    assert snapshot["local_bootstrap"]["rpc_url_policy"] == "dynamic"
    assert snapshot["local_bootstrap"]["required_env"] == {
        "ALKAHEST_ADDRESS_CONFIG_PATH": "core/agent/app/data/alkahest_anvil_addresses.json"
    }
