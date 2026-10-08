"""Building the storefront runtime from its process environment.

The server builds its runtime only this way, so the app tests, which construct a
runtime directly, cannot see a defect in it. Every value below is a development
fixture and must never be used on a public network.
"""

from __future__ import annotations

import json

import pytest
from market_identity import Eip191Signer

from arkhai_bare_metal_storefront import runtime as runtime_module
from arkhai_bare_metal_storefront.runtime import build_runtime_from_environment
from arkhai_bare_metal_storefront.settlement_composition import (
    BareMetalStorefrontSettlementComposition,
)

SELLER = Eip191Signer(bytes.fromhex("11" * 32))
ADMIN = Eip191Signer(bytes.fromhex("33" * 32))
SITE = Eip191Signer(bytes.fromhex("44" * 32))

CONTACT_SECTION = {
    "enabled": True,
    "contact_payload": {"email": "seller@bare-metal-test.invalid"},
    "profiles": {"default": {"channel": "email", "terms": "Test introduction."}},
    "retention_seconds": 60,
    "retention_sweep_interval_seconds": 3600,
}


def _alkahest_section(*, enabled: bool) -> dict:
    return {
        "enabled": enabled,
        "address_config_path": "/app/alkahest_anvil_addresses.json",
        "oracle_gated": False,
        "trusted_oracle_addresses": [],
        "interruptible": False,
        "interruptible_oracle_addresses": [],
    }


def _settlement(*, alkahest: bool | None) -> str:
    """A contact-exchange root, with an Alkahest section when ``alkahest`` is
    not None, enabled or disabled as it says."""
    root: dict = {"schema_version": 1, "priority": ["contact-exchange.v1"]}
    root["contact"] = CONTACT_SECTION
    if alkahest is not None:
        root["alkahest"] = _alkahest_section(enabled=alkahest)
        if alkahest:
            root["priority"] = ["alkahest.v1", "contact-exchange.v1"]
    return json.dumps(root)


ALKAHEST_INPUTS = {
    "BARE_METAL_STOREFRONT_EVM_ADDRESS": "0x" + "33" * 20,
    "BARE_METAL_STOREFRONT_CHAINS": json.dumps(
        {"anvil": {"rpc_url": "http://anvil:8545"}}
    ),
    "BARE_METAL_STOREFRONT_EVM_PRIVATE_KEY": "0x" + "55" * 32,
}


@pytest.fixture
def environment(monkeypatch, tmp_path):
    values = {
        "BARE_METAL_STOREFRONT_IDENTITY_SCHEME": str(SELLER.identity.scheme.value),
        "BARE_METAL_STOREFRONT_IDENTITY_IDENTIFIER": SELLER.identity.identifier,
        "ARKHAI_IDENTITY_CREDENTIAL": "0x" + "11" * 32,
        "BARE_METAL_STOREFRONT_ADMIN_IDENTITIES": json.dumps(
            [ADMIN.identity.model_dump(mode="json")]
        ),
        "BARE_METAL_STOREFRONT_PUBLIC_URL": "http://seller:8000",
        "BARE_METAL_STOREFRONT_SETTLEMENT": _settlement(alkahest=None),
        "BARE_METAL_STOREFRONT_SITES": json.dumps(
            [
                {
                    "site_id": "site-a",
                    "authority_principal": SITE.identity.model_dump(mode="json"),
                    "authority_url": "http://site-a",
                }
            ]
        ),
        "BARE_METAL_STOREFRONT_DB_PATH": str(tmp_path / "storefront.db"),
    }
    for name in ALKAHEST_INPUTS:
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


@pytest.fixture
def chain_clients(monkeypatch):
    """Stand in for the Alkahest chain clients, the external chain boundary."""
    built = {"anvil": object()}
    monkeypatch.setattr(
        runtime_module, "build_alkahest_clients", lambda policy, **_kwargs: built
    )
    return built


def test_the_runtime_takes_its_principal_from_the_configured_identity(environment):
    runtime = build_runtime_from_environment()

    assert runtime.seller_principal == SELLER.identity
    assert runtime.marketplace_signer.identity == SELLER.identity
    assert runtime.pool_override_service() is not None


