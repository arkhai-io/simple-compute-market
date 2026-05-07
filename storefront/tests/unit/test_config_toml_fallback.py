"""Unit tests for the seller agent's TOML config loader.

`load_config()` reads every value from
`$XDG_CONFIG_HOME/arkhai/config.toml` (or its default fallback). This
module verifies the TOML→default precedence by monkey-patching the
module-level `_USER_CFG` dict — no real file is touched, no env vars
are read.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from market_storefront.utils import config as agent_config


def _load_with_toml(doc: dict):
    """Reload the agent config with a fake TOML document."""
    with patch.object(agent_config, "_USER_CFG", doc):
        return agent_config.load_config()


# ---------------------------------------------------------------------------
# Empty TOML — everything falls through to defaults.
# ---------------------------------------------------------------------------


def test_empty_toml_uses_all_defaults():
    cfg = _load_with_toml({"seller": {"agent_id": "test_agent"}})
    assert cfg.agent_id == "test_agent"
    assert cfg.chain_name == "ethereum_sepolia"
    assert cfg.port == 8000
    assert cfg.agent_db_path == "/tmp/agent.db"
    assert cfg.indexer_url == "http://localhost:8080"
    assert cfg.provisioning_service_url == "http://localhost:8085"
    assert cfg.provisioning_timeout == 3600
    # Default is "bisection" (not "") — prevents silent RL failures when torch
    # is unavailable. See ARCHITECTURE.md Known Issues: "Negotiation strategy
    # default was 'rl' (implicit)".
    assert cfg.negotiation_policy_mode == "bisection"


def test_empty_toml_with_no_seller_section_still_loads():
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
# TOML → default precedence
# ---------------------------------------------------------------------------


def test_toml_used_when_set():
    cfg = _load_with_toml({
        "seller": {"agent_id": "test_agent"},
        "chain": {"name": "from_toml"},
    })
    assert cfg.chain_name == "from_toml"


def test_default_when_toml_absent():
    cfg = _load_with_toml({"seller": {"agent_id": "test_agent"}})
    assert cfg.chain_name == "ethereum_sepolia"


def test_empty_string_treated_as_unset():
    """An explicit empty string in TOML should not shadow the default."""
    cfg = _load_with_toml({
        "seller": {"agent_id": "test_agent"},
        "chain": {"name": ""},
    })
    assert cfg.chain_name == "ethereum_sepolia"


# ---------------------------------------------------------------------------
# Type coercion for int / bool fields
# ---------------------------------------------------------------------------


def test_int_coerced_from_toml_int():
    cfg = _load_with_toml({"seller": {"agent_id": "test_agent", "port": 9001}})
    assert cfg.port == 9001


def test_int_bad_toml_value_falls_back_to_default():
    cfg = _load_with_toml({
        "seller": {"agent_id": "test_agent", "port": "definitely-not-an-int"},
    })
    assert cfg.port == 8000


def test_bool_from_toml_native():
    cfg = _load_with_toml({
        "seller": {"agent_id": "test_agent", "auto_register": True},
    })
    assert cfg.auto_register is True


def test_bool_from_toml_string_truthy():
    cfg = _load_with_toml({
        "seller": {"agent_id": "test_agent", "auto_register": "true"},
    })
    assert cfg.auto_register is True


# ---------------------------------------------------------------------------
# Nested sub-tables
# ---------------------------------------------------------------------------


def test_seller_provisioning_subtable():
    cfg = _load_with_toml({
        "seller": {
            "agent_id": "test_agent",
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




def test_seller_negotiation_subtable():
    cfg = _load_with_toml({
        "seller": {
            "agent_id": "test_agent",
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


def test_shared_wallet_section():
    cfg = _load_with_toml({
        "seller": {"agent_id": "test_agent"},
        "wallet": {
            "address": "0xdeadbeef",
            "private_key": "0xabc",
            "ssh_public_key": "ssh-ed25519 AAAA foo@bar",
        },
    })
    assert cfg.agent_wallet_address == "0xdeadbeef"
    assert cfg.agent_priv_key == "0xabc"
    assert cfg.ssh_public_key == "ssh-ed25519 AAAA foo@bar"


def test_shared_chain_section():
    cfg = _load_with_toml({
        "seller": {"agent_id": "test_agent"},
        "chain": {
            "name": "anvil",
            "rpc_url": "http://localhost:8545",
            "chain_id": 31337,
            "alkahest_address_config_path": "/etc/arkhai/alkahest.json",
        },
    })
    assert cfg.chain_name == "anvil"
    assert cfg.chain_rpc_url == "http://localhost:8545"
    assert cfg.chain_id == 31337
    assert cfg.alkahest_address_config_path == "/etc/arkhai/alkahest.json"


def test_chain_id_defaults_to_zero_when_absent():
    """chain.chain_id absent in TOML → CONFIG.chain_id == 0 (unset sentinel)."""
    cfg = _load_with_toml({
        "seller": {"agent_id": "test_agent"},
        "chain": {"name": "anvil", "rpc_url": "http://localhost:8545"},
    })
    assert cfg.chain_id == 0


def test_shared_registry_section():
    cfg = _load_with_toml({
        "seller": {"agent_id": "test_agent"},
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


def test_toml_agent_id_validated():
    """Invalid agent_id in TOML must raise."""
    with pytest.raises(ValueError, match="not a valid identifier"):
        _load_with_toml({"seller": {"agent_id": "has-a-hyphen"}})


def test_toml_agent_id_from_seller_section():
    cfg = _load_with_toml({"seller": {"agent_id": "alice"}})
    assert cfg.agent_id == "alice"


def test_missing_agent_id_warns_and_falls_back_to_default():
    with pytest.warns(UserWarning, match="agent_id not set"):
        cfg = _load_with_toml({})
    assert cfg.agent_id == agent_config.DEFAULT_AGENT_ID


# ---------------------------------------------------------------------------
# _resolve_chain_id
# ---------------------------------------------------------------------------


def test_resolve_chain_id_returns_config_value_when_set():
    """When chain_id is non-zero in config, _resolve_chain_id returns it directly."""
    with patch.object(agent_config, "_USER_CFG", {
        "seller": {"agent_id": "test_agent"},
        "chain": {"chain_id": 31337},
    }):
        agent_config.CONFIG = agent_config.load_config()
        result = agent_config._resolve_chain_id()
    assert result == 31337


def test_resolve_chain_id_calls_rpc_when_config_is_zero(monkeypatch):
    """When chain_id is 0 (unset), _resolve_chain_id falls back to RPC."""
    from unittest.mock import MagicMock, patch as _patch

    mock_w3 = MagicMock()
    mock_w3.eth.chain_id = 42161  # simulated RPC response

    with patch.object(agent_config, "_USER_CFG", {
        "seller": {"agent_id": "test_agent"},
        "chain": {"rpc_url": "http://localhost:8545"},
    }):
        agent_config.CONFIG = agent_config.load_config()
        with _patch.object(agent_config, "Web3", return_value=mock_w3):
            result = agent_config._resolve_chain_id()

    assert result == 42161


def test_resolve_chain_id_raises_when_zero_and_no_rpc():
    """When chain_id is 0 and rpc_url is absent, _resolve_chain_id raises RuntimeError."""
    with patch.object(agent_config, "_USER_CFG", {"seller": {"agent_id": "test_agent"}}):
        agent_config.CONFIG = agent_config.load_config()
        with pytest.raises(RuntimeError, match="chain.chain_id is not set"):
            agent_config._resolve_chain_id()


# ---------------------------------------------------------------------------
# default_resources_csv_path
# ---------------------------------------------------------------------------


def test_default_resources_csv_path_is_none_when_absent():
    """resources_csv_path absent from TOML → default_resources_csv_path is None."""
    cfg = _load_with_toml({"seller": {"agent_id": "test_agent"}})
    assert cfg.default_resources_csv_path is None


def test_default_resources_csv_path_reads_from_toml():
    """resources_csv_path set in TOML → value is propagated."""
    cfg = _load_with_toml({
        "seller": {
            "agent_id": "test_agent",
            "resources_csv_path": "/data/resources.csv",
        },
    })
    assert cfg.default_resources_csv_path == "/data/resources.csv"


def test_default_resources_csv_path_empty_string_becomes_none():
    """Empty string in TOML → treated as unset (None), not as a path."""
    cfg = _load_with_toml({
        "seller": {
            "agent_id": "test_agent",
            "resources_csv_path": "",
        },
    })
    assert cfg.default_resources_csv_path is None
