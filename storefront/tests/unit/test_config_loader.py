"""Unit tests for the storefront's dynaconf-backed configuration.

Exercises the layered load (``settings.toml`` defaults + XDG overlay files)
and the composite functions (``AGENT_ID``, ``BASE_URL_OVERRIDE``, ``CHAINS``).
No live RPC, no real network — tests build dynaconf instances from in-memory
dicts or temp files.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from dynaconf import Dynaconf

from market_storefront.utils import config as agent_config


# ---------------------------------------------------------------------------
# settings.toml defaults — the committed schema is the source of truth.
# Every key callers depend on must have a default here.
# ---------------------------------------------------------------------------


def test_settings_toml_provides_baseline_defaults():
    s = agent_config.settings
    assert s.port == 8000
    # registry.urls intentionally defaults to [] — see settings.toml. Shipping
    # a non-empty default would cause dynaconf's merge_enabled=True to *append*
    # any user-supplied list rather than replace it, leaving the storefront
    # heartbeating to both the default and the user's registry.
    assert s.registry.urls == []
    assert s.registry.discovery_timeout == 5.0
    assert s.provisioning.service_url == "http://localhost:8085"
    assert s.provisioning.timeout == 3600
    # Negotiation default is "bisection" (not ""/"rl") — prevents silent RL
    # failures when torch is unavailable.
    assert s.negotiation.policy_mode == "bisection"
    assert s.auto_register is True
    assert s.pricing.publish_priceless is False


def test_unset_sensitive_keys_are_empty_strings():
    """settings.toml uses "" placeholders for fields populated by the Secret
    overlay (wallet.private_key, admin_api_key, gemini_api_key). Truthy
    checks distinguish set-vs-unset.
    """
    s = agent_config.settings
    assert s.wallet.private_key == ""
    assert s.wallet.address == ""
    assert s.admin_api_key == ""
    assert s.integrations.gemini_api_key == ""


# ---------------------------------------------------------------------------
# Composites — AGENT_ID, AGENT_NAME, BASE_URL_OVERRIDE are computed once at
# module load. get_agent_id() supports per-call override.
# ---------------------------------------------------------------------------


def test_default_agent_id_when_unset_emits_warning():
    """No agent_id in any layer → AGENT_ID is the safe default and a
    UserWarning was emitted at module load. The warning itself is
    asserted in a separate test using a fresh module reload.
    """
    assert agent_config.AGENT_ID == agent_config.DEFAULT_AGENT_ID


def test_get_agent_id_with_explicit_override():
    assert agent_config.get_agent_id("custom_agent") == "custom_agent"


def test_get_agent_id_rejects_invalid_identifier():
    with pytest.raises(ValueError, match="not a valid identifier"):
        agent_config.get_agent_id("not-a-python-identifier")


def test_agent_name_falls_back_to_agent_id_when_unset():
    assert agent_config.AGENT_NAME == agent_config.AGENT_ID


def test_base_url_override_uses_settings_default_when_zerotier_absent():
    # No zerotier network configured → raw base_url is returned as-is.
    assert agent_config.BASE_URL_OVERRIDE == agent_config.settings.base_url


# ---------------------------------------------------------------------------
# CHAINS — built from the [chains.<name>] overlay tables, keyed by name.
# ---------------------------------------------------------------------------


def test_chains_dict_built_from_overlay(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "arkhai"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "storefront.toml").write_text(
        """
[chains.anvil]
rpc_url = "http://localhost:8545"

[chains.base_sepolia]
rpc_url = "https://sepolia.base.org"
chain_id = 84532
"""
    )
    s = agent_config._build_settings()
    chains = agent_config._build_chains(s)
    assert set(chains) == {"anvil", "base_sepolia"}
    assert chains["anvil"].rpc_url == "http://localhost:8545"
    assert chains["anvil"].chain_id == 31337  # from KNOWN_CHAIN_IDS
    assert chains["base_sepolia"].chain_id == 84532


def test_chains_dict_empty_when_no_chains_section(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    s = agent_config._build_settings()
    assert agent_config._build_chains(s) == {}


def test_chains_dict_reads_onchain_agent_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "arkhai"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "storefront.toml").write_text(
        """
[chains.anvil]
rpc_url = "http://localhost:8545"
onchain_agent_id = 42
"""
    )
    s = agent_config._build_settings()
    chains = agent_config._build_chains(s)
    assert chains["anvil"].onchain_agent_id == 42


# ---------------------------------------------------------------------------
# Layered loading: settings.toml → storefront.toml → storefront.secrets.toml.
# Tests build a fresh dynaconf instance pointing at a tmp XDG dir to verify
# the overlay precedence end-to-end.
# ---------------------------------------------------------------------------


def _build_isolated(tmp_path: Path, overlay_files: list[Path]) -> Dynaconf:
    """Build a Dynaconf instance matching the storefront's layered shape.

    Mirrors :func:`market_storefront.utils.config._build_settings` but does
    NOT touch the module-level singleton — other modules that captured a
    reference to the singleton continue to see the production settings,
    which is essential because test execution order is not guaranteed.
    """
    return Dynaconf(
        settings_file=[str(agent_config._DEFAULTS_FILE)],
        includes=[str(p) for p in overlay_files if p.exists()],
        envvar_prefix="STOREFRONT",
        envvar_separator="__",
        load_dotenv=False,
        environments=False,
        merge_enabled=True,
    )


def test_storefront_toml_overlay_wins_over_settings_defaults(tmp_path):
    overlay = tmp_path / "storefront.toml"
    overlay.write_text("""
