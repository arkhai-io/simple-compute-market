from __future__ import annotations

import pytest
from market_core.schemas import (
    RateValue,
    SettlementOption,
    SettlementSelection,
    derive_settlement_option_id,
)
from market_identity import Ed25519Signer
from pydantic import ValidationError

from domains.apicredits.listings import checked_credit_total, selected_unit_price
from domains.apicredits.schema import ApiCreditsListing, ApiCreditsMessage

BUYER = Ed25519Signer(b"\x75" * 32).identity
SELLER = Ed25519Signer(b"\x76" * 32).identity


def _option(profile: str = "card.v1", rate: int = 125) -> SettlementOption:
    rates = [RateValue(field="amount", per="credit", value=rate)]
    params = {
        "funding_profile": profile,
        "claimant_principal": SELLER.model_dump(mode="json"),
        "condition": {"protocol": "arkhai.condition.v1"},
    }
    return SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism="fiat.stripe.v1",
            asset="usd",
            rates=rates,
            params=params,
        ),
        mechanism="fiat.stripe.v1",
        asset="usd",
        rates=rates,
        params=params,
    )


def _resource() -> dict[str, object]:
    return {
        "kind": "api_credits.v1",
        "service_name": "weather",
        "resource_id": "quota-weather",
        "capacity_site_id": "site-1",
        "offering_mode": "api_credits",
    }


def test_hosted_only_listing_accepts_options_without_escrows() -> None:
    listing = ApiCreditsListing(
        offer_resource=_resource(),
        settlement_options=[_option()],
    )
    assert listing.accepted_escrows == []
    assert listing.settlement_options[0].params["funding_profile"] == "card.v1"


def test_duplicate_settlement_identity_is_rejected() -> None:
    option = _option()
    with pytest.raises(ValidationError, match="duplicate option identities"):
        ApiCreditsListing(
            offer_resource=_resource(),
            settlement_options=[option, option],
        )


def test_selection_and_canonical_parties_are_atomic() -> None:
    option = _option()
    selection = SettlementSelection(
        mechanism=option.mechanism,
        option_id=option.option_id,
        expiration_unix=2_000_000_000,
    )
    with pytest.raises(ValidationError, match="recorded together"):
        ApiCreditsMessage(
            payload={"quantity": 2, "key": {"mode": "new"}},
            settlement_selection=selection,
            buyer_principal=BUYER,
        )


def test_quantity_pricing_is_exact_and_checked() -> None:
    option = _option(rate=125)
    selection = SettlementSelection(
        mechanism=option.mechanism,
        option_id=option.option_id,
        expiration_unix=2_000_000_000,
    )
    listing = {"settlement_options": [option.model_dump(mode="json")]}
    assert selected_unit_price(listing, selection) == 125
    assert checked_credit_total(125, 3) == 375
    with pytest.raises(ValueError, match="fractional"):
        checked_credit_total(1.5, 2)
    with pytest.raises(ValueError, match="uint256"):
        checked_credit_total(2**255, 3)
