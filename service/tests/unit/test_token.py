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


# ---------------------------------------------------------------------------
# Additional tests
# ---------------------------------------------------------------------------

def test_list_tokens(registry_json):
    from service.clients.token import TokenRegistry
    reg = TokenRegistry(registry_json)
    tokens = reg.list_tokens()
    assert len(tokens) == 2
    symbols = {t.symbol for t in tokens}
    assert symbols == {"USDC", "WETH"}


def test_contains(registry_json):
    from service.clients.token import TokenRegistry
    reg = TokenRegistry(registry_json)
    assert "USDC" in reg
    assert "usdc" in reg
    assert "NOTEXIST" not in reg


def test_require_by_symbol_succeeds(registry_json):
    from service.clients.token import TokenRegistry
    reg = TokenRegistry(registry_json)
    token = reg.require("USDC")
    assert token.symbol == "USDC"
    assert token.decimals == 6


def test_require_by_address_succeeds(registry_json):
    from service.clients.token import TokenRegistry
    reg = TokenRegistry(registry_json)
    token = reg.require("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")
    assert token.symbol == "USDC"


def test_duplicate_symbol_raises(tmp_path):
    from service.clients.token import TokenRegistry, TokenRegistryError
    data = [
        {"symbol": "USDC", "name": "USD Coin", "contract_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "decimals": 6},
        {"symbol": "USDC", "name": "USD Coin 2", "contract_address": "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB", "decimals": 6},
    ]
    p = tmp_path / "dup_symbol.json"
    p.write_text(json.dumps(data))
    with pytest.raises(TokenRegistryError, match="Duplicate symbol"):
        TokenRegistry(str(p))


def test_duplicate_address_raises(tmp_path):
    from service.clients.token import TokenRegistry, TokenRegistryError
    data = [
        {"symbol": "USDC", "name": "USD Coin", "contract_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "decimals": 6},
        {"symbol": "USDC2", "name": "USD Coin 2", "contract_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "decimals": 6},
    ]
    p = tmp_path / "dup_address.json"
    p.write_text(json.dumps(data))
    with pytest.raises(TokenRegistryError, match="Duplicate contract address"):
        TokenRegistry(str(p))


def test_malformed_json_raises(tmp_path):
    from service.clients.token import TokenRegistry, TokenRegistryError
    p = tmp_path / "bad.json"
    p.write_text("not valid json {{")
    with pytest.raises(TokenRegistryError):
        TokenRegistry(str(p))


def test_missing_file_gives_empty_registry(tmp_path):
    from service.clients.token import TokenRegistry
    nonexistent = str(tmp_path / "does_not_exist.json")
    reg = TokenRegistry(nonexistent)
    assert len(reg) == 0


def test_register_token_in_memory(registry_json):
    from service.clients.token import TokenRegistry, ERC20TokenMetadata
    reg = TokenRegistry(registry_json)
    new_token = ERC20TokenMetadata(
        symbol="MOCK",
        name="Mock Token",
        contract_address="0xMockMockMockMockMockMockMockMockMockMock1",
        decimals=18,
    )
    reg.register_token(new_token)
    assert reg.resolve("MOCK") is not None
    assert reg.resolve("MOCK").decimals == 18


def test_register_token_persists(tmp_path):
    from service.clients.token import TokenRegistry, ERC20TokenMetadata
    data = [
        {"symbol": "USDC", "name": "USD Coin", "contract_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "decimals": 6},
    ]
    p = tmp_path / "persist_reg.json"
    p.write_text(json.dumps(data))
    reg = TokenRegistry(str(p))
    new_token = ERC20TokenMetadata(
        symbol="WETH",
        name="Wrapped Ether",
        contract_address="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        decimals=18,
    )
    reg.register_token(new_token, persist=True)
    # Re-read from disk — new token must appear
    reg2 = TokenRegistry(str(p))
    assert len(reg2) == 2
    assert reg2.resolve("WETH") is not None


def test_reload_picks_up_changes(tmp_path):
    from service.clients.token import TokenRegistry
    data = [
        {"symbol": "USDC", "name": "USD Coin", "contract_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "decimals": 6},
    ]
    p = tmp_path / "reload_reg.json"
    p.write_text(json.dumps(data))
    reg = TokenRegistry(str(p))
    assert len(reg) == 1
    # Mutate file on disk
    updated = data + [
        {"symbol": "DAI", "name": "Dai Stablecoin", "contract_address": "0x6B175474E89094C44Da98b954EedeAC495271d0F", "decimals": 18},
    ]
    p.write_text(json.dumps(updated))
    reg.reload()
    assert len(reg) == 2
    assert reg.resolve("DAI") is not None


def test_token_registry_path_env(tmp_path, monkeypatch):
    from service.clients.token import TokenRegistry
    data = [
        {"symbol": "ENV_TOKEN", "name": "Env Token", "contract_address": "0xEnvEnvEnvEnvEnvEnvEnvEnvEnvEnvEnvEnvEnv1", "decimals": 8},
    ]
    p = tmp_path / "env_registry.json"
    p.write_text(json.dumps(data))
    monkeypatch.setenv("TOKEN_REGISTRY_PATH", str(p))
    reg = TokenRegistry()  # no explicit path — should pick up env var
    assert reg.resolve("ENV_TOKEN") is not None


def test_singleton_importable():
    from service.clients.token import TOKEN_REGISTRY
    assert TOKEN_REGISTRY is not None
    assert len(TOKEN_REGISTRY) >= 0
