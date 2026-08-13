from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EffectKind = Literal["transfer", "refund"]
OutcomeKind = Literal[
    "retryable_before_submission",
    "timeout_before_submission",
    "unknown_after_submission",
    "delayed_visibility",
]
RestartComponent = Literal["authority_api", "authority_worker", "storefront"]
RestartBoundary = Literal[
    "materialization", "funding", "fulfillment_evidence", "provider_submission"
]

_EFFECT_KINDS: tuple[EffectKind, ...] = ("transfer", "refund")
_OUTCOME_KINDS: tuple[OutcomeKind, ...] = (
    "retryable_before_submission",
    "timeout_before_submission",
    "unknown_after_submission",
    "delayed_visibility",
)
_RESTART_COMPONENTS: tuple[RestartComponent, ...] = (
    "authority_api",
    "authority_worker",
    "storefront",
)
_RESTART_BOUNDARIES: tuple[RestartBoundary, ...] = (
    "materialization",
    "funding",
    "fulfillment_evidence",
    "provider_submission",
)


@dataclass(frozen=True)
class EventCase:
    name: str
    action: Literal["withhold", "duplicate", "reorder"]
    authoritative_retrieval: bool


EVENT_CASES = (
    EventCase("withheld_event", "withhold", True),
    EventCase("duplicate_event", "duplicate", True),
    EventCase("out_of_order_event", "reorder", True),
)


@dataclass(frozen=True)
class UncertaintyCase:
    effect: EffectKind
    outcome: OutcomeKind
    restart_component: Literal["authority_api", "authority_worker"]


UNCERTAINTY_CASES = tuple(
    UncertaintyCase(
        effect=effect,
        outcome=outcome,
        restart_component=(
            "authority_api" if outcome == "timeout_before_submission" else "authority_worker"
        ),
    )
    for effect in _EFFECT_KINDS
    for outcome in _OUTCOME_KINDS
)


@dataclass(frozen=True)
class RestartCase:
    component: RestartComponent
    boundary: RestartBoundary


RESTART_CASES = tuple(
    RestartCase(component, boundary)
    for component in _RESTART_COMPONENTS
    for boundary in _RESTART_BOUNDARIES
)


@dataclass(frozen=True)
class MechanismCase:
    name: str
    priority: tuple[str, ...]
    stripe_ready: bool
    alkahest_ready: bool
    expected: str | None
    recovery: bool = False
    mutate_after_acceptance: bool = False


MECHANISM_CASES = (
    MechanismCase("hosted_only", ("fiat.stripe.v1",), True, False, "fiat.stripe.v1"),
    MechanismCase("alkahest_only", ("alkahest.v1",), False, True, "alkahest.v1"),
    MechanismCase(
        "both_ready_stripe_first",
        ("fiat.stripe.v1", "alkahest.v1"),
        True,
        True,
        "fiat.stripe.v1",
    ),
    MechanismCase(
        "both_ready_alkahest_first",
        ("alkahest.v1", "fiat.stripe.v1"),
        True,
        True,
        "alkahest.v1",
    ),
    MechanismCase(
        "stripe_unready", ("fiat.stripe.v1", "alkahest.v1"), False, True, "alkahest.v1"
    ),
    MechanismCase(
        "alkahest_unready", ("alkahest.v1", "fiat.stripe.v1"), True, False, "fiat.stripe.v1"
    ),
    MechanismCase("none_ready", ("fiat.stripe.v1", "alkahest.v1"), False, False, None),
    MechanismCase(
        "readiness_recovery",
        ("fiat.stripe.v1", "alkahest.v1"),
        True,
        False,
        "fiat.stripe.v1",
        recovery=True,
    ),
    MechanismCase(
        "priority_changes_after_acceptance",
        ("fiat.stripe.v1", "alkahest.v1"),
        True,
        True,
        "fiat.stripe.v1",
        mutate_after_acceptance=True,
    ),
    MechanismCase(
        "enablement_changes_after_acceptance",
        ("fiat.stripe.v1", "alkahest.v1"),
        True,
        True,
        "fiat.stripe.v1",
        mutate_after_acceptance=True,
    ),
)


@dataclass(frozen=True)
class EasConditionCase:
    name: str
    arbiter_allowlisted: bool
    attestation_satisfied: bool
    expected_condition_state: Literal["ready", "failed"]


EAS_CONDITION_CASES = (
    EasConditionCase("allowlisted_satisfied", True, True, "ready"),
    EasConditionCase("allowlisted_unsatisfied", True, False, "failed"),
    EasConditionCase("unallowlisted_arbiter", False, True, "failed"),
)
