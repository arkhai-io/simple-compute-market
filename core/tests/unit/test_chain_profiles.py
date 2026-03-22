from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/chain_profiles.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("chain_profiles", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_testnet_chain_profile_uses_canonical_validation_registry() -> None:
    module = _load_script_module()

    profile = module.get_chain_profile("ethereum_sepolia")

    assert profile.chain_id == 11155111
    assert profile.http_rpc_env == "ETH_SEPOLIA_HTTP_RPC_URL"
    assert profile.wss_rpc_env == "ETH_SEPOLIA_WSS_RPC_URL"
    assert profile.runtime_token_registry_path == "/app/core/agent/app/data/token_registry_eth_sepolia.json"
    assert profile.default_contract_addresses["IDENTITY_REGISTRY_ADDRESS"] == "0x8004A818BFB912233c491871b3d84c89A494BD9e"
    assert profile.default_contract_addresses["REPUTATION_REGISTRY_ADDRESS"] == "0x8004B663056A597Dffe9eCcC1965A193B7388713"
    assert profile.default_contract_addresses["VALIDATION_REGISTRY_ADDRESS"] == "0x8004Cb1BF31DAf7788923b405b754f57acEB4272"


def test_mainnet_chain_profile_uses_canonical_validation_registry() -> None:
    module = _load_script_module()

    profile = module.get_chain_profile("ethereum_mainnet")

    assert profile.chain_id == 1
    assert profile.http_rpc_env == "ETH_MAINNET_HTTP_RPC_URL"
    assert profile.runtime_token_registry_path is None
    assert profile.default_contract_addresses["VALIDATION_REGISTRY_ADDRESS"] == "0x8004Cc8439f36fd5F9F049D9fF86523Df6dAAB58"


def test_merge_contract_overrides_prefers_local_values_without_losing_defaults() -> None:
    module = _load_script_module()

    merged = module.merge_contract_overrides(
        "ethereum_sepolia",
        {
            "VALIDATION_REGISTRY_ADDRESS": "0x9999999999999999999999999999999999999999",
        },
    )

    assert merged["IDENTITY_REGISTRY_ADDRESS"] == "0x8004A818BFB912233c491871b3d84c89A494BD9e"
    assert merged["REPUTATION_REGISTRY_ADDRESS"] == "0x8004B663056A597Dffe9eCcC1965A193B7388713"
    assert merged["VALIDATION_REGISTRY_ADDRESS"] == "0x9999999999999999999999999999999999999999"


def test_get_chain_profile_rejects_unknown_chain_name() -> None:
    module = _load_script_module()

    with pytest.raises(ValueError, match="Unsupported chain profile"):
        module.get_chain_profile("devnet")
