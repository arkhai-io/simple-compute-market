import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from market_alkahest.alkahest import (
    NETWORK_ANVIL,
    NETWORK_BASE_SEPOLIA,
    NETWORK_ETHEREUM_SEPOLIA,
    NETWORK_ETHEREUM_MAINNET,
    get_alkahest_network,
    get_erc20_splitter,
    get_native_token_splitter,
    get_trusted_oracle_arbiter,
    resolve_alkahest_address_config,
)


def test_get_alkahest_network_defaults_to_base_sepolia() -> None:
    assert get_alkahest_network(None) == NETWORK_BASE_SEPOLIA


def test_get_alkahest_network_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        get_alkahest_network("devnet")


def test_resolve_config_base_sepolia_uses_sdk_defaults() -> None:
    assert resolve_alkahest_address_config(NETWORK_BASE_SEPOLIA) is None


def test_resolve_config_ethereum_mainnet_returns_sdk_config() -> None:
    """Non-base-sepolia named chains return alkahest-py's
    ``DefaultExtensionConfig.for_chain``. The SDK normalises addresses to
    lowercase hex (alloy ``Address`` Display)."""
    config = resolve_alkahest_address_config(NETWORK_ETHEREUM_MAINNET)
    assert config is not None
    assert config.erc20_addresses.eas.lower() == "0xa1207f3bba224e2c9c3c6d5af63d0eb1582ce587"


def test_resolve_config_ethereum_sepolia_returns_sdk_config() -> None:
    config = resolve_alkahest_address_config(NETWORK_ETHEREUM_SEPOLIA)
    assert config is not None
    assert config.erc20_addresses.eas.lower() == "0xc2679fbd37d54388ce493f1db75320d236e1815e"


def test_resolve_config_anvil_requires_override() -> None:
    with pytest.raises(ValueError, match="anvil"):
        resolve_alkahest_address_config(NETWORK_ANVIL)


def test_resolve_config_from_path_override(tmp_path: Path) -> None:
    override = {
        "erc20_addresses": {
            "eas": "0x1111111111111111111111111111111111111111",
            "barter_utils": "0x2222222222222222222222222222222222222222",
            "escrow_obligation_default": "0x3333333333333333333333333333333333333333",
            "escrow_obligation_unconditional": "0x0000000000000000000000000000000000000000",
            "payment_obligation": "0x4444444444444444444444444444444444444444",
        },
        "arbiters_addresses": {
            "trusted_oracle_arbiter": "0x5555555555555555555555555555555555555555",
        },
    }
    path = tmp_path / "alkahest_override.json"
    path.write_text(json.dumps(override), encoding="utf-8")
    config = resolve_alkahest_address_config(
        NETWORK_ANVIL,
        config_path=str(path),
    )
    assert config is not None
    assert config.erc20_addresses.barter_utils == override["erc20_addresses"]["barter_utils"]


def test_get_trusted_oracle_arbiter_prefers_override(tmp_path: Path) -> None:
    override = {
        "arbiters_addresses": {
            "trusted_oracle_arbiter": "0x6666666666666666666666666666666666666666",
        }
    }
    path = tmp_path / "arbiter_override.json"
    path.write_text(json.dumps(override), encoding="utf-8")
    # Clear the lru_cache so the new path is picked up.
    from market_alkahest.alkahest import _load_override_config_cached
    _load_override_config_cached.cache_clear()
    resolved = get_trusted_oracle_arbiter(NETWORK_BASE_SEPOLIA, config_path=str(path))
    assert resolved == override["arbiters_addresses"]["trusted_oracle_arbiter"]


def test_get_splitter_arbiters_prefer_override(tmp_path: Path) -> None:
    override = {
        "arbiters_addresses": {
            "erc20_splitter": "0x7777777777777777777777777777777777777777",
            "native_token_splitter": "0x8888888888888888888888888888888888888888",
        }
    }
    path = tmp_path / "splitter_override.json"
    path.write_text(json.dumps(override), encoding="utf-8")
    from market_alkahest.alkahest import _load_override_config_cached
    _load_override_config_cached.cache_clear()
    assert get_erc20_splitter(NETWORK_BASE_SEPOLIA, config_path=str(path)) == (
        override["arbiters_addresses"]["erc20_splitter"]
    )
    assert get_native_token_splitter(
        NETWORK_BASE_SEPOLIA, config_path=str(path)
    ) == override["arbiters_addresses"]["native_token_splitter"]
