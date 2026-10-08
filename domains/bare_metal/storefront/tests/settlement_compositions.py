"""Settlement compositions for tests, built the way the server builds them.

The storefront has no settlement without a composition, so a test that
negotiates a hosted selection or settles an escrow composes the real
``BareMetalStorefrontSettlementComposition`` from a strict settlement root. Only
what lies beyond the storefront is a double: the Alkahest chain clients.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from market_hosted_settlement import REQUIRED_STRIPE_CAPABILITIES
from market_identity import Signer

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


def alkahest_composition(
    signer: Signer,
    *,
    wallet: str,
    chain_clients: Mapping[str, Any],
    enabled: bool = True,
) -> BareMetalStorefrontSettlementComposition:
    """Alkahest settlement over ``chain_clients``, the chain boundary's doubles."""
    return BareMetalStorefrontSettlementComposition.from_raw_config(
        {
            "schema_version": 1,
            "priority": ["alkahest.v1"] if enabled else [],
            "alkahest": {**ALKAHEST_SECTION, "enabled": enabled},
        },
        resources={
            "marketplace_signer": signer,
            "claimant_principal": signer.identity,
            "wallet": wallet,
            "wallet_ready": True,
            "clients": dict(chain_clients),
            "chains": {name: {"rpc_url": "http://anvil:8545"} for name in chain_clients},
        },
    )
