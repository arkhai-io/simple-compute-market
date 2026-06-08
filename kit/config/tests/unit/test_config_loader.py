"""Unit tests for the XDG-aware user config loader.

The loader is what lets `market buy` / `market negotiate` pick up chain
+ wallet + registry defaults from `~/.config/arkhai/buyer.toml`. These
tests cover the resolution path surface: file discovery via XDG,
missing + malformed files falling back to empty, dotted get/set,
write roundtrip, and the precedence hierarchy used by resolve_value().
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from market_config import config_loader


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
    assert config_loader.user_config_file() == tmp_path / "arkhai" / "buyer.toml"


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
# Layered config — buyer.toml + buyer.secrets.toml merge
# ---------------------------------------------------------------------------


def test_layered_load_merges_base_then_secrets(monkeypatch, tmp_path):
    """The Secret overlay (buyer.secrets.toml) merges on top of the
    ConfigMap base (buyer.toml). Disjoint tables compose as siblings;
    same-key conflicts resolve overlay-wins."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "arkhai"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "buyer.toml").write_text("""
[wallet]
ssh_public_key = "ssh-ed25519 AAAA..."

[chain]
name = "anvil"
""")
    (cfg_dir / "buyer.secrets.toml").write_text("""
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
    (cfg_dir / "buyer.toml").write_text('[seller]\nadmin_api_key = "from-base"\n')
    (cfg_dir / "buyer.secrets.toml").write_text('[seller]\nadmin_api_key = "from-secret"\n')
    cfg = config_loader.load_user_config()
    assert cfg["seller"]["admin_api_key"] == "from-secret"


