"""Settlement compositions for tests, built the way the server builds them.

The storefront has no settlement without a composition, so a test that
negotiates a hosted selection or settles an escrow composes the real
``BareMetalStorefrontSettlementComposition`` from a strict settlement root. Only
what lies beyond the storefront is a double: the Alkahest chain clients the
evidence is published through, and, where a test drives the worker, the
Alkahest mechanism client that reads and claims the escrow on chain.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

from market_alkahest import create_alkahest_registration
from market_contact_exchange import create_contact_exchange_registration
from market_hosted_settlement import (
    REQUIRED_STRIPE_CAPABILITIES,
    create_stripe_registration,
)
from market_identity import Signer
from market_settlement_runtime import (
    ConditionOutcome,
    EffectOutcome,
    SettlementConfigurationRegistry,
    StatusOutcome,
)

from arkhai_bare_metal_storefront.settlement_composition import (
    BareMetalStorefrontSettlementComposition,
)

ALKAHEST_SECTION = {
    "enabled": True,
    "address_config_path": "/app/alkahest_anvil_addresses.json",
    "oracle_gated": False,
    "trusted_oracle_addresses": [],
    "interruptible": False,
    "interruptible_oracle_addresses": [],
}


def stripe_section(signer: Signer) -> dict[str, Any]:
    """An enabled hosted section trusting ``signer`` as the authority."""
    return {
        "enabled": True,
        "base_url": "https://settlement.example",
        "authority_id": "authority-main",
        "environment": "test",
        "authority": {"principals": [signer.identity.model_dump(mode="json")]},
        "expected_manifest_digest": "sha256:" + "ab" * 32,
        "expected_api_version": "0.2.1",
        "expected_schema_version": 5,
        "required_capabilities": list(REQUIRED_STRIPE_CAPABILITIES),
        "account_ref": "seller-main",
        "currency": "usd",
        "country": "US",
        "condition_profile": "bare-metal-lease-ready",
        "condition_profiles": {
            "bare-metal-lease-ready": {
                "condition_id": "bare-metal-lease-ready",
                "evaluator": {
                    "kind": "builtin.v1",
                    "version": "trivial.v1",
                    "params": {"kind": "trivial"},
                },
                "demand": {"encoding": "application/jcs+json", "value": {}},
            }
        },
    }


def hosted_composition(signer: Signer) -> BareMetalStorefrontSettlementComposition:
    """Hosted settlement only, signed by ``signer`` as the storefront."""
    return BareMetalStorefrontSettlementComposition.from_raw_config(
        {
            "schema_version": 1,
            "priority": ["fiat.stripe.v1"],
            "stripe": stripe_section(signer),
        },
        resources={
            "marketplace_signer": signer,
            "claimant_principal": signer.identity,
        },
    )


class EscrowOnChain:
    """The Alkahest mechanism client, doubled: an open escrow it can claim.

    It answers what the chain would for a funded escrow: ready until claimed,
    its condition met, and a claim that succeeds. ``calls`` records each
    operation the worker drove.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def materialize(self, obligation, *, operation_ref):
        raise AssertionError("a buyer-funded escrow is adopted, never materialized")

    async def get_status(self, obligation, *, mechanism_ref, operation_ref, mechanism_state):
        self.calls.append(("status", mechanism_ref))
        return StatusOutcome(
            status="ready",
            mechanism_ref=mechanism_ref,
            condition_anchor=mechanism_ref,
            mechanism_state=mechanism_state,
        )

    async def check(
        self, obligation, *, mechanism_ref, fulfillment_ref, operation_ref, mechanism_state
    ):
        self.calls.append(("check", fulfillment_ref))
        return ConditionOutcome(decision="ready", mechanism_state=mechanism_state)

    async def collect(
        self, obligation, *, mechanism_ref, fulfillment_ref, operation_ref, mechanism_state
    ):
        self.calls.append(("collect", fulfillment_ref))
        return EffectOutcome(receipt={"collected": mechanism_ref})

    async def reclaim_expired(
        self, obligation, *, mechanism_ref, operation_ref, mechanism_state,
        mechanism_options=None,
    ):
        self.calls.append(("reclaim", mechanism_ref))
        return EffectOutcome(receipt={"reclaimed": mechanism_ref})


class StringObligations:
    """A chain client's string obligations, doubled; records each submission."""

    def __init__(self, *, uid: str = "0x" + "cd" * 32, raises: Exception | None = None):
        self.uid = uid
        self.raises = raises
        self.submitted: list[tuple[str, str]] = []

    async def do_obligation(self, item, ref_uid=None, schema=None):
        self.submitted.append((item, ref_uid))
        if self.raises is not None:
            raise self.raises
        return self.uid


class ChainClient:
    """An Alkahest chain client, doubled to the one surface publication uses."""

    def __init__(self, string_obligation: StringObligations | None = None) -> None:
        self.string_obligation = string_obligation or StringObligations()


def alkahest_composition(
    signer: Signer,
    *,
    wallet: str,
    chain_clients: Mapping[str, Any],
    enabled: bool = True,
    escrow: Any | None = None,
) -> BareMetalStorefrontSettlementComposition:
    """Alkahest settlement over ``chain_clients``, the chain boundary's doubles.

    ``escrow`` stands in for the Alkahest mechanism client the registration
    would build over those chain clients; without it, the registration builds
    the real one.
    """
    raw = {
        "schema_version": 1,
        "priority": ["alkahest.v1"] if enabled else [],
        "alkahest": {**ALKAHEST_SECTION, "enabled": enabled},
    }
    alkahest = create_alkahest_registration()
    if escrow is not None:
        alkahest = dataclasses.replace(
            alkahest, client_factory=lambda _section, _resources, _role: escrow
        )
    registry = SettlementConfigurationRegistry(
        (
            alkahest,
            create_stripe_registration(),
            create_contact_exchange_registration(),
        )
    )
    return BareMetalStorefrontSettlementComposition(
        registry=registry,
        config=registry.resolve(raw, role="seller"),
        resources={
            "marketplace_signer": signer,
            "claimant_principal": signer.identity,
            "wallet": wallet,
            "wallet_ready": True,
            "clients": dict(chain_clients),
            "chains": {name: {"rpc_url": "http://anvil:8545"} for name in chain_clients},
        },
    )
