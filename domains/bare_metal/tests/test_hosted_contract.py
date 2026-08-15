from __future__ import annotations

import base64
from datetime import datetime, timezone

import pytest
from arkhai_bare_metal import (
    BareMetalBuyerDemand,
    BareMetalHostedOptionFacts,
    CanonicalPrincipal,
    bind_bare_metal_hosted_option,
    derive_accepted_hosted_binding,
    validate_buyer_selection,
)
from market_core.schemas import (
    RateValue,
    SettlementOption,
    SettlementSelection,
    derive_settlement_option_id,
)

BUYER = CanonicalPrincipal(scheme="ed25519", identifier="buyer")
SELLER = CanonicalPrincipal(scheme="ed25519", identifier="seller")
KEY = "ssh-ed25519 " + base64.b64encode(b"x" * 48).decode()
OFFER_EXPIRY = datetime(2099, 1, 1, 2, tzinfo=timezone.utc)
FUNDING_DEADLINE = datetime(2099, 1, 1, 1, tzinfo=timezone.utc)
FULFILLMENT_DEADLINE = datetime(2099, 1, 1, 3, tzinfo=timezone.utc)


def _base_option(profile: str = "card.v1") -> SettlementOption:
    rates = [RateValue(field="amount", per="hour", value=1200)]
    params = {
        "authority_id": "authority",
        "account_ref": "account-safe-ref",
        "country": "US",
        "environment": "test",
        "claimant_principal": SELLER.model_dump(mode="json"),
        "funds_flow": "separate_charges_transfers",
        "funding_profile": profile,
        "interaction": "interactive",
        "contract_fingerprint": "sha256:" + "1" * 64,
        "condition": {"kind": "portable-remote.v1", "identifier": "lease-ready"},
    }
    return SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism="fiat.stripe.v1", asset="usd", rates=rates, params=params
        ),
        mechanism="fiat.stripe.v1",
        asset="usd",
        rates=rates,
        params=params,
    )


def _facts() -> BareMetalHostedOptionFacts:
    return BareMetalHostedOptionFacts(
        derivation_key="site-a:resource-a",
        projection_digest="sha256:" + "2" * 64,
        site_id="site-a",
        executor_kind="bare_metal",
        resource_selection="specific",
        physical_resource_id="resource-a",
        physical_host_id="host-a",
        access_method="ssh",
        offer_expires_at=OFFER_EXPIRY,
        funding_deadline=FUNDING_DEADLINE,
        fulfillment_deadline=FULFILLMENT_DEADLINE,
    )


def _demand(option: SettlementOption) -> BareMetalBuyerDemand:
    return BareMetalBuyerDemand(
        duration_seconds=3600,
        ssh_public_key=KEY,
        settlement=SettlementSelection(
            mechanism=option.mechanism,
            option_id=option.option_id,
            expiration_unix=int(FUNDING_DEADLINE.timestamp()),
        ),
    )


def test_binding_is_deterministic_and_preserves_trusted_resource() -> None:
    first = bind_bare_metal_hosted_option(_base_option(), facts=_facts())
    second = bind_bare_metal_hosted_option(_base_option(), facts=_facts())

    assert first.option.option_id == second.option.option_id
    assert first.option.params["bare_metal"]["site_id"] == "site-a"
    assert first.option.params["bare_metal"]["physical_resource_id"] == "resource-a"


def test_buyer_demand_rejects_seller_authority_fields() -> None:
    bound = bind_bare_metal_hosted_option(_base_option(), facts=_facts())
    value = _demand(bound.option).model_dump(mode="json")
    value["site_id"] = "buyer-invented-site"

    with pytest.raises(ValueError):
        BareMetalBuyerDemand.model_validate(value)


def test_exact_selection_rejects_nonadvertised_profile() -> None:
    card = bind_bare_metal_hosted_option(_base_option(), facts=_facts())
    ach = bind_bare_metal_hosted_option(_base_option("us_ach_debit.v1"), facts=_facts())

    with pytest.raises(ValueError, match="exact advertised"):
        validate_buyer_selection(
            demand=_demand(ach.option),
            advertised_options=[card.option],
        )


def test_accepted_binding_uses_minimum_authority_deadline() -> None:
    option = bind_bare_metal_hosted_option(_base_option(), facts=_facts())
    demand = _demand(option.option)
    authorization_expiry = datetime(2099, 1, 1, 1, 30, tzinfo=timezone.utc)

    accepted = derive_accepted_hosted_binding(
        agreement_ref="agreement-a",
        negotiation_id="negotiation-a",
        listing_id="listing-a",
        obligation_ref="a" * 64,
        option=option,
        demand=demand,
        buyer_principal=BUYER,
        seller_principal=SELLER,
        claimant_principal=SELLER,
        signed_listing={
            "listing_id": "listing-a",
            "option_id": option.option.option_id,
        },
        seller_terms={"site_id": "site-a", "price": "1200"},
        accepted_plan={"obligations": [{"mechanism": "fiat.stripe.v1"}]},
        authorization_expires_at=authorization_expiry,
    )

    assert accepted.funding_deadline == FUNDING_DEADLINE
    assert accepted.option.facts.site_id == "site-a"
    assert accepted.binding_digest.startswith("sha256:")
