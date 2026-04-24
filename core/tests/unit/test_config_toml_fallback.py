"""Unit tests for the seller agent's TOML config fallback.

The seller agent's `load_config()` reads every value via env > TOML >
default. This module verifies that hierarchy by monkey-patching the
TOML doc and toggling env vars, then calling load_config() fresh each
time.

The tests deliberately avoid touching a real `~/.config/arkhai/
config.toml` file — everything goes through the module-level `_USER_CFG`
dict.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from core.agent.app.utils import config as agent_config


@pytest.fixture
def seller_env(monkeypatch):
    """Start from a minimal known env — only AGENT_ID set so load_config
    doesn't raise the default-agent-id warning mid-test."""
    # Wipe anything the outer shell might have set.
    for var in [
        "AGENT_ID", "AGENT_NAME", "BASE_URL_OVERRIDE", "PORT",
        "CHAIN_NAME", "CHAIN_RPC_URL", "ALKAHEST_ADDRESS_CONFIG_PATH",
        "AGENT_PRIV_KEY", "AGENT_WALLET_ADDRESS", "SSH_PUBLIC_KEY",
        "AGENT_DB_PATH", "LOG_LEVEL", "LOG_FILE_PATH", "TOKEN_REGISTRY_PATH",
        "INDEXER_URL", "REGISTRY_URL", "IDENTITY_REGISTRY_ADDRESS",
        "ONCHAIN_AGENT_ID", "PROVISIONING_SERVICE_URL",
        "PROVISIONING_TIMEOUT", "PROVISIONING_POLL_INTERVAL",
        "ENABLE_REDIS_INGEST", "REDIS_URL", "REDIS_CHANNELS",
        "ENABLE_REGISTRY_DISCOVERY", "ENABLE_ORDER_RETRY",
        "EVENT_VALIDATION_MODE", "NEGOTIATION_POLICY_MODE",
        "ZEROTIER_NETWORK", "DEFAULT_VM_HOST", "MCP_SERVER_URL",
    ]:
        monkeypatch.delenv(var, raising=False)
    # Give AGENT_ID a value so we don't hit the default-id warning path.
    monkeypatch.setenv("AGENT_ID", "test_agent")
    yield


def _load_with_toml(doc: dict):
    """Reload the agent config with a fake TOML document."""
    with patch.object(agent_config, "_USER_CFG", doc):
        return agent_config.load_config()


# ---------------------------------------------------------------------------
# Empty TOML — everything falls through to defaults or env.
# ---------------------------------------------------------------------------


def test_empty_toml_uses_all_defaults(seller_env):
    cfg = _load_with_toml({})
    assert cfg.chain_name == "ethereum_sepolia"
    assert cfg.port == 8000
    assert cfg.agent_db_path == "/tmp/agent.db"
    assert cfg.indexer_url == "http://localhost:8080"
    assert cfg.provisioning_service_url == "http://localhost:8085"
    assert cfg.provisioning_timeout == 3600
    assert cfg.enable_redis_ingest is False
    assert cfg.negotiation_policy_mode == "bisection"


def test_empty_toml_with_no_seller_section_still_loads(seller_env):
    """The whole [seller] block is optional — a buyer's config.toml
    should not break seller-side load_config() if it somehow ends up
    being read."""
    buyer_only = {
        "wallet": {"address": "0xbuyer", "private_key": "0xabc"},
        "chain": {"name": "base_sepolia", "rpc_url": "https://sepolia.base.org"},
        "registry": {"url": "http://registry.example"},
    }
    cfg = _load_with_toml(buyer_only)
    # Shared keys pick up TOML values.
    assert cfg.chain_name == "base_sepolia"
    assert cfg.chain_rpc_url == "https://sepolia.base.org"
    assert cfg.agent_wallet_address == "0xbuyer"
    assert cfg.agent_priv_key == "0xabc"
    assert cfg.indexer_url == "http://registry.example"
    # Seller-only keys still get defaults.
    assert cfg.port == 8000
    assert cfg.agent_db_path == "/tmp/agent.db"


# ---------------------------------------------------------------------------
# Env > TOML > default precedence
# ---------------------------------------------------------------------------


def test_env_wins_over_toml(seller_env, monkeypatch):
    monkeypatch.setenv("CHAIN_NAME", "from_env")
    cfg = _load_with_toml({"chain": {"name": "from_toml"}})
    assert cfg.chain_name == "from_env"


def test_toml_used_when_env_absent(seller_env):
    cfg = _load_with_toml({"chain": {"name": "from_toml"}})
    assert cfg.chain_name == "from_toml"


def test_default_when_both_absent(seller_env):
    cfg = _load_with_toml({})
    assert cfg.chain_name == "ethereum_sepolia"


def test_empty_env_string_treated_as_unset(seller_env, monkeypatch):
    """CHAIN_NAME= (empty) should not shadow a TOML value."""
    monkeypatch.setenv("CHAIN_NAME", "")
    cfg = _load_with_toml({"chain": {"name": "from_toml"}})
    assert cfg.chain_name == "from_toml"


