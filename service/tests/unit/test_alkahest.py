"""Unit tests for service.clients.alkahest.

The helpers take ``chain_name`` + optional ``config_path`` arguments —
no env reads. Tests pass values explicitly.
"""
import pytest


def test_get_alkahest_network_base_sepolia():
    from service.clients.alkahest import get_alkahest_network
    assert get_alkahest_network("base_sepolia") == "base_sepolia"


def test_get_alkahest_network_default():
    from service.clients.alkahest import get_alkahest_network
    assert get_alkahest_network(None) == "base_sepolia"


def test_get_alkahest_network_invalid():
    from service.clients.alkahest import get_alkahest_network
    with pytest.raises(ValueError, match="Unsupported"):
        get_alkahest_network("unknown_network")


def test_get_trusted_oracle_arbiter_base_sepolia():
    from service.clients.alkahest import get_trusted_oracle_arbiter
    import service.clients.alkahest as alc
    alc._load_override_config_cached.cache_clear()
    addr = get_trusted_oracle_arbiter("base_sepolia")
    assert addr.startswith("0x")


def test_get_trusted_oracle_arbiter_ethereum_mainnet():
    from service.clients.alkahest import get_trusted_oracle_arbiter
    import service.clients.alkahest as alc
    alc._load_override_config_cached.cache_clear()
    addr = get_trusted_oracle_arbiter("ethereum_mainnet")
    assert addr.startswith("0x")


def test_get_trusted_oracle_arbiter_ethereum_sepolia():
    from service.clients.alkahest import get_trusted_oracle_arbiter
    import service.clients.alkahest as alc
    alc._load_override_config_cached.cache_clear()
    addr = get_trusted_oracle_arbiter("ethereum_sepolia")
    # alkahest-py SDK normalises addresses to lowercase hex (alloy
    # ``Address`` Display); compare case-insensitively.
    assert addr.lower() == "0x3b2a812e3eb3b729d40d866da16c2bb2b6cdd2f2"


def test_resolve_alkahest_address_config_base_sepolia_returns_none():
    from service.clients.alkahest import resolve_alkahest_address_config
    # Base Sepolia is the alkahest SDK default, so None means "use the SDK's
    # built-in Base Sepolia addresses" rather than "no config available".
    result = resolve_alkahest_address_config("base_sepolia")
    assert result is None


def test_resolve_alkahest_address_config_ethereum_sepolia_returns_config():
    from service.clients.alkahest import resolve_alkahest_address_config
    result = resolve_alkahest_address_config("ethereum_sepolia")
    assert result is not None
    assert result.erc20_addresses.eas.lower() == "0xc2679fbd37d54388ce493f1db75320d236e1815e"


def test_address_to_slot_base_sepolia_recipient_arbiter():
    from service.clients.alkahest import (
        address_to_slot,
        get_recipient_arbiter,
        _reverse_address_map,
    )
    _reverse_address_map.cache_clear()
    ra = get_recipient_arbiter("base_sepolia")
    assert address_to_slot("base_sepolia", ra) == "recipient_arbiter"


def test_address_to_slot_base_sepolia_erc20_escrow():
    from service.clients.alkahest import (
        address_to_slot,
        get_erc20_escrow_obligation_nontierable,
        get_erc20_escrow_obligation_tierable,
        _reverse_address_map,
    )
    _reverse_address_map.cache_clear()
    non_tierable = get_erc20_escrow_obligation_nontierable("base_sepolia")
    tierable = get_erc20_escrow_obligation_tierable("base_sepolia")
    assert address_to_slot("base_sepolia", non_tierable) == "erc20_escrow_obligation_nontierable"
    if int(tierable, 16) != 0:
        assert address_to_slot("base_sepolia", tierable) == "erc20_escrow_obligation_tierable"
    else:
        assert address_to_slot("base_sepolia", tierable) is None


def test_address_to_slot_base_sepolia_erc721_escrows():
    from service.clients.alkahest import (
        address_to_slot,
        get_erc721_escrow_obligation_nontierable,
        get_erc721_escrow_obligation_tierable,
        _reverse_address_map,
    )
    _reverse_address_map.cache_clear()
    non_tierable = get_erc721_escrow_obligation_nontierable("base_sepolia")
    tierable = get_erc721_escrow_obligation_tierable("base_sepolia")
    assert address_to_slot("base_sepolia", non_tierable) == "erc721_escrow_obligation_nontierable"
    if int(tierable, 16) != 0:
        assert address_to_slot("base_sepolia", tierable) == "erc721_escrow_obligation_tierable"
    else:
        assert address_to_slot("base_sepolia", tierable) is None


