from __future__ import annotations

import pytest
from pydantic import ValidationError

from market_core.schemas import (
    RateValue,
    SettlementOption,
    SettlementSelection,
    derive_settlement_option_id,
)


def _option() -> SettlementOption:
    rates = [RateValue(field="amount", per="hour", value=125)]
    params = {
        "account_ref": "account-1",
        "funds_flow": "separate_charges_transfers",
        "payment_method_types": ["card"],
        "condition": {"protocol": "arkhai.condition.v1"},
    }
    option_id = derive_settlement_option_id(
        mechanism="fiat.stripe.v1", asset="usd", rates=rates, params=params
    )
    return SettlementOption(
        option_id=option_id,
        mechanism="fiat.stripe.v1",
        asset="usd",
        rates=rates,
        params=params,
    )


def test_settlement_option_identity_is_canonical_and_stable() -> None:
    first = _option()
    second = SettlementOption.model_validate(first.model_dump())
    assert first.option_id == second.option_id
    assert first.option_id == first.option_id.lower()
    assert len(first.option_id) == 64


def test_settlement_option_rejects_payload_drift() -> None:
    raw = _option().model_dump()
    raw["asset"] = "eur"
    with pytest.raises(ValidationError, match="canonical payload"):
        SettlementOption.model_validate(raw)


def test_settlement_selection_is_exact_and_expiry_bounded() -> None:
    option = _option()
    selection = SettlementSelection(
        mechanism=option.mechanism,
        option_id=option.option_id,
        expiration_unix=2_000_000_000,
    )
    assert selection.option_id == option.option_id
