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
# Layered config — config.toml + config.secrets.toml merge
# ---------------------------------------------------------------------------


def test_layered_load_merges_base_then_secrets(monkeypatch, tmp_path):
    """The Secret overlay (config.secrets.toml) merges on top of the
    ConfigMap base (config.toml). Disjoint tables compose as siblings;
    same-key conflicts resolve overlay-wins."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "arkhai"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.toml").write_text("""
[wallet]
ssh_public_key = "ssh-ed25519 AAAA..."

[chain]
name = "anvil"
""")
    (cfg_dir / "config.secrets.toml").write_text("""
[wallet]
private_key = "0xkey"
address = "0xaddr"
""")
    cfg = config_loader.load_user_config()
    # Sibling keys in the [wallet] table merged from both files.
    assert cfg["wallet"]["ssh_public_key"] == "ssh-ed25519 AAAA..."
    assert cfg["wallet"]["private_key"] == "0xkey"
    assert cfg["wallet"]["address"] == "0xaddr"
    # Disjoint table from the base survives.
    assert cfg["chain"]["name"] == "anvil"


def test_layered_load_secrets_wins_on_conflict(monkeypatch, tmp_path):
    """If both files set the same scalar key, the secrets file overrides."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "arkhai"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.toml").write_text('[seller]\nadmin_api_key = "from-base"\n')
    (cfg_dir / "config.secrets.toml").write_text('[seller]\nadmin_api_key = "from-secret"\n')
    cfg = config_loader.load_user_config()
    assert cfg["seller"]["admin_api_key"] == "from-secret"


def test_layered_load_secrets_optional(monkeypatch, tmp_path):
    """Missing config.secrets.toml is a no-op — base file alone still loads."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "arkhai"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.toml").write_text('[chain]\nname = "base_sepolia"\n')
    cfg = config_loader.load_user_config()
    assert cfg["chain"]["name"] == "base_sepolia"


def test_layered_load_both_missing_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # Don't create the dir or files.
    assert config_loader.load_user_config() == {}


def test_cli_path_override_skips_secrets_layer(monkeypatch, tmp_path):
    """``set_user_config_path`` collapses the stack to a single file —
    secrets-layer auto-discovery does not apply when the override is set."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "arkhai"
    cfg_dir.mkdir(parents=True)
    # An ambient secrets file in the XDG dir that should be IGNORED.
    (cfg_dir / "config.secrets.toml").write_text('[wallet]\nprivate_key = "0xshould-not-leak"\n')
    explicit = tmp_path / "only.toml"
    explicit.write_text('[chain]\nname = "anvil"\n')
    config_loader.set_user_config_path(explicit)
    try:
        cfg = config_loader.load_user_config()
        assert cfg == {"chain": {"name": "anvil"}}
        assert "wallet" not in cfg
    finally:
        config_loader.set_user_config_path(None)


def test_user_config_files_lists_base_and_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    files = config_loader.user_config_files()
    assert files == [
        tmp_path / "arkhai" / "config.toml",
        tmp_path / "arkhai" / "config.secrets.toml",
    ]


def test_user_config_files_collapses_to_override(monkeypatch, tmp_path):
    explicit = tmp_path / "elsewhere.toml"
    config_loader.set_user_config_path(explicit)
    try:
        assert config_loader.user_config_files() == [explicit]
    finally:
        config_loader.set_user_config_path(None)


# ---------------------------------------------------------------------------
# storefront_config_file / load_storefront_config — distinct from the
# buyer's user_config_file so the two roles' state on one host stays
# separate. `market-storefront config init-user` previously wrote to
# config.toml and so was silently scaffolding into the buyer's file.
# ---------------------------------------------------------------------------


def test_storefront_config_file_nests_under_arkhai_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_loader.storefront_config_file() == tmp_path / "arkhai" / "storefront.toml"


def test_storefront_config_file_is_distinct_from_buyer(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_loader.storefront_config_file() != config_loader.user_config_file()


def test_storefront_config_file_honors_override(tmp_path):
    explicit = tmp_path / "explicit.toml"
    config_loader.set_user_config_path(explicit)
    try:
        assert config_loader.storefront_config_file() == explicit
    finally:
        config_loader.set_user_config_path(None)


def test_load_storefront_config_walks_storefront_files(monkeypatch, tmp_path):
    """`load_storefront_config` reads `storefront.toml` + `storefront.secrets.toml`
    and ignores the buyer's `config.toml` even when both pairs exist side by side."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "arkhai"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.toml").write_text('[seller]\nagent_id = "from-buyer-file"\n')
    (cfg_dir / "storefront.toml").write_text('[seller]\nagent_id = "from-base"\n')
    (cfg_dir / "storefront.secrets.toml").write_text('[wallet]\nprivate_key = "0xkey"\n')

    cfg = config_loader.load_storefront_config()

    assert cfg["seller"]["agent_id"] == "from-base"        # not "from-buyer-file"
    assert cfg["wallet"]["private_key"] == "0xkey"          # secrets layer merged


def test_load_storefront_config_returns_empty_when_neither_file_present(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_loader.load_storefront_config() == {}


def test_deep_merge_recurses_into_nested_tables():
    base = {
        "seller": {
            "agent_id": "bob",
            "provisioning": {"mode": "mock", "poll_interval": 30},
        }
    }
    overlay = {
        "seller": {
            "admin_api_key": "secret",
            "provisioning": {"poll_interval": 60},
        }
    }
    merged = config_loader._deep_merge(base, overlay)
    assert merged["seller"]["agent_id"] == "bob"
    assert merged["seller"]["admin_api_key"] == "secret"
    assert merged["seller"]["provisioning"]["mode"] == "mock"  # preserved
    assert merged["seller"]["provisioning"]["poll_interval"] == 60  # overridden


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
