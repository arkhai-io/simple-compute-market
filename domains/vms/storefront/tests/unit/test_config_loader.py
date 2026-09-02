"""Unit tests for the storefront's dynaconf-backed configuration.

Exercises the layered load (``settings.toml`` defaults + XDG overlay files)
and the composite functions (``AGENT_ID``, ``BASE_URL_OVERRIDE``, ``CHAINS``).
No live RPC, no real network — tests build dynaconf instances from in-memory
dicts or temp files.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import tomllib
from dynaconf import Dynaconf
from market_identity import TrustedIdentitySet, create_signer

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
    assert list(s.provisioning.identity.principals) == []
    # Default policy chain ends in "bisection" (not "rl") — prevents
    # silent RL failures when torch is unavailable.
    assert s.negotiation.policies == [
        "has_matching_inventory_guard",
        "escrow_shape_guard",
        "bisection",
    ]
    assert s.pricing.publish_priceless is False
    assert list(s.pricing.settlements) == []
    packaged = tomllib.loads(agent_config._DEFAULTS_FILE.read_text())
    assert "storefront_domains" not in packaged
    # On by default -- the projection path has parity with the local-table
    # path it supersedes. A staged/canary rollout sets this false
    # explicitly rather than relying on a default that no longer matches.
    assert s.capacity.use_site_projection_for_listings is True


def test_structured_settlement_publication_defaults_are_validated() -> None:
    source = Dynaconf(environments=False)
    source.set(
        "settlement",
        {
            "schema_version": 1,
            "priority": ["alkahest.v1"],
            "alkahest": {"enabled": True},
        },
    )
    source.set(
        "pricing.settlements",
        [
            {
                "mechanism": "alkahest.v1",
                "asset": "0x" + "11" * 20,
                "rate": "2.00",
                "per": "hour",
                "mechanism_input": {
                    "chain": "base_sepolia",
                    "escrow_kind": "erc20_escrow_obligation_default",
                },
            }
        ],
    )

    clauses = agent_config.settlement_publication_defaults(source)

    assert len(clauses) == 1
    assert clauses[0].mechanism == "alkahest.v1"
    assert clauses[0].rate == "2.00"
    assert clauses[0].mechanism_input == {
        "chain": "base_sepolia",
        "escrow_kind": "erc20_escrow_obligation_default",
    }


def test_structured_publication_defaults_reject_partial_or_secret_input() -> None:
    source = Dynaconf(environments=False)
    source.set(
        "settlement",
        {
            "schema_version": 1,
            "priority": ["alkahest.v1"],
            "alkahest": {"enabled": True},
        },
    )
    source.set(
        "pricing.settlements",
        [
            {
                "mechanism": "alkahest.v1",
                "asset": "0x" + "11" * 20,
                "rate": "2",
                "per": "hour",
                "mechanism_input": {
                    "chain": "base_sepolia",
                    "escrow_kind": "erc20_escrow_obligation_default",
                    "private_key": "must-not-cross",
                },
            }
        ],
    )

    with pytest.raises(ValueError, match="not public metadata"):
        agent_config.settlement_publication_defaults(source)


def test_use_site_projection_for_listings_can_still_be_disabled_explicitly(
    tmp_path,
    monkeypatch,
):
    """The default flip doesn't remove the ability to opt back out for a
    staged/canary rollout -- an explicit override still wins."""
    monkeypatch.setenv(
        "STOREFRONT_CAPACITY__USE_SITE_PROJECTION_FOR_LISTINGS",
        "false",
    )
    cfg = _build_isolated(tmp_path, [])
    assert cfg.capacity.use_site_projection_for_listings is False


def test_public_identity_defaults_do_not_include_secret_or_wallet_values():
    s = agent_config.settings
    assert s.identity.principal.scheme == ""
    assert s.identity.principal.identifier == ""
    assert s.get("wallet") is None
    assert s.integrations.gemini_api_key == ""


def _identity_source(principal):
    source = Dynaconf(environments=False)
    source.set("identity.principal", principal.model_dump(mode="json"))
    return source


def test_resolve_marketplace_signer_matches_public_ed25519_principal(monkeypatch):
    credential = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE"
    principal = create_signer("ed25519", credential).identity
    monkeypatch.setenv(agent_config.IDENTITY_CREDENTIAL_ENV, credential)

    signer = agent_config.resolve_marketplace_signer(_identity_source(principal))

    assert signer.identity == principal


def test_resolve_marketplace_signer_rejects_mismatched_credential():
    expected = create_signer("ed25519", b"\x01" * 32).identity

    with pytest.raises(ValueError, match="does not match"):
        agent_config.resolve_marketplace_signer(
            _identity_source(expected),
            credential=b"\x02" * 32,
        )


def test_resolve_marketplace_signer_requires_secret_boundary(monkeypatch):
    principal = create_signer("ed25519", b"\x01" * 32).identity
    monkeypatch.delenv(agent_config.IDENTITY_CREDENTIAL_ENV, raising=False)

    with pytest.raises(ValueError, match=agent_config.IDENTITY_CREDENTIAL_ENV):
        agent_config.resolve_marketplace_signer(_identity_source(principal))


def test_public_administrator_binding_is_scheme_tagged():
    administrator = create_signer("ed25519", b"\x05" * 32).identity
    source = Dynaconf(environments=False)
    source.set(
        "identity.administrators",
        {
            "operator": {
                "principals": [administrator.model_dump(mode="json")],
            }
        },
    )

    assert agent_config.get_administrator_configs(source) == {
        "operator": TrustedIdentitySet(identities=(administrator,))
    }


def test_public_provisioning_authorities_and_service_peer_bindings_are_structured():
    current = create_signer("ed25519", b"\x03" * 32).identity
    next_authority = create_signer("ed25519", b"\x06" * 32).identity
    principals = [
        current.model_dump(mode="json"),
        next_authority.model_dump(mode="json"),
    ]
    source = Dynaconf(environments=False)
    source.set("provisioning.identity.principals", principals)
    source.set(
        "identity.service_peers",
        {
            "provisioning_default": {
                "role": "service",
                "site_id": "default",
                "principals": principals,
            }
        },
    )

    trust = TrustedIdentitySet(identities=(current, next_authority))
    assert agent_config.get_provisioning_authorities(source) == trust
    assert agent_config.get_service_peer_configs(source) == {
        "provisioning_default": ("service", "default", trust)
    }


def test_service_peer_binding_rejects_missing_site():
    authority = create_signer("ed25519", b"\x04" * 32).identity
    source = Dynaconf(environments=False)
    source.set(
        "identity.service_peers",
        {
            "provisioning_default": {
                "role": "service",
                "principals": [authority.model_dump(mode="json")],
            }
        },
    )

    with pytest.raises(ValueError, match="site_id"):
        agent_config.get_service_peer_configs(source)


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
    assert cfg.negotiation.policies == [
        "has_matching_inventory_guard",
        "escrow_shape_guard",
        "bisection",
    ]


def test_storefront_domain_overlay_is_the_complete_explicit_selection(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("STOREFRONT_STOREFRONT_DOMAINS")
    overlay = tmp_path / "storefront.toml"
    overlay.write_text(
        """
