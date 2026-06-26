"""Unit tests for market_alkahest.alkahest.

The helpers take ``chain_name`` + optional ``config_path`` arguments —
no env reads. Tests pass values explicitly.
"""
import json

import pytest


def test_get_alkahest_network_base_sepolia():
    from market_alkahest.alkahest import get_alkahest_network
    assert get_alkahest_network("base_sepolia") == "base_sepolia"


def test_get_alkahest_network_default():
    from market_alkahest.alkahest import get_alkahest_network
    assert get_alkahest_network(None) == "base_sepolia"


def test_get_alkahest_network_invalid():
    from market_alkahest.alkahest import get_alkahest_network
    with pytest.raises(ValueError, match="Unsupported"):
        get_alkahest_network("unknown_network")


def test_get_trusted_oracle_arbiter_base_sepolia():
    from market_alkahest.alkahest import get_trusted_oracle_arbiter
    import market_alkahest.alkahest as alc
    alc._load_override_config_cached.cache_clear()
    addr = get_trusted_oracle_arbiter("base_sepolia")
    assert addr.startswith("0x")


def test_get_trusted_oracle_arbiter_ethereum_mainnet():
    from market_alkahest.alkahest import get_trusted_oracle_arbiter
    import market_alkahest.alkahest as alc
    alc._load_override_config_cached.cache_clear()
    addr = get_trusted_oracle_arbiter("ethereum_mainnet")
    assert addr.startswith("0x")


def test_get_trusted_oracle_arbiter_ethereum_sepolia():
    from market_alkahest.alkahest import get_trusted_oracle_arbiter
    import market_alkahest.alkahest as alc
    alc._load_override_config_cached.cache_clear()
    addr = get_trusted_oracle_arbiter("ethereum_sepolia")
    # alkahest-py SDK normalises addresses to lowercase hex (alloy
    # ``Address`` Display); compare case-insensitively.
    assert addr.lower() == "0x61dc9c2d757a1c9d0d38a281288d9ef918e77baa"


def test_resolve_alkahest_address_config_base_sepolia_returns_none():
    from market_alkahest.alkahest import resolve_alkahest_address_config
    # Base Sepolia is the alkahest SDK default, so None means "use the SDK's
    # built-in Base Sepolia addresses" rather than "no config available".
    result = resolve_alkahest_address_config("base_sepolia")
    assert result is None


def test_resolve_alkahest_address_config_ethereum_sepolia_returns_config():
    from market_alkahest.alkahest import resolve_alkahest_address_config
    result = resolve_alkahest_address_config("ethereum_sepolia")
    assert result is not None
    assert result.erc20_addresses.eas.lower() == "0xc2679fbd37d54388ce493f1db75320d236e1815e"


def test_escrow_override_accepts_flat_sdk_keys(tmp_path):
    from market_alkahest.alkahest import get_erc20_escrow_obligation_default
    import market_alkahest.alkahest as alc

    alc._load_override_config_cached.cache_clear()
    config_path = tmp_path / "addresses.json"
    config_path.write_text(
        json.dumps(
            {
                "erc20_addresses": {
                    "escrow_obligation_default": (
                        "0xa82ff9afd8f496c3d6ac40e2a0f282e47488cfc9"
                    )
                }
            }
        )
    )

    assert (
        get_erc20_escrow_obligation_default(
            "anvil", config_path=str(config_path)
        )
        == "0xa82ff9afd8f496c3d6ac40e2a0f282e47488cfc9"
    )


def test_address_to_slot_uses_sdk_lookup(monkeypatch):
    import market_alkahest.alkahest as alc

    class _Info:
        escrow_kind = "erc20_escrow_obligation_default"
        field = "escrow_obligation_default"

    class _Config:
        def __init__(self):
            self.calls = []

        def lookup_address(self, address):
            self.calls.append(address)
            return [_Info()]

    cfg = _Config()
    monkeypatch.setattr(alc, "_sdk_addresses_for_chain", lambda chain: cfg)

    assert (
        alc.address_to_slot("base_sepolia", "0xABC")
        == "erc20_escrow_obligation_default"
    )
    assert cfg.calls == ["0xABC"]


def test_address_to_slot_base_sepolia_recipient_arbiter():
    from market_alkahest.alkahest import (
        address_to_slot,
        get_recipient_arbiter,
        _override_reverse_address_map,
    )
    _override_reverse_address_map.cache_clear()
    ra = get_recipient_arbiter("base_sepolia")
    assert address_to_slot("base_sepolia", ra) == "recipient_arbiter"


def test_address_to_slot_base_sepolia_erc20_escrow():
    from market_alkahest.alkahest import (
        address_to_slot,
        get_erc20_escrow_obligation_default,
        get_erc20_escrow_obligation_unconditional,
        _override_reverse_address_map,
    )
    _override_reverse_address_map.cache_clear()
    default = get_erc20_escrow_obligation_default("base_sepolia")
    unconditional = get_erc20_escrow_obligation_unconditional("base_sepolia")
    assert address_to_slot("base_sepolia", default) == "erc20_escrow_obligation_default"
    if int(unconditional, 16) != 0:
        assert address_to_slot("base_sepolia", unconditional) == "erc20_escrow_obligation_unconditional"
    else:
        assert address_to_slot("base_sepolia", unconditional) is None


