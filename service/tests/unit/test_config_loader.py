"""Unit tests for the XDG-aware user config loader.

The loader is what lets `market buy` / `market negotiate` pick up chain
+ wallet + registry defaults from `~/.config/arkhai/config.toml`. These
tests cover the resolution path surface: file discovery via XDG,
missing + malformed files falling back to empty, dotted get/set,
write roundtrip, and the precedence hierarchy used by resolve_value().
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from service import config_loader


# ---------------------------------------------------------------------------
# user_config_dir / user_config_file
# ---------------------------------------------------------------------------


def test_user_config_dir_honors_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_loader.user_config_dir() == tmp_path / "arkhai"


def test_user_config_dir_defaults_to_dot_config(monkeypatch, tmp_path):
    """Absent XDG_CONFIG_HOME, fall back to ~/.config/arkhai."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert config_loader.user_config_dir() == tmp_path / ".config" / "arkhai"


def test_user_config_file_nests_under_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_loader.user_config_file() == tmp_path / "arkhai" / "config.toml"


# ---------------------------------------------------------------------------
# load_user_config — missing / malformed / happy
# ---------------------------------------------------------------------------


def test_load_returns_empty_when_file_absent(tmp_path):
    assert config_loader.load_user_config(tmp_path / "nonexistent.toml") == {}