def test_a_credential_that_does_not_own_the_identity_is_refused(environment, monkeypatch):
    monkeypatch.setenv("ARKHAI_IDENTITY_CREDENTIAL", "0x" + "22" * 32)

    with pytest.raises(RuntimeError, match="identity"):
        build_runtime_from_environment()


def test_the_seller_chain_defaults_when_none_is_configured(environment):
    runtime = build_runtime_from_environment()

    assert runtime.negotiation_policies is None


def test_the_seller_chain_is_read_from_the_environment(environment, monkeypatch):
    monkeypatch.setenv(
        "BARE_METAL_STOREFRONT_NEGOTIATION_POLICIES",
        json.dumps(["escrow_shape_guard", "bisection"]),
    )

    runtime = build_runtime_from_environment()

    assert runtime.negotiation_policies == ["escrow_shape_guard", "bisection"]


def test_a_malformed_seller_chain_is_refused(environment, monkeypatch):
    monkeypatch.setenv("BARE_METAL_STOREFRONT_NEGOTIATION_POLICIES", "[escrow_shape_guard")

    with pytest.raises(RuntimeError, match="NEGOTIATION_POLICIES"):
        build_runtime_from_environment()


def test_an_unknown_seller_policy_is_refused_at_composition(environment, monkeypatch):
    monkeypatch.setenv(
        "BARE_METAL_STOREFRONT_NEGOTIATION_POLICIES", json.dumps(["no_such_policy"])
    )

    with pytest.raises(KeyError, match="no_such_policy"):
        build_runtime_from_environment()


def test_a_storefront_without_a_settlement_configuration_is_refused(
    environment, monkeypatch
):
    monkeypatch.delenv("BARE_METAL_STOREFRONT_SETTLEMENT")

    with pytest.raises(RuntimeError, match="BARE_METAL_STOREFRONT_SETTLEMENT"):
        build_runtime_from_environment()


@pytest.mark.parametrize("enabled", [True, False])
def test_a_configured_alkahest_section_composes_its_client_and_worker(
    environment, monkeypatch, chain_clients, enabled
):
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", _settlement(alkahest=enabled))
    for name, value in ALKAHEST_INPUTS.items():
        monkeypatch.setenv(name, value)

    runtime = build_runtime_from_environment()

    assert "alkahest.v1" in runtime.settlement_clients
    assert runtime.settlement_composition.resources["clients"] is chain_clients
    assert runtime.settlement_worker is not None
    assert "settlement-servicing" in runtime.loops.step_routes()


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("missing", sorted(ALKAHEST_INPUTS))
def test_a_configured_alkahest_section_requires_every_input(
    environment, monkeypatch, chain_clients, enabled, missing
):
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", _settlement(alkahest=enabled))
    for name, value in ALKAHEST_INPUTS.items():
        if name != missing:
            monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match=missing):
        build_runtime_from_environment()


@pytest.mark.parametrize("stale", sorted(ALKAHEST_INPUTS))
def test_alkahest_inputs_without_a_section_are_refused(
    environment, monkeypatch, stale
):
    monkeypatch.setenv(stale, ALKAHEST_INPUTS[stale])

    with pytest.raises(RuntimeError, match="no Alkahest section"):
        build_runtime_from_environment()


def test_a_disabled_section_is_still_configured():
    # The runtime builds a mechanism's servicing (the hosted lifecycle, the
    # Alkahest resources) for every configured section, enabled or not.
    root = json.loads(_settlement(alkahest=False))
    root["stripe"] = {"enabled": False}

    composition = BareMetalStorefrontSettlementComposition.from_raw_config(root)

    assert composition.enabled_mechanisms == ("contact-exchange.v1",)
    assert composition.configures("alkahest.v1")
    assert composition.configures("fiat.stripe.v1")
    assert composition.configures("contact-exchange.v1")


def test_a_root_without_a_stripe_section_composes_no_hosted_lifecycle(environment):
    runtime = build_runtime_from_environment()

    assert runtime.hosted_domain_callbacks is None
    assert runtime.settlement_worker is not None