def test_address_to_slot_base_sepolia_erc1155_escrows():
    from service.clients.alkahest import (
        address_to_slot,
        get_erc1155_escrow_obligation_nontierable,
        get_erc1155_escrow_obligation_tierable,
        _reverse_address_map,
    )
    _reverse_address_map.cache_clear()
    non_tierable = get_erc1155_escrow_obligation_nontierable("base_sepolia")
    tierable = get_erc1155_escrow_obligation_tierable("base_sepolia")
    assert address_to_slot("base_sepolia", non_tierable) == "erc1155_escrow_obligation_nontierable"
    if int(tierable, 16) != 0:
        assert address_to_slot("base_sepolia", tierable) == "erc1155_escrow_obligation_tierable"
    else:
        assert address_to_slot("base_sepolia", tierable) is None


def test_address_to_slot_base_sepolia_native_token_escrows():
    from service.clients.alkahest import (
        address_to_slot,
        get_native_token_escrow_obligation_nontierable,
        get_native_token_escrow_obligation_tierable,
        _reverse_address_map,
    )
    _reverse_address_map.cache_clear()
    non_tierable = get_native_token_escrow_obligation_nontierable("base_sepolia")
    tierable = get_native_token_escrow_obligation_tierable("base_sepolia")
    assert (
        address_to_slot("base_sepolia", non_tierable)
        == "native_token_escrow_obligation_nontierable"
    )
    if int(tierable, 16) != 0:
        assert (
            address_to_slot("base_sepolia", tierable)
            == "native_token_escrow_obligation_tierable"
        )
    else:
        assert address_to_slot("base_sepolia", tierable) is None


def test_address_to_slot_base_sepolia_token_bundle_escrows():
    from service.clients.alkahest import (
        address_to_slot,
        get_token_bundle_escrow_obligation_nontierable,
        get_token_bundle_escrow_obligation_tierable,
        _reverse_address_map,
    )
    _reverse_address_map.cache_clear()
    non_tierable = get_token_bundle_escrow_obligation_nontierable("base_sepolia")
    tierable = get_token_bundle_escrow_obligation_tierable("base_sepolia")
    assert (
        address_to_slot("base_sepolia", non_tierable)
        == "token_bundle_escrow_obligation_nontierable"
    )
    if int(tierable, 16) != 0:
        assert (
            address_to_slot("base_sepolia", tierable)
            == "token_bundle_escrow_obligation_tierable"
        )
    else:
        assert address_to_slot("base_sepolia", tierable) is None


def test_address_to_slot_base_sepolia_attestation_escrows():
    from service.clients.alkahest import (
        address_to_slot,
        get_attestation_escrow_obligation_2_nontierable,
        get_attestation_escrow_obligation_2_tierable,
        get_attestation_escrow_obligation_nontierable,
        get_attestation_escrow_obligation_tierable,
        _reverse_address_map,
    )
    _reverse_address_map.cache_clear()
    v1_non_tierable = get_attestation_escrow_obligation_nontierable("base_sepolia")
    v1_tierable = get_attestation_escrow_obligation_tierable("base_sepolia")
    v2_non_tierable = get_attestation_escrow_obligation_2_nontierable("base_sepolia")
    v2_tierable = get_attestation_escrow_obligation_2_tierable("base_sepolia")
    assert (
        address_to_slot("base_sepolia", v1_non_tierable)
        == "attestation_escrow_obligation_nontierable"
    )
    assert (
        address_to_slot("base_sepolia", v2_non_tierable)
        == "attestation_escrow_obligation_2_nontierable"
    )
    if int(v1_tierable, 16) != 0:
        assert (
            address_to_slot("base_sepolia", v1_tierable)
            == "attestation_escrow_obligation_tierable"
        )
    else:
        assert address_to_slot("base_sepolia", v1_tierable) is None
    if int(v2_tierable, 16) != 0:
        assert (
            address_to_slot("base_sepolia", v2_tierable)
            == "attestation_escrow_obligation_2_tierable"
        )
    else:
        assert address_to_slot("base_sepolia", v2_tierable) is None


def test_address_to_slot_unknown_address_returns_none():
    from service.clients.alkahest import address_to_slot, _reverse_address_map
    _reverse_address_map.cache_clear()
    unknown = "0x" + "12" * 20
    assert address_to_slot("base_sepolia", unknown) is None


