"""Recurring option derivation from a publication clause (``derive_rate_preset``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
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
    {MECHANISM: RateServicingDeclaration(MECHANISM, frozenset({"charged", "returned"}))},
)


def _declared(*treatments: str, setup: bool = False) -> RateServicing:
    return RateServicing({MECHANISM: RateServicingDeclaration(MECHANISM, frozenset(treatments), setup)})


class FixtureHelper:
    """An injected encoder pricing 900-second periods at 625000 base units."""

    def __init__(self, *, supported=frozenset({"charged", "returned"}), setup=False) -> None:
        self.requests = []
        self.supported = supported
        self.setup = setup

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
                supported_partial_periods=self.supported,
            ),
            supports_setup_delivery_end=self.setup,
        )

    def build(self, request):
        self.requests.append(request)
        price = SettlementPrice(asset=request.quote.asset, rates=[
            RateValue(field="amount", per="hour", value=2500000),
        ])
        settlement = {"schema": MECHANISM, "period": request.preset.period,
                      "reserve_ahead_seconds": request.preset.reserve_ahead_seconds}
        if request.preset.setup_amount is not None:
            settlement["setup_amount"] = request.preset.setup_amount
        lifecycle = encode_terms(request.lifecycle)
        return SettlementOption(
            option_id=derive_settlement_option_id(price=price, settlement=settlement, lifecycle=lifecycle),
            price=price, settlement=settlement, lifecycle=lifecycle,
        )


def _derive(helper, *, preset=None, **changes):
    clause = SimpleNamespace(mechanism=MECHANISM, asset="USD/6", recurring=RecurringPublicationPreset(
        period="PT15M", reserve_ahead_seconds=1800, **(preset or {}),
    ))
    arguments = dict(
        helper=helper, servicing=SERVICING, authorities=[ENTRY], max_duration_seconds=7200,
        available_until_utc=None, delivery_deadline_seconds=1200, now=NOW, default_penalty_periods=24,
    )
    return derive_rate_preset(clause, **{**arguments, **changes})


def test_a_declared_preset_is_encoded_with_the_selected_declaration():
    helper = FixtureHelper()
    option = _derive(helper, preset={"payee_notice_seconds": 0})
    assert isinstance(option, SettlementOption)
    assert helper.requests[0].servicing == SERVICING.select(MECHANISM)


@pytest.mark.parametrize(("servicing", "preset", "undeclared"), [
    (RateServicing(), {}, "undeclared for"),
    (_declared(), {}, "undeclared for"),
    # The seller's stop returns its period; only charged is declared.
    (_declared("charged"), {"settles_through": "started_period", "payee_notice_seconds": 0}, "returned"),
    # The term end returns its period; only charged is declared.
    (_declared("charged"), {}, "returned"),
    (_declared("charged", "returned"), {"settles_through": "stop"}, "prorated"),
    (_declared("charged", "returned"), {"setup_amount": "100"}, "setup charge"),
], ids=["absent", "empty", "entitlement", "term-end", "prorated-term-end", "setup"])
def test_an_undeclared_treatment_or_setup_omits_the_recurring_candidate(servicing, preset, undeclared):
    helper = FixtureHelper(setup=True)
    refusal = _derive(helper, servicing=servicing, preset=preset)
    assert isinstance(refusal, RatePresetRefusal) and refusal.code == "rate_servicing_undeclared"
    assert undeclared in refusal.detail
    assert helper.requests == []


def test_a_declared_charged_term_end_is_admitted_without_returned():
    option = _derive(FixtureHelper(), servicing=_declared("charged"), preset={"settles_through": "started_period"})
    assert isinstance(option, SettlementOption)


def test_a_declared_treatment_the_helper_cannot_enforce_is_refused():
    refusal = _derive(FixtureHelper(supported=frozenset({"charged"})))
    assert isinstance(refusal, RatePresetRefusal) and refusal.code == "recurring_preset_unusable"


def test_a_declared_setup_charge_still_needs_the_helper_s_support():
    servicing = _declared("charged", "returned", setup=True)
    refusal = _derive(FixtureHelper(), servicing=servicing, preset={"setup_amount": "100"})
    assert isinstance(refusal, RatePresetRefusal) and refusal.code == "setup_delivery_end_unsupported"
    option = _derive(FixtureHelper(setup=True), servicing=servicing, preset={"setup_amount": "100"})
    assert isinstance(option, SettlementOption) and option.settlement["setup_amount"] == "100"


def test_a_fractional_limiting_absolute_bound_floors_the_default_horizon():
    helper = FixtureHelper()
    # 72000.4 seconds after the whole-second publication start.
    option = _derive(helper, max_duration_seconds=None, available_until_utc="2030-01-01T20:00:00.4Z")
    assert isinstance(option, SettlementOption)
    assert helper.requests[0].default_horizon_seconds == 72000


def test_a_default_horizon_without_runway_is_a_close_reason():
    # Approval window 300 + deadline 1200 + one 900-second period.
    refusal = _derive(FixtureHelper(), max_duration_seconds=2399)
    assert refusal == RatePresetRefusal(
        "recurring_horizon_no_runway", "The horizon leaves no runway: minimum duration_seconds is 2400",
    )


def test_an_unbounded_recurring_candidate_is_omitted():
    refusal = _derive(FixtureHelper(), max_duration_seconds=None)
    assert isinstance(refusal, RatePresetRefusal) and refusal.code == "recurring_horizon_unbounded"
