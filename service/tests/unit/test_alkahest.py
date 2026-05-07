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