def test_address_to_slot_base_sepolia_erc721_escrows():
    from market_alkahest.alkahest import (
        address_to_slot,
        get_erc721_escrow_obligation_default,
        get_erc721_escrow_obligation_unconditional,
        _override_reverse_address_map,
    )
    _override_reverse_address_map.cache_clear()
    default = get_erc721_escrow_obligation_default("base_sepolia")
    unconditional = get_erc721_escrow_obligation_unconditional("base_sepolia")
    assert address_to_slot("base_sepolia", default) == "erc721_escrow_obligation_default"
    if int(unconditional, 16) != 0:
        assert address_to_slot("base_sepolia", unconditional) == "erc721_escrow_obligation_unconditional"
    else:
        assert address_to_slot("base_sepolia", unconditional) is None


def test_address_to_slot_base_sepolia_erc1155_escrows():
    from market_alkahest.alkahest import (
        address_to_slot,
        get_erc1155_escrow_obligation_default,
        get_erc1155_escrow_obligation_unconditional,
        _override_reverse_address_map,
    )
    _override_reverse_address_map.cache_clear()
    default = get_erc1155_escrow_obligation_default("base_sepolia")
    unconditional = get_erc1155_escrow_obligation_unconditional("base_sepolia")
    assert address_to_slot("base_sepolia", default) == "erc1155_escrow_obligation_default"
    if int(unconditional, 16) != 0:
        assert address_to_slot("base_sepolia", unconditional) == "erc1155_escrow_obligation_unconditional"
    else:
        assert address_to_slot("base_sepolia", unconditional) is None


def test_address_to_slot_base_sepolia_native_token_escrows():
    from market_alkahest.alkahest import (
        address_to_slot,
        get_native_token_escrow_obligation_default,
        get_native_token_escrow_obligation_unconditional,
        _override_reverse_address_map,
    )
    _override_reverse_address_map.cache_clear()
    default = get_native_token_escrow_obligation_default("base_sepolia")
    unconditional = get_native_token_escrow_obligation_unconditional("base_sepolia")
    assert (
        address_to_slot("base_sepolia", default)
        == "native_token_escrow_obligation_default"
    )
    if int(unconditional, 16) != 0:
        assert (
            address_to_slot("base_sepolia", unconditional)
            == "native_token_escrow_obligation_unconditional"
        )
    else:
        assert address_to_slot("base_sepolia", unconditional) is None


def test_address_to_slot_base_sepolia_token_bundle_escrows():
    from market_alkahest.alkahest import (
        address_to_slot,
        get_token_bundle_escrow_obligation_default,
        get_token_bundle_escrow_obligation_unconditional,
        _override_reverse_address_map,
    )
    _override_reverse_address_map.cache_clear()
    default = get_token_bundle_escrow_obligation_default("base_sepolia")
    unconditional = get_token_bundle_escrow_obligation_unconditional("base_sepolia")
    assert (
        address_to_slot("base_sepolia", default)
        == "token_bundle_escrow_obligation_default"
    )
    if int(unconditional, 16) != 0:
        assert (
            address_to_slot("base_sepolia", unconditional)
            == "token_bundle_escrow_obligation_unconditional"
        )
    else:
        assert address_to_slot("base_sepolia", unconditional) is None


def test_address_to_slot_base_sepolia_attestation_escrows():
    from market_alkahest.alkahest import (
        address_to_slot,
        get_attestation_reference_escrow_obligation_default,
        get_attestation_reference_escrow_obligation_unconditional,
        get_attestation_escrow_obligation_default,
        get_attestation_escrow_obligation_unconditional,
        _override_reverse_address_map,
    )
    _override_reverse_address_map.cache_clear()
    v1_default = get_attestation_escrow_obligation_default("base_sepolia")
    v1_unconditional = get_attestation_escrow_obligation_unconditional("base_sepolia")
    reference_default = get_attestation_reference_escrow_obligation_default("base_sepolia")
    reference_unconditional = get_attestation_reference_escrow_obligation_unconditional("base_sepolia")
    assert (
        address_to_slot("base_sepolia", v1_default)
        == "attestation_escrow_obligation_default"
    )
    assert (
        address_to_slot("base_sepolia", reference_default)
        == "attestation_reference_escrow_obligation_default"
    )
    if int(v1_unconditional, 16) != 0:
        assert (
            address_to_slot("base_sepolia", v1_unconditional)
            == "attestation_escrow_obligation_unconditional"
        )
    else:
        assert address_to_slot("base_sepolia", v1_unconditional) is None
    if int(reference_unconditional, 16) != 0:
        assert (
            address_to_slot("base_sepolia", reference_unconditional)
            == "attestation_reference_escrow_obligation_unconditional"
        )
    else:
        assert address_to_slot("base_sepolia", reference_unconditional) is None


