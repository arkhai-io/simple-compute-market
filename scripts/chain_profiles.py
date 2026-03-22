#!/usr/bin/env python3
"""Centralized chain-profile defaults used by live deployment tooling."""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple


ROOT = Path(__file__).resolve().parents[1]
BASE_SEPOLIA_TOKEN_REGISTRY = ROOT / "core/agent/app/data/token_registry_base_sepolia.json"
ETH_SEPOLIA_TOKEN_REGISTRY = ROOT / "core/agent/app/data/token_registry_eth_sepolia.json"


class ChainProfile(NamedTuple):
    chain_name: str
    chain_id: int
    http_rpc_env: str
    wss_rpc_env: str | None
    funder_env: str | None
    token_registry_path: Path | None
    runtime_token_registry_path: str | None
    default_contract_addresses: dict[str, str]
    temp_file_suffix: str


CHAIN_PROFILES: dict[str, ChainProfile] = {
    "base_sepolia": ChainProfile(
        chain_name="base_sepolia",
        chain_id=84532,
        http_rpc_env="ALCHEMY_BASE_SEPOLIA_HTTP_URL",
        wss_rpc_env="ALCHEMY_BASE_SEPOLIA_WSS_URL",
        funder_env="SEPOLIA_FUNDER_PRIVATE_KEY",
        token_registry_path=BASE_SEPOLIA_TOKEN_REGISTRY,
        runtime_token_registry_path="/app/core/agent/app/data/token_registry_base_sepolia.json",
        default_contract_addresses={
            "IDENTITY_REGISTRY_ADDRESS": "0x8004A818BFB912233c491871b3d84c89A494BD9e",
            "REPUTATION_REGISTRY_ADDRESS": "0x8004B663056A597Dffe9eCcC1965A193B7388713",
            "VALIDATION_REGISTRY_ADDRESS": "0x8004Cb1BF31DAf7788923b405b754f57acEB4272",
        },
        temp_file_suffix="base-sepolia",
    ),
    "base": ChainProfile(
        chain_name="base",
        chain_id=8453,
        http_rpc_env="ALCHEMY_BASE_MAINNET_HTTP_URL",
        wss_rpc_env="ALCHEMY_BASE_MAINNET_WSS_URL",
        funder_env="MAINNET_FUNDER_PRIVATE_KEY",
        token_registry_path=None,
        runtime_token_registry_path=None,
        default_contract_addresses={
            "IDENTITY_REGISTRY_ADDRESS": "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
            "REPUTATION_REGISTRY_ADDRESS": "0x8004BAa17C55a88189AE136b182e5fdA19dE9b63",
            "VALIDATION_REGISTRY_ADDRESS": "0x8004Cc8439f36fd5F9F049D9fF86523Df6dAAB58",
        },
        temp_file_suffix="base-mainnet",
    ),
    "ethereum_sepolia": ChainProfile(
        chain_name="ethereum_sepolia",
        chain_id=11155111,
        http_rpc_env="ETH_SEPOLIA_HTTP_RPC_URL",
        wss_rpc_env="ETH_SEPOLIA_WSS_RPC_URL",
        funder_env="SEPOLIA_FUNDER_PRIVATE_KEY",
        token_registry_path=ETH_SEPOLIA_TOKEN_REGISTRY,
        runtime_token_registry_path="/app/core/agent/app/data/token_registry_eth_sepolia.json",
        default_contract_addresses={
            "IDENTITY_REGISTRY_ADDRESS": "0x8004A818BFB912233c491871b3d84c89A494BD9e",
            "REPUTATION_REGISTRY_ADDRESS": "0x8004B663056A597Dffe9eCcC1965A193B7388713",
            "VALIDATION_REGISTRY_ADDRESS": "0x8004Cb1BF31DAf7788923b405b754f57acEB4272",
        },
        temp_file_suffix="eth-sepolia",
    ),
    "ethereum_mainnet": ChainProfile(
        chain_name="ethereum_mainnet",
        chain_id=1,
        http_rpc_env="ETH_MAINNET_HTTP_RPC_URL",
        wss_rpc_env=None,
        funder_env="MAINNET_FUNDER_PRIVATE_KEY",
        token_registry_path=None,
        runtime_token_registry_path=None,
        default_contract_addresses={
            "IDENTITY_REGISTRY_ADDRESS": "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
            "REPUTATION_REGISTRY_ADDRESS": "0x8004BAa17C55a88189AE136b182e5fdA19dE9b63",
            "VALIDATION_REGISTRY_ADDRESS": "0x8004Cc8439f36fd5F9F049D9fF86523Df6dAAB58",
        },
        temp_file_suffix="eth-mainnet",
    ),
}


def get_chain_profile(chain_name: str) -> ChainProfile:
    try:
        return CHAIN_PROFILES[chain_name]
    except KeyError as exc:
        raise ValueError(
            "Unsupported chain profile: "
            + chain_name
            + ". Expected one of "
            + ", ".join(sorted(CHAIN_PROFILES))
        ) from exc


def merge_contract_overrides(chain_name: str, overrides: dict[str, str] | None) -> dict[str, str]:
    profile = get_chain_profile(chain_name)
    merged = dict(profile.default_contract_addresses)
    if overrides:
        for key, value in overrides.items():
            if value:
                merged[key] = value
    return merged
