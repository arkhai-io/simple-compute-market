from __future__ import annotations

import pytest
from pydantic import ValidationError

from market_core.schemas import (
    Agreement,
    PriceBasis,
    RateValue,
    SettlementOption,
    SettlementSelection,
    agreed_price,
    derive_settlement_option_id,
)


def _option() -> SettlementOption:
    rates = [RateValue(field="amount", per="hour", value=125)]
    params = {
        "account_ref": "account-1",
        "funds_flow": "separate_charges_transfers",
        "funding_profile": "card.v1",
        "interaction": "interactive",
        "condition": {"protocol": "arkhai.condition.v1"},
    }
    option_id = derive_settlement_option_id(
        price={"asset": "usd", "rates": rates},
        settlement={"schema": "example.payment.v1", **(params or {})},
    )
    return SettlementOption(
        option_id=option_id,
        price={"asset": "usd", "rates": rates},
        settlement={"schema": "example.payment.v1", **(params or {})},
    )


def test_settlement_option_identity_is_canonical_and_stable() -> None:
    first = _option()
    second = SettlementOption.model_validate(first.model_dump())
    assert first.option_id == second.option_id
    assert first.option_id == first.option_id.lower()
    assert len(first.option_id) == 64


def test_settlement_option_rejects_payload_drift() -> None:
    raw = _option().model_dump()
    raw["price"]["asset"] = "eur"
    with pytest.raises(ValidationError, match="canonical payload"):
        SettlementOption.model_validate(raw)


def _accepted(option: SettlementOption) -> Agreement:
    return Agreement(
        negotiation_id="neg-1", listing_id="listing-1", listing_hash="0" * 64,
        buyer={"scheme": "ed25519", "identifier": "buyer"},
        seller={"scheme": "ed25519", "identifier": "seller"},
        settlement=option, amount=250, asset="usd", duration_seconds=7200,
        start_utc="2026-01-01T00:00:00Z", accepted_at="2026-01-01T00:00:00Z",
    )


def _total(_option: SettlementOption) -> PriceBasis:
    return PriceBasis(unit="total")


def test_an_acceptance_bound_listing_must_hold_the_exact_selected_option() -> None:
    option = _option()
    agreement = _accepted(option)
    listing = {"listing_id": "listing-1", "settlement_options": [option.model_dump(mode="json")]}
    assert agreed_price(agreement, listing, project_billing=_total).amount == 250
    # A registry record names its listing ``id``.
    record = {"id": "listing-1", "settlement_options": listing["settlement_options"]}
    assert agreed_price(agreement, record, project_billing=_total).amount == 250
    with pytest.raises(ValueError, match="identity differs"):
        agreed_price(agreement, {**listing, "listing_id": "listing-2"}, project_billing=_total)
    with pytest.raises(ValueError, match="exact selected option"):
        agreed_price(agreement, {**listing, "settlement_options": []}, project_billing=_total)
    repriced = option.model_dump(mode="json")
    repriced["price"]["rates"][0]["value"] = "126"
    repriced.pop("option_id")
    repriced["option_id"] = derive_settlement_option_id(**repriced)
    with pytest.raises(ValueError, match="exact selected option"):
        agreed_price(agreement, {**listing, "settlement_options": [repriced]}, project_billing=_total)


def test_settlement_selection_is_exact_and_expiry_bounded() -> None:
    option = _option()
    selection = SettlementSelection(
        option_id=option.option_id,
        settlement={"schema": option.settlement_schema},
        expiration_unix=2_000_000_000,
    )
    assert selection.option_id == option.option_id