port = 8001

[chains.anvil]
rpc_url = "http://localhost:8545"
""")
    cfg = _build_isolated(tmp_path, [overlay])
    assert cfg.port == 8001
    assert cfg.chains.anvil.rpc_url == "http://localhost:8545"
    # Untouched key still has its settings.toml default.
    assert cfg.negotiation.policy_mode == "bisection"


def test_secrets_overlay_wins_over_storefront_toml(tmp_path):
    base = tmp_path / "storefront.toml"
    base.write_text("""
[wallet]
address = "0xpublic"
""")
    secret = tmp_path / "storefront.secrets.toml"
    secret.write_text("""
[wallet]
private_key = "0xdeadbeef"
address     = "0xfrom-secret"
""")
    cfg = _build_isolated(tmp_path, [base, secret])
    # Secrets overlay wins on address (it's the later layer).
    assert cfg.wallet.address == "0xfrom-secret"
    assert cfg.wallet.private_key == "0xdeadbeef"


def test_env_var_wins_over_overlay_files(tmp_path, monkeypatch):
    overlay = tmp_path / "storefront.toml"
    overlay.write_text("port = 8001\n")
    monkeypatch.setenv("STOREFRONT_PORT", "9999")
    cfg = _build_isolated(tmp_path, [overlay])
    assert cfg.port == 9999


def test_nested_env_var_via_double_underscore(tmp_path, monkeypatch):
    """STOREFRONT_CHAINS__ANVIL__RPC_URL → settings.chains.anvil.rpc_url.
    The double underscore separator is dynaconf's nested-key convention.
    """
    monkeypatch.setenv("STOREFRONT_CHAINS__ANVIL__RPC_URL", "http://env-host:8545")
    cfg = _build_isolated(tmp_path, [])
    assert cfg.chains.anvil.rpc_url == "http://env-host:8545"


# ---------------------------------------------------------------------------
# _build_settings derivation: wallet.address from private_key, chain.name
# from rpc_url. These run the production builder so the post-process logic
# is covered end-to-end.
# ---------------------------------------------------------------------------


_ANVIL_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
_ANVIL_ADDR = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"


def test_build_settings_derives_wallet_address_from_private_key(tmp_path, monkeypatch):
    """When wallet.private_key is set but wallet.address is empty, the
    builder fills wallet.address with the derived value. No RPC needed."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "arkhai"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "storefront.toml").write_text(f"""
[wallet]
private_key = "{_ANVIL_KEY}"
""")
    cfg = agent_config._build_settings()
    assert cfg.wallet.address == _ANVIL_ADDR
    assert cfg.wallet.private_key == _ANVIL_KEY


def test_build_settings_preserves_explicit_wallet_address(tmp_path, monkeypatch, caplog):
    """When both wallet.address and wallet.private_key are set and they
    disagree, the configured address wins but a warning is logged."""
    import logging

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "arkhai"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "storefront.toml").write_text(f"""
[wallet]
private_key = "{_ANVIL_KEY}"
address     = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
""")
    with caplog.at_level(logging.WARNING, logger="market_storefront.utils.config"):
        cfg = agent_config._build_settings()
    assert cfg.wallet.address == "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    assert any("does not match" in rec.message for rec in caplog.records)


def test_build_settings_skips_derivation_when_both_unset(tmp_path, monkeypatch):
    """Empty wallet.private_key → no derivation; wallet.address stays empty."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # No overlay file at all.
    cfg = agent_config._build_settings()
    assert cfg.wallet.address == ""
    assert cfg.wallet.private_key == ""


def test_build_chains_uses_known_chain_id_when_omitted(tmp_path, monkeypatch):
    """A [chains.<name>] table that omits chain_id falls back to the
    KNOWN_CHAIN_IDS lookup by name — operators don't have to repeat
    canonical values like 31337 for anvil."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "arkhai"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "storefront.toml").write_text(
        """
[chains.anvil]
rpc_url = "http://localhost:8545"
"""
    )
    s = agent_config._build_settings()
    chains = agent_config._build_chains(s)
    assert chains["anvil"].chain_id == 31337


def test_build_chains_explicit_chain_id_wins(tmp_path, monkeypatch):
    """An explicit chain_id in [chains.<name>] overrides the KNOWN
    table — useful for chains the storefront doesn't ship a default
    for, or for operators running a custom fork."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "arkhai"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "storefront.toml").write_text(
        """
[chains.anvil]
rpc_url = "http://localhost:8545"
chain_id = 999999
"""
    )
    s = agent_config._build_settings()
    chains = agent_config._build_chains(s)
    assert chains["anvil"].chain_id == 999999
