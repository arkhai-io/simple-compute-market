#!/usr/bin/env python3
"""Canonical bootstrap contract for repo onboarding, packaging, and validation."""

from __future__ import annotations

import json
from typing import Any


BOOTSTRAP_CONTRACT_VERSION = "2026-03-23"


SURFACE_MATRIX: dict[str, dict[str, str]] = {
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

CANONICAL_SUBMODULE_INIT_COMMAND = [
    "git",
    "submodule",
    "update",
    "--init",
    "--recursive",
]
CANONICAL_NODE_INSTALL_COMMAND = ["npm", "ci", "--legacy-peer-deps"]
CANONICAL_LOCAL_DEPLOY_WRAPPER = [
    "python",
    "scripts/deploy_local_contracts.py",
    "--rpc-url",
    "<rpc-url>",
]
LOCAL_TEST_ENV_ENTRYPOINT = ["cd", "core/agent", "&&", "make", "test-env"]
LOCAL_RPC_URL_POLICY = "dynamic"
ALKAHEST_ADDRESS_CONFIG_PATH = "core/agent/app/data/alkahest_anvil_addresses.json"
CANONICAL_INSTALLED_RUNTIME = {
    "venv_path": "core/.venv",
    "market_binary": "~/.local/bin/market",
    "role_wrapper_support": "repo_checkout_only",
}


def contract_snapshot() -> dict[str, Any]:
    """Return the canonical bootstrap contract as a machine-readable mapping."""

    return {
        "version": BOOTSTRAP_CONTRACT_VERSION,
        "surfaces": SURFACE_MATRIX,
        "local_bootstrap": {
            "submodule_init": CANONICAL_SUBMODULE_INIT_COMMAND,
            "node_install": CANONICAL_NODE_INSTALL_COMMAND,
            "deploy_wrapper": CANONICAL_LOCAL_DEPLOY_WRAPPER,
            "test_env_entrypoint": LOCAL_TEST_ENV_ENTRYPOINT,
            "rpc_url_policy": LOCAL_RPC_URL_POLICY,
            "required_env": {
                "ALKAHEST_ADDRESS_CONFIG_PATH": ALKAHEST_ADDRESS_CONFIG_PATH,
            },
        },
        "installed_runtime": CANONICAL_INSTALLED_RUNTIME,
    }


def main() -> int:
    print(json.dumps(contract_snapshot(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
