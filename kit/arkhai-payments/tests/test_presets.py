"""The hosted rate preset helper's pricing facts and the price it encodes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from market_core.schemas import SettlementOption
from market_deal_lifecycle.configuration import DisputeEntry
from market_settlement_runtime import SettlementPublicationClause
from market_settlement_runtime.rate_publication import RatePresetRefusal
from market_settlement_runtime.rate_servicing import RateServicingDeclaration

from market_arkhai_payments.fixtures import dispute_lifecycle, recurring_options
from market_arkhai_payments.presets import PaymentsRatePresetHelper, payments_rate_wiring
from market_arkhai_payments.settlement_config import ARKHAI_PAYMENTS_MECHANISM, clause_rate_minor_units

from payment_terms import OTHER, PAYEE


def _authority() -> DisputeEntry:
    return DisputeEntry.model_validate({
        **dispute_lifecycle(OTHER)["adjudication"]["dispute"],
        "advertisement": {"mechanisms": [ARKHAI_PAYMENTS_MECHANISM],
                          "minimum_dispute_window_seconds": 0, "minimum_case_hold_seconds": None},
    })


def _clause(*, rate: str = "60", asset: str = "USD/2", **mechanism_input: Any) -> SettlementPublicationClause:
    return SettlementPublicationClause.model_validate({
        "mechanism": ARKHAI_PAYMENTS_MECHANISM, "asset": asset, "rate": rate, "per": "hour",
        "mechanism_input": {"asset": asset, "payee_account": PAYEE, "approval_window": "PT10M",
                            "dispute_window_seconds": 604800, **mechanism_input},
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
