from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .cases import (
    EAS_CONDITION_CASES,
    EVENT_CASES,
    MECHANISM_CASES,
    RESTART_CASES,
    UNCERTAINTY_CASES,
    EasConditionCase,
    EventCase,
    MechanismCase,
    RestartCase,
    UncertaintyCase,
)
from .control import ReleasedControlCli, stable_operation_ref
from .driver import HostedEvidenceReport, HostedScenarioDriver
from .funding import PrivateFundingDriver
from .state import DealState, require_state


class ProcessRestarter(Protocol):
    def restart(self, component: str, *, preserve_state: bool) -> None: ...


class MechanismPort(Protocol):
    def configure(
        self,
        *,
        priority: tuple[str, ...],
        stripe_ready: bool,
        alkahest_ready: bool,
    ) -> None: ...

    def selected_mechanism(self) -> str | None: ...

    def recover_readiness(self) -> None: ...

    def mutate_after_acceptance(self) -> None: ...

    def existing_operation_mechanism(self) -> str: ...


class EasConditionPort(Protocol):
    def assert_local_anvil_eas_profile(self) -> None: ...

    def evaluate_allowlisted_arbiter(
        self, *, arbiter_allowlisted: bool, attestation_satisfied: bool
    ) -> str: ...


@dataclass
class HermeticRecoveryDriver:
    scenario: HostedScenarioDriver
    control: ReleasedControlCli
    funding: PrivateFundingDriver
    restarter: ProcessRestarter

    def run_event_case(self, case: EventCase) -> HostedEvidenceReport:
        self.funding.event_action = case.action
        state = DealState()
        report = self.scenario.run_collection(state)
        if case.authoritative_retrieval and report.authority_status != "collected":
            raise AssertionError("withheld event did not converge by authoritative retrieval")
        if report.effect_kind != "transfer" or state.effect_count != 1:
            raise AssertionError("event replay changed exactly-once transfer semantics")
        return report

    def run_uncertainty_case(self, case: UncertaintyCase) -> HostedEvidenceReport:
        state, action = self._materialized()
        operation_prefix = "collect" if case.effect == "transfer" else "reclaim"
        operation_ref = stable_operation_ref(operation_prefix, state.settlement_ref or "")
        self.control.plan_outcome(
            operation_ref=operation_ref,
            outcomes=({"kind": case.outcome},),
            request_id=stable_operation_ref("request-plan", operation_ref),
        )
        self.scenario.fund(state, action)
        self.scenario.fulfill(state)
        if case.effect == "refund":
            if self.scenario.clock is None:
                raise RuntimeError("refund uncertainty requires controlled clock")
            if state.condition_decision != "unsatisfied":
                raise AssertionError("refund uncertainty requires a false condition")
            self.scenario.clock.advance_clock(
                seconds=3601,
                request_id=stable_operation_ref(
                    "request-advance-refund", state.settlement_ref or ""
                ),
            )
        elif state.condition_decision != "satisfied":
            raise AssertionError("transfer uncertainty requires a satisfied condition")
        self.restarter.restart(case.restart_component, preserve_state=True)
        self.scenario.observe_terminal(state, reclaim=case.effect == "refund")
        if state.effect_operation_ref != operation_ref:
            raise AssertionError("recovery changed the stable provider operation identity")
        return self.scenario.terminal_report(state)

    def run_restart_case(self, case: RestartCase) -> HostedEvidenceReport:
        state = DealState()
        self.scenario.verify_composition(state)
        self.scenario.verify_runtime(state)
        self.scenario.publish_listing(state)
        self.scenario.discover(state)
        self.scenario.negotiate(state)
        action = self.scenario.materialize(state)
        if case.boundary == "materialization":
            self.restarter.restart(case.component, preserve_state=True)
        self.scenario.fund(state, action)
        if case.boundary == "funding":
            self.restarter.restart(case.component, preserve_state=True)
        self.scenario.fulfill(state)
        if case.boundary == "fulfillment_evidence":
            self.restarter.restart(case.component, preserve_state=True)
        if state.condition_decision != "satisfied":
            raise AssertionError("restart collection requires a satisfied condition")
        if case.boundary == "provider_submission":
            operation_ref = stable_operation_ref("collect", state.settlement_ref or "")
            self.control.plan_outcome(
                operation_ref=operation_ref,
                outcomes=({"kind": "unknown_after_submission"},),
                request_id=stable_operation_ref("request-plan-restart", operation_ref),
            )
            self.restarter.restart(case.component, preserve_state=True)
        self.scenario.observe_terminal(state)
        if state.accepted_mechanism != "fiat.stripe.v1":
            raise AssertionError("restart rematerialized through a fallback mechanism")
        return self.scenario.terminal_report(state)

    def _materialized(self):
        state = DealState()
        self.scenario.verify_composition(state)
        self.scenario.verify_runtime(state)
        self.scenario.publish_listing(state)
        self.scenario.discover(state)
        self.scenario.negotiate(state)
        action = self.scenario.materialize(state)
        require_state(state, "accepted_mechanism", "settlement_ref")
        return state, action


def run_mechanism_case(port: MechanismPort, case: MechanismCase) -> str | None:
    port.configure(
        priority=case.priority,
        stripe_ready=case.stripe_ready,
        alkahest_ready=case.alkahest_ready,
    )
    selected = port.selected_mechanism()
    if selected != case.expected:
        raise AssertionError(
            f"mechanism readiness/priority selected {selected!r}, expected {case.expected!r}"
        )
    if case.recovery:
        port.recover_readiness()
        selected = port.selected_mechanism()
        if selected != case.expected:
            raise AssertionError("readiness recovery did not restore deterministic selection")
    if case.mutate_after_acceptance:
        accepted = selected
        port.mutate_after_acceptance()
        if port.existing_operation_mechanism() != accepted:
            raise AssertionError("post-acceptance configuration changed the pinned mechanism")
    return selected


def run_eas_condition_case(port: EasConditionPort, case: EasConditionCase) -> str:
    """Run only the local EAS condition boundary; finance stays simulated."""

    port.assert_local_anvil_eas_profile()
    state = port.evaluate_allowlisted_arbiter(
        arbiter_allowlisted=case.arbiter_allowlisted,
        attestation_satisfied=case.attestation_satisfied,
    )
    if state != case.expected_condition_state:
        raise AssertionError(
            f"local EAS condition state {state!r}, expected {case.expected_condition_state!r}"
        )
    return state


__all__ = [
    "EAS_CONDITION_CASES",
    "EVENT_CASES",
    "MECHANISM_CASES",
    "RESTART_CASES",
    "UNCERTAINTY_CASES",
    "EasConditionPort",
    "HermeticRecoveryDriver",
    "MechanismPort",
    "ProcessRestarter",
    "run_eas_condition_case",
    "run_mechanism_case",
]