[[storefront_domains]]
contribution = "vms"
offering_mode = "vm"
domain_identity = "compute.v1"
contract_version = "1.0"

[[storefront_domains]]
contribution = "bare_metal"
offering_mode = "bare_metal"
domain_identity = "bare_metal.v1"
contract_version = "1.0"
"""
    )

    cfg = _build_isolated(tmp_path, [overlay])

    assert [domain.contribution for domain in cfg.storefront_domains] == [
        "vms",
        "bare_metal",
    ]


def test_secrets_overlay_wins_over_storefront_toml(tmp_path):
    base = tmp_path / "storefront.toml"
    base.write_text("""
[integrations]
gemini_api_key = "public-placeholder"
""")
    secret = tmp_path / "storefront.secrets.toml"
    secret.write_text("""
[integrations]
gemini_api_key = "secret-value"
""")
    cfg = _build_isolated(tmp_path, [base, secret])
    assert cfg.integrations.gemini_api_key == "secret-value"


def test_secrets_overlay_completes_public_chain_configuration(tmp_path):
    base = tmp_path / "storefront.toml"
    base.write_text("""
[Chains.base_sepolia]
chain_id = 84532
""")
    secret = tmp_path / "storefront.secrets.toml"
    secret.write_text("""
[chains.base_sepolia]
rpc_url = "https://rpc.example.invalid"
""")

    cfg = _build_isolated(tmp_path, [base, secret])

    assert cfg.chains.base_sepolia.chain_id == 84532
    assert cfg.chains.base_sepolia.rpc_url == "https://rpc.example.invalid"


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
# EVM wallet settings are optional, explicit mechanism inputs. Marketplace
# configuration never derives an address from a private key.
# ---------------------------------------------------------------------------


_ANVIL_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"


def test_build_settings_leaves_wallet_absent_for_hosted_only_profile(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = agent_config._build_settings()
    assert cfg.get("wallet") is None
    assert agent_config.get_evm_wallet_address(cfg) == ""
    assert agent_config.get_evm_wallet_private_key(cfg) == ""


def test_evm_wallet_helpers_return_only_explicit_values(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "arkhai"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "storefront.toml").write_text(f"""
[wallet]
private_key = "{_ANVIL_KEY}"
address = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
""")
    cfg = agent_config._build_settings()
    assert agent_config.get_evm_wallet_address(cfg) == (
        "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    )
    assert agent_config.get_evm_wallet_private_key(cfg) == _ANVIL_KEY


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
