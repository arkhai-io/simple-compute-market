"""Unit tests for market_alkahest.token (chain-resolved cache)."""
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Point the cache at a per-test directory so tests don't pollute each
    other or the user's real cache."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    import market_alkahest.token as token_mod
    token_mod._MEMORY_CACHE.clear()
    yield tmp_path
    token_mod._MEMORY_CACHE.clear()


def _fake_web3(symbol: str, decimals: int, name: str | None = None):
    """Build a web3.Web3 stand-in whose contract().functions return our values."""
    contract = MagicMock()
    contract.functions.symbol.return_value.call.return_value = symbol
    contract.functions.decimals.return_value.call.return_value = decimals
    if name is None:
        contract.functions.name.return_value.call.side_effect = Exception("no name")
    else:
        contract.functions.name.return_value.call.return_value = name
    w3 = MagicMock()
    w3.eth.contract.return_value = contract
    return w3


def test_erc20_token_metadata_model():
    from market_alkahest.token import ERC20TokenMetadata
    token = ERC20TokenMetadata(
        symbol="TEST",
        name="Test Token",
        contract_address="0x1234567890abcdef1234567890abcdef12345678",
        decimals=18,
    )
    assert token.symbol == "TEST"
    assert token.chain_id is None


def test_resolve_token_rejects_non_address():
    from market_alkahest.token import resolve_token, TokenResolutionError
    with pytest.raises(TokenResolutionError):
        resolve_token("USDC", rpc_url="http://x", chain_id=1)
    with pytest.raises(TokenResolutionError):
        resolve_token("0xabc", rpc_url="http://x", chain_id=1)


def test_resolve_token_calls_rpc_on_miss_and_caches(isolated_cache):
    from market_alkahest.token import resolve_token
    address = "0xA0b86991c6218b36c1D19D4A2e9eb0Ce3606eB48"
    fake = _fake_web3("USDC", 6, "USD Coin")
    with patch("web3.Web3", return_value=fake), \
         patch("web3.Web3.to_checksum_address", return_value=address):
        meta = resolve_token(address, rpc_url="http://rpc", chain_id=1)
    assert meta.symbol == "USDC"
    assert meta.decimals == 6
    assert meta.name == "USD Coin"
    assert meta.chain_id == 1

    # Second call hits the in-memory cache; RPC must not be touched.
    with patch("web3.Web3", side_effect=AssertionError("must not RPC again")):
        meta2 = resolve_token(address, rpc_url="http://rpc", chain_id=1)
    assert meta2.contract_address == meta.contract_address

    # And the disk file exists with that entry.
    cache_file = isolated_cache / "arkhai" / "tokens" / "1.json"
    assert cache_file.exists()
    payload = json.loads(cache_file.read_text())
    assert address.lower() in payload


def test_resolve_token_normalizes_websocket_rpc_url():
    from market_alkahest.token import resolve_token
    address = "0xA0b86991c6218b36c1D19D4A2e9eb0Ce3606eB48"
    fake = _fake_web3("USDC", 6, "USD Coin")
    with patch("web3.providers.HTTPProvider", side_effect=lambda url: f"provider:{url}") as provider, \
         patch("web3.Web3", return_value=fake) as web3_cls, \
         patch("web3.Web3.to_checksum_address", return_value=address):
        resolve_token(address, rpc_url="ws://anvil:8545", chain_id=31337)

    provider.assert_called_once_with("http://anvil:8545")
    web3_cls.assert_called_once_with("provider:http://anvil:8545")


def test_resolve_token_refresh_bypasses_cache():
    from market_alkahest.token import resolve_token
    address = "0xA0b86991c6218b36c1D19D4A2e9eb0Ce3606eB48"
    fake1 = _fake_web3("USDC", 6)
    with patch("web3.Web3", return_value=fake1), \
         patch("web3.Web3.to_checksum_address", return_value=address):
        resolve_token(address, rpc_url="http://rpc", chain_id=1)

    fake2 = _fake_web3("USDC2", 8)
    with patch("web3.Web3", return_value=fake2), \
         patch("web3.Web3.to_checksum_address", return_value=address):
        meta = resolve_token(address, rpc_url="http://rpc", chain_id=1, refresh=True)
    assert meta.symbol == "USDC2"
    assert meta.decimals == 8


