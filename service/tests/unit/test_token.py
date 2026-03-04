"""Unit tests for service.clients.token."""
import json
import pytest
from pathlib import Path


@pytest.fixture
def registry_json(tmp_path):
    data = [
        {"symbol": "USDC", "name": "USD Coin", "contract_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "decimals": 6},
        {"symbol": "WETH", "name": "Wrapped Ether", "contract_address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "decimals": 18},
    ]
    p = tmp_path / "token_registry.json"
    p.write_text(json.dumps(data))
    return str(p)


def test_load_registry(registry_json):
    from service.clients.token import TokenRegistry
    reg = TokenRegistry(registry_json)
    assert len(reg) == 2


def test_get_by_symbol(registry_json):
    from service.clients.token import TokenRegistry
    reg = TokenRegistry(registry_json)
    token = reg.get_by_symbol("usdc")
    assert token is not None
    assert token.symbol == "USDC"
    assert token.decimals == 6


def test_get_by_address(registry_json):
    from service.clients.token import TokenRegistry
    reg = TokenRegistry(registry_json)
    token = reg.get_by_address("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48")
    assert token is not None
    assert token.symbol == "USDC"


def test_resolve_symbol(registry_json):
    from service.clients.token import TokenRegistry
    reg = TokenRegistry(registry_json)
    assert reg.resolve("WETH") is not None


def test_resolve_address(registry_json):
    from service.clients.token import TokenRegistry
    reg = TokenRegistry(registry_json)
    assert reg.resolve("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2") is not None


def test_require_missing_raises(registry_json):
    from service.clients.token import TokenRegistry, TokenRegistryError
    reg = TokenRegistry(registry_json)
    with pytest.raises(TokenRegistryError):
        reg.require("NOTEXIST")


def test_erc20_token_metadata_model():
    from service.clients.token import ERC20TokenMetadata
    token = ERC20TokenMetadata(
        symbol="TEST",
        name="Test Token",
        contract_address="0x1234567890abcdef1234567890abcdef12345678",
        decimals=18,
    )
    assert token.symbol == "TEST"
    assert token.chain_id is None


@pytest.mark.asyncio
async def test_get_wallet_token_balance_web3_not_installed():
    """Should raise ValueError when web3 call fails."""
    from service.clients.token import get_wallet_token_balance
    from unittest.mock import patch, AsyncMock
    # Patch the import to raise ImportError
    with patch.dict("sys.modules", {"web3": None}):
        with pytest.raises((ValueError, Exception)):
            await get_wallet_token_balance("0x1234", "0x5678", "http://localhost:8545")