def test_address_to_slot_unknown_address_returns_none():
    from market_alkahest.alkahest import address_to_slot, _override_reverse_address_map
    _override_reverse_address_map.cache_clear()
    unknown = "0x" + "12" * 20
    assert address_to_slot("base_sepolia", unknown) is None


def test_address_to_slot_case_insensitive():
    from market_alkahest.alkahest import (
        address_to_slot,
        get_recipient_arbiter,
        _override_reverse_address_map,
    )
    _override_reverse_address_map.cache_clear()
    ra = get_recipient_arbiter("base_sepolia")
    assert address_to_slot("base_sepolia", ra.upper()) == "recipient_arbiter"
    assert address_to_slot("base_sepolia", ra.lower()) == "recipient_arbiter"


def test_address_to_slot_anvil_override(tmp_path):
    """Override JSON path (anvil) — uses the same enumeration as SDK
    objects but via SimpleNamespace."""
    import json
    from market_alkahest.alkahest import address_to_slot, _override_reverse_address_map
    _override_reverse_address_map.cache_clear()
    override = tmp_path / "anvil.json"
    arbiter_addr = "0x" + "ab" * 20
    escrow_addr = "0x" + "cd" * 20
    override.write_text(json.dumps({
        "arbiters_addresses": {
            "recipient_arbiter": arbiter_addr,
            "eas": "0x" + "00" * 20,  # zero-address slot should be skipped
        },
        "erc20_addresses": {
            "escrow_obligation_default": escrow_addr,
            "escrow_obligation_unconditional": "0x" + "98" * 20,
        },
        "erc721_addresses": {
            "escrow_obligation_default": "0x" + "ef" * 20,
            "escrow_obligation_unconditional": "0x" + "34" * 20,
        },
        "erc1155_addresses": {
            "escrow_obligation_default": "0x" + "56" * 20,
            "escrow_obligation_unconditional": "0x" + "78" * 20,
        },
        "native_token_addresses": {
            "escrow_obligation_default": "0x" + "9a" * 20,
            "escrow_obligation_unconditional": "0x" + "bc" * 20,
        },
        "token_bundle_addresses": {
            "escrow_obligation_default": "0x" + "de" * 20,
            "escrow_obligation_unconditional": "0x" + "f1" * 20,
        },
        "attestation_addresses": {
            "escrow_obligation_default": "0x" + "13" * 20,
            "escrow_obligation_unconditional": "0x" + "24" * 20,
            "attestation_reference_escrow_obligation_default": "0x" + "35" * 20,
            "attestation_reference_escrow_obligation_unconditional": "0x" + "46" * 20,
        },
    }))
    cfg_path = str(override)
    assert address_to_slot("anvil", arbiter_addr, config_path=cfg_path) == "recipient_arbiter"
    assert address_to_slot("anvil", escrow_addr, config_path=cfg_path) == "erc20_escrow_obligation_default"
    assert address_to_slot("anvil", "0x" + "98" * 20, config_path=cfg_path) == "erc20_escrow_obligation_unconditional"
    assert address_to_slot("anvil", "0x" + "ef" * 20, config_path=cfg_path) == "erc721_escrow_obligation_default"
    assert address_to_slot("anvil", "0x" + "34" * 20, config_path=cfg_path) == "erc721_escrow_obligation_unconditional"
    assert address_to_slot("anvil", "0x" + "56" * 20, config_path=cfg_path) == "erc1155_escrow_obligation_default"
    assert address_to_slot("anvil", "0x" + "78" * 20, config_path=cfg_path) == "erc1155_escrow_obligation_unconditional"
    assert address_to_slot("anvil", "0x" + "9a" * 20, config_path=cfg_path) == "native_token_escrow_obligation_default"
    assert address_to_slot("anvil", "0x" + "bc" * 20, config_path=cfg_path) == "native_token_escrow_obligation_unconditional"
    assert address_to_slot("anvil", "0x" + "de" * 20, config_path=cfg_path) == "token_bundle_escrow_obligation_default"
    assert address_to_slot("anvil", "0x" + "f1" * 20, config_path=cfg_path) == "token_bundle_escrow_obligation_unconditional"
    assert address_to_slot("anvil", "0x" + "13" * 20, config_path=cfg_path) == "attestation_escrow_obligation_default"
    assert address_to_slot("anvil", "0x" + "24" * 20, config_path=cfg_path) == "attestation_escrow_obligation_unconditional"
    assert address_to_slot("anvil", "0x" + "35" * 20, config_path=cfg_path) == "attestation_reference_escrow_obligation_default"
    assert address_to_slot("anvil", "0x" + "46" * 20, config_path=cfg_path) == "attestation_reference_escrow_obligation_unconditional"
    assert address_to_slot("anvil", "0x" + "00" * 20, config_path=cfg_path) is None