def test_address_to_slot_case_insensitive():
    from service.clients.alkahest import (
        address_to_slot,
        get_recipient_arbiter,
        _reverse_address_map,
    )
    _reverse_address_map.cache_clear()
    ra = get_recipient_arbiter("base_sepolia")
    assert address_to_slot("base_sepolia", ra.upper()) == "recipient_arbiter"
    assert address_to_slot("base_sepolia", ra.lower()) == "recipient_arbiter"


def test_address_to_slot_anvil_override(tmp_path):
    """Override JSON path (anvil) — uses the same enumeration as SDK
    objects but via SimpleNamespace."""
    import json
    from service.clients.alkahest import address_to_slot, _reverse_address_map
    _reverse_address_map.cache_clear()
    override = tmp_path / "anvil.json"
    arbiter_addr = "0x" + "ab" * 20
    escrow_addr = "0x" + "cd" * 20
    override.write_text(json.dumps({
        "arbiters_addresses": {
            "recipient_arbiter": arbiter_addr,
            "eas": "0x" + "00" * 20,  # zero-address slot should be skipped
        },
        "erc20_addresses": {
            "escrow_obligation_nontierable": escrow_addr,
            "escrow_obligation_tierable": "0x" + "98" * 20,
        },
        "erc721_addresses": {
            "escrow_obligation_nontierable": "0x" + "ef" * 20,
            "escrow_obligation_tierable": "0x" + "34" * 20,
        },
        "erc1155_addresses": {
            "escrow_obligation_nontierable": "0x" + "56" * 20,
            "escrow_obligation_tierable": "0x" + "78" * 20,
        },
        "native_token_addresses": {
            "escrow_obligation_nontierable": "0x" + "9a" * 20,
            "escrow_obligation_tierable": "0x" + "bc" * 20,
        },
        "token_bundle_addresses": {
            "escrow_obligation_nontierable": "0x" + "de" * 20,
            "escrow_obligation_tierable": "0x" + "f1" * 20,
        },
        "attestation_addresses": {
            "escrow_obligation_nontierable": "0x" + "13" * 20,
            "escrow_obligation_tierable": "0x" + "24" * 20,
            "escrow_obligation_2_nontierable": "0x" + "35" * 20,
            "escrow_obligation_2_tierable": "0x" + "46" * 20,
        },
    }))
    cfg_path = str(override)
    assert address_to_slot("anvil", arbiter_addr, config_path=cfg_path) == "recipient_arbiter"
    assert address_to_slot("anvil", escrow_addr, config_path=cfg_path) == "erc20_escrow_obligation_nontierable"
    assert address_to_slot("anvil", "0x" + "98" * 20, config_path=cfg_path) == "erc20_escrow_obligation_tierable"
    assert address_to_slot("anvil", "0x" + "ef" * 20, config_path=cfg_path) == "erc721_escrow_obligation_nontierable"
    assert address_to_slot("anvil", "0x" + "34" * 20, config_path=cfg_path) == "erc721_escrow_obligation_tierable"
    assert address_to_slot("anvil", "0x" + "56" * 20, config_path=cfg_path) == "erc1155_escrow_obligation_nontierable"
    assert address_to_slot("anvil", "0x" + "78" * 20, config_path=cfg_path) == "erc1155_escrow_obligation_tierable"
    assert address_to_slot("anvil", "0x" + "9a" * 20, config_path=cfg_path) == "native_token_escrow_obligation_nontierable"
    assert address_to_slot("anvil", "0x" + "bc" * 20, config_path=cfg_path) == "native_token_escrow_obligation_tierable"
    assert address_to_slot("anvil", "0x" + "de" * 20, config_path=cfg_path) == "token_bundle_escrow_obligation_nontierable"
    assert address_to_slot("anvil", "0x" + "f1" * 20, config_path=cfg_path) == "token_bundle_escrow_obligation_tierable"
    assert address_to_slot("anvil", "0x" + "13" * 20, config_path=cfg_path) == "attestation_escrow_obligation_nontierable"
    assert address_to_slot("anvil", "0x" + "24" * 20, config_path=cfg_path) == "attestation_escrow_obligation_tierable"
    assert address_to_slot("anvil", "0x" + "35" * 20, config_path=cfg_path) == "attestation_escrow_obligation_2_nontierable"
    assert address_to_slot("anvil", "0x" + "46" * 20, config_path=cfg_path) == "attestation_escrow_obligation_2_tierable"
    assert address_to_slot("anvil", "0x" + "00" * 20, config_path=cfg_path) is None
