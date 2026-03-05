"""Unit tests for service.clients.alkahest (ported from core tests, using monkeypatch.setenv)."""
import pytest


def test_get_alkahest_network_base_sepolia(monkeypatch):
    from service.clients.alkahest import get_alkahest_network
    assert get_alkahest_network("base_sepolia") == "base_sepolia"


def test_get_alkahest_network_default(monkeypatch):
    from service.clients.alkahest import get_alkahest_network
    assert get_alkahest_network(None) == "base_sepolia"


def test_get_alkahest_network_invalid():
    from service.clients.alkahest import get_alkahest_network
    with pytest.raises(ValueError, match="Unsupported ALKAHEST_NETWORK"):
        get_alkahest_network("unknown_network")


def test_get_trusted_oracle_arbiter_base_sepolia(monkeypatch):
    monkeypatch.setenv("ALKAHEST_NETWORK", "base_sepolia")
    monkeypatch.delenv("ALKAHEST_ADDRESS_CONFIG_PATH", raising=False)
    from service.clients.alkahest import get_trusted_oracle_arbiter
    import importlib, service.clients.alkahest as alc
    # Clear lru_cache
    alc._load_override_config_cached.cache_clear()
    addr = get_trusted_oracle_arbiter()
    assert addr.startswith("0x")


def test_get_trusted_oracle_arbiter_ethereum_mainnet(monkeypatch):
    monkeypatch.setenv("ALKAHEST_NETWORK", "ethereum_mainnet")
    monkeypatch.delenv("ALKAHEST_ADDRESS_CONFIG_PATH", raising=False)
    from service.clients.alkahest import get_trusted_oracle_arbiter
    import service.clients.alkahest as alc
    alc._load_override_config_cached.cache_clear()
    addr = get_trusted_oracle_arbiter()
    assert addr.startswith("0x")


def test_resolve_alkahest_address_config_base_sepolia_returns_none():
    from service.clients.alkahest import resolve_alkahest_address_config
    result = resolve_alkahest_address_config("base_sepolia")
    assert result is None
