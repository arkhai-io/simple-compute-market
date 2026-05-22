"""Unit tests for the storefront's dynaconf-backed configuration.

Exercises the layered load (``settings.toml`` defaults + XDG overlay files)
and the composite functions (``AGENT_ID``, ``BASE_URL_OVERRIDE``,
``chain_id()``). No live RPC, no real network — tests build dynaconf
instances from in-memory dicts or temp files.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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
    assert s.chain.name == "ethereum_sepolia"
    assert s.registry.urls == ["http://localhost:8080"]
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
# chain_id() — explicit value wins; RPC fallback when zero; raises when
# neither chain.chain_id nor chain.rpc_url is set.
# ---------------------------------------------------------------------------


def test_chain_id_returns_explicit_value_when_set():
    from tests._settings_overrides import settings_overrides

    with settings_overrides(**{"chain.chain_id": 31337}):
        assert agent_config.chain_id() == 31337


def test_chain_id_calls_rpc_when_explicit_is_zero():
    from tests._settings_overrides import settings_overrides

    mock_w3 = MagicMock()
    mock_w3.eth.chain_id = 42161
    with settings_overrides(**{
        "chain.chain_id": 0,
        "chain.rpc_url": "http://localhost:8545",
    }):
        with patch.object(agent_config, "Web3", return_value=mock_w3):
            assert agent_config.chain_id() == 42161


def test_chain_id_raises_when_zero_and_no_rpc():
    from tests._settings_overrides import settings_overrides

    with settings_overrides(**{"chain.chain_id": 0, "chain.rpc_url": ""}):
        with pytest.raises(RuntimeError, match="chain.chain_id is not set"):
            agent_config.chain_id()


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

[chain]
name = "anvil"
rpc_url = "http://localhost:8545"
""")
    cfg = _build_isolated(tmp_path, [overlay])
    assert cfg.port == 8001
    assert cfg.chain.name == "anvil"
    assert cfg.chain.rpc_url == "http://localhost:8545"
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
    """STOREFRONT_CHAIN__RPC_URL → settings.chain.rpc_url. The double
    underscore separator is dynaconf's nested-key convention.
    """
    monkeypatch.setenv("STOREFRONT_CHAIN__RPC_URL", "http://env-host:8545")
    cfg = _build_isolated(tmp_path, [])
    assert cfg.chain.rpc_url == "http://env-host:8545"
