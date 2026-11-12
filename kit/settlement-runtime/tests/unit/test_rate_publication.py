"""Recurring option derivation from a publication clause (``derive_rate_preset``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from market_core.schemas import (
    AgreedPrice, RateValue, SettlementOption, SettlementPrice, derive_settlement_option_id,
)
from market_deal_lifecycle.configuration import DisputeEntry
from market_deal_lifecycle.terms import Adjudication, TermContext, encode_terms
from market_settlement_runtime.rate_publication import (
    RatePresetPricing, RatePresetRefusal, RecurringPublicationPreset, derive_rate_preset,
)
from market_settlement_runtime.rate_servicing import RateServicing, RateServicingDeclaration

MECHANISM = "fixture.rate.v1"
# A fictional authority: the origin is a reserved name that resolves nowhere.
ENTRY = DisputeEntry.model_validate({
    "interface": "fixture.mediation.v1", "origin": "https://mediation.invalid",
    "account": "fixture-account", "record_key": "fixture-record", "params": {},
    "advertisement": {"mechanisms": [MECHANISM], "minimum_dispute_window_seconds": 60,
                      "minimum_case_hold_seconds": None},
})
NOW = datetime(2030, 1, 1, tzinfo=UTC) + timedelta(microseconds=250000)
SERVICING = RateServicing(
    {MECHANISM: "fixture-rate-v1"},
    {MECHANISM: RateServicingDeclaration(MECHANISM, "fixture-rate-v1", "published")},
)


class FixtureHelper:
    """An injected encoder pricing 900-second periods at 625000 base units."""

    def __init__(self) -> None:
        self.requests = []

    def pricing(self, clause, authorities):
        return RatePresetPricing(
            quote=AgreedPrice(unit="per_period", period="PT15M", period_seconds=900,
                              amount=625000, asset=clause.asset),
            approval_window_seconds=300,
            adjudication=Adjudication(version=1, dispute=ENTRY.authority,
                                      dispute_window_seconds=604800, case_hold_max_seconds=None),
            context=TermContext(
                mechanism=clause.mechanism, has_adapter=True,
                dispute_interfaces=frozenset({ENTRY.interface}), authority=ENTRY.requirements,
                supported_partial_periods=frozenset({"charged", "returned"}),
            ),
        )

    def build(self, request):
        self.requests.append(request)
        price = SettlementPrice(asset=request.quote.asset, rates=[
            RateValue(field="amount", per="hour", value=2500000),
        ])
        settlement = {"schema": MECHANISM, "period": request.preset.period,
                      "reserve_ahead_seconds": request.preset.reserve_ahead_seconds}
        lifecycle = encode_terms(request.lifecycle)
        return SettlementOption(
            option_id=derive_settlement_option_id(price=price, settlement=settlement, lifecycle=lifecycle),
            price=price, settlement=settlement, lifecycle=lifecycle,
        )


def _derive(helper, **changes):
    clause = SimpleNamespace(mechanism=MECHANISM, asset="USD/6", recurring=RecurringPublicationPreset(
        period="PT15M", reserve_ahead_seconds=1800,
    ))
    arguments = dict(
        helper=helper, servicing=SERVICING, authorities=[ENTRY], max_duration_seconds=None,
        available_until_utc=None, delivery_deadline_seconds=1200, now=NOW, default_penalty_periods=24,
    )
    return derive_rate_preset(clause, **{**arguments, **changes})


def test_a_fractional_limiting_absolute_bound_floors_the_default_horizon():
    helper = FixtureHelper()
    # 72000.4 seconds after the whole-second publication start.
    option = _derive(helper, available_until_utc="2030-01-01T20:00:00.4Z")
    assert isinstance(option, SettlementOption)
    assert helper.requests[0].default_horizon_seconds == 72000


def test_a_default_horizon_without_runway_is_a_close_reason():
    # Approval window 300 + deadline 1200 + one 900-second period.
    refusal = _derive(FixtureHelper(), max_duration_seconds=2399)
    assert refusal == RatePresetRefusal(
        "recurring_horizon_no_runway", "The horizon leaves no runway: minimum duration_seconds is 2400",
    )


def test_an_unbounded_recurring_candidate_is_omitted():
    refusal = _derive(FixtureHelper())
    assert isinstance(refusal, RatePresetRefusal) and refusal.code == "recurring_horizon_unbounded"
