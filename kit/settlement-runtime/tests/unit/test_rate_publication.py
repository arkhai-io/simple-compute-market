"""Recurring option derivation from a publication clause (``derive_rate_preset``)
and the per-clause publication step both storefronts compose (``ClausePublication``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from market_core.schemas import (
    AgreedPrice, RateValue, SettlementOption, SettlementPrice, derive_settlement_option_id,
)
from market_deal_lifecycle.configuration import DisputeEntry
from market_deal_lifecycle.terms import Adjudication, TermContext, encode_terms
from market_settlement_runtime import MechanismReadiness
from market_settlement_runtime.rate_publication import (
    DEFAULT_PREMATURE_STOP_PENALTY_PERIODS, ClauseArtifacts, ClausePublication,
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


# The shared per-clause step (``ClausePublication.publish``).

READY = MechanismReadiness(mechanism=MECHANISM, configured=True, enabled=True, ready=True)
CONFIG = object()


def _once_option(*, lifecycle=None):
    price = SettlementPrice(asset="USD/6", rates=[RateValue(field="amount", per="hour", value=2500000)])
    settlement = {"schema": MECHANISM}
    return SettlementOption(
        option_id=derive_settlement_option_id(price=price, settlement=settlement, lifecycle=lifecycle),
        price=price, settlement=settlement, lifecycle=lifecycle,
    ).model_dump(mode="json")


def _step(*, helper=None, registry=None, servicing=SERVICING, **changes):
    return ClausePublication(
        registry=registry or MagicMock(), config=CONFIG, servicing=servicing,
        helpers={MECHANISM: helper} if helper is not None else {},
        authorities=[ENTRY], dispute_interfaces=frozenset({ENTRY.interface}), compute=True,
        clock=lambda: NOW, **changes,
    )


def _clause(**preset):
    recurring = RecurringPublicationPreset(period="PT15M", reserve_ahead_seconds=1800, **preset)
    return SimpleNamespace(mechanism=MECHANISM, asset="USD/6", recurring=recurring)


def _publish(step, clause, *, deadline=1200, max_duration_seconds=7200):
    diagnostics = []
    artifacts = step.publish(
        READY, clause, resources={"origin": "site-a"}, delivery_deadline=lambda: deadline,
        max_duration_seconds=max_duration_seconds, available_until_utc=None,
        diagnose=diagnostics.append,
    )
    return artifacts, diagnostics


def test_a_once_clause_is_built_by_its_registry_with_the_composition_s_inputs():
    registry = MagicMock()
    registry.build_option.return_value = {
        "accepted_escrows": [{"chain_name": "fixture-chain"}],
        "settlement_options": [_once_option()],
    }
    clause = SimpleNamespace(mechanism=MECHANISM, asset="USD/6", recurring=None)
    artifacts, diagnostics = _publish(_step(registry=registry), clause)
    assert artifacts.accepted_escrows == ({"chain_name": "fixture-chain"},)
    assert artifacts.settlement_options == (_once_option(),)
    assert diagnostics == []
    (status, config), kwargs = registry.build_option.call_args
    assert status is READY and config is CONFIG and kwargs["role"] == "seller"
    assert kwargs["resources"] == {
        "origin": "site-a", "dispute_authorities": [ENTRY],
        "dispute_interfaces": frozenset({ENTRY.interface}), "compute": True,
        "delivery_deadline_seconds": 1200, "publication_clause": clause,
    }


def test_a_mechanism_with_no_clause_is_built_from_its_section_alone():
    registry = MagicMock()
    registry.build_option.return_value = {"settlement_options": [_once_option()]}
    artifacts, _ = _publish(_step(registry=registry), None)
    assert artifacts.settlement_options == (_once_option(),)
    assert "publication_clause" not in registry.build_option.call_args.kwargs["resources"]


def test_a_once_option_lacking_a_default_buyer_term_publishes_with_its_diagnostic():
    # A hosted once option's adjudication alone: no delivery deadline.
    adjudication = {key: value for key, value in _derive(FixtureHelper()).lifecycle.items()
                    if key == "adjudication"}
    registry = MagicMock()
    registry.build_option.return_value = {"settlement_options": [_once_option(lifecycle=adjudication)]}
    clause = SimpleNamespace(mechanism=MECHANISM, asset="USD/6", recurring=None)
    artifacts, diagnostics = _publish(_step(registry=registry), clause)
    assert len(artifacts.settlement_options) == 1
    assert diagnostics == [{
        "code": "default_buyer_refusal", "mechanism": MECHANISM,
        "detail": "a default buyer refuses this option: no delivery deadline",
        "option_id": artifacts.settlement_options[0]["option_id"],
    }]


def test_a_built_rate_option_the_servicing_declaration_withholds_is_omitted():
    registry = MagicMock()
    registry.build_option.return_value = {"settlement_options": [_derive(FixtureHelper()).model_dump(mode="json")]}
    clause = SimpleNamespace(mechanism=MECHANISM, asset="USD/6", recurring=None)
    artifacts, diagnostics = _publish(_step(registry=registry, servicing=_declared("charged")), clause)
    assert artifacts.settlement_options == ()
    assert [entry["code"] for entry in diagnostics] == ["rate_servicing_undeclared"]


def test_a_recurring_clause_is_derived_through_its_helper_and_never_the_registry():
    registry, helper = MagicMock(), FixtureHelper()
    artifacts, diagnostics = _publish(_step(helper=helper, registry=registry), _clause())
    (option,) = artifacts.settlement_options
    assert option["settlement"] == {"schema": MECHANISM, "period": "PT15M", "reserve_ahead_seconds": 1800}
    assert artifacts.accepted_escrows == ()
    assert diagnostics == []
    registry.build_option.assert_not_called()
    assert helper.requests[0].lifecycle.delivery_deadline_seconds == 1200


@pytest.mark.parametrize(("changes", "code"), [
    ({"helper": None}, "rate_helper_missing"),
    ({"servicing": RateServicing()}, "rate_servicing_undeclared"),
    ({"max_duration_seconds": None}, "recurring_horizon_unbounded"),
], ids=["missing-helper", "undeclared-servicing", "unbounded-horizon"])
def test_a_recurring_clause_that_cannot_publish_is_omitted_with_its_diagnostic(changes, code):
    step_changes = {key: value for key, value in changes.items() if key in ("helper", "servicing")}
    step = _step(**{"helper": FixtureHelper(), **step_changes})
    artifacts, diagnostics = _publish(
        step, _clause(), max_duration_seconds=changes.get("max_duration_seconds", 7200),
    )
    assert artifacts == ClauseArtifacts()
    assert [(entry["code"], entry["mechanism"]) for entry in diagnostics] == [(code, MECHANISM)]


def _penalty(step, clause):
    (option,) = _publish(step, clause)[0].settlement_options
    return option["lifecycle"]["early_termination"].get("premature_stop_penalty")


def test_on_demand_with_no_stated_penalty_takes_the_default_multiple_of_its_period_price():
    assert DEFAULT_PREMATURE_STOP_PENALTY_PERIODS == 24
    assert _penalty(_step(helper=FixtureHelper()), _clause()) == str(625000 * 24)


def test_a_configured_multiple_replaces_the_default():
    assert _penalty(_step(helper=FixtureHelper(), default_penalty_periods=6), _clause()) == str(625000 * 6)


@pytest.mark.parametrize("stated", ["0", "1000"])
def test_a_penalty_stated_on_the_clause_wins_over_any_multiple(stated):
    step = _step(helper=FixtureHelper(), default_penalty_periods=6)
    assert _penalty(step, _clause(premature_stop_penalty=stated)) == stated


def test_spot_carries_no_default_penalty():
    assert _penalty(_step(helper=FixtureHelper()), _clause(payee_notice_seconds=0)) is None
