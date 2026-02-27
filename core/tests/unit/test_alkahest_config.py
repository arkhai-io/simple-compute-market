import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.agent.app.utils.alkahest_config import (
    NETWORK_ANVIL,
    NETWORK_BASE_SEPOLIA,
    NETWORK_ETHEREUM_MAINNET,
    get_alkahest_network,
    get_trusted_oracle_arbiter,
    resolve_alkahest_address_config,
)


def test_get_alkahest_network_defaults_to_base_sepolia() -> None:
    assert get_alkahest_network(None) == NETWORK_BASE_SEPOLIA


def test_get_alkahest_network_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unsupported ALKAHEST_NETWORK"):
        get_alkahest_network("devnet")


def test_resolve_config_base_sepolia_uses_sdk_defaults() -> None:
    assert resolve_alkahest_address_config(NETWORK_BASE_SEPOLIA) is None


def test_resolve_config_ethereum_mainnet_returns_explicit_config() -> None:
    config = resolve_alkahest_address_config(NETWORK_ETHEREUM_MAINNET)
    assert config is not None
    assert isinstance(config, SimpleNamespace)
    assert config.erc20_addresses.eas == "0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587"


def test_resolve_config_anvil_requires_override() -> None:
    with pytest.raises(ValueError, match="ALKAHEST_NETWORK=anvil requires"):
        resolve_alkahest_address_config(NETWORK_ANVIL)


def test_resolve_config_from_path_override(tmp_path: Path) -> None:
    override = {
        "erc20_addresses": {
            "eas": "0x1111111111111111111111111111111111111111",
            "barter_utils": "0x2222222222222222222222222222222222222222",
            "escrow_obligation_nontierable": "0x3333333333333333333333333333333333333333",
            "escrow_obligation_tierable": "0x0000000000000000000000000000000000000000",
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


def test_get_trusted_oracle_arbiter_prefers_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override = {
        "arbiters_addresses": {
            "trusted_oracle_arbiter": "0x6666666666666666666666666666666666666666",
        }
    }
    path = tmp_path / "arbiter_override.json"
    path.write_text(json.dumps(override), encoding="utf-8")
    from core.agent.app.utils import alkahest_config as module

    monkeypatch.setattr(
        module,
        "CONFIG",
        replace(
            module.CONFIG,
            alkahest_network=NETWORK_BASE_SEPOLIA,
            alkahest_address_config_path=str(path),
        ),
    )
    resolved = get_trusted_oracle_arbiter()
    assert resolved == override["arbiters_addresses"]["trusted_oracle_arbiter"]