def test_layered_load_secrets_optional(monkeypatch, tmp_path):
    """Missing buyer.secrets.toml is a no-op — base file alone still loads."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "arkhai"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "buyer.toml").write_text('[chain]\nname = "base_sepolia"\n')
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
    (cfg_dir / "buyer.secrets.toml").write_text('[wallet]\nprivate_key = "0xshould-not-leak"\n')
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
        tmp_path / "arkhai" / "buyer.toml",
        tmp_path / "arkhai" / "buyer.secrets.toml",
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
# buyer.toml and so was silently scaffolding into the buyer's file.
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
    and ignores the buyer's `buyer.toml` even when both pairs exist side by side."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "arkhai"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "buyer.toml").write_text('[seller]\nagent_id = "from-buyer-file"\n')
    (cfg_dir / "storefront.toml").write_text('[seller]\nagent_id = "from-base"\n')
    (cfg_dir / "storefront.secrets.toml").write_text('[wallet]\nprivate_key = "0xkey"\n')

    cfg = config_loader.load_storefront_config()

    assert cfg["seller"]["agent_id"] == "from-base"        # not "from-buyer-file"
    assert cfg["wallet"]["private_key"] == "0xkey"          # secrets layer merged


def test_load_storefront_config_returns_empty_when_neither_file_present(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_loader.load_storefront_config() == {}


# ---------------------------------------------------------------------------
# chains_from_config — the [chains.<name>] tables become ChainConfig
# entries keyed by chain name. Each entry inherits per-chain defaults
# (KNOWN_CHAIN_IDS for chain_id, KNOWN_IDENTITY_REGISTRY for identity
# registry) when the table omits them, so the standard chains need
# only ``rpc_url`` set.
# ---------------------------------------------------------------------------


def test_chains_from_config_returns_empty_when_no_chains_table():
    assert config_loader.chains_from_config({}) == {}
    assert config_loader.chains_from_config({"chains": "not a dict"}) == {}


def test_chains_from_config_skips_entries_without_rpc_url():
    cfg = {"chains": {"orphan": {"chain_id": 1}}}
    assert config_loader.chains_from_config(cfg) == {}


def test_chains_from_config_chain_id_explicit_wins():
    cfg = {"chains": {"base_sepolia": {
        "rpc_url": "https://x",
        "chain_id": 999999,
    }}}
    chains = config_loader.chains_from_config(cfg)
    assert chains["base_sepolia"].chain_id == 999999


def test_chains_from_config_chain_id_falls_back_to_known_table():
    cfg = {"chains": {"base_sepolia": {"rpc_url": "https://x"}}}
    chains = config_loader.chains_from_config(cfg)
    assert chains["base_sepolia"].chain_id == config_loader.KNOWN_CHAIN_IDS["base_sepolia"]


def test_chains_from_config_chain_id_zero_when_unknown_and_omitted():
    cfg = {"chains": {"some_random_chain": {"rpc_url": "https://x"}}}
    chains = config_loader.chains_from_config(cfg)
    assert chains["some_random_chain"].chain_id == 0


def test_chains_from_config_alkahest_path_preserved():
    cfg = {"chains": {"anvil": {
        "rpc_url": "http://localhost:8545",
        "alkahest_address_config_path": "/etc/arkhai/alkahest.json",
    }}}
    chains = config_loader.chains_from_config(cfg)
    assert chains["anvil"].alkahest_address_config_path == "/etc/arkhai/alkahest.json"


def test_chains_from_config_name_field_matches_dict_key():
    cfg = {"chains": {
        "base_sepolia": {"rpc_url": "https://x"},
        "anvil": {"rpc_url": "http://localhost:8545"},
    }}
    chains = config_loader.chains_from_config(cfg)
    for key, entry in chains.items():
        assert entry.name == key


# ---------------------------------------------------------------------------
# escrow_templates_from_config — [escrow_templates.<name>] tables become
# EscrowTemplate entries. ``auto:`` escrow addresses route through the
# chain's alkahest address config; literal ``0x...`` addresses pass
# through unchanged.
# ---------------------------------------------------------------------------


def test_escrow_templates_returns_empty_when_no_table():
    assert config_loader.escrow_templates_from_config({}) == {}
    assert config_loader.escrow_templates_from_config(
        {"escrow_templates": "not a dict"}
    ) == {}


def test_escrow_templates_skips_template_with_unknown_chain(capsys):
    cfg = {
        "chains": {"anvil": {"rpc_url": "http://localhost:8545"}},
        "escrow_templates": {
            "ghost": {"chain": "polygon", "escrow_address": "0x" + "ab" * 20},
        },
    }
    out = config_loader.escrow_templates_from_config(cfg)
    assert out == {}
    captured = capsys.readouterr()
    assert "unknown chain 'polygon'" in captured.err


def test_escrow_templates_literal_address_passes_through():
    cfg = {
        "chains": {"anvil": {
            "rpc_url": "http://localhost:8545",
            "alkahest_address_config_path": None,
        }},
        "escrow_templates": {
            "usdc": {
                "chain": "anvil",
                "escrow_address": "0xDEADBEEF" + "00" * 16,
                "literal": {"token": "0xCAFEBABE" + "00" * 16},
                "rates": {
                    "amount": {"field": "amount", "per": "hour"},
                },
            },
        },
    }
    out = config_loader.escrow_templates_from_config(cfg)
    tpl = out["usdc"]
    assert tpl.chain == "anvil"
    assert tpl.escrow_address.lower() == ("0xDEADBEEF" + "00" * 16).lower()
    assert tpl.literal_fields == {"token": "0xCAFEBABE" + "00" * 16}
    assert "amount" in tpl.rate_slots
    assert tpl.rate_slots["amount"].field == "amount"
    assert tpl.rate_slots["amount"].per == "hour"


def test_escrow_templates_skips_when_field_missing(capsys):
    cfg = {
        "chains": {"anvil": {"rpc_url": "http://localhost:8545"}},
        "escrow_templates": {
            "bad": {
                "chain": "anvil",
                "escrow_address": "0x" + "ab" * 20,
                "rates": {"x": {"per": "hour"}},
            },
        },
    }
    out = config_loader.escrow_templates_from_config(cfg)
    assert out == {}
    err = capsys.readouterr().err
    assert "missing 'field'" in err


def test_escrow_templates_preserves_rate_slot_order():
    cfg = {
        "chains": {"anvil": {"rpc_url": "http://localhost:8545"}},
        "escrow_templates": {
            "bundle": {
                "chain": "anvil",
                "escrow_address": "0x" + "ab" * 20,
                "rates": {
                    "usdc":    {"field": "erc20Amounts[0]", "per": "hour"},
                    "credits": {"field": "erc20Amounts[1]", "per": "hour"},
                    "eth":     {"field": "nativeAmount",    "per": "hour"},
                },
            },
        },
    }
    tpl = config_loader.escrow_templates_from_config(cfg)["bundle"]
    assert list(tpl.rate_slots) == ["usdc", "credits", "eth"]


def test_escrow_templates_zero_rate_slots_is_legal():
    """Attestation escrows have no rate-bearing fields."""
    cfg = {
        "chains": {"anvil": {"rpc_url": "http://localhost:8545"}},
        "escrow_templates": {
            "svc": {
                "chain": "anvil",
                "escrow_address": "0x" + "ab" * 20,
                "literal": {"attestationUid": "0x" + "cd" * 32},
            },
        },
    }
    tpl = config_loader.escrow_templates_from_config(cfg)["svc"]
    assert tpl.rate_slots == {}
    assert tpl.literal_fields == {"attestationUid": "0x" + "cd" * 32}


def test_escrow_templates_unknown_auto_key_drops_template(capsys):
    cfg = {
        "chains": {"anvil": {
            "rpc_url": "http://localhost:8545",
            "alkahest_address_config_path": None,
        }},
        "escrow_templates": {
            "weird": {
                "chain": "anvil",
                "escrow_address": "auto:nonsense_kind",
            },
        },
    }
    out = config_loader.escrow_templates_from_config(cfg)
    assert out == {}
    err = capsys.readouterr().err
    assert "unknown auto:" in err


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
    p = tmp_path / "buyer.toml"
    doc = {
        "wallet": {"address": "0xdeadbeef", "private_key": "0xabc"},
        "chain": {"name": "base_sepolia", "rpc_url": "https://sepolia.base.org"},
    }
    config_loader.write_user_config(doc, p)
    reloaded = config_loader.load_user_config(p)
    assert reloaded == doc


def test_write_creates_parent_directory(tmp_path):
    nested = tmp_path / "deep" / "path" / "buyer.toml"
    config_loader.write_user_config({"chain": {"name": "anvil"}}, nested)
    assert nested.exists()
    assert config_loader.load_user_config(nested) == {"chain": {"name": "anvil"}}


def test_write_serializes_bool_int_float():
    from market_config.config_loader import _serialize_toml
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
    p = tmp_path / "buyer.toml"
    doc = {"wallet": {"note": 'has "quotes" and a backslash \\'}}
    config_loader.write_user_config(doc, p)
    assert config_loader.load_user_config(p) == doc


# ---------------------------------------------------------------------------
# Structured shortcuts (wallet_address, etc.)
# ---------------------------------------------------------------------------


def test_wallet_address_prefers_flag(monkeypatch):
    monkeypatch.setenv("AGENT_WALLET_ADDRESS", "0xfromenv")
    cfg = {"wallet": {"address": "0xfromtoml"}}
    assert config_loader.wallet_address(flag="0xfromflag", config=cfg) == "0xfromflag"


def test_wallet_address_falls_back_to_toml(monkeypatch):
    monkeypatch.delenv("AGENT_WALLET_ADDRESS", raising=False)
    cfg = {"wallet": {"address": "0xfromtoml"}}
    assert config_loader.wallet_address(config=cfg) == "0xfromtoml"


# ---------------------------------------------------------------------------
# derive_wallet_address
# ---------------------------------------------------------------------------


# Test vector: deterministic eth_account derivation from a well-known key.
# This is the first key from Anvil's default mnemonic.
_ANVIL_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
_ANVIL_ADDR = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"


def test_derive_wallet_address_known_key():
    assert config_loader.derive_wallet_address(_ANVIL_KEY) == _ANVIL_ADDR


def test_derive_wallet_address_empty_returns_none():
    assert config_loader.derive_wallet_address("") is None
    assert config_loader.derive_wallet_address(None) is None


def test_derive_wallet_address_malformed_returns_none():
    assert config_loader.derive_wallet_address("not a real key") is None
    assert config_loader.derive_wallet_address("0xdeadbeef") is None  # too short


# ---------------------------------------------------------------------------
# query_chain_id_via_rpc + chain_name_for_rpc
# ---------------------------------------------------------------------------


def _fake_urlopen(returned_chain_hex: str):
    """Build a urlopen replacement that always replies with a fixed chain id."""
    import io
    import json

    class _Resp:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self._payload

    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "result": returned_chain_hex}).encode()
    return lambda req, timeout=None: _Resp(payload)


def test_query_chain_id_via_rpc_returns_int(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen", _fake_urlopen("0xaa36a7"),  # 11155111 = sepolia
    )
    assert config_loader.query_chain_id_via_rpc("https://sepolia.example") == 11155111


def test_query_chain_id_via_rpc_handles_ws_url(monkeypatch):
    captured = {}

    def _urlopen(req, timeout=None):
        captured["url"] = req.full_url
        import io
        import json
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "0x14a34"}).encode()

        class _R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return payload

        return _R()

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    cid = config_loader.query_chain_id_via_rpc("ws://localhost:8546")
    assert cid == 84532
    assert captured["url"].startswith("http://"), (
        f"ws:// should be rewritten to http://, got {captured['url']}"
    )


def test_query_chain_id_via_rpc_returns_none_on_error(monkeypatch):
    def _raise(*a, **kw):
        raise OSError("boom")

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    assert config_loader.query_chain_id_via_rpc("https://broken.example") is None


def test_query_chain_id_via_rpc_returns_none_for_empty_url():
    assert config_loader.query_chain_id_via_rpc("") is None
    assert config_loader.query_chain_id_via_rpc(None) is None
    assert config_loader.query_chain_id_via_rpc("   ") is None


def test_chain_name_for_rpc_resolves_known_chain(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen", _fake_urlopen("0xaa36a7"),  # 11155111
    )
    assert config_loader.chain_name_for_rpc("https://sepolia.example") == "ethereum_sepolia"


def test_chain_name_for_rpc_anvil(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen", _fake_urlopen(hex(31337)),
    )
    assert config_loader.chain_name_for_rpc("http://localhost:8545") == "anvil"


def test_chain_name_for_rpc_anvil_legacy_id(monkeypatch):
    """Anvil ships with 1337 as well as 31337 — both map to 'anvil'."""
    monkeypatch.setattr(
        "urllib.request.urlopen", _fake_urlopen(hex(1337)),
    )
    assert config_loader.chain_name_for_rpc("http://localhost:8545") == "anvil"


def test_chain_name_for_rpc_unknown_id_returns_none(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen", _fake_urlopen(hex(999999)),
    )
    assert config_loader.chain_name_for_rpc("https://exotic.example") is None


def test_chain_name_for_rpc_returns_none_on_rpc_failure(monkeypatch):
    def _raise(*a, **kw):
        raise OSError("boom")

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    assert config_loader.chain_name_for_rpc("https://broken.example") is None
