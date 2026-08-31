from __future__ import annotations

from datetime import datetime, timezone

from arkhai_bare_metal import (
    BareMetalHostedPublicationPolicy,
    BareMetalListing,
    build_ready_bare_metal_hosted_options,
)
from market_core.schemas import RateValue, SettlementOption, derive_settlement_option_id

NOW = datetime(2099, 1, 1, tzinfo=timezone.utc)
OFFER = datetime(2099, 1, 1, 2, tzinfo=timezone.utc)
FULFILL = datetime(2099, 1, 1, 3, tzinfo=timezone.utc)


def _base(profile: str) -> SettlementOption:
    rates = [RateValue(field="amount", per="hour", value=100)]
    params = {
        "authority_id": "authority",
        "account_ref": "seller-account-ref",
        "country": "US",
        "environment": "test",
        "claimant_principal": {"scheme": "ed25519", "identifier": "seller"},
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


def _candidate(access_methods: list[str] | None = None) -> dict:
    listing = BareMetalListing(
        machine_id="machine-a",
        physical_host_id="host-a",
        access_methods=access_methods or ["ssh"],
    )
    return {
        "derivation_key": "site-a:resource-a",
        "site_id": "site-a",
        "projection_revision": 4,
        "projection_digest": "generation-4",
        "physical_resource_id": "resource-a",
        "machine_id": "machine-a",
        "physical_host_id": "host-a",
        "pool_id": "pool-a",
        "listing": listing,
    }


def test_partial_profile_readiness_omits_only_unready_profile() -> None:
    result = build_ready_bare_metal_hosted_options(
        candidate=_candidate(),
        base_hosted_options=[_base("card.v1"), _base("us_ach_debit.v1")],
        policy=BareMetalHostedPublicationPolicy(),
        offer_expires_at=OFFER,
        funding_deadlines={
            "card.v1": datetime(2099, 1, 1, 1, tzinfo=timezone.utc),
            "us_ach_debit.v1": datetime(2099, 1, 1, 1, 30, tzinfo=timezone.utc),
        },
        fulfillment_deadline=FULFILL,
        now=NOW,
    )

    profiles = [item.params["funding_profile"] for item in result.settlement_options]
    assert profiles == ["card.v1", "us_ach_debit.v1"]
    assert result.blockers["us_bank_transfer.v1"] == ("hosted_profile_unready",)
    assert len({item.option_id for item in result.settlement_options}) == 2


def test_unsupported_access_omits_every_hosted_option() -> None:
    result = build_ready_bare_metal_hosted_options(
        candidate=_candidate(["serial"]),
        base_hosted_options=[_base("card.v1")],
        policy=BareMetalHostedPublicationPolicy(),
        offer_expires_at=OFFER,
        funding_deadlines={"card.v1": datetime(2099, 1, 1, 1, tzinfo=timezone.utc)},
        fulfillment_deadline=FULFILL,
        now=NOW,
    )

    assert result.settlement_options == ()
    assert result.blockers["card.v1"] == ("unsupported_access",)


def test_profile_deadline_cannot_outlive_signed_offer() -> None:
    result = build_ready_bare_metal_hosted_options(
        candidate=_candidate(),
        base_hosted_options=[_base("us_bank_transfer.v1")],
        policy=BareMetalHostedPublicationPolicy(),
        offer_expires_at=OFFER,
        funding_deadlines={
            "us_bank_transfer.v1": datetime(2099, 1, 1, 2, 1, tzinfo=timezone.utc)
        },
        fulfillment_deadline=FULFILL,
        now=NOW,
    )

    assert result.settlement_options == ()
    assert result.blockers["us_bank_transfer.v1"] == ("funding_exceeds_offer",)