def test_disk_cache_survives_process_restart(isolated_cache):
    from market_alkahest.token import resolve_token, resolve_token_cached
    import market_alkahest.token as token_mod
    address = "0xA0b86991c6218b36c1D19D4A2e9eb0Ce3606eB48"
    fake = _fake_web3("USDC", 6)
    with patch("web3.Web3", return_value=fake), \
         patch("web3.Web3.to_checksum_address", return_value=address):
        resolve_token(address, rpc_url="http://rpc", chain_id=42)

    # Simulate fresh process: drop the in-memory cache.
    token_mod._MEMORY_CACHE.clear()

    hit = resolve_token_cached(address, chain_id=42)
    assert hit is not None
    assert hit.symbol == "USDC"


def test_resolve_token_cached_returns_none_when_uncached():
    from market_alkahest.token import resolve_token_cached
    assert resolve_token_cached("0x" + "ab" * 20, chain_id=1) is None
    assert resolve_token_cached("not-an-address") is None
    assert resolve_token_cached("") is None


def test_resolve_token_cached_searches_across_chains_when_no_chain_id():
    """When chain_id is omitted, the cache is searched across every chain
    loaded so far. Documented as "ambiguous if same address resolved on
    multiple chains" — first hit wins."""
    from market_alkahest.token import resolve_token, resolve_token_cached
    address = "0xA0b86991c6218b36c1D19D4A2e9eb0Ce3606eB48"
    fake = _fake_web3("USDC", 6)
    with patch("web3.Web3", return_value=fake), \
         patch("web3.Web3.to_checksum_address", return_value=address):
        resolve_token(address, rpc_url="http://rpc", chain_id=1)
    hit = resolve_token_cached(address)
    assert hit is not None


def test_render_token_with_cache_hit():
    from market_alkahest.token import resolve_token, render_token
    address = "0xA0b86991c6218b36c1D19D4A2e9eb0Ce3606eB48"
    fake = _fake_web3("USDC", 6)
    with patch("web3.Web3", return_value=fake), \
         patch("web3.Web3.to_checksum_address", return_value=address):
        resolve_token(address, rpc_url="http://rpc", chain_id=1)
    assert render_token(address) == f"USDC ({address})"


def test_render_token_falls_through_to_address_only():
    from market_alkahest.token import render_token
    address = "0xDeAdBeEfDeAdBeEfDeAdBeEfDeAdBeEfDeAdBeEf"
    assert render_token(address) == address


def test_render_token_handles_metadata_dict():
    from market_alkahest.token import render_token
    payload = {"symbol": "FOO", "contract_address": "0xfoo"}
    assert render_token(payload) == "FOO (0xfoo)"


def test_render_token_handles_none():
    from market_alkahest.token import render_token
    assert render_token(None) == "-"
    assert render_token("") == "-"


def test_resolve_token_by_symbol_in_finds_match():
    """Stub resolve_token directly; the goal is to test the symbol-match
    filter, not the on-chain plumbing (which is covered separately)."""
    from market_alkahest import token as token_mod
    addr_a = "0xA0b86991c6218b36c1D19D4A2e9eb0Ce3606eB48"
    addr_b = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    canned = {
        addr_a.lower(): token_mod.ERC20TokenMetadata(
            symbol="USDC", contract_address=addr_a, decimals=6, chain_id=1,
        ),
        addr_b.lower(): token_mod.ERC20TokenMetadata(
            symbol="WETH", contract_address=addr_b, decimals=18, chain_id=1,
        ),
    }
    with patch.object(
        token_mod, "resolve_token",
        lambda address, *, rpc_url, chain_id, refresh=False: canned[address.lower()],
    ):
        match = token_mod.resolve_token_by_symbol_in(
            "WETH", [addr_a, addr_b], rpc_url="http://rpc", chain_id=1,
        )
    assert match is not None
    assert match.symbol == "WETH"
    assert match.contract_address == addr_b


def test_resolve_token_by_symbol_in_returns_none_when_no_match():
    from market_alkahest import token as token_mod
    addr_a = "0xA0b86991c6218b36c1D19D4A2e9eb0Ce3606eB48"
    canned = token_mod.ERC20TokenMetadata(
        symbol="USDC", contract_address=addr_a, decimals=6, chain_id=1,
    )
    with patch.object(
        token_mod, "resolve_token",
        lambda address, *, rpc_url, chain_id, refresh=False: canned,
    ):
        match = token_mod.resolve_token_by_symbol_in(
            "WETH", [addr_a], rpc_url="http://rpc", chain_id=1,
        )
    assert match is None


@pytest.mark.asyncio
async def test_get_wallet_token_balance_web3_not_installed():
    """Falls through when web3 import fails."""
    from market_alkahest.token import get_wallet_token_balance
    with patch.dict("sys.modules", {"web3": None}):
        with pytest.raises((ValueError, Exception)):
            await get_wallet_token_balance("0x1234", "0x5678", "http://localhost:8545")
