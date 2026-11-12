"""Unit tests for the rate/literal-field accessor helpers in ``market_core.schemas``.

Every reader of ``accepted_escrows`` eventually swaps to
``primary_rate_value()`` / ``accepted_token_address()`` so the templates
wire format ships transparently. These tests pin the contracts both
helpers must honour:

  - dict input (the JSON shape coming out of SQLite + the wire),
  - Pydantic ``AcceptedEscrow`` input (the in-memory typed shape),
  - empty/missing inputs return ``None`` rather than raising.

``agreed_price`` labels an Agreement's accepted money as a total or one
period's price, never recomputing it: a reader that assumed a total would
charge or cap a recurring deal wrongly.
"""

from __future__ import annotations

import pytest

from market_core.schemas import (
    AcceptedEscrow,
    AgreedPrice,
    Agreement,
    PER_UNIT_SECONDS,
    PriceBasis,
    RateValue,
    SettlementOption,
    accepted_token_address,
    agreed_price,
    compute_rate_total,
    compute_rate_unit_total,
    derive_settlement_option_id,
    primary_rate_value,
    rate_scales_by_time,
)


_TOKEN = "0x" + "ab" * 20
_ESCROW = "0x" + "ee" * 20


# ---------------------------------------------------------------------------
# primary_rate_value
# ---------------------------------------------------------------------------


def test_primary_rate_value_dict_int():
    entry = {"rates": [{"field": "amount", "per": "hour", "value": 1234}]}
    assert primary_rate_value(entry) == 1234


def test_primary_rate_value_dict_string_uint256():
    entry = {"rates": [{"field": "amount", "per": "hour", "value": "1" + "0" * 30}]}
    assert primary_rate_value(entry) == 10**30


def test_primary_rate_value_hidden_reserve_dict():
    """Hidden reserve = empty ``rates``."""
    entry = {"rates": [], "literal_fields": {"token": _TOKEN}}
    assert primary_rate_value(entry) is None


def test_primary_rate_value_empty_dict():
    assert primary_rate_value({}) is None


def test_primary_rate_value_pydantic():
    entry = AcceptedEscrow(
        chain_name="anvil",
        escrow_address=_ESCROW,
        literal_fields={"token": _TOKEN},
        rates=[RateValue(field="amount", per="hour", value=5000)],
    )
    assert primary_rate_value(entry) == 5000


def test_primary_rate_value_pydantic_hidden_reserve():
    entry = AcceptedEscrow(
        chain_name="anvil",
        escrow_address=_ESCROW,
        literal_fields={"token": _TOKEN},
    )
    assert primary_rate_value(entry) is None


# ---------------------------------------------------------------------------
# accepted_token_address
# ---------------------------------------------------------------------------


def test_accepted_token_address_dict():
    entry = {"literal_fields": {"token": _TOKEN}}
    assert accepted_token_address(entry) == _TOKEN


def test_accepted_token_address_empty():
    assert accepted_token_address({}) is None
    assert accepted_token_address({"literal_fields": {}}) is None


def test_accepted_token_address_pydantic():
    entry = AcceptedEscrow(
        chain_name="anvil",
        escrow_address=_ESCROW,
        literal_fields={"token": _TOKEN},
        rates=[RateValue(field="amount", per="hour", value=1)],
    )
    assert accepted_token_address(entry) == _TOKEN


# ---------------------------------------------------------------------------
# compute_rate_total
# ---------------------------------------------------------------------------


def test_compute_rate_total_full_hour():
    rate = RateValue(field="amount", per="hour", value=1000)
    assert compute_rate_total(rate, 3600) == 1000


def test_compute_rate_total_two_hours():
    rate = RateValue(field="amount", per="hour", value=1000)
    assert compute_rate_total(rate, 7200) == 2000


def test_compute_rate_total_partial_hour_truncates():
    """Integer division truncates sub-unit fractions."""
    rate = RateValue(field="amount", per="hour", value=1000)
    assert compute_rate_total(rate, 1800) == 500  # half hour
    assert compute_rate_total(rate, 3599) == 999  # truncated, not rounded


def test_compute_rate_total_unknown_unit_raises():
    rate = RateValue(field="amount", per="hour", value=1000)
    object.__setattr__(rate, "per", "request")  # bypass validator
    with pytest.raises(ValueError, match="unknown rate.per unit"):
        compute_rate_total(rate, 3600)


def test_per_unit_seconds_includes_hour():
    assert PER_UNIT_SECONDS["hour"] == 3600


def test_rate_scales_by_time_distinguishes_counted_units():
    assert rate_scales_by_time(RateValue(field="amount", per="hour", value=1))
    assert not rate_scales_by_time(RateValue(field="amount", per="credit", value=1))


def test_compute_rate_unit_total_scales_by_count():
    rate = RateValue(field="amount", per="credit", value=100)
    assert compute_rate_unit_total(rate, 1) == 100
    assert compute_rate_unit_total(rate, 25) == 2500


