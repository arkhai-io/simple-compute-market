"""The VM buyer holds a seller's signed horizon to what the listing advertised."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from core_buyer.settlement import SelectedSettlementOption
from market_core.schemas import (
    SettlementOption, SettlementPrice, SettlementSelection, derive_settlement_option_id,
)

from arkhai_vms_buyer.settlement_composition import (
    accepted_listing_record,
    listing_acceptance_validator,
    validate_buyer_acceptance,
)

_PRICE = SettlementPrice.model_validate(
    {"asset": "USD/6", "rates": [{"field": "amount", "per": "hour", "value": 100}]},
)
PAYMENT = SettlementOption(
    option_id=derive_settlement_option_id(price=_PRICE, settlement={"schema": "arkhai.payments.v1"}),
    price=_PRICE, settlement={"schema": "arkhai.payments.v1"},
)


def _match(**bounds) -> dict:
    selected = SelectedSettlementOption(
        option=PAYMENT,
        selection=SettlementSelection(option_id=PAYMENT.option_id, settlement={"schema": "arkhai.payments.v1"}),
        registration=MagicMock(),
    )
    return {"listing_id": "L-1", "_selected_settlement": selected, **bounds}


def _outcome(duration_seconds: int) -> SimpleNamespace:
    return SimpleNamespace(agreement=SimpleNamespace(
        settlement=PAYMENT, start_utc="2030-01-01T00:00:00Z", duration_seconds=duration_seconds,
    ))


def test_the_acceptance_record_keeps_the_advertised_bounds_for_a_resumed_run():
    record = accepted_listing_record(
        _match(max_duration_seconds=7200, available_until_utc="2030-01-02T00:00:00Z"), None,
    )
    assert record == {"max_duration_seconds": 7200, "available_until_utc": "2030-01-02T00:00:00Z"}
    assert accepted_listing_record(_match(max_duration_seconds=None), None) == {}


@pytest.mark.parametrize(("listing", "requested", "refusal"), [
    ({"max_duration_seconds": 3600}, 7200, "exceeds the listing's bound of 3600"),
    ({"available_until_utc": "2030-01-01T01:00:00Z"}, 7200, "exceeds the listing's bound of 3600"),
    ({"max_duration_seconds": 7200}, 3600, "differs from the requested 3600"),
    ({"max_duration_seconds": 10800}, None, "differs from the default horizon 10800"),
])
def test_a_signed_horizon_the_buyer_was_not_offered_is_refused(
    listing, requested, refusal,
):
    with pytest.raises(RuntimeError, match=f"accepted horizon refused: .*{refusal}"):
        validate_buyer_acceptance(_outcome(7200), listing=listing, requested_duration_seconds=requested)


def test_each_listing_s_validator_binds_that_listing_and_the_request():
    validate = listing_acceptance_validator(None)(_match(max_duration_seconds=3600))
    with pytest.raises(RuntimeError, match="exceeds the listing's bound of 3600"):
        validate(_outcome(7200))
