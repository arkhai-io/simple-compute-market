"""The rates an inference listing may advertise: one base unit per credit."""

from __future__ import annotations

import pytest
from market_core.schemas import RateValue, SettlementOption, derive_settlement_option_id

from arkhai_inference.listings.pricing import (
    UNIT_RATE,
    checked_credit_total,
    validate_listing_rates,
)

_ASSET = "0x" + "01" * 20
_OTHER_ASSET = "0x" + "02" * 20


def _option(*rates: RateValue) -> SettlementOption:
    rates = rates or (RateValue(field="amount", per="credit", value=1),)
    return SettlementOption.model_validate(
        {
            "option_id": derive_settlement_option_id(
                price={"asset": _ASSET, "rates": list(rates)}, settlement={"schema": "alkahest.v1"}
            ),
            "price": {"asset": _ASSET, "rates": [rate.model_dump(mode="json") for rate in rates]},
            "settlement": {"schema": "alkahest.v1"},
        }
    )


def _escrow(*rates: dict, token: str | None = _ASSET) -> dict:
    escrow: dict = {"chain_name": "anvil", "escrow_address": "0x" + "11" * 20, "rates": list(rates)}
    if token is not None:
        escrow["literal_fields"] = {"token": token}
    return escrow


_UNIT = {"field": "amount", "per": "credit", "value": "1"}


def test_a_credit_total_is_the_exact_product():
    assert checked_credit_total(UNIT_RATE, 7) == 7
    assert checked_credit_total(UNIT_RATE, 2_000_000) == 2_000_000


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True, "five", 2**256])
def test_a_credit_total_refuses_what_is_not_a_positive_integer_within_uint256(quantity):
    with pytest.raises(ValueError):
        checked_credit_total(UNIT_RATE, quantity)


def test_unit_rate_options_and_escrows_in_the_card_asset_are_admitted():
    validate_listing_rates([_option()], [_escrow(_UNIT), _escrow(_UNIT, token=None)], asset=_ASSET)


@pytest.mark.parametrize("value", [0, 2, 100])
def test_an_option_at_another_rate_is_refused(value):
    with pytest.raises(ValueError, match="exactly one"):
        validate_listing_rates([_option(RateValue(field="amount", per="credit", value=value))], [])


@pytest.mark.parametrize("per", ["hour", "token", "request"])
def test_an_option_not_priced_per_credit_is_refused(per):
    with pytest.raises(ValueError, match="per credit"):
        validate_listing_rates([_option(RateValue(field="amount", per=per, value=1))], [])


def test_an_option_with_two_amount_rates_is_refused():
    unit = RateValue(field="amount", per="credit", value=1)
    with pytest.raises(ValueError, match="exactly one amount rate"):
        validate_listing_rates([_option(unit, unit)], [])


@pytest.mark.parametrize(
    "rates,reason",
    [
        ((), "exactly one amount rate"),
        ((_UNIT, _UNIT), "exactly one amount rate"),
        (({**_UNIT, "value": "2"},), "exactly one base unit"),
        (({**_UNIT, "per": "token"},), "per credit"),
        (({"per": "credit", "value": "1"},), "exactly one amount rate"),
        (({"field": "amount", "value": "1"},), "per credit"),
    ],
)
def test_an_escrow_without_one_unit_rate_is_refused(rates, reason):
    with pytest.raises(ValueError, match=reason):
        validate_listing_rates([], [_escrow(*rates)])


def test_an_option_or_escrow_in_another_asset_is_refused():
    with pytest.raises(ValueError, match="option asset"):
        validate_listing_rates([_option()], [], asset=_OTHER_ASSET)
    with pytest.raises(ValueError, match="escrow token"):
        validate_listing_rates([], [_escrow(_UNIT)], asset=_OTHER_ASSET)
