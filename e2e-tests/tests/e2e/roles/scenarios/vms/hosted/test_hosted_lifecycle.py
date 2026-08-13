from __future__ import annotations

import pytest

from .cases import EVENT_CASES, MECHANISM_CASES, RESTART_CASES, UNCERTAINTY_CASES
from .driver import HostedScenarioDriver
from .recovery import HermeticRecoveryDriver, run_mechanism_case
from .state import DealState

pytestmark = pytest.mark.e2e_hosted_settlement


def test_satisfied_condition_collects_once(
    hosted_scenario_driver: HostedScenarioDriver,
    deal_state: DealState,
) -> None:
    report = hosted_scenario_driver.run_collection(deal_state)
    assert report.evidence == "simulated"
    assert report.mechanism == "fiat.stripe.v1"
    assert report.marketplace_status == "collected"
    assert report.authority_status == "collected"
    assert report.effect_kind == "transfer"


def test_false_condition_expires_and_reclaims_once(
    hosted_scenario_driver: HostedScenarioDriver,
    deal_state: DealState,
) -> None:
    report = hosted_scenario_driver.run_expiry_reclaim(
        deal_state,
        advance_seconds=3601,
    )
    assert report.evidence == "simulated"
    assert report.marketplace_status == "reclaimed"
    assert report.authority_status == "reclaimed"
    assert report.effect_kind == "refund"


@pytest.mark.parametrize("case", EVENT_CASES, ids=lambda case: case.name)
def test_event_delivery_converges_without_duplicate_effects(
    hermetic_recovery_driver: HermeticRecoveryDriver,
    case,
) -> None:
    report = hermetic_recovery_driver.run_event_case(case)
    assert report.effect_kind == "transfer"


@pytest.mark.parametrize(
    "case",
    UNCERTAINTY_CASES,
    ids=lambda case: f"{case.effect}-{case.outcome}",
)
def test_provider_uncertainty_recovers_by_stable_operation_ref(
    hermetic_recovery_driver: HermeticRecoveryDriver,
    case,
) -> None:
    report = hermetic_recovery_driver.run_uncertainty_case(case)
    assert report.effect_kind == case.effect
    assert report.operation_ref


@pytest.mark.parametrize(
    "case",
    RESTART_CASES,
    ids=lambda case: f"{case.component}-{case.boundary}",
)
def test_preserved_store_restart_resumes_accepted_obligation(
    hermetic_recovery_driver: HermeticRecoveryDriver,
    case,
) -> None:
    report = hermetic_recovery_driver.run_restart_case(case)
    assert report.mechanism == "fiat.stripe.v1"
    assert report.effect_kind == "transfer"


@pytest.mark.parametrize("case", MECHANISM_CASES, ids=lambda case: case.name)
def test_dual_mechanism_readiness_priority_and_pinning(mechanism_port, case) -> None:
    assert run_mechanism_case(mechanism_port, case) == case.expected