def test_compute_rate_unit_total_rejects_time_units_and_bad_counts():
    time_rate = RateValue(field="amount", per="hour", value=100)
    with pytest.raises(ValueError, match="scales by duration"):
        compute_rate_unit_total(time_rate, 5)
    counted = RateValue(field="amount", per="credit", value=100)
    for bad in (0, -1, True, "5", None):
        with pytest.raises(ValueError, match="unit count"):
            compute_rate_unit_total(counted, bad)


def test_compute_rate_unit_total_guards_uint256_overflow():
    rate = RateValue(field="amount", per="credit", value=2**255)
    with pytest.raises(ValueError, match="uint256"):
        compute_rate_unit_total(rate, 4)


# ---------------------------------------------------------------------------
# agreed_price: the accepted money, labelled with its billing unit
# ---------------------------------------------------------------------------

#: 2.5 USD an hour in six-decimal minor units, accepted at 1.0x (10,000 bps):
#: two hours prepaid is 5,000,000 in total; a PT15M period is 625,000 and a
#: PT1M period 41,667, each rounded up once by the seller's quote.
_HOURLY = 2_500_000


def _rated_option(settlement: dict) -> SettlementOption:
    fields = {
        "price": {"asset": "USD/6", "rates": [{"field": "amount", "per": "hour", "value": str(_HOURLY)}]},
        "settlement": settlement,
    }
    return SettlementOption(option_id=derive_settlement_option_id(**fields), **fields)


def _agreement(option: SettlementOption | None, amount: int, *, duration_seconds: int = 7200) -> dict:
    return Agreement(
        negotiation_id="neg-1", listing_id="listing-1", listing_hash="0" * 64,
        buyer={"scheme": "ed25519", "identifier": "buyer"},
        seller={"scheme": "ed25519", "identifier": "seller"},
        settlement=option, amount=amount, asset=option.price_asset if option else None,
        duration_seconds=duration_seconds, start_utc="2026-01-01T00:00:00Z",
        accepted_at="2026-01-01T00:00:00Z",
    ).model_dump(mode="json", exclude_none=True)


def _per_period(period: str, seconds: int):
    return lambda option: PriceBasis(unit="per_period", period=period, period_seconds=seconds)


def test_a_prepaid_agreement_reads_its_whole_term_total_unchanged():
    option = _rated_option({"schema": "fixture.once.v1"})
    quote = agreed_price(_agreement(option, 5_000_000), project_billing=lambda _: PriceBasis(unit="total"))
    assert quote == AgreedPrice(unit="total", amount=5_000_000, asset="USD/6")
    assert quote.model_dump(mode="json")["amount"] == "5000000"


@pytest.mark.parametrize(("period", "seconds", "amount"), [
    ("PT15M", 900, 625_000), ("PT1M", 60, 41_667),
])
@pytest.mark.parametrize("duration_seconds", [7200, 172_800])
def test_a_per_period_agreement_reads_one_periods_price_whatever_its_horizon(
    period, seconds, amount, duration_seconds,
):
    option = _rated_option({"schema": "fixture.rate.v1", "period": period})
    agreement = _agreement(option, amount, duration_seconds=duration_seconds)
    quote = agreed_price(agreement, project_billing=_per_period(period, seconds))
    # Neither rescaled by the horizon nor re-rounded: the accepted amount is
    # already the seller's one upward-rounded period quote.
    assert quote == AgreedPrice(
        unit="per_period", period=period, period_seconds=seconds, amount=amount, asset="USD/6",
    )


def test_a_selected_option_without_a_billing_projection_is_refused():
    option = _rated_option({"schema": "fixture.once.v1"})
    with pytest.raises(ValueError, match="requires a billing projection"):
        agreed_price(_agreement(option, 5_000_000))


def test_an_agreement_with_no_selected_option_keeps_its_absolute_amount():
    # A legacy raw escrow acceptance names no option; its amount was always a
    # whole-term total, and no projection is asked for.
    assert agreed_price(_agreement(None, 123)) == AgreedPrice(unit="total", amount=123)


def test_a_projection_that_contradicts_its_unit_is_refused():
    option = _rated_option({"schema": "fixture.rate.v1", "period": "PT1M"})
    agreement = _agreement(option, 41_667)
    for basis in (
        {"unit": "per_period"},
        {"unit": "per_period", "period": "PT1M"},
        {"unit": "per_period", "period": "PT1M", "period_seconds": 0},
        {"unit": "total", "period": "PT1M"},
        {"unit": "total", "period_seconds": 60},
    ):
        with pytest.raises(ValueError):
            agreed_price(agreement, project_billing=lambda _option, basis=basis: basis)


def test_an_amount_beyond_uint256_is_refused():
    option = _rated_option({"schema": "fixture.once.v1"})
    agreement = _agreement(option, 1)
    agreement["amount"] = str(2**256)
    with pytest.raises(ValueError):
        agreed_price(agreement, project_billing=lambda _: PriceBasis(unit="total"))
