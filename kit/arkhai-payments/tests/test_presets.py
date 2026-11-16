"""The hosted rate preset helper's pricing facts and the price it encodes."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from market_core.schemas import SettlementOption, derive_settlement_option_id
from market_deal_lifecycle.configuration import DisputeEntry
from market_settlement_runtime import SettlementPublicationClause
from market_settlement_runtime.rate_publication import RatePresetRefusal, derive_rate_preset
from market_settlement_runtime.rate_servicing import RateServicing, RateServicingDeclaration

from market_arkhai_payments.fixtures import dispute_lifecycle, recurring_options
from market_arkhai_payments.presets import PaymentsRatePresetHelper, payments_rate_wiring, rate_term_timing
from market_arkhai_payments.settlement_config import ARKHAI_PAYMENTS_MECHANISM, clause_rate_minor_units

from payment_terms import OTHER, PAYEE


def _authority() -> DisputeEntry:
    return DisputeEntry.model_validate({
        **dispute_lifecycle(OTHER)["adjudication"]["dispute"],
        "advertisement": {"mechanisms": [ARKHAI_PAYMENTS_MECHANISM],
                          "minimum_dispute_window_seconds": 0, "minimum_case_hold_seconds": None},
    })


def _clause(*, rate: str = "60", asset: str = "USD/2", **mechanism_input: Any) -> SettlementPublicationClause:
    # An input given as None is left out of the clause.
    inputs = {"asset": asset, "payee_account": PAYEE, "approval_window": "PT10M",
              "dispute_window_seconds": 604800, **mechanism_input}
    return SettlementPublicationClause.model_validate({
        "mechanism": ARKHAI_PAYMENTS_MECHANISM, "asset": asset, "rate": rate, "per": "hour",
        "mechanism_input": {key: value for key, value in inputs.items() if value is not None},
        "recurring": {"period": "PT15M", "reserve_ahead_seconds": 1800},
    })


@pytest.mark.parametrize("deadline", [None, 600])
def test_pricing_returns_the_clauses_own_delivery_deadline(deadline):
    # The pool's effective deadline, when the composition has one, wins over this
    # value; without one, the clause's own is what the published term promises.
    clause = _clause(**({"delivery_deadline_seconds": deadline} if deadline is not None else {}))
    pricing = PaymentsRatePresetHelper().pricing(clause, (_authority(),))
    assert pricing.delivery_deadline_seconds == deadline


def test_pricing_charges_one_periods_share_of_the_hourly_rate_in_minor_units():
    pricing = PaymentsRatePresetHelper().pricing(_clause(rate="60"), (_authority(),))
    # 60.00 per hour in USD/2 is 6000 minor units an hour, 1500 a 15-minute period.
    assert (pricing.quote.amount, pricing.quote.asset, pricing.quote.period) == (1500, "USD/2", "PT15M")


def test_the_shared_wiring_reads_the_offered_authorities_at_each_projection():
    # A change to the offered dispute authorities is seen without rebuilding
    # the composition: the projection asks for them every time it runs.
    reads: list[int] = []

    def authorities() -> tuple[DisputeEntry, ...]:
        reads.append(1)
        return (_authority(),)

    helpers, projections = payments_rate_wiring(authorities)
    assert set(helpers) == set(projections) == {ARKHAI_PAYMENTS_MECHANISM}
    option = SettlementOption.model_validate(recurring_options(_authority(), payee=PAYEE)["spot"])
    first = projections[ARKHAI_PAYMENTS_MECHANISM](option)
    projections[ARKHAI_PAYMENTS_MECHANISM](option)
    assert (first.period_seconds, len(reads)) == (900, 2)


def test_build_refuses_another_mechanisms_declaration():
    request = SimpleNamespace(servicing=RateServicingDeclaration("other.v1", frozenset({"charged"})))
    refusal = PaymentsRatePresetHelper().build(request)  # type: ignore[arg-type]
    assert isinstance(refusal, RatePresetRefusal) and refusal.code == "rate_servicing_undeclared"


def _encoded(*, setup: str | None, **mechanism_input: Any) -> SettlementOption:
    clause = _clause(**mechanism_input).model_copy(deep=True)
    recurring = {"period": "PT15M", "reserve_ahead_seconds": 1800, "payee_notice_seconds": 30,
                 **({"setup_amount": setup} if setup is not None else {})}
    clause = SettlementPublicationClause.model_validate({**clause.model_dump(mode="json"), "recurring": recurring})
    servicing = RateServicing({ARKHAI_PAYMENTS_MECHANISM: RateServicingDeclaration(
        ARKHAI_PAYMENTS_MECHANISM, frozenset({"charged", "returned"}), setup=setup is not None,
    )})
    option = derive_rate_preset(
        clause, helper=PaymentsRatePresetHelper(), servicing=servicing, authorities=(_authority(),),
        max_duration_seconds=3600, available_until_utc=None, delivery_deadline_seconds=30,
        now=datetime(2027, 1, 1, tzinfo=timezone.utc), default_penalty_periods=24,
    )
    assert not isinstance(option, RatePresetRefusal), option
    return SettlementOption.model_validate(option)


@pytest.mark.parametrize("setup", [None, "2500"])
def test_build_encodes_the_rate_parameters_under_their_option_identity(setup):
    option = _encoded(setup=setup)
    settlement = option.settlement_params
    assert {key: settlement.get(key) for key in ("payee_account", "approval_window", "period",
                                                 "reserve_ahead_seconds", "setup_amount")} == {
        "payee_account": PAYEE, "approval_window": "PT10M", "period": "PT15M",
        "reserve_ahead_seconds": 1800, "setup_amount": setup,
    }
    # The setup charge is present only when the seller priced one, and the
    # option identity binds every encoded term.
    assert ("setup_amount" in settlement) == (setup is not None)
    assert option.option_id == derive_settlement_option_id(
        price=option.price, settlement=option.settlement, lifecycle=option.lifecycle,
    )
    assert option.price.rates[0].value == 6000 and option.price.asset == "USD/2"


def test_build_writes_approval_window_whichever_name_the_clause_used():
    clause_input = {"window": "PT10M", "approval_window": None}
    option = _encoded(setup=None, **clause_input)
    assert option.settlement_params["approval_window"] == "PT10M"
    assert "window" not in option.settlement_params


def test_pricing_refuses_a_clause_whose_asset_differs_from_its_payment_input():
    clause = SettlementPublicationClause.model_validate({
        **_clause().model_dump(mode="json"), "asset": "USD/6",
    })
    with pytest.raises(ValueError, match="matching asset"):
        PaymentsRatePresetHelper().pricing(clause, (_authority(),))


def test_the_timing_projection_reads_the_options_period_and_approval_window():
    option = _encoded(setup=None)
    timing = rate_term_timing(option, authorities=(_authority(),))
    assert (timing.period_seconds, timing.approval_window_seconds) == (900, 600)
    settlement = {"schema": ARKHAI_PAYMENTS_MECHANISM, "payee_account": PAYEE, "window": "PT10M"}
    once = SettlementOption(
        option_id=derive_settlement_option_id(price=option.price, settlement=settlement),
        price=option.price, settlement=settlement,
    )
    with pytest.raises(ValueError, match="recurring payment option"):
        rate_term_timing(once, authorities=(_authority(),))


@pytest.mark.parametrize(("rate", "per", "asset", "minor"), [
    ("60", "hour", "USD/2", 6000), ("0.25", "hour", "USD/2", 25), ("60", "hour", "USD", 60),
    ("6000", "gpu_hour", "USD/2", 6000),
])
def test_one_conversion_scales_only_hourly_major_units(rate, per, asset, minor):
    assert clause_rate_minor_units(rate, per, asset) == minor


@pytest.mark.parametrize(("rate", "per", "rule"), [
    ("0.001", "hour", "more than 2 decimal places"), ("1.5", "gpu_hour", "integer base units"),
])
def test_a_rate_finer_than_the_asset_precision_is_refused_not_rounded(rate, per, rule):
    with pytest.raises(ValueError, match=rule):
        clause_rate_minor_units(rate, per, "USD/2")
    if per == "hour":
        with pytest.raises(ValueError, match=rule):
            PaymentsRatePresetHelper().pricing(_clause(rate=rate), (_authority(),))