# ---------------------------------------------------------------------------
# Type coercion for int / bool fields
# ---------------------------------------------------------------------------


def test_int_coerced_from_env_string(seller_env, monkeypatch):
    monkeypatch.setenv("PORT", "9001")
    cfg = _load_with_toml({})
    assert cfg.port == 9001


def test_int_coerced_from_toml_int(seller_env):
    cfg = _load_with_toml({"seller": {"port": 9001}})
    assert cfg.port == 9001


def test_int_bad_env_falls_back_to_default(seller_env, monkeypatch):
    monkeypatch.setenv("PORT", "definitely-not-an-int")
    cfg = _load_with_toml({})
    assert cfg.port == 8000


def test_bool_from_toml_native(seller_env):
    cfg = _load_with_toml({"seller": {"redis": {"enable": True}}})
    assert cfg.enable_redis_ingest is True


def test_bool_from_env_string(seller_env, monkeypatch):
    monkeypatch.setenv("ENABLE_REDIS_INGEST", "true")
    cfg = _load_with_toml({"seller": {"redis": {"enable": False}}})
    assert cfg.enable_redis_ingest is True  # env wins
    monkeypatch.setenv("ENABLE_REDIS_INGEST", "false")
    cfg = _load_with_toml({"seller": {"redis": {"enable": True}}})
    assert cfg.enable_redis_ingest is False


# ---------------------------------------------------------------------------
# Nested sub-tables
# ---------------------------------------------------------------------------


def test_seller_provisioning_subtable(seller_env):
    cfg = _load_with_toml({
        "seller": {
            "provisioning": {
                "service_url": "http://prov.example:8085",
                "timeout": 1800,
                "poll_interval": 5,
            },
        },
    })
    assert cfg.provisioning_service_url == "http://prov.example:8085"
    assert cfg.provisioning_timeout == 1800
    assert cfg.provisioning_poll_interval == 5


def test_seller_redis_subtable(seller_env):
    cfg = _load_with_toml({
        "seller": {
            "redis": {
                "enable": True,
                "url": "redis://cache.example:6379/1",
                "channels": "events:orders,events:trades",
            },
        },
    })
    assert cfg.enable_redis_ingest is True
    assert cfg.redis_url == "redis://cache.example:6379/1"
    assert cfg.redis_channels == "events:orders,events:trades"


def test_seller_negotiation_subtable(seller_env):
    cfg = _load_with_toml({
        "seller": {
            "negotiation": {
                "policy_mode": "rl",
                "seller_model_path": "/models/seller.pt",
                "buyer_model_path": "/models/buyer.pt",
            },
        },
    })
    assert cfg.negotiation_policy_mode == "rl"
    assert cfg.arkhai_negotiator_seller_model_path == "/models/seller.pt"
    assert cfg.arkhai_negotiator_buyer_model_path == "/models/buyer.pt"


# ---------------------------------------------------------------------------
# Shared sections read the same keys a buyer would
# ---------------------------------------------------------------------------


def test_shared_wallet_section(seller_env):
    cfg = _load_with_toml({
        "wallet": {
            "address": "0xdeadbeef",
            "private_key": "0xabc",
            "ssh_public_key": "ssh-ed25519 AAAA foo@bar",
        },
    })
    assert cfg.agent_wallet_address == "0xdeadbeef"
    assert cfg.agent_priv_key == "0xabc"
    assert cfg.ssh_public_key == "ssh-ed25519 AAAA foo@bar"


def test_shared_chain_section(seller_env):
    cfg = _load_with_toml({
        "chain": {
            "name": "anvil",
            "rpc_url": "http://localhost:8545",
            "alkahest_address_config_path": "/etc/arkhai/alkahest.json",
        },
    })
    assert cfg.chain_name == "anvil"
    assert cfg.chain_rpc_url == "http://localhost:8545"
    assert cfg.alkahest_address_config_path == "/etc/arkhai/alkahest.json"


def test_shared_registry_section(seller_env):
    cfg = _load_with_toml({
        "registry": {
            "url": "http://registry.example:8080",
            "identity_registry_address": "0xreg1",
        },
    })
    assert cfg.indexer_url == "http://registry.example:8080"
    assert cfg.identity_registry_address == "0xreg1"


# ---------------------------------------------------------------------------
# agent_id validation still fires
# ---------------------------------------------------------------------------


def test_toml_agent_id_validated(monkeypatch):
    """Invalid agent_id in TOML must raise, same as env."""
    for var in ["AGENT_ID"]:
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ValueError, match="not a valid identifier"):
        _load_with_toml({"seller": {"agent_id": "has-a-hyphen"}})


def test_toml_agent_id_from_seller_section(monkeypatch):
    monkeypatch.delenv("AGENT_ID", raising=False)
    cfg = _load_with_toml({"seller": {"agent_id": "alice"}})
    assert cfg.agent_id == "alice"