def test_load_parses_valid_toml(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("""
[chain]
name = "base_sepolia"
rpc_url = "https://sepolia.base.org"

[wallet]
address = "0xdeadbeef"
""")
    cfg = config_loader.load_user_config(p)
    assert cfg["chain"]["name"] == "base_sepolia"
    assert cfg["wallet"]["address"] == "0xdeadbeef"


def test_load_returns_empty_on_malformed_toml(tmp_path, capsys):
    """Corrupted file shouldn't break the CLI — fall back to empty + warn on stderr."""
    p = tmp_path / "c.toml"
    p.write_text("this is = not = valid toml [[")
    cfg = config_loader.load_user_config(p)
    assert cfg == {}
    captured = capsys.readouterr()
    assert "could not read" in captured.err


# ---------------------------------------------------------------------------
# get_dotted / set_dotted
# ---------------------------------------------------------------------------


def test_get_dotted_walks_nested_dict():
    doc = {"chain": {"name": "anvil", "nested": {"deep": 42}}}
    assert config_loader.get_dotted(doc, "chain.name") == "anvil"
    assert config_loader.get_dotted(doc, "chain.nested.deep") == 42


def test_get_dotted_returns_none_on_missing():
    assert config_loader.get_dotted({"chain": {}}, "chain.name") is None
    assert config_loader.get_dotted({}, "any") is None
    # Intermediate non-dict → None, not an AttributeError.
    assert config_loader.get_dotted({"chain": "anvil"}, "chain.name") is None


def test_set_dotted_creates_intermediate_tables():
    doc: dict = {}
    config_loader.set_dotted(doc, "chain.rpc_url", "https://foo")
    assert doc == {"chain": {"rpc_url": "https://foo"}}


def test_set_dotted_preserves_siblings():
    doc = {"chain": {"name": "anvil"}}
    config_loader.set_dotted(doc, "chain.rpc_url", "https://foo")
    assert doc["chain"]["name"] == "anvil"
    assert doc["chain"]["rpc_url"] == "https://foo"


def test_set_dotted_overwrites_non_dict_intermediate():
    """If a middle slot is a scalar, the setter replaces it with a table."""
    doc = {"chain": "anvil"}
    config_loader.set_dotted(doc, "chain.name", "base_sepolia")
    assert doc == {"chain": {"name": "base_sepolia"}}


# ---------------------------------------------------------------------------
# resolve_value — the precedence hierarchy
# ---------------------------------------------------------------------------


def test_flag_wins_over_everything(monkeypatch):
    monkeypatch.setenv("CHAIN_NAME", "from_env")
    cfg = {"chain": {"name": "from_toml"}}
    got = config_loader.resolve_value(
        flag="from_flag",
        env_name="CHAIN_NAME",
        toml_path="chain.name",
        default="from_default",
        config=cfg,
    )
    assert got == "from_flag"


def test_env_wins_over_toml_and_default(monkeypatch):
    monkeypatch.setenv("CHAIN_NAME", "from_env")
    cfg = {"chain": {"name": "from_toml"}}
    got = config_loader.resolve_value(
        env_name="CHAIN_NAME",
        toml_path="chain.name",
        default="from_default",
        config=cfg,
    )
    assert got == "from_env"


def test_toml_used_when_no_flag_or_env(monkeypatch):
    monkeypatch.delenv("CHAIN_NAME", raising=False)
    cfg = {"chain": {"name": "from_toml"}}
    got = config_loader.resolve_value(
        env_name="CHAIN_NAME",
        toml_path="chain.name",
        default="from_default",
        config=cfg,
    )
    assert got == "from_toml"


def test_default_as_last_resort(monkeypatch):
    monkeypatch.delenv("CHAIN_NAME", raising=False)
    got = config_loader.resolve_value(
        env_name="CHAIN_NAME",
        toml_path="chain.name",
        default="from_default",
        config={},
    )
    assert got == "from_default"


def test_empty_env_var_treated_as_unset(monkeypatch):
    """Setting CHAIN_NAME= (empty) should not shadow the toml."""
    monkeypatch.setenv("CHAIN_NAME", "")
    cfg = {"chain": {"name": "from_toml"}}
    got = config_loader.resolve_value(
        env_name="CHAIN_NAME",
        toml_path="chain.name",
        default="from_default",
        config=cfg,
    )
    assert got == "from_toml"


def test_coerce_applied_to_env_string(monkeypatch):
    monkeypatch.setenv("SOME_PORT", "8081")
    got = config_loader.resolve_value(
        env_name="SOME_PORT", default=8000, coerce=int, config={},
    )
    assert got == 8081


# ---------------------------------------------------------------------------
# Write roundtrip
# ---------------------------------------------------------------------------


def test_write_then_read_roundtrips(tmp_path):
    p = tmp_path / "config.toml"
    doc = {
        "wallet": {"address": "0xdeadbeef", "private_key": "0xabc"},
        "chain": {"name": "base_sepolia", "rpc_url": "https://sepolia.base.org"},
    }
    config_loader.write_user_config(doc, p)
    reloaded = config_loader.load_user_config(p)
    assert reloaded == doc


def test_write_creates_parent_directory(tmp_path):
    nested = tmp_path / "deep" / "path" / "config.toml"
    config_loader.write_user_config({"chain": {"name": "anvil"}}, nested)
    assert nested.exists()
    assert config_loader.load_user_config(nested) == {"chain": {"name": "anvil"}}


def test_write_serializes_bool_int_float():
    from service.config_loader import _serialize_toml
    text = _serialize_toml({
        "seller": {"port": 8000, "enabled": True, "ratio": 0.5},
        "nested": {"inner": {"flag": False}},
    })
    # Loading it back should preserve all the types.
    import tomllib
    loaded = tomllib.loads(text)
    assert loaded["seller"]["port"] == 8000
    assert loaded["seller"]["enabled"] is True
    assert loaded["seller"]["ratio"] == pytest.approx(0.5)
    assert loaded["nested"]["inner"]["flag"] is False


def test_write_escapes_quotes_and_backslashes(tmp_path):
    p = tmp_path / "config.toml"
    doc = {"wallet": {"note": 'has "quotes" and a backslash \\'}}
    config_loader.write_user_config(doc, p)
    assert config_loader.load_user_config(p) == doc


# ---------------------------------------------------------------------------
# Structured shortcuts (wallet_address, chain_name, etc.)
# ---------------------------------------------------------------------------


def test_wallet_address_prefers_flag(monkeypatch):
    monkeypatch.setenv("AGENT_WALLET_ADDRESS", "0xfromenv")
    cfg = {"wallet": {"address": "0xfromtoml"}}
    assert config_loader.wallet_address(flag="0xfromflag", config=cfg) == "0xfromflag"


def test_wallet_address_falls_back_to_toml(monkeypatch):
    monkeypatch.delenv("AGENT_WALLET_ADDRESS", raising=False)
    cfg = {"wallet": {"address": "0xfromtoml"}}
    assert config_loader.wallet_address(config=cfg) == "0xfromtoml"


def test_chain_name_default_when_everything_missing(monkeypatch):
    monkeypatch.delenv("CHAIN_NAME", raising=False)
    assert config_loader.chain_name(config={}) == "ethereum_sepolia"
