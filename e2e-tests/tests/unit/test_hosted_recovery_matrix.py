from __future__ import annotations

from tests.e2e.roles.scenarios.vms.hosted.cases import (
    EAS_CONDITION_CASES,
    EVENT_CASES,
    MECHANISM_CASES,
    RESTART_CASES,
    UNCERTAINTY_CASES,
)
from tests.e2e.roles.scenarios.vms.hosted.recovery import (
    run_eas_condition_case,
    run_mechanism_case,
)


def test_event_matrix_covers_withheld_duplicate_and_out_of_order() -> None:
    assert {case.action for case in EVENT_CASES} == {"withhold", "duplicate", "reorder"}
    assert all(case.authoritative_retrieval for case in EVENT_CASES)


def test_transfer_and_refund_cover_all_uncertainty_modes_and_restart_boundaries() -> None:
    expected = {
        "retryable_before_submission",
        "timeout_before_submission",
        "unknown_after_submission",
        "delayed_visibility",
    }
    for effect in ("transfer", "refund"):
        assert {case.outcome for case in UNCERTAINTY_CASES if case.effect == effect} == expected
    assert {
        case.restart_component
        for case in UNCERTAINTY_CASES
        if case.outcome == "timeout_before_submission"
    } == {"authority_api"}
    assert {
        case.restart_component
        for case in UNCERTAINTY_CASES
        if case.outcome == "unknown_after_submission"
    } == {"authority_worker"}


def test_restart_matrix_covers_api_worker_storefront_and_all_durable_boundaries() -> None:
    assert {case.component for case in RESTART_CASES} == {
        "authority_api",
        "authority_worker",
        "storefront",
    }
    assert {case.boundary for case in RESTART_CASES} == {
        "materialization",
        "funding",
        "fulfillment_evidence",
        "provider_submission",
    }
    assert len(RESTART_CASES) == 12


class Mechanisms:
    def __init__(self):
        self.selected = None
        self.accepted = None

    def configure(self, *, priority, stripe_ready, alkahest_ready):
        ready = {
            "fiat.stripe.v1": stripe_ready,
            "alkahest.v1": alkahest_ready,
        }
        self.selected = next((item for item in priority if ready[item]), None)
        self.accepted = self.selected

    def selected_mechanism(self):
        return self.selected

    def recover_readiness(self):
        pass

    def mutate_after_acceptance(self):
        self.selected = "alkahest.v1"

    def existing_operation_mechanism(self):
        return self.accepted


def test_mechanism_matrix_covers_readiness_priority_failure_recovery_and_pinning() -> None:
    names = {case.name for case in MECHANISM_CASES}
    assert {
        "hosted_only",
        "alkahest_only",
        "both_ready_stripe_first",
        "both_ready_alkahest_first",
        "stripe_unready",
        "alkahest_unready",
        "none_ready",
        "readiness_recovery",
        "priority_changes_after_acceptance",
        "enablement_changes_after_acceptance",
    } <= names
    for case in MECHANISM_CASES:
        assert run_mechanism_case(Mechanisms(), case) == case.expected


class EasPort:
    profile_checked = False

    def assert_local_anvil_eas_profile(self):
        self.profile_checked = True

    def evaluate_allowlisted_arbiter(
        self, *, arbiter_allowlisted, attestation_satisfied
    ):
        return "ready" if arbiter_allowlisted and attestation_satisfied else "failed"


def test_separate_eas_matrix_covers_allowlist_and_condition_decision_only() -> None:
    assert {case.name for case in EAS_CONDITION_CASES} == {
        "allowlisted_satisfied",
        "allowlisted_unsatisfied",
        "unallowlisted_arbiter",
    }
    for case in EAS_CONDITION_CASES:
        port = EasPort()
        assert run_eas_condition_case(port, case) == case.expected_condition_state
        assert port.profile_checked
