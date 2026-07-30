from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from issue_discovery.capacity import (
    CAPACITY_PROFILE_PATH,
    CapacityValidationError,
    canonical_sha256,
    retained_buyer_refinement_counts,
    resolve_pinned_profile_registry,
    select_buyer_refinement_counts,
)
from issue_discovery.capacity_outcomes import (
    ValidatedBuyerFrontierReceipt,
    ValidatedCapacityResult,
    ValidatedEvaluationPolicy,
    ValidatedReferencePolicy,
    maximum_half_open_overlap,
    select_seller_stages_from_results,
    validate_buyer_frontier_receipt,
    validate_capacity_result,
    validate_evaluation_policy,
    validate_reference_policy,
    validate_serialized_reuse,
)
from issue_discovery.capacity_roles import (
    ACTOR_INVOCATION_BINDING_DOMAIN,
    CUDA_RESULT_CHECKSUM,
    CUDA_SOURCE_PATH,
    CUDA_SUCCESS_MARKER,
    CUDA_WRAPPER_PATH,
    NATIVE_EVIDENCE_BINDING_DOMAIN,
    RUNTIME_BINDING_DOMAIN,
    TOPOLOGY_BINDING_DOMAIN,
    SubstantiveRoleEvidence,
    ValidatedActorSet,
    ValidatedOracleAuthority,
    validate_action_result,
    validate_actor_set_observation,
    validate_role_plan,
    validate_role_receipt,
    validate_substantive_actor_set,
    validate_substantive_role_evidence,
)
from test_capacity_roles import (
    RealChain,
    _oracle,
    _real_chain,
    _replace_host_observation,
    _role_evidence,
    _validated_plans,
    authority_repo as _roles_authority_repo,
    binding,
    digest,
    tracked,
)


_REVERSIBLE_COMPONENTS = (
    "capacity-reservations-and-leases",
    "settlement-resources",
    "fulfillment-provider-jobs",
    "vms",
    "disks",
    "networks",
    "ansible-processes",
    "gpu-assignments",
    "listing-service-set",
)
_ACCOUNTING_DELTA_CATEGORIES = (
    "deal-history",
    "settlement-history",
    "request-history",
    "escrow-claim-history",
    "transaction-fees",
    "wallet-accounting",
)
_ZERO_RESIDUE_COUNTS = {
    "capacity_reservations": 0,
    "settlement_resources": 0,
    "fulfillment_provider_jobs": 0,
    "vms": 0,
    "disks": 0,
    "networks": 0,
    "ansible_processes": 0,
    "gpu_assignments": 0,
    "active_claims": 0,
    "active_locks": 0,
}
_SELLER_MEASURED_STAGES = {
    "b2-s2-g1-measured",
    "b4-s2-g1-measured",
    "b4-s3-g1-measured",
    "b4-s4-g1-measured",
}


@dataclass(frozen=True)
class CapacityCase:
    chain: RealChain
    actor_set: ValidatedActorSet
    evaluation_policy: ValidatedEvaluationPolicy
    result_value: dict[str, Any]
    result: ValidatedCapacityResult
    buyer_frontier: ValidatedBuyerFrontierReceipt | None = None
    reuse_baseline: ValidatedCapacityResult | None = None
    prior_seller_results: tuple[ValidatedCapacityResult, ...] = ()


@dataclass(frozen=True)
class ReferenceCase:
    oracle: ValidatedOracleAuthority
    reference_policy: ValidatedReferencePolicy
    evidence: tuple[SubstantiveRoleEvidence, ...]
    evaluation_policy: ValidatedEvaluationPolicy
    result_value: dict[str, Any]
    result: ValidatedCapacityResult


@pytest.fixture(scope="module")
def outcome_authority_repo(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, str]:
    return _roles_authority_repo.__wrapped__(
        tmp_path_factory.mktemp("capacity-outcomes-authority")
    )


def _validated_evaluation_policy(
    repo: Path,
    scm_ref: str,
) -> ValidatedEvaluationPolicy:
    registry = resolve_pinned_profile_registry(repo, scm_ref)
    value = {
        "schema_version": 2,
        "evaluation_policy_id": "g1-capacity-policy",
        "scm_ref": scm_ref,
        "profile_registry": {
            "path": CAPACITY_PROFILE_PATH.as_posix(),
            "canonical_sha256": registry.canonical_sha256,
            "raw_sha256": registry.raw_sha256,
        },
        "frozen_at": "2026-07-30T09:59:00.000000Z",
        "frozen_before_q0": True,
        "clock_evidence_binding": binding(
            NATIVE_EVIDENCE_BINDING_DOMAIN,
            "evaluation-policy-clock",
        ),
        "request_processing_slo_ns": 1_000,
        "provisioning_queue_slo_ns": 100,
        "ansible_service_slo_ns": 100,
        "terminal_observation_timeout_ns": 1_000,
        "frontier_definitions": {
            "request_processing": (
                "all-expected-terminal-within-slo-without-generator-saturation"
            ),
            "simultaneous_fulfillment": (
                "maximum-independent-overlapping-whole-gpu-vms"
            ),
            "provisioning": "greatest-shape-meeting-queue-and-ansible-slos",
            "correctness": ("greatest-shape-with-complete-oracle-cleanup-and-baseline"),
            "load_generator": (
                "greatest-shape-with-overlap-skew-liveness-and-no-local-queue"
            ),
        },
    }
    return validate_evaluation_policy(
        value,
        repo,
        expected_scm_ref=scm_ref,
    )


def _evaluation_policy_with_request_slo(
    policy: ValidatedEvaluationPolicy,
    request_processing_slo_ns: int,
) -> ValidatedEvaluationPolicy:
    value = policy.policy
    value["evaluation_policy_id"] = (
        f"g1-capacity-policy-slo-{request_processing_slo_ns}"
    )
    value["request_processing_slo_ns"] = request_processing_slo_ns
    return validate_evaluation_policy(
        value,
        policy.repo_root,
        expected_scm_ref=policy.scm_ref,
    )


def _clean_stage_observation(
    chain: RealChain,
) -> tuple[ValidatedActorSet, dict[str, Any]]:
    actor_set = validate_substantive_actor_set(
        chain.actor_set,
        chain.policy,
        chain.evidence,
    )
    host = next(
        evidence for evidence in chain.evidence if evidence.plan.role == "host-operator"
    )
    observer = next(
        evidence for evidence in chain.evidence if evidence.plan.role == "observer"
    )
    buyer = next(
        evidence for evidence in chain.evidence if evidence.plan.role == "buyer"
    )
    host_observation = host.receipt.receipt["role_evidence"]
    observer_observation = observer.receipt.receipt["role_evidence"]
    buyer_plan = buyer.plan.plan["role_plan"]
    actor_value = actor_set.actor_set
    buyer_action = next(
        action
        for action in actor_value["actions"]
        if action["actor_slot"] == buyer.plan.actor_slot
        and action["action_kind"] == "buyer-request"
    )
    listing = next(
        item
        for item in actor_value["runtime_listing_bindings"]
        if item["seller_slot"] == "seller-1" and item["listing_slot"] == "listing-1"
    )

    invoked_offset_ns = buyer_action["invoked_offset_ns"]
    terminal_offset_ns = invoked_offset_ns + 80
    fulfillment_id = "buyer-1-fulfillment"
    capacity_reservation_id = "request-1-reservation"
    common_clock_binding = actor_value["clock_evidence_binding"]
    request_outcome = {
        "request_id": "request-1",
        "outcome_kind": "vm-succeeded",
        "deal_reference": {
            "request_id": "request-1",
            "seller_slot": "seller-1",
            "listing_slot": "listing-1",
            "runtime_binding": listing["runtime_binding"],
            "negotiation_reference_sha256": digest("request-1-negotiation"),
            "escrow_reference_sha256": digest("request-1-escrow"),
        },
        "invoked_offset_ns": invoked_offset_ns,
        "terminal_offset_ns": terminal_offset_ns,
        "capacity_reservation_id": capacity_reservation_id,
        "fulfillment_id": fulfillment_id,
        "settlement_record": {
            "capacity_reservation_id": capacity_reservation_id,
            "fulfillment_id": fulfillment_id,
            "state": "torn_down",
            "selected_resource_binding": binding(
                NATIVE_EVIDENCE_BINDING_DOMAIN,
                "request-1-selected-resource",
            ),
            "active_claim": False,
        },
        "provisioned_resource_id": "request-1-vm",
        "allocation_id": "request-1-allocation",
        "provisioning_job_id": "request-1-provisioning",
        "commercial_resolution": {
            "deal_state": "fulfilled-terminal",
            "escrow_state": "released",
            "failure_policy_state": "not-applicable",
            "zero_active_claims": True,
            "zero_active_locks": True,
            "zero_run_owned_funds": True,
        },
        "independent_observation_bindings": [
            binding(
                NATIVE_EVIDENCE_BINDING_DOMAIN,
                "request-1-independent-observation",
            )
        ],
        "request_cleanup": {
            "teardown_complete": True,
            "zero_active_residue": True,
            "native_evidence_binding": binding(
                NATIVE_EVIDENCE_BINDING_DOMAIN,
                "request-1-cleanup",
            ),
        },
        "failure_category": None,
        "success_observation": {
            "reservation_fulfillment_join": {
                "fulfillment_capacity_reservation_id": (capacity_reservation_id),
                "settlement_capacity_reservation_id": (capacity_reservation_id),
                "settlement_fulfillment_id": fulfillment_id,
                "provisioned_fulfillment_id": fulfillment_id,
            },
            "provisioning": {
                "provisioning_kind": "real-kvm-ansible",
                "gpu_assignment": "whole-device-passthrough",
                "queue_wait_ns": 10,
                "ansible_service_ns": 20,
                "output_observed": True,
            },
            "gpu_exercise": {
                "fulfillment_id": fulfillment_id,
                "ssh_resumed": True,
                "visible_gpus": 1,
                "wrapper": buyer_plan["guest_exercise"]["wrapper"],
                "source": buyer_plan["guest_exercise"]["source"],
                "compiled": True,
                "device_kernel_executed": True,
                "success_marker": CUDA_SUCCESS_MARKER,
                "result_checksum": CUDA_RESULT_CHECKSUM,
                "native_evidence_binding": binding(
                    NATIVE_EVIDENCE_BINDING_DOMAIN,
                    "request-1-guest-exercise",
                ),
            },
            "active_interval": {
                "start_offset_ns": invoked_offset_ns + 10,
                "end_offset_ns": terminal_offset_ns - 10,
                "interval_semantics": "half-open",
                "clock_evidence_binding": common_clock_binding,
            },
        },
    }
    cleanup = {
        "terminal_correlations_complete": True,
        "teardown_complete": True,
        "residue_counts": dict(_ZERO_RESIDUE_COUNTS),
        "reversible_baseline_binding": host_observation["reversible_baseline_binding"],
        "baseline_equivalence_binding": host_observation[
            "baseline_equivalence_binding"
        ],
        "reversible_components": [
            {
                "component": component,
                "exactly_equal": True,
                "native_evidence_binding": binding(
                    NATIVE_EVIDENCE_BINDING_DOMAIN,
                    f"cleanup-component:{component}",
                ),
            }
            for component in _REVERSIBLE_COMPONENTS
        ],
        "accounting_deltas": [
            {
                "category": category,
                "expected_delta_binding": binding(
                    NATIVE_EVIDENCE_BINDING_DOMAIN,
                    f"expected-accounting-delta:{category}",
                ),
                "observed_delta_binding": binding(
                    NATIVE_EVIDENCE_BINDING_DOMAIN,
                    f"observed-accounting-delta:{category}",
                ),
                "reconciled": True,
                "active_lock": False,
                "unexplained_value": False,
            }
            for category in _ACCOUNTING_DELTA_CATEGORIES
        ],
        "native_evidence_bindings": [
            binding(
                NATIVE_EVIDENCE_BINDING_DOMAIN,
                "complete-stage-cleanup",
            ),
            *observer_observation["native_evidence_bindings"],
        ],
        "ready_for_next_stage": True,
    }
    request_outcome["independent_observation_bindings"].append(
        observer_observation["native_evidence_bindings"][0]
    )
    return actor_set, {
        "request_outcome": request_outcome,
        "cleanup": cleanup,
        "topology_authority_binding": host_observation["topology_authority_binding"],
        "observer_native_evidence_bindings": observer_observation[
            "native_evidence_bindings"
        ],
    }


def _clean_cleanup_from_evidence(
    evidence: Sequence[SubstantiveRoleEvidence],
    *,
    identity_prefix: str,
) -> dict[str, Any]:
    host = next(item for item in evidence if item.plan.role == "host-operator")
    host_observation = host.receipt.receipt["role_evidence"]
    observer = next(item for item in evidence if item.plan.role == "observer")
    observer_bindings = observer.receipt.receipt["role_evidence"][
        "native_evidence_bindings"
    ]
    return {
        "terminal_correlations_complete": True,
        "teardown_complete": True,
        "residue_counts": dict(_ZERO_RESIDUE_COUNTS),
        "reversible_baseline_binding": host_observation["reversible_baseline_binding"],
        "baseline_equivalence_binding": host_observation[
            "baseline_equivalence_binding"
        ],
        "reversible_components": [
            {
                "component": component,
                "exactly_equal": True,
                "native_evidence_binding": binding(
                    NATIVE_EVIDENCE_BINDING_DOMAIN,
                    f"{identity_prefix}:component:{component}",
                ),
            }
            for component in _REVERSIBLE_COMPONENTS
        ],
        "accounting_deltas": [
            {
                "category": category,
                "expected_delta_binding": binding(
                    NATIVE_EVIDENCE_BINDING_DOMAIN,
                    f"{identity_prefix}:expected:{category}",
                ),
                "observed_delta_binding": binding(
                    NATIVE_EVIDENCE_BINDING_DOMAIN,
                    f"{identity_prefix}:observed:{category}",
                ),
                "reconciled": True,
                "active_lock": False,
                "unexplained_value": False,
            }
            for category in _ACCOUNTING_DELTA_CATEGORIES
        ],
        "native_evidence_bindings": [
            binding(
                NATIVE_EVIDENCE_BINDING_DOMAIN,
                f"{identity_prefix}:cleanup",
            ),
            *observer_bindings,
        ],
        "ready_for_next_stage": True,
    }


def _seal_observer_result_evidence(
    evidence: Sequence[SubstantiveRoleEvidence],
    *,
    request_outcomes: Sequence[Mapping[str, Any]],
    cleanup: Mapping[str, Any],
    stage_started_at: str,
    terminal_observed_at: str,
    cleanup_completed_at: str,
) -> tuple[SubstantiveRoleEvidence, ...]:
    sealed: list[SubstantiveRoleEvidence] = []
    for item in evidence:
        if item.plan.role != "observer":
            sealed.append(item)
            continue
        receipt_value = item.receipt.receipt
        role_evidence = receipt_value["role_evidence"]
        native_binding = role_evidence["native_evidence_bindings"][0]
        role_evidence["request_observations"] = [
            {
                "request_id": outcome["request_id"],
                "request_outcome_sha256": canonical_sha256(outcome),
                "native_evidence_binding": native_binding,
            }
            for outcome in request_outcomes
        ]
        role_evidence["cleanup_observation"] = {
            "cleanup_sha256": canonical_sha256(cleanup),
            "stage_started_at": stage_started_at,
            "terminal_observed_at": terminal_observed_at,
            "cleanup_completed_at": cleanup_completed_at,
            "clock_evidence_binding": binding(
                NATIVE_EVIDENCE_BINDING_DOMAIN,
                "evaluation-policy-clock",
            ),
            "native_evidence_binding": native_binding,
        }
        receipt = validate_role_receipt(receipt_value, item.plan)
        sealed.append(
            validate_substantive_role_evidence(
                item.plan,
                receipt,
                item.actions,
                item.results,
            )
        )
    return tuple(sealed)


def _rebind_actor_set_observer_receipt(
    chain: RealChain,
    *,
    request_outcomes: Sequence[Mapping[str, Any]],
    cleanup: Mapping[str, Any],
    stage_started_at: str,
    terminal_observed_at: str,
    cleanup_completed_at: str,
) -> ValidatedActorSet:
    sealed_evidence = _seal_observer_result_evidence(
        chain.evidence,
        request_outcomes=request_outcomes,
        cleanup=cleanup,
        stage_started_at=stage_started_at,
        terminal_observed_at=terminal_observed_at,
        cleanup_completed_at=cleanup_completed_at,
    )
    observer = next(item for item in sealed_evidence if item.plan.role == "observer")
    next(
        actor
        for actor in chain.actor_set["actors"]
        if actor["actor_slot"] == observer.plan.actor_slot
    )["receipt_sha256"] = observer.receipt.canonical_sha256
    chain.evidence = list(sealed_evidence)
    return validate_actor_set_observation(
        chain.actor_set,
        chain.policy,
        chain.evidence,
    )


def _request_authority(
    chain: RealChain,
    actor_set: ValidatedActorSet,
    request_id: str,
) -> dict[str, Any]:
    stage = chain.plans[0].profile_stage
    assert stage.scenario is not None
    request = next(
        item
        for item in stage.scenario.scenario["requests"]
        if item["request_id"] == request_id
    )
    buyer = next(
        item
        for item in chain.evidence
        if item.plan.role == "buyer"
        and item.plan.plan["role_plan"]["request_id"] == request_id
    )
    actor_value = actor_set.actor_set
    action = next(
        item
        for item in actor_value["actions"]
        if item["actor_slot"] == request["buyer_slot"]
        and item["action_kind"] == "buyer-request"
    )
    actor = next(
        item
        for item in actor_value["actors"]
        if item["actor_slot"] == request["buyer_slot"]
    )
    listing = next(
        item
        for item in actor_value["runtime_listing_bindings"]
        if item["seller_slot"] == request["seller_slot"]
        and item["listing_slot"] == request["listing_slot"]
    )
    invoked = action["invoked_offset_ns"]
    terminal = min(invoked + 80, actor["completed_offset_ns"] - 1)
    assert action["terminal_offset_ns"] <= terminal
    return {
        "request": request,
        "buyer": buyer,
        "action": action,
        "actor": actor,
        "runtime_binding": listing["runtime_binding"],
        "invoked_offset_ns": invoked,
        "terminal_offset_ns": terminal,
    }


def _deal_reference(
    authority: Mapping[str, Any],
    *,
    identity_prefix: str,
) -> dict[str, Any]:
    request = authority["request"]
    return {
        "request_id": request["request_id"],
        "seller_slot": request["seller_slot"],
        "listing_slot": request["listing_slot"],
        "runtime_binding": authority["runtime_binding"],
        "negotiation_reference_sha256": digest(f"{identity_prefix}:negotiation"),
        "escrow_reference_sha256": digest(f"{identity_prefix}:escrow"),
    }


def _successful_request_outcome(
    chain: RealChain,
    actor_set: ValidatedActorSet,
    request_id: str,
    *,
    identity_prefix: str,
) -> dict[str, Any]:
    authority = _request_authority(chain, actor_set, request_id)
    buyer = authority["buyer"]
    guest = buyer.receipt.receipt["role_evidence"]["guest_verification"]
    assert isinstance(guest, dict)
    fulfillment_id = guest["fulfillment_id"]
    reservation_id = f"{identity_prefix}-reservation"
    common_clock = actor_set.actor_set["clock_evidence_binding"]
    invoked = authority["invoked_offset_ns"]
    terminal = authority["terminal_offset_ns"]
    guest_exercise = buyer.plan.plan["role_plan"]["guest_exercise"]
    return {
        "request_id": request_id,
        "outcome_kind": "vm-succeeded",
        "deal_reference": _deal_reference(
            authority,
            identity_prefix=identity_prefix,
        ),
        "invoked_offset_ns": invoked,
        "terminal_offset_ns": terminal,
        "capacity_reservation_id": reservation_id,
        "fulfillment_id": fulfillment_id,
        "settlement_record": {
            "capacity_reservation_id": reservation_id,
            "fulfillment_id": fulfillment_id,
            "state": "torn_down",
            "selected_resource_binding": binding(
                NATIVE_EVIDENCE_BINDING_DOMAIN,
                f"{identity_prefix}:selected-resource",
            ),
            "active_claim": False,
        },
        "provisioned_resource_id": f"{identity_prefix}-vm",
        "allocation_id": f"{identity_prefix}-allocation",
        "provisioning_job_id": f"{identity_prefix}-provisioning",
        "commercial_resolution": {
            "deal_state": "fulfilled-terminal",
            "escrow_state": "released",
            "failure_policy_state": "not-applicable",
            "zero_active_claims": True,
            "zero_active_locks": True,
            "zero_run_owned_funds": True,
        },
        "independent_observation_bindings": [
            binding(
                NATIVE_EVIDENCE_BINDING_DOMAIN,
                f"{identity_prefix}:independent-observation",
            )
        ],
        "request_cleanup": {
            "teardown_complete": True,
            "zero_active_residue": True,
            "native_evidence_binding": binding(
                NATIVE_EVIDENCE_BINDING_DOMAIN,
                f"{identity_prefix}:request-cleanup",
            ),
        },
        "failure_category": None,
        "success_observation": {
            "reservation_fulfillment_join": {
                "fulfillment_capacity_reservation_id": reservation_id,
                "settlement_capacity_reservation_id": reservation_id,
                "settlement_fulfillment_id": fulfillment_id,
                "provisioned_fulfillment_id": fulfillment_id,
            },
            "provisioning": {
                "provisioning_kind": "real-kvm-ansible",
                "gpu_assignment": "whole-device-passthrough",
                "queue_wait_ns": 10,
                "ansible_service_ns": 20,
                "output_observed": True,
            },
            "gpu_exercise": {
                "fulfillment_id": fulfillment_id,
                "ssh_resumed": True,
                "visible_gpus": 1,
                "wrapper": guest_exercise["wrapper"],
                "source": guest_exercise["source"],
                "compiled": True,
                "device_kernel_executed": True,
                "success_marker": CUDA_SUCCESS_MARKER,
                "result_checksum": CUDA_RESULT_CHECKSUM,
                "native_evidence_binding": binding(
                    NATIVE_EVIDENCE_BINDING_DOMAIN,
                    f"{identity_prefix}:guest-exercise",
                ),
            },
            "active_interval": {
                "start_offset_ns": invoked + 10,
                "end_offset_ns": terminal - 10,
                "interval_semantics": "half-open",
                "clock_evidence_binding": common_clock,
            },
        },
    }


def _atomic_reservation_observation(
    deal_reference: Mapping[str, Any],
    *,
    identity_prefix: str,
    invoked_offset_ns: int,
    clock_evidence_binding: Mapping[str, Any],
    response_kind: str = "routine-reservation-null",
    final: bool = True,
    commercial_error: str | None = None,
    reservation_id: str | None = None,
    observed: bool = True,
    skipped: bool = False,
) -> dict[str, Any]:
    routine = response_kind == "routine-reservation-null"
    return {
        "final_escrow_scoped_call": final,
        "deal_reference_sha256": canonical_sha256(dict(deal_reference)),
        "started_offset_ns": invoked_offset_ns + 5,
        "completed_offset_ns": invoked_offset_ns + 10,
        "clock_evidence_binding": dict(clock_evidence_binding),
        "eligible_site_set_binding": binding(
            NATIVE_EVIDENCE_BINDING_DOMAIN,
            f"{identity_prefix}:eligible-sites",
        ),
        "eligible_site_slots": ["site-1"],
        "site_attempts": [
            {
                "site_slot": "site-1",
                "site_binding": binding(
                    NATIVE_EVIDENCE_BINDING_DOMAIN,
                    f"{identity_prefix}:site-1",
                ),
                "response_kind": response_kind,
                "reservation_id": reservation_id,
                "error_category": commercial_error,
                "observed": observed,
                "skipped": skipped,
            }
        ],
        "aggregate_reservation_id": None,
        "capacity_hold_unavailable_observed": not routine or not final,
    }


def _terminal_commercial_resolution(
    *,
    refused: bool,
) -> dict[str, Any]:
    return {
        "deal_state": ("refused-terminal" if refused else "failed-terminal"),
        "escrow_state": "refunded" if refused else "compensated",
        "failure_policy_state": "compensated",
        "zero_active_claims": True,
        "zero_active_locks": True,
        "zero_run_owned_funds": True,
    }


def _refused_request_outcome(
    chain: RealChain,
    actor_set: ValidatedActorSet,
    request_id: str,
    *,
    identity_prefix: str,
) -> dict[str, Any]:
    authority = _request_authority(chain, actor_set, request_id)
    deal = _deal_reference(authority, identity_prefix=identity_prefix)
    invoked = authority["invoked_offset_ns"]
    return {
        "request_id": request_id,
        "outcome_kind": "capacity-refused",
        "deal_reference": deal,
        "invoked_offset_ns": invoked,
        "terminal_offset_ns": authority["terminal_offset_ns"],
        "capacity_reservation_id": None,
        "fulfillment_id": None,
        "settlement_record": None,
        "provisioned_resource_id": None,
        "allocation_id": None,
        "provisioning_job_id": None,
        "commercial_resolution": _terminal_commercial_resolution(
            refused=True,
        ),
        "independent_observation_bindings": [
            binding(
                NATIVE_EVIDENCE_BINDING_DOMAIN,
                f"{identity_prefix}:independent-refusal",
            )
        ],
        "request_cleanup": {
            "teardown_complete": True,
            "zero_active_residue": True,
            "native_evidence_binding": binding(
                NATIVE_EVIDENCE_BINDING_DOMAIN,
                f"{identity_prefix}:refusal-cleanup",
            ),
        },
        "failure_category": None,
        "refusal_observation": _atomic_reservation_observation(
            deal,
            identity_prefix=identity_prefix,
            invoked_offset_ns=invoked,
            clock_evidence_binding=actor_set.actor_set["clock_evidence_binding"],
        ),
    }


def _fault_request_outcome(
    chain: RealChain,
    actor_set: ValidatedActorSet,
    request_id: str,
    *,
    identity_prefix: str,
    variant: str,
) -> dict[str, Any]:
    authority = _request_authority(chain, actor_set, request_id)
    deal = _deal_reference(authority, identity_prefix=identity_prefix)
    invoked = authority["invoked_offset_ns"]
    atomic: dict[str, Any] | None
    if variant == "swallowed-site-error":
        category = "atomic-refusal-incomplete"
        phase = "reservation"
        timed_out = False
        atomic = _atomic_reservation_observation(
            deal,
            identity_prefix=identity_prefix,
            invoked_offset_ns=invoked,
            clock_evidence_binding=actor_set.actor_set["clock_evidence_binding"],
            response_kind="error",
            commercial_error="site-rpc-failed",
        )
        commercial = _terminal_commercial_resolution(refused=False)
        request_clean = True
    elif variant == "missing-site-response":
        category = "atomic-refusal-incomplete"
        phase = "reservation"
        timed_out = False
        atomic = _atomic_reservation_observation(
            deal,
            identity_prefix=identity_prefix,
            invoked_offset_ns=invoked,
            clock_evidence_binding=actor_set.actor_set["clock_evidence_binding"],
            response_kind="missing",
        )
        commercial = _terminal_commercial_resolution(refused=False)
        request_clean = True
    elif variant == "skipped-site-response":
        category = "atomic-refusal-incomplete"
        phase = "reservation"
        timed_out = False
        atomic = _atomic_reservation_observation(
            deal,
            identity_prefix=identity_prefix,
            invoked_offset_ns=invoked,
            clock_evidence_binding=actor_set.actor_set["clock_evidence_binding"],
            response_kind="missing",
            observed=False,
            skipped=True,
        )
        commercial = _terminal_commercial_resolution(refused=False)
        request_clean = True
    elif variant == "reservation-created-site-response":
        category = "atomic-refusal-incomplete"
        phase = "reservation"
        timed_out = False
        atomic = _atomic_reservation_observation(
            deal,
            identity_prefix=identity_prefix,
            invoked_offset_ns=invoked,
            clock_evidence_binding=actor_set.actor_set["clock_evidence_binding"],
            response_kind="reservation-created",
            reservation_id=f"{identity_prefix}-partial-reservation",
        )
        commercial = _terminal_commercial_resolution(refused=False)
        request_clean = True
    elif variant == "nonterminal-complete-atomic":
        category = "uncompensated"
        phase = "settlement"
        timed_out = False
        atomic = _atomic_reservation_observation(
            deal,
            identity_prefix=identity_prefix,
            invoked_offset_ns=invoked,
            clock_evidence_binding=actor_set.actor_set["clock_evidence_binding"],
        )
        commercial = {
            "deal_state": "nonterminal",
            "escrow_state": "locked",
            "failure_policy_state": "pending",
            "zero_active_claims": False,
            "zero_active_locks": False,
            "zero_run_owned_funds": False,
        }
        request_clean = False
    elif variant == "timeout":
        category = "timeout"
        phase = "provisioning"
        timed_out = True
        atomic = None
        commercial = {
            "deal_state": "nonterminal",
            "escrow_state": "locked",
            "failure_policy_state": "pending",
            "zero_active_claims": False,
            "zero_active_locks": False,
            "zero_run_owned_funds": False,
        }
        request_clean = False
    elif variant == "generator-rejection":
        category = "generator-failure"
        phase = "pre-emission"
        timed_out = False
        atomic = None
        deal["negotiation_reference_sha256"] = None
        deal["escrow_reference_sha256"] = None
        commercial = _terminal_commercial_resolution(refused=False)
        request_clean = True
    elif variant in {
        "generic-failure",
        "provisioning-error",
        "policy-denial",
        "unknown-reason",
        "missing-durable-correlation",
        "cleanup-incomplete",
    }:
        category = variant
        phase = {
            "generic-failure": "negotiation",
            "provisioning-error": "provisioning",
            "policy-denial": "reservation",
            "unknown-reason": "settlement",
            "missing-durable-correlation": "settlement",
            "cleanup-incomplete": "cleanup",
        }[variant]
        timed_out = False
        atomic = None
        commercial = _terminal_commercial_resolution(refused=False)
        request_clean = variant != "cleanup-incomplete"
    else:
        raise AssertionError(f"unsupported test fault variant: {variant}")
    return {
        "request_id": request_id,
        "outcome_kind": "fault",
        "deal_reference": deal,
        "invoked_offset_ns": invoked,
        "terminal_offset_ns": authority["terminal_offset_ns"],
        "capacity_reservation_id": None,
        "fulfillment_id": None,
        "settlement_record": None,
        "provisioned_resource_id": None,
        "allocation_id": None,
        "provisioning_job_id": None,
        "commercial_resolution": commercial,
        "independent_observation_bindings": [
            binding(
                NATIVE_EVIDENCE_BINDING_DOMAIN,
                f"{identity_prefix}:independent-fault",
            )
        ],
        "request_cleanup": {
            "teardown_complete": request_clean,
            "zero_active_residue": request_clean,
            "native_evidence_binding": binding(
                NATIVE_EVIDENCE_BINDING_DOMAIN,
                f"{identity_prefix}:fault-cleanup",
            ),
        },
        "failure_category": category,
        "fault_observation": {
            "phase": phase,
            "timed_out": timed_out,
            "atomic_reservation_observation": atomic,
            "diagnostic_code": variant,
        },
    }


def _result_assessment(
    *,
    scenario: Mapping[str, Any],
    outcomes: Sequence[Mapping[str, Any]],
    evaluation_policy: ValidatedEvaluationPolicy,
    cleanup_passed: bool,
    load_generator_passed: bool,
    execution_boundary: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    observed = Counter(outcome["outcome_kind"] for outcome in outcomes)
    observed_counts = {
        "vm-succeeded": observed["vm-succeeded"],
        "capacity-refused": observed["capacity-refused"],
        "fault": observed["fault"],
    }
    outcomes_match = observed_counts == scenario["expected_outcomes"]
    maximum_latency = max(
        outcome["terminal_offset_ns"] - outcome["invoked_offset_ns"]
        for outcome in outcomes
    )
    success_intervals = [
        (
            outcome["success_observation"]["active_interval"]["start_offset_ns"],
            outcome["success_observation"]["active_interval"]["end_offset_ns"],
        )
        for outcome in outcomes
        if outcome["outcome_kind"] == "vm-succeeded"
    ]
    events = sorted(
        [
            (offset, delta)
            for start, end in success_intervals
            for offset, delta in ((start, 1), (end, -1))
        ],
        key=lambda item: (item[0], item[1]),
    )
    active = 0
    maximum_overlap = 0
    for _offset, delta in events:
        active += delta
        maximum_overlap = max(maximum_overlap, active)
    queue_waits = [
        outcome["success_observation"]["provisioning"]["queue_wait_ns"]
        for outcome in outcomes
        if outcome["outcome_kind"] == "vm-succeeded"
    ]
    ansible_services = [
        outcome["success_observation"]["provisioning"]["ansible_service_ns"]
        for outcome in outcomes
        if outcome["outcome_kind"] == "vm-succeeded"
    ]
    maximum_queue = max(queue_waits, default=0)
    maximum_ansible = max(ansible_services, default=0)
    request_processing = (
        outcomes_match
        and maximum_latency <= evaluation_policy.request_processing_slo_ns
        and maximum_latency < evaluation_policy.terminal_observation_timeout_ns
        and load_generator_passed
    )
    provisioning = (
        bool(queue_waits)
        and maximum_queue <= evaluation_policy.provisioning_queue_slo_ns
        and maximum_ansible <= evaluation_policy.ansible_service_slo_ns
    )
    physical_gpus = scenario["physical_capacity"]["independently_assignable_gpus"]
    correctness = outcomes_match and maximum_overlap <= physical_gpus and cleanup_passed
    stage_passed = (
        request_processing and provisioning and correctness and load_generator_passed
    )
    assessment = {
        "outcomes_match_expected": outcomes_match,
        "request_processing_passed": request_processing,
        "simultaneous_fulfillment_count": maximum_overlap,
        "provisioning_passed": provisioning,
        "correctness_passed": correctness,
        "load_generator_passed": load_generator_passed,
        "cleanup_passed": cleanup_passed,
        "stage_passed": stage_passed,
        "agent_capacity_evidence": True,
        "eligible_for_capacity_frontier": (
            execution_boundary == "real-measured" and load_generator_passed
        ),
        "derived_faults": (
            ["double-allocation"] if maximum_overlap > physical_gpus else []
        ),
    }
    frontier = {
        "offered_buyers": scenario["actor_counts"]["buyers"],
        "request_processing": {
            "passed": request_processing,
            "observed_max_ns": maximum_latency,
            "slo_ns": evaluation_policy.request_processing_slo_ns,
        },
        "simultaneous_fulfillment": {
            "max_overlapping_whole_gpu_vms": maximum_overlap,
        },
        "provisioning_queue": {
            "passed": (
                maximum_queue <= evaluation_policy.provisioning_queue_slo_ns
                and maximum_overlap > 0
            ),
            "observed_max_ns": maximum_queue,
            "slo_ns": evaluation_policy.provisioning_queue_slo_ns,
        },
        "ansible_service": {
            "passed": (
                maximum_ansible <= evaluation_policy.ansible_service_slo_ns
                and maximum_overlap > 0
            ),
            "observed_max_ns": maximum_ansible,
            "slo_ns": evaluation_policy.ansible_service_slo_ns,
        },
        "correctness_passed": correctness,
        "load_generator_passed": load_generator_passed,
    }
    return assessment, frontier


def _replace_buyer_result_with_generator_rejection(
    chain: RealChain,
    request_id: str,
) -> None:
    buyer = next(
        item
        for item in chain.evidence
        if item.plan.role == "buyer"
        and item.plan.plan["role_plan"]["request_id"] == request_id
    )
    action_chain = next(
        item
        for item in chain.chains
        if item.authority.actor_slot == buyer.plan.actor_slot
        and item.authority.action_kind == "buyer-request"
    )
    assert action_chain.result is not None
    result_value = action_chain.result.result
    result_value.update(
        {
            "result_kind": "rejected-before-emission",
            "emission_count": 0,
            "terminal_payload_sha256": None,
            "failure_code": "emission-failed",
        }
    )
    rejected_result = validate_action_result(
        result_value,
        action_chain.authority,
    )
    action_chain.result = rejected_result
    receipt_value = buyer.receipt.receipt
    receipt_value["role_evidence"]["action_result_sha256"] = (
        rejected_result.canonical_sha256
    )
    receipt = validate_role_receipt(receipt_value, buyer.plan)
    rejected_evidence = validate_substantive_role_evidence(
        buyer.plan,
        receipt,
        buyer.actions,
        (rejected_result,),
        allow_rejected_observation=True,
    )
    chain.evidence = [
        (rejected_evidence if item.plan.actor_slot == buyer.plan.actor_slot else item)
        for item in chain.evidence
    ]
    buyer_actor = next(
        item
        for item in chain.actor_set["actors"]
        if item["actor_slot"] == buyer.plan.actor_slot
    )
    buyer_actor["receipt_sha256"] = receipt.canonical_sha256
    buyer_action = next(
        item
        for item in chain.actor_set["actions"]
        if item["action_id"] == action_chain.authority.action_id
    )
    buyer_action["action_result_sha256"] = rejected_result.canonical_sha256


def _measured_case(
    repo: Path,
    scm_ref: str,
    stage_id: str,
    *,
    evaluation_policy: ValidatedEvaluationPolicy | None = None,
    outcome_kinds: Mapping[str, str] | None = None,
    fault_variants: Mapping[str, str] | None = None,
    guest_fulfillment_ids: Mapping[str, str] | None = None,
    topology_authority_binding: Mapping[str, str] | None = None,
    host_reversible_baseline_binding: Mapping[str, str] | None = None,
    seller_scaling_admission_counts: tuple[int, int] = (4, 4),
    predecessor: ValidatedCapacityResult | None = None,
    buyer_frontier: ValidatedBuyerFrontierReceipt | None = None,
    reuse_baseline: ValidatedCapacityResult | None = None,
    prior_seller_results: Sequence[ValidatedCapacityResult] = (),
    wall_clock_minute: int = 0,
    cleanup_failure: bool = False,
    generator_rejection_request_id: str | None = None,
    omit_success_diagnostic_ids: bool = False,
    terminal_latency_ns: Mapping[str, int] | None = None,
) -> CapacityCase:
    policy = evaluation_policy or _validated_evaluation_policy(repo, scm_ref)
    stage_chain = _real_chain(
        repo,
        scm_ref,
        stage_id,
        successful_guest_request_ids={
            request_id
            for request_id, kind in (outcome_kinds or {}).items()
            if kind == "vm-succeeded"
        },
        guest_fulfillment_ids=guest_fulfillment_ids,
        topology_authority_binding=topology_authority_binding,
        host_reversible_baseline_binding=host_reversible_baseline_binding,
        seller_scaling_admission_counts=seller_scaling_admission_counts,
        wall_clock_shift=timedelta(minutes=wall_clock_minute),
    )
    stage = stage_chain.plans[0].profile_stage
    assert stage.scenario is not None
    scenario = stage.scenario.scenario
    kinds = dict(outcome_kinds or {})
    if not kinds:
        kinds = {
            request["request_id"]: (
                "vm-succeeded" if index == 0 else "capacity-refused"
            )
            for index, request in enumerate(scenario["requests"])
        }
        # Rebuild guest evidence now that the scenario-derived success set exists.
        return _measured_case(
            repo,
            scm_ref,
            stage_id,
            evaluation_policy=evaluation_policy,
            outcome_kinds=kinds,
            fault_variants=fault_variants,
            guest_fulfillment_ids=guest_fulfillment_ids,
            topology_authority_binding=topology_authority_binding,
            host_reversible_baseline_binding=(host_reversible_baseline_binding),
            seller_scaling_admission_counts=(seller_scaling_admission_counts),
            predecessor=predecessor,
            buyer_frontier=buyer_frontier,
            reuse_baseline=reuse_baseline,
            prior_seller_results=prior_seller_results,
            wall_clock_minute=wall_clock_minute,
            cleanup_failure=cleanup_failure,
            generator_rejection_request_id=(generator_rejection_request_id),
            omit_success_diagnostic_ids=omit_success_diagnostic_ids,
            terminal_latency_ns=terminal_latency_ns,
        )
    fault_by_request = dict(fault_variants or {})
    terminal_latencies = dict(terminal_latency_ns or {})
    for request_id, variant in fault_by_request.items():
        if variant == "timeout":
            terminal_latencies.setdefault(
                request_id,
                policy.terminal_observation_timeout_ns,
            )
    for request in scenario["requests"]:
        latency = terminal_latencies.get(request["request_id"])
        if latency is None:
            continue
        action = next(
            item
            for item in stage_chain.actor_set["actions"]
            if item["actor_slot"] == request["buyer_slot"]
            and item["action_kind"] == "buyer-request"
        )
        actor = next(
            item
            for item in stage_chain.actor_set["actors"]
            if item["actor_slot"] == request["buyer_slot"]
        )
        actor["completed_offset_ns"] = max(
            actor["completed_offset_ns"],
            action["invoked_offset_ns"] + latency + 1,
        )
    if generator_rejection_request_id is not None:
        _clean_actor_set, observation = _clean_stage_observation(stage_chain)
        _replace_buyer_result_with_generator_rejection(
            stage_chain,
            generator_rejection_request_id,
        )
        actor_set = validate_actor_set_observation(
            stage_chain.actor_set,
            stage_chain.policy,
            stage_chain.evidence,
        )
    else:
        actor_set, observation = _clean_stage_observation(stage_chain)
    if cleanup_failure:
        _receipt, failed_evidence, failed_actor_value = _replace_host_observation(
            stage_chain,
            cleanup_complete=False,
            baseline_equivalent=False,
            active_residue_detected=True,
        )
        stage_chain.evidence = failed_evidence
        stage_chain.actor_set = failed_actor_value
        actor_set = validate_actor_set_observation(
            failed_actor_value,
            stage_chain.policy,
            failed_evidence,
        )
        failed_cleanup = deepcopy(observation["cleanup"])
        failed_cleanup["teardown_complete"] = False
        failed_cleanup["residue_counts"]["vms"] = 1
        next(
            item
            for item in failed_cleanup["reversible_components"]
            if item["component"] == "vms"
        )["exactly_equal"] = False
        failed_cleanup["ready_for_next_stage"] = False
        observation["cleanup"] = failed_cleanup
    outcomes: list[dict[str, Any]] = []
    for request in scenario["requests"]:
        request_id = request["request_id"]
        prefix = f"{scenario['scenario_id']}-{request_id}"
        kind = kinds[request_id]
        if kind == "vm-succeeded":
            outcome = _successful_request_outcome(
                stage_chain,
                actor_set,
                request_id,
                identity_prefix=prefix,
            )
        elif kind == "capacity-refused":
            outcome = _refused_request_outcome(
                stage_chain,
                actor_set,
                request_id,
                identity_prefix=prefix,
            )
        elif kind == "fault":
            outcome = _fault_request_outcome(
                stage_chain,
                actor_set,
                request_id,
                identity_prefix=prefix,
                variant=fault_by_request.get(
                    request_id,
                    "swallowed-site-error",
                ),
            )
        else:
            raise AssertionError(f"unsupported outcome kind: {kind}")
        terminal_latency = terminal_latencies.get(request_id)
        if terminal_latency is not None:
            outcome["terminal_offset_ns"] = (
                outcome["invoked_offset_ns"] + terminal_latency
            )
        outcomes.append(outcome)
    if omit_success_diagnostic_ids:
        for outcome in outcomes:
            if outcome["outcome_kind"] == "vm-succeeded":
                outcome["allocation_id"] = None
                outcome["provisioning_job_id"] = None
    timing_binding = observation["observer_native_evidence_bindings"][0]
    for outcome in outcomes:
        if timing_binding not in outcome["independent_observation_bindings"]:
            outcome["independent_observation_bindings"].append(timing_binding)
    minute = wall_clock_minute
    stage_started_at = f"2026-07-30T10:{minute:02d}:00.200000Z"
    terminal_observed_at = f"2026-07-30T10:{minute:02d}:10.000000Z"
    cleanup_completed_at = f"2026-07-30T10:{minute:02d}:11.000000Z"
    actor_set = _rebind_actor_set_observer_receipt(
        stage_chain,
        request_outcomes=outcomes,
        cleanup=observation["cleanup"],
        stage_started_at=stage_started_at,
        terminal_observed_at=terminal_observed_at,
        cleanup_completed_at=cleanup_completed_at,
    )
    assessment, frontier = _result_assessment(
        scenario=scenario,
        outcomes=outcomes,
        evaluation_policy=policy,
        cleanup_passed=not cleanup_failure,
        load_generator_passed=actor_set.load_generator_passed,
        execution_boundary=stage.stage["execution_boundary"],
    )
    actor_value = actor_set.actor_set
    reuse_predecessor = None
    if predecessor is not None:
        prior = predecessor.result
        reuse_predecessor = {
            "result_id": predecessor.result_id,
            "result_sha256": predecessor.canonical_sha256,
            "progression_ready_at": prior["progression_ready_at"],
            "baseline_equivalence_binding": prior["cleanup"][
                "baseline_equivalence_binding"
            ],
        }
    scenario_id = stage.scenario.scenario_id
    buyer_frontier_authority = None
    if scenario_id == "serialized-reuse-a" and buyer_frontier is not None:
        buyer_frontier_authority = {
            "buyer_frontier_receipt_id": (buyer_frontier.frontier_receipt_id),
            "buyer_frontier_receipt_sha256": (buyer_frontier.canonical_sha256),
        }
    elif scenario_id == "serialized-reuse-b" and predecessor is not None:
        buyer_frontier_authority = predecessor.result["buyer_frontier_authority"]

    prior_results = tuple(prior_seller_results)
    seller_progression_authority = None
    if stage_id in _SELLER_MEASURED_STAGES:
        assert buyer_frontier is not None
        assert reuse_baseline is not None
        prior = prior_results[-1] if prior_results else None
        seller_progression_authority = {
            "buyer_frontier_receipt_id": (buyer_frontier.frontier_receipt_id),
            "buyer_frontier_receipt_sha256": (buyer_frontier.canonical_sha256),
            "reuse_baseline_result_id": reuse_baseline.result_id,
            "reuse_baseline_result_sha256": (reuse_baseline.canonical_sha256),
            "prior_seller_result_id": (prior.result_id if prior is not None else None),
            "prior_seller_result_sha256": (
                prior.canonical_sha256 if prior is not None else None
            ),
            "distinct_seller_identities": (reuse_baseline.admitted_seller_identities),
            "distinct_service_instances": (reuse_baseline.admitted_service_instances),
        }
    result_value = {
        "schema_version": 2,
        "result_id": f"{stage_id}-result",
        "scm_ref": scm_ref,
        "profile_stage_id": stage.stage_id,
        "profile_stage_sha256": stage.canonical_sha256,
        "scenario_id": stage.scenario.scenario_id,
        "scenario_sha256": stage.scenario.scenario_sha256,
        "execution_boundary": stage.stage["execution_boundary"],
        "actor_trigger": stage.stage["actor_trigger"],
        "evaluation_policy": {
            "evaluation_policy_id": policy.policy_id,
            "evaluation_policy_sha256": policy.canonical_sha256,
        },
        "oracle_authority": {
            "oracle_authority_id": stage_chain.oracle.oracle_authority_id,
            "oracle_authority_sha256": stage_chain.oracle.canonical_sha256,
            "observer_plan_sha256": stage_chain.oracle.authority[
                "observer_plan_sha256"
            ],
        },
        "execution_authority": {
            "kind": "agent-actor-set",
            "actor_set_id": actor_set.actor_set_id,
            "actor_set_sha256": actor_set.canonical_sha256,
            "release_id": actor_value["release_id"],
            "concurrency_policy_id": actor_value["concurrency_policy_id"],
            "concurrency_policy_sha256": actor_value["concurrency_policy_sha256"],
        },
        "topology_authority_binding": observation["topology_authority_binding"],
        "started_at": stage_started_at,
        "terminal_observed_at": terminal_observed_at,
        "cleanup_completed_at": cleanup_completed_at,
        "progression_ready_at": (f"2026-07-30T10:{minute:02d}:12.000000Z"),
        "expected_outcomes": scenario["expected_outcomes"],
        "observed_outcomes": {
            kind: sum(outcome["outcome_kind"] == kind for outcome in outcomes)
            for kind in ("vm-succeeded", "capacity-refused", "fault")
        },
        "request_outcomes": outcomes,
        "aggregate_observation": {
            "observer_plan_sha256": stage_chain.oracle.authority[
                "observer_plan_sha256"
            ],
            "observed_request_ids": [
                request["request_id"] for request in scenario["requests"]
            ],
            "request_timing_observations": [
                {
                    "request_id": outcome["request_id"],
                    "invoked_offset_ns": outcome["invoked_offset_ns"],
                    "terminal_offset_ns": outcome["terminal_offset_ns"],
                    "native_evidence_binding": timing_binding,
                }
                for outcome in outcomes
            ],
            "observed_at": f"2026-07-30T10:{minute:02d}:09.000000Z",
            "common_clock_binding": actor_value["clock_evidence_binding"],
            "native_evidence_bindings": observation[
                "observer_native_evidence_bindings"
            ],
            "max_overlapping_whole_gpu_vms": assessment[
                "simultaneous_fulfillment_count"
            ],
        },
        "cleanup": observation["cleanup"],
        "stage_assessment": assessment,
        "buyer_frontier_authority": buyer_frontier_authority,
        "reuse_predecessor": reuse_predecessor,
        "seller_progression_authority": seller_progression_authority,
        "frontier_observation": (
            frontier if stage.stage["execution_boundary"] == "real-measured" else None
        ),
    }
    validated = validate_capacity_result(
        result_value,
        repo,
        evaluation_policy=policy,
        oracle_authority=stage_chain.oracle,
        actor_set=actor_set,
        role_evidence=stage_chain.evidence,
        predecessor=predecessor,
        buyer_frontier=buyer_frontier,
        reuse_baseline=reuse_baseline,
        prior_seller_results=prior_results,
        expected_scm_ref=scm_ref,
    )
    return CapacityCase(
        chain=stage_chain,
        actor_set=actor_set,
        evaluation_policy=policy,
        result_value=result_value,
        result=validated,
        buyer_frontier=buyer_frontier,
        reuse_baseline=reuse_baseline,
        prior_seller_results=prior_results,
    )


def _reference_b1_case(
    repo: Path,
    scm_ref: str,
    evaluation_policy: ValidatedEvaluationPolicy,
) -> ReferenceCase:
    stage_id = "b1-s1-g1-reference"
    plans = _validated_plans(
        repo,
        scm_ref,
        stage_id,
        roles={"host-operator", "observer"},
    )
    oracle = _oracle(repo, scm_ref, stage_id, plans)
    reference_policy_id = "b1-reference-policy"
    release_id = "b1-reference-release"
    stage = plans[0].profile_stage
    assert stage.scenario is not None
    scenario = stage.scenario.scenario
    observer_plan = next(plan for plan in plans if plan.role == "observer")
    host_plan = next(plan for plan in plans if plan.role == "host-operator")
    reference_policy = validate_reference_policy(
        {
            "schema_version": 2,
            "reference_policy_id": reference_policy_id,
            "scm_ref": scm_ref,
            "profile_stage_id": stage.stage_id,
            "profile_stage_sha256": stage.canonical_sha256,
            "scenario_id": stage.scenario.scenario_id,
            "scenario_sha256": stage.scenario.scenario_sha256,
            "evaluation_policy": {
                "evaluation_policy_id": evaluation_policy.policy_id,
                "evaluation_policy_sha256": (evaluation_policy.canonical_sha256),
            },
            "release_id": release_id,
            "frozen_at": "2026-07-30T09:59:30.000000Z",
            "controller_is_counted": False,
            "clock_evidence_binding": evaluation_policy.policy[
                "clock_evidence_binding"
            ],
            "observer_plan": {
                "plan_id": observer_plan.plan_id,
                "plan_sha256": observer_plan.canonical_sha256,
            },
            "host_plan": {
                "plan_id": host_plan.plan_id,
                "plan_sha256": host_plan.canonical_sha256,
            },
            "request_schedule": [
                {
                    "request_id": request["request_id"],
                    "invoked_offset_ns": 10 + (index * 100),
                }
                for index, request in enumerate(scenario["requests"])
            ],
        },
        repo,
        evaluation_policy=evaluation_policy,
        observer_plan=observer_plan,
        host_plan=host_plan,
        expected_scm_ref=scm_ref,
    )
    run_authority = {
        "release_id": release_id,
        "concurrency_policy_id": reference_policy_id,
        "concurrency_policy_sha256": (reference_policy.canonical_sha256),
    }
    evidence = tuple(
        _role_evidence(
            plans,
            [],
            run_authority_override=run_authority,
        )
    )
    host = next(item for item in evidence if item.plan.role == "host-operator")
    observer = next(item for item in evidence if item.plan.role == "observer")
    clock_binding = evaluation_policy.policy["clock_evidence_binding"]
    timing_binding = observer.receipt.receipt["role_evidence"][
        "native_evidence_bindings"
    ][0]
    runtime_binding = binding(
        RUNTIME_BINDING_DOMAIN,
        "b1-reference-listing",
    )
    reservation_id = "b1-reference-reservation"
    fulfillment_id = "b1-reference-fulfillment"
    deal = {
        "request_id": "request-1",
        "seller_slot": "seller-1",
        "listing_slot": "listing-1",
        "runtime_binding": runtime_binding,
        "negotiation_reference_sha256": digest("b1-reference-negotiation"),
        "escrow_reference_sha256": digest("b1-reference-escrow"),
    }
    request_outcome = {
        "request_id": "request-1",
        "outcome_kind": "vm-succeeded",
        "deal_reference": deal,
        "invoked_offset_ns": 10,
        "terminal_offset_ns": 90,
        "capacity_reservation_id": reservation_id,
        "fulfillment_id": fulfillment_id,
        "settlement_record": {
            "capacity_reservation_id": reservation_id,
            "fulfillment_id": fulfillment_id,
            "state": "torn_down",
            "selected_resource_binding": binding(
                NATIVE_EVIDENCE_BINDING_DOMAIN,
                "b1-reference-selected-resource",
            ),
            "active_claim": False,
        },
        "provisioned_resource_id": "b1-reference-vm",
        "allocation_id": None,
        "provisioning_job_id": None,
        "commercial_resolution": {
            "deal_state": "fulfilled-terminal",
            "escrow_state": "released",
            "failure_policy_state": "not-applicable",
            "zero_active_claims": True,
            "zero_active_locks": True,
            "zero_run_owned_funds": True,
        },
        "independent_observation_bindings": [timing_binding],
        "request_cleanup": {
            "teardown_complete": True,
            "zero_active_residue": True,
            "native_evidence_binding": binding(
                NATIVE_EVIDENCE_BINDING_DOMAIN,
                "b1-reference-request-cleanup",
            ),
        },
        "failure_category": None,
        "success_observation": {
            "reservation_fulfillment_join": {
                "fulfillment_capacity_reservation_id": reservation_id,
                "settlement_capacity_reservation_id": reservation_id,
                "settlement_fulfillment_id": fulfillment_id,
                "provisioned_fulfillment_id": fulfillment_id,
            },
            "provisioning": {
                "provisioning_kind": "real-kvm-ansible",
                "gpu_assignment": "whole-device-passthrough",
                "queue_wait_ns": 10,
                "ansible_service_ns": 20,
                "output_observed": True,
            },
            "gpu_exercise": {
                "fulfillment_id": fulfillment_id,
                "ssh_resumed": True,
                "visible_gpus": 1,
                "wrapper": tracked(repo, CUDA_WRAPPER_PATH),
                "source": tracked(repo, CUDA_SOURCE_PATH),
                "compiled": True,
                "device_kernel_executed": True,
                "success_marker": CUDA_SUCCESS_MARKER,
                "result_checksum": CUDA_RESULT_CHECKSUM,
                "native_evidence_binding": binding(
                    NATIVE_EVIDENCE_BINDING_DOMAIN,
                    "b1-reference-guest",
                ),
            },
            "active_interval": {
                "start_offset_ns": 20,
                "end_offset_ns": 80,
                "interval_semantics": "half-open",
                "clock_evidence_binding": clock_binding,
            },
        },
    }
    timing = {
        "request_id": "request-1",
        "invoked_offset_ns": 10,
        "terminal_offset_ns": 90,
        "native_evidence_binding": timing_binding,
    }
    assessment = {
        "outcomes_match_expected": True,
        "request_processing_passed": True,
        "simultaneous_fulfillment_count": 1,
        "provisioning_passed": True,
        "correctness_passed": True,
        "load_generator_passed": False,
        "cleanup_passed": True,
        "stage_passed": True,
        "agent_capacity_evidence": False,
        "eligible_for_capacity_frontier": False,
        "derived_faults": [],
    }
    cleanup = _clean_cleanup_from_evidence(
        evidence,
        identity_prefix="b1-reference",
    )
    evidence = _seal_observer_result_evidence(
        evidence,
        request_outcomes=(request_outcome,),
        cleanup=cleanup,
        stage_started_at="2026-07-30T10:00:00.200000Z",
        terminal_observed_at="2026-07-30T10:00:10.000000Z",
        cleanup_completed_at="2026-07-30T10:00:11.000000Z",
    )
    host = next(item for item in evidence if item.plan.role == "host-operator")
    observer = next(item for item in evidence if item.plan.role == "observer")
    value = {
        "schema_version": 2,
        "result_id": "b1-reference-result",
        "scm_ref": scm_ref,
        "profile_stage_id": stage.stage_id,
        "profile_stage_sha256": stage.canonical_sha256,
        "scenario_id": stage.scenario.scenario_id,
        "scenario_sha256": stage.scenario.scenario_sha256,
        "execution_boundary": "real-reference",
        "actor_trigger": "controller-driven",
        "evaluation_policy": {
            "evaluation_policy_id": evaluation_policy.policy_id,
            "evaluation_policy_sha256": (evaluation_policy.canonical_sha256),
        },
        "oracle_authority": {
            "oracle_authority_id": oracle.oracle_authority_id,
            "oracle_authority_sha256": oracle.canonical_sha256,
            "observer_plan_sha256": oracle.authority["observer_plan_sha256"],
        },
        "execution_authority": {
            "kind": "controller-reference",
            "reference_execution_binding": binding(
                NATIVE_EVIDENCE_BINDING_DOMAIN,
                "b1-reference-execution",
            ),
            "reference_policy_id": reference_policy.policy_id,
            "reference_policy_sha256": (reference_policy.canonical_sha256),
            "observer_receipt_id": observer.receipt.receipt_id,
            "observer_receipt_sha256": (observer.receipt.canonical_sha256),
            "host_receipt_id": host.receipt.receipt_id,
            "host_receipt_sha256": host.receipt.canonical_sha256,
            "clock_evidence_binding": clock_binding,
            "request_timing_observations": [timing],
            "controller_is_counted": False,
            "release_id": release_id,
            "released_at": "2026-07-30T10:00:01.000000Z",
        },
        "topology_authority_binding": host.receipt.receipt["role_evidence"][
            "topology_authority_binding"
        ],
        "started_at": "2026-07-30T10:00:00.200000Z",
        "terminal_observed_at": "2026-07-30T10:00:10.000000Z",
        "cleanup_completed_at": "2026-07-30T10:00:11.000000Z",
        "progression_ready_at": "2026-07-30T10:00:12.000000Z",
        "expected_outcomes": scenario["expected_outcomes"],
        "observed_outcomes": {
            "vm-succeeded": 1,
            "capacity-refused": 0,
            "fault": 0,
        },
        "request_outcomes": [request_outcome],
        "aggregate_observation": {
            "observer_plan_sha256": oracle.authority["observer_plan_sha256"],
            "observed_request_ids": ["request-1"],
            "request_timing_observations": [timing],
            "observed_at": "2026-07-30T10:00:09.000000Z",
            "common_clock_binding": clock_binding,
            "native_evidence_bindings": observer.receipt.receipt["role_evidence"][
                "native_evidence_bindings"
            ],
            "max_overlapping_whole_gpu_vms": 1,
        },
        "cleanup": cleanup,
        "stage_assessment": assessment,
        "buyer_frontier_authority": None,
        "reuse_predecessor": None,
        "seller_progression_authority": None,
        "frontier_observation": None,
    }
    result = validate_capacity_result(
        value,
        repo,
        evaluation_policy=evaluation_policy,
        oracle_authority=oracle,
        actor_set=None,
        reference_policy=reference_policy,
        role_evidence=evidence,
        expected_scm_ref=scm_ref,
    )
    return ReferenceCase(
        oracle=oracle,
        reference_policy=reference_policy,
        evidence=evidence,
        evaluation_policy=evaluation_policy,
        result_value=value,
        result=result,
    )


def _shape_frontier(
    results: Sequence[ValidatedCapacityResult],
    *,
    passed: Mapping[int, bool],
    load_is_censor: bool = True,
) -> dict[str, Any]:
    load_by_count = {
        result.buyer_count: result.load_generator_passed for result in results
    }
    passing = sorted(
        count
        for count, is_passing in passed.items()
        if is_passing and (not load_is_censor or load_by_count.get(count) is True)
    )
    if not passing:
        return {
            "greatest_passing_buyer_count": 0,
            "classification": "not-observed",
            "limit_reason": "no-passing-shape",
        }
    greatest = max(passing)
    valid_failures = sorted(
        count
        for count, is_passing in passed.items()
        if count > greatest
        and not is_passing
        and (not load_is_censor or load_by_count.get(count) is True)
    )
    if valid_failures and valid_failures[0] == greatest + 1:
        return {
            "greatest_passing_buyer_count": greatest,
            "classification": "exact-bound",
            "limit_reason": "observed-failure",
        }
    generator_failures = (
        sorted(
            count
            for count, load_passed in load_by_count.items()
            if count > greatest and not load_passed
        )
        if load_is_censor
        else []
    )
    if not load_is_censor and valid_failures:
        limit_reason = "load-generator-ended-first"
    elif generator_failures:
        limit_reason = "load-generator-ended-first"
    else:
        limit_reason = "frozen-envelope-ended"
    return {
        "greatest_passing_buyer_count": greatest,
        "classification": "lower-bound",
        "limit_reason": limit_reason,
    }


def _buyer_frontier_value(
    evaluation_policy: ValidatedEvaluationPolicy,
    results: Sequence[ValidatedCapacityResult],
) -> dict[str, Any]:
    stage_passes = {
        result.profile_stage_id: (
            result.request_processing_passed
            and result.provisioning_passed
            and result.correctness_passed
        )
        for result in results
    }
    product_by_count = {
        result.buyer_count: stage_passes[result.profile_stage_id] for result in results
    }
    load_by_count = {
        result.buyer_count: result.load_generator_passed for result in results
    }
    request_by_count = {
        result.buyer_count: result.request_processing_passed for result in results
    }
    provisioning_by_count = {
        result.buyer_count: result.provisioning_passed for result in results
    }
    correctness_by_count = {
        result.buyer_count: result.correctness_passed for result in results
    }
    by_stage = {result.profile_stage_id: result for result in results}
    initial_stage_ids = (
        "q0-b1-s1-g1-measured",
        "b2-s1-g1-measured",
        "b4-s1-g1-measured",
        "b8-s1-g1-measured",
    )
    initial_generator_failure = any(
        not by_stage[stage_id].load_generator_passed for stage_id in initial_stage_ids
    )
    if initial_generator_failure:
        refinement_counts: tuple[int, ...] = ()
        censored = True
    else:
        refinement_counts = select_buyer_refinement_counts(
            {
                stage_id: passed
                for stage_id, passed in stage_passes.items()
                if by_stage[stage_id].load_generator_passed
            }
        )
        censored = any(
            stage_id in by_stage and not by_stage[stage_id].load_generator_passed
            for stage_id in (f"b{count}-s1-g1-measured" for count in refinement_counts)
        )
    clean_counts = sorted(
        count
        for count, passed in product_by_count.items()
        if passed and load_by_count[count]
    )
    retained_counts = (
        tuple(clean_counts[-3:])
        if censored
        else retained_buyer_refinement_counts(stage_passes)
    )
    largest_clean = max(clean_counts, default=0)
    product_failures = sorted(
        count
        for count, passed in product_by_count.items()
        if not passed and load_by_count[count]
    )
    higher_product_failures = [
        count for count in product_failures if count > largest_clean
    ]
    if not clean_counts:
        classification = "no-clean-shape"
        lower_bound_reason = None
    elif censored:
        classification = "lower-bound"
        lower_bound_reason = "load-generator-ended-first"
    elif higher_product_failures and min(higher_product_failures) == largest_clean + 1:
        classification = "exact-bound"
        lower_bound_reason = None
    else:
        classification = "lower-bound"
        lower_bound_reason = "frozen-envelope-ended"
    registry = resolve_pinned_profile_registry(
        evaluation_policy.repo_root,
        evaluation_policy.scm_ref,
    )
    return {
        "schema_version": 2,
        "frontier_receipt_id": "buyer-frontier-receipt",
        "scm_ref": evaluation_policy.scm_ref,
        "profile_registry": {
            "path": CAPACITY_PROFILE_PATH.as_posix(),
            "canonical_sha256": registry.canonical_sha256,
            "raw_sha256": registry.raw_sha256,
        },
        "evaluation_policy": {
            "evaluation_policy_id": evaluation_policy.policy_id,
            "evaluation_policy_sha256": (evaluation_policy.canonical_sha256),
        },
        "topology_authority_binding": results[0].result["topology_authority_binding"],
        "ordered_results": [
            {
                "profile_stage_id": result.profile_stage_id,
                "result_id": result.result_id,
                "result_sha256": result.canonical_sha256,
            }
            for result in results
        ],
        "initial_stage_ids": list(initial_stage_ids),
        "refinement_stage_ids": [
            f"b{count}-s1-g1-measured" for count in refinement_counts
        ],
        "retained_buyer_counts": list(retained_counts),
        "stage_observations": [
            {
                "profile_stage_id": result.profile_stage_id,
                "buyer_count": result.buyer_count,
                "request_processing_passed": (result.request_processing_passed),
                "provisioning_passed": result.provisioning_passed,
                "correctness_passed": result.correctness_passed,
                "load_generator_passed": result.load_generator_passed,
                "progression_passed": (
                    stage_passes[result.profile_stage_id]
                    and result.load_generator_passed
                ),
            }
            for result in results
        ],
        "frontiers": {
            "request_processing": _shape_frontier(
                results,
                passed=request_by_count,
            ),
            "simultaneous_fulfillment": {
                "maximum_whole_gpu_vms": max(
                    result.simultaneous_fulfillment_count for result in results
                ),
                "classification": "exact-observation",
            },
            "provisioning": _shape_frontier(
                results,
                passed=provisioning_by_count,
            ),
            "correctness": _shape_frontier(
                results,
                passed=correctness_by_count,
            ),
            "load_generator": _shape_frontier(
                results,
                passed=load_by_count,
                load_is_censor=False,
            ),
        },
        "progression": {
            "selection_predicate": (
                "request-processing-and-provisioning-and-correctness-"
                "with-load-generator-censoring"
            ),
            "largest_clean_buyer_count": largest_clean,
            "classification": classification,
            "lower_bound_reason": lower_bound_reason,
            "completed_before_reuse": True,
        },
        "clock_evidence_binding": evaluation_policy.policy["clock_evidence_binding"],
        "completed_at": "2026-07-30T10:10:00.000000Z",
    }


def _validated_buyer_frontier(
    evaluation_policy: ValidatedEvaluationPolicy,
    results: Sequence[ValidatedCapacityResult],
) -> tuple[dict[str, Any], ValidatedBuyerFrontierReceipt]:
    value = _buyer_frontier_value(evaluation_policy, results)
    validated = validate_buyer_frontier_receipt(
        value,
        evaluation_policy.repo_root,
        evaluation_policy=evaluation_policy,
        results=results,
        expected_scm_ref=evaluation_policy.scm_ref,
    )
    return value, validated


@pytest.fixture(scope="module")
def outcome_policy(
    outcome_authority_repo: tuple[Path, str],
) -> ValidatedEvaluationPolicy:
    repo, scm_ref = outcome_authority_repo
    return _validated_evaluation_policy(repo, scm_ref)


@pytest.fixture(scope="module")
def reference_b1_capacity_case(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
) -> ReferenceCase:
    repo, scm_ref = outcome_authority_repo
    return _reference_b1_case(repo, scm_ref, outcome_policy)


@pytest.fixture(scope="module")
def b2_capacity_case(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
) -> CapacityCase:
    repo, scm_ref = outcome_authority_repo
    return _measured_case(
        repo,
        scm_ref,
        "b2-s1-g1-measured",
        evaluation_policy=outcome_policy,
        wall_clock_minute=1,
    )


@pytest.fixture(scope="module")
def atomic_refusal_fault_case(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
) -> CapacityCase:
    repo, scm_ref = outcome_authority_repo
    return _measured_case(
        repo,
        scm_ref,
        "b2-s1-g1-measured",
        evaluation_policy=outcome_policy,
        outcome_kinds={
            "request-1": "vm-succeeded",
            "request-2": "fault",
        },
        fault_variants={"request-2": "swallowed-site-error"},
        wall_clock_minute=1,
    )


@pytest.fixture(scope="module")
def serialized_reuse_cases(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
    lower_bound_buyer_frontier: tuple[
        tuple[CapacityCase, ...],
        dict[str, Any],
        ValidatedBuyerFrontierReceipt,
    ],
) -> tuple[CapacityCase, CapacityCase]:
    repo, scm_ref = outcome_authority_repo
    _buyer_cases, _frontier_value, buyer_frontier = lower_bound_buyer_frontier
    reuse_a = _measured_case(
        repo,
        scm_ref,
        "serialized-reuse-a-measured",
        evaluation_policy=outcome_policy,
        guest_fulfillment_ids={
            "request-1": "serialized-reuse-a-fulfillment",
        },
        buyer_frontier=buyer_frontier,
        wall_clock_minute=11,
    )
    baseline = reuse_a.result_value["cleanup"]["reversible_baseline_binding"]
    reuse_b = _measured_case(
        repo,
        scm_ref,
        "serialized-reuse-b-measured",
        evaluation_policy=outcome_policy,
        guest_fulfillment_ids={
            "request-1": "serialized-reuse-b-fulfillment",
        },
        host_reversible_baseline_binding=baseline,
        seller_scaling_admission_counts=(2, 2),
        predecessor=reuse_a.result,
        buyer_frontier=buyer_frontier,
        wall_clock_minute=12,
    )
    return reuse_a, reuse_b


@pytest.fixture(scope="module")
def qualification_reuse_cases(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
) -> tuple[CapacityCase, CapacityCase]:
    repo, scm_ref = outcome_authority_repo
    reuse_a = _measured_case(
        repo,
        scm_ref,
        "serialized-reuse-a-qualification",
        evaluation_policy=outcome_policy,
        guest_fulfillment_ids={
            "request-1": "qualification-reuse-a-fulfillment",
        },
        wall_clock_minute=20,
    )
    baseline = reuse_a.result_value["cleanup"]["reversible_baseline_binding"]
    reuse_b = _measured_case(
        repo,
        scm_ref,
        "serialized-reuse-b-qualification",
        evaluation_policy=outcome_policy,
        guest_fulfillment_ids={
            "request-1": "qualification-reuse-b-fulfillment",
        },
        host_reversible_baseline_binding=baseline,
        predecessor=reuse_a.result,
        wall_clock_minute=21,
    )
    return reuse_a, reuse_b


@pytest.fixture(scope="module")
def lower_bound_buyer_frontier(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
    b2_capacity_case: CapacityCase,
) -> tuple[
    tuple[CapacityCase, ...],
    dict[str, Any],
    ValidatedBuyerFrontierReceipt,
]:
    repo, scm_ref = outcome_authority_repo
    cases = (
        _measured_case(
            repo,
            scm_ref,
            "q0-b1-s1-g1-measured",
            evaluation_policy=outcome_policy,
        ),
        b2_capacity_case,
        _measured_case(
            repo,
            scm_ref,
            "b4-s1-g1-measured",
            evaluation_policy=outcome_policy,
            wall_clock_minute=2,
        ),
        _measured_case(
            repo,
            scm_ref,
            "b8-s1-g1-measured",
            evaluation_policy=outcome_policy,
            wall_clock_minute=3,
        ),
    )
    value, receipt = _validated_buyer_frontier(
        outcome_policy,
        [case.result for case in cases],
    )
    return cases, value, receipt


@pytest.fixture(scope="module")
def exact_buyer_frontier(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
    b2_capacity_case: CapacityCase,
) -> tuple[
    tuple[CapacityCase, ...],
    dict[str, Any],
    ValidatedBuyerFrontierReceipt,
]:
    repo, scm_ref = outcome_authority_repo
    b4_failure = _measured_case(
        repo,
        scm_ref,
        "b4-s1-g1-measured",
        evaluation_policy=outcome_policy,
        outcome_kinds={
            "request-1": "vm-succeeded",
            "request-2": "fault",
            "request-3": "capacity-refused",
            "request-4": "capacity-refused",
        },
        fault_variants={"request-2": "swallowed-site-error"},
        wall_clock_minute=2,
    )
    b8_failure = _measured_case(
        repo,
        scm_ref,
        "b8-s1-g1-measured",
        evaluation_policy=outcome_policy,
        outcome_kinds={
            "request-1": "vm-succeeded",
            "request-2": "fault",
            **{f"request-{number}": "capacity-refused" for number in range(3, 9)},
        },
        fault_variants={"request-2": "swallowed-site-error"},
        wall_clock_minute=3,
    )
    cases = (
        _measured_case(
            repo,
            scm_ref,
            "q0-b1-s1-g1-measured",
            evaluation_policy=outcome_policy,
        ),
        b2_capacity_case,
        b4_failure,
        b8_failure,
        _measured_case(
            repo,
            scm_ref,
            "b3-s1-g1-measured",
            evaluation_policy=outcome_policy,
            wall_clock_minute=4,
        ),
    )
    value, receipt = _validated_buyer_frontier(
        outcome_policy,
        [case.result for case in cases],
    )
    return cases, value, receipt


@pytest.fixture(scope="module")
def seller_progression_cases(
    lower_bound_buyer_frontier: tuple[
        tuple[CapacityCase, ...],
        dict[str, Any],
        ValidatedBuyerFrontierReceipt,
    ],
    serialized_reuse_cases: tuple[CapacityCase, CapacityCase],
) -> tuple[CapacityCase, CapacityCase]:
    buyer_cases, _frontier_value, buyer_frontier = lower_bound_buyer_frontier
    repo = buyer_cases[0].chain.repo
    scm_ref = buyer_cases[0].chain.scm_ref
    policy = buyer_cases[0].evaluation_policy
    _reuse_a, reuse_b = serialized_reuse_cases
    seller_b2 = _measured_case(
        repo,
        scm_ref,
        "b2-s2-g1-measured",
        evaluation_policy=policy,
        buyer_frontier=buyer_frontier,
        reuse_baseline=reuse_b.result,
        wall_clock_minute=13,
    )
    seller_b4 = _measured_case(
        repo,
        scm_ref,
        "b4-s2-g1-measured",
        evaluation_policy=policy,
        buyer_frontier=buyer_frontier,
        reuse_baseline=reuse_b.result,
        prior_seller_results=(seller_b2.result,),
        wall_clock_minute=14,
    )
    return seller_b2, seller_b4


def _revalidate_case(
    case: CapacityCase,
    value: dict[str, Any],
    *,
    evaluation_policy: ValidatedEvaluationPolicy | None = None,
    predecessor: ValidatedCapacityResult | None = None,
    buyer_frontier: ValidatedBuyerFrontierReceipt | None = None,
    reuse_baseline: ValidatedCapacityResult | None = None,
    prior_seller_results: Sequence[ValidatedCapacityResult] | None = None,
) -> ValidatedCapacityResult:
    return validate_capacity_result(
        value,
        case.chain.repo,
        evaluation_policy=evaluation_policy or case.evaluation_policy,
        oracle_authority=case.chain.oracle,
        actor_set=case.actor_set,
        role_evidence=case.chain.evidence,
        predecessor=predecessor,
        buyer_frontier=buyer_frontier or case.buyer_frontier,
        reuse_baseline=reuse_baseline or case.reuse_baseline,
        prior_seller_results=(
            case.prior_seller_results
            if prior_seller_results is None
            else prior_seller_results
        ),
        expected_scm_ref=case.chain.scm_ref,
    )


def _revalidate_reference_case(
    case: ReferenceCase,
    *,
    value: dict[str, Any] | None = None,
    role_evidence: Sequence[SubstantiveRoleEvidence] | None = None,
    oracle_authority: ValidatedOracleAuthority | None = None,
) -> ValidatedCapacityResult:
    plan = case.evidence[0].plan
    return validate_capacity_result(
        value or case.result_value,
        plan.repo_root,
        evaluation_policy=case.evaluation_policy,
        oracle_authority=oracle_authority or case.oracle,
        actor_set=None,
        reference_policy=case.reference_policy,
        role_evidence=role_evidence or case.evidence,
        expected_scm_ref=plan.scm_ref,
    )


def _positive_real_measured_b1_case(
    repo: Path,
    scm_ref: str,
) -> CapacityCase:
    chain = _real_chain(
        repo,
        scm_ref,
        "q0-b1-s1-g1-measured",
        successful_guest_request_ids={"request-1"},
    )
    actor_set, observation = _clean_stage_observation(chain)
    evaluation_policy = _validated_evaluation_policy(repo, scm_ref)
    stage = chain.plans[0].profile_stage
    assert stage.scenario is not None
    scenario = stage.scenario.scenario
    request_outcome = observation["request_outcome"]
    actor_set = _rebind_actor_set_observer_receipt(
        chain,
        request_outcomes=(request_outcome,),
        cleanup=observation["cleanup"],
        stage_started_at="2026-07-30T10:00:00.200000Z",
        terminal_observed_at="2026-07-30T10:00:10.000000Z",
        cleanup_completed_at="2026-07-30T10:00:11.000000Z",
    )
    actor_value = actor_set.actor_set
    latency_ns = (
        request_outcome["terminal_offset_ns"] - request_outcome["invoked_offset_ns"]
    )
    assessment = {
        "outcomes_match_expected": True,
        "request_processing_passed": True,
        "simultaneous_fulfillment_count": 1,
        "provisioning_passed": True,
        "correctness_passed": True,
        "load_generator_passed": True,
        "cleanup_passed": True,
        "stage_passed": True,
        "agent_capacity_evidence": True,
        "eligible_for_capacity_frontier": True,
        "derived_faults": [],
    }
    result_value = {
        "schema_version": 2,
        "result_id": "q0-b1-s1-g1-measured-result",
        "scm_ref": scm_ref,
        "profile_stage_id": stage.stage_id,
        "profile_stage_sha256": stage.canonical_sha256,
        "scenario_id": stage.scenario.scenario_id,
        "scenario_sha256": stage.scenario.scenario_sha256,
        "execution_boundary": "real-measured",
        "actor_trigger": "agent-triggered",
        "evaluation_policy": {
            "evaluation_policy_id": evaluation_policy.policy_id,
            "evaluation_policy_sha256": evaluation_policy.canonical_sha256,
        },
        "oracle_authority": {
            "oracle_authority_id": chain.oracle.oracle_authority_id,
            "oracle_authority_sha256": chain.oracle.canonical_sha256,
            "observer_plan_sha256": chain.oracle.authority["observer_plan_sha256"],
        },
        "execution_authority": {
            "kind": "agent-actor-set",
            "actor_set_id": actor_set.actor_set_id,
            "actor_set_sha256": actor_set.canonical_sha256,
            "release_id": actor_value["release_id"],
            "concurrency_policy_id": actor_value["concurrency_policy_id"],
            "concurrency_policy_sha256": actor_value["concurrency_policy_sha256"],
        },
        "topology_authority_binding": observation["topology_authority_binding"],
        "started_at": "2026-07-30T10:00:00.200000Z",
        "terminal_observed_at": "2026-07-30T10:00:10.000000Z",
        "cleanup_completed_at": "2026-07-30T10:00:11.000000Z",
        "progression_ready_at": "2026-07-30T10:00:12.000000Z",
        "expected_outcomes": scenario["expected_outcomes"],
        "observed_outcomes": {
            "vm-succeeded": 1,
            "capacity-refused": 0,
            "fault": 0,
        },
        "request_outcomes": [request_outcome],
        "aggregate_observation": {
            "observer_plan_sha256": chain.oracle.authority["observer_plan_sha256"],
            "observed_request_ids": ["request-1"],
            "request_timing_observations": [
                {
                    "request_id": "request-1",
                    "invoked_offset_ns": request_outcome["invoked_offset_ns"],
                    "terminal_offset_ns": request_outcome["terminal_offset_ns"],
                    "native_evidence_binding": observation[
                        "observer_native_evidence_bindings"
                    ][0],
                }
            ],
            "observed_at": "2026-07-30T10:00:09.000000Z",
            "common_clock_binding": actor_value["clock_evidence_binding"],
            "native_evidence_bindings": observation[
                "observer_native_evidence_bindings"
            ],
            "max_overlapping_whole_gpu_vms": 1,
        },
        "cleanup": observation["cleanup"],
        "stage_assessment": assessment,
        "buyer_frontier_authority": None,
        "reuse_predecessor": None,
        "seller_progression_authority": None,
        "frontier_observation": {
            "offered_buyers": 1,
            "request_processing": {
                "passed": True,
                "observed_max_ns": latency_ns,
                "slo_ns": evaluation_policy.request_processing_slo_ns,
            },
            "simultaneous_fulfillment": {
                "max_overlapping_whole_gpu_vms": 1,
            },
            "provisioning_queue": {
                "passed": True,
                "observed_max_ns": 10,
                "slo_ns": evaluation_policy.provisioning_queue_slo_ns,
            },
            "ansible_service": {
                "passed": True,
                "observed_max_ns": 20,
                "slo_ns": evaluation_policy.ansible_service_slo_ns,
            },
            "correctness_passed": True,
            "load_generator_passed": True,
        },
    }
    result = validate_capacity_result(
        result_value,
        repo,
        evaluation_policy=evaluation_policy,
        oracle_authority=chain.oracle,
        actor_set=actor_set,
        role_evidence=chain.evidence,
        expected_scm_ref=scm_ref,
    )
    return CapacityCase(
        chain=chain,
        actor_set=actor_set,
        evaluation_policy=evaluation_policy,
        result_value=result_value,
        result=result,
    )


def test_positive_real_measured_b1_capacity_result(
    outcome_authority_repo: tuple[Path, str],
) -> None:
    repo, scm_ref = outcome_authority_repo
    case = _positive_real_measured_b1_case(repo, scm_ref)

    assert case.result.stage_passed is True
    assert case.result.agent_capacity_evidence is True
    assert case.result.eligible_for_capacity_frontier is True
    assert case.result.derived_faults == ()
    assert case.result.simultaneous_fulfillment_count == 1
    assert case.result.outcome_kinds == ("vm-succeeded",)


def test_positive_real_reference_b1_is_actionless_non_frontier_evidence(
    reference_b1_capacity_case: ReferenceCase,
) -> None:
    case = reference_b1_capacity_case

    assert case.result.stage_passed is True
    assert case.result.agent_capacity_evidence is False
    assert case.result.eligible_for_capacity_frontier is False
    assert {item.plan.role for item in case.evidence} == {
        "host-operator",
        "observer",
    }
    assert all(not item.actions and not item.results for item in case.evidence)
    assert case.result_value["execution_authority"]["controller_is_counted"] is False


def test_reference_result_requires_pre_release_policy_and_exact_receipts(
    reference_b1_capacity_case: ReferenceCase,
) -> None:
    case = reference_b1_capacity_case
    tampered = deepcopy(case.result_value)
    tampered["execution_authority"]["observer_receipt_sha256"] = "f" * 64
    with pytest.raises(
        CapacityValidationError,
        match="exact observer_receipt_sha256",
    ):
        validate_capacity_result(
            tampered,
            case.evidence[0].plan.repo_root,
            evaluation_policy=case.evaluation_policy,
            oracle_authority=case.oracle,
            reference_policy=case.reference_policy,
            role_evidence=case.evidence,
            expected_scm_ref=case.evidence[0].plan.scm_ref,
        )

    with pytest.raises(
        CapacityValidationError,
        match="validated pre-release policy",
    ):
        validate_capacity_result(
            case.result_value,
            case.evidence[0].plan.repo_root,
            evaluation_policy=case.evaluation_policy,
            oracle_authority=case.oracle,
            role_evidence=case.evidence,
            expected_scm_ref=case.evidence[0].plan.scm_ref,
        )


def test_reference_result_rejects_raw_unvalidated_reference_policy(
    reference_b1_capacity_case: ReferenceCase,
) -> None:
    case = reference_b1_capacity_case

    with pytest.raises(
        CapacityValidationError,
        match="validated pre-release policy",
    ):
        validate_capacity_result(
            case.result_value,
            case.evidence[0].plan.repo_root,
            evaluation_policy=case.evaluation_policy,
            oracle_authority=case.oracle,
            reference_policy=(  # type: ignore[arg-type]
                case.reference_policy.policy
            ),
            role_evidence=case.evidence,
            expected_scm_ref=case.evidence[0].plan.scm_ref,
        )


def test_reference_policy_clock_property_is_an_immutable_snapshot(
    reference_b1_capacity_case: ReferenceCase,
) -> None:
    policy = reference_b1_capacity_case.reference_policy
    expected = policy.policy["clock_evidence_binding"]
    leaked = policy.clock_evidence_binding
    leaked["value"] = "f" * 64

    assert policy.clock_evidence_binding == expected
    assert policy.policy["clock_evidence_binding"] == expected


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("release", "validated policy release_id"),
        ("clock", "validated policy clock_evidence_binding"),
        ("schedule", "frozen request schedule"),
        ("controller-proof", "reference_execution_binding"),
    ],
)
def test_reference_result_rejects_changed_controller_authority(
    reference_b1_capacity_case: ReferenceCase,
    mutation: str,
    message: str,
) -> None:
    case = reference_b1_capacity_case
    value = deepcopy(case.result_value)
    authority = value["execution_authority"]
    if mutation == "release":
        authority["release_id"] = "post-freeze-reference-release"
    elif mutation == "clock":
        authority["clock_evidence_binding"] = binding(
            NATIVE_EVIDENCE_BINDING_DOMAIN,
            "post-freeze-reference-clock",
        )
    elif mutation == "schedule":
        authority["request_timing_observations"][0]["invoked_offset_ns"] += 1
    else:
        authority["reference_execution_binding"] = digest("raw-controller-proof")

    with pytest.raises(CapacityValidationError, match=message):
        _revalidate_reference_case(case, value=value)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("plan-id", "distinct plan IDs"),
        ("isolated-identity", "distinct isolated identities"),
        ("invocation-capability", "distinct invocation capabilities"),
    ],
)
def test_reference_policy_rejects_shared_o1_h1_authority(
    reference_b1_capacity_case: ReferenceCase,
    mutation: str,
    message: str,
) -> None:
    case = reference_b1_capacity_case
    observer = next(item.plan for item in case.evidence if item.plan.role == "observer")
    host = next(
        item.plan for item in case.evidence if item.plan.role == "host-operator"
    )
    host_value = host.plan
    if mutation == "plan-id":
        host_value["plan_id"] = observer.plan_id
    elif mutation == "isolated-identity":
        host_value["isolated_identity_fingerprint"] = observer.plan[
            "isolated_identity_fingerprint"
        ]
    else:
        host_value["actor_invocation_capability_binding"] = observer.plan[
            "actor_invocation_capability_binding"
        ]
    shared_host = validate_role_plan(
        host_value,
        host.repo_root,
        expected_scm_ref=host.scm_ref,
    )
    policy_value = case.reference_policy.policy
    policy_value["host_plan"] = {
        "plan_id": shared_host.plan_id,
        "plan_sha256": shared_host.canonical_sha256,
    }

    with pytest.raises(CapacityValidationError, match=message):
        validate_reference_policy(
            policy_value,
            host.repo_root,
            evaluation_policy=case.evaluation_policy,
            observer_plan=observer,
            host_plan=shared_host,
            expected_scm_ref=host.scm_ref,
        )


@pytest.mark.parametrize(
    ("role", "policy_field"),
    [
        ("observer", "observer_plan"),
        ("host-operator", "host_plan"),
    ],
)
def test_reference_result_rejects_post_freeze_role_plan_substitution(
    reference_b1_capacity_case: ReferenceCase,
    role: str,
    policy_field: str,
) -> None:
    case = reference_b1_capacity_case
    original = next(item for item in case.evidence if item.plan.role == role)
    plan_value = original.plan.plan
    plan_value["plan_id"] = f"{original.plan.plan_id}-post-freeze"
    plan_value["isolated_identity_fingerprint"] = digest(f"{role}:post-freeze-identity")
    plan_value["actor_invocation_capability_binding"] = binding(
        ACTOR_INVOCATION_BINDING_DOMAIN,
        f"{role}:post-freeze-capability",
    )
    alternate_plan = validate_role_plan(
        plan_value,
        original.plan.repo_root,
        expected_scm_ref=original.plan.scm_ref,
    )

    receipt_value = original.receipt.receipt
    receipt_value["receipt_id"] = f"{original.receipt.receipt_id}-post-freeze"
    receipt_value["plan_id"] = alternate_plan.plan_id
    receipt_value["plan_sha256"] = alternate_plan.canonical_sha256
    receipt_value["isolated_identity_fingerprint"] = alternate_plan.plan[
        "isolated_identity_fingerprint"
    ]
    receipt_value["provenance"]["actor_invocation_capability_binding"] = (
        alternate_plan.plan["actor_invocation_capability_binding"]
    )
    receipt_value["provenance"]["actor_liveness_binding"] = binding(
        NATIVE_EVIDENCE_BINDING_DOMAIN,
        f"{role}:post-freeze-liveness",
    )
    alternate_receipt = validate_role_receipt(
        receipt_value,
        alternate_plan,
    )
    alternate_evidence = validate_substantive_role_evidence(
        alternate_plan,
        alternate_receipt,
        (),
        (),
    )
    evidence = tuple(
        alternate_evidence if item.plan.role == role else item for item in case.evidence
    )

    value = deepcopy(case.result_value)
    authority = value["execution_authority"]
    authority[f"{'observer' if role == 'observer' else 'host'}_receipt_id"] = (
        alternate_receipt.receipt_id
    )
    authority[f"{'observer' if role == 'observer' else 'host'}_receipt_sha256"] = (
        alternate_receipt.canonical_sha256
    )
    oracle = case.oracle
    if role == "observer":
        oracle = _oracle(
            original.plan.repo_root,
            original.plan.scm_ref,
            original.plan.profile_stage_id,
            [alternate_plan],
        )
        value["oracle_authority"] = {
            "oracle_authority_id": oracle.oracle_authority_id,
            "oracle_authority_sha256": oracle.canonical_sha256,
            "observer_plan_sha256": oracle.authority["observer_plan_sha256"],
        }
        value["aggregate_observation"]["observer_plan_sha256"] = oracle.authority[
            "observer_plan_sha256"
        ]

    with pytest.raises(
        CapacityValidationError,
        match=f"exact policy-bound {policy_field}",
    ):
        _revalidate_reference_case(
            case,
            value=value,
            role_evidence=evidence,
            oracle_authority=oracle,
        )


@pytest.mark.parametrize("role", ["host-operator", "observer"])
def test_reference_receipts_require_explicit_non_controller_run_authority(
    reference_b1_capacity_case: ReferenceCase,
    role: str,
) -> None:
    item = next(
        evidence
        for evidence in reference_b1_capacity_case.evidence
        if evidence.plan.role == role
    )

    missing = item.receipt.receipt
    missing.pop("run_authority")
    with pytest.raises(CapacityValidationError, match="run_authority"):
        validate_role_receipt(missing, item.plan)

    controller_authored = item.receipt.receipt
    controller_authored["provenance"]["controller_authored"] = True
    with pytest.raises(CapacityValidationError, match="controller"):
        validate_role_receipt(controller_authored, item.plan)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("receipt-id", "distinct receipt IDs"),
        ("liveness", "distinct liveness evidence"),
    ],
)
def test_reference_result_rejects_shared_o1_h1_receipt_authority(
    reference_b1_capacity_case: ReferenceCase,
    mutation: str,
    message: str,
) -> None:
    case = reference_b1_capacity_case
    observer = next(item for item in case.evidence if item.plan.role == "observer")
    host = next(item for item in case.evidence if item.plan.role == "host-operator")
    receipt_value = host.receipt.receipt
    if mutation == "receipt-id":
        receipt_value["receipt_id"] = observer.receipt.receipt_id
    else:
        receipt_value["provenance"]["actor_liveness_binding"] = (
            observer.receipt.receipt["provenance"]["actor_liveness_binding"]
        )
    receipt = validate_role_receipt(receipt_value, host.plan)
    shared_host = validate_substantive_role_evidence(
        host.plan,
        receipt,
        (),
        (),
    )
    evidence = tuple(
        shared_host if item.plan.role == "host-operator" else item
        for item in case.evidence
    )
    value = deepcopy(case.result_value)
    authority = value["execution_authority"]
    authority["host_receipt_id"] = receipt.receipt_id
    authority["host_receipt_sha256"] = receipt.canonical_sha256

    with pytest.raises(CapacityValidationError, match=message):
        _revalidate_reference_case(
            case,
            value=value,
            role_evidence=evidence,
        )


@pytest.mark.parametrize("role", ["host-operator", "observer"])
def test_reference_result_rejects_stale_o1_h1_run_authority(
    reference_b1_capacity_case: ReferenceCase,
    role: str,
) -> None:
    stale_evidence: list[SubstantiveRoleEvidence] = []
    for item in reference_b1_capacity_case.evidence:
        if item.plan.role != role:
            stale_evidence.append(item)
            continue
        receipt_value = item.receipt.receipt
        receipt_value["run_authority"] = {
            "release_id": "stale-reference-release",
            "concurrency_policy_id": "stale-reference-policy",
            "concurrency_policy_sha256": "0" * 64,
        }
        receipt = validate_role_receipt(receipt_value, item.plan)
        stale_evidence.append(
            validate_substantive_role_evidence(
                item.plan,
                receipt,
                (),
                (),
            )
        )

    with pytest.raises(
        CapacityValidationError,
        match="exact controller reference policy and release",
    ):
        _revalidate_reference_case(
            reference_b1_capacity_case,
            role_evidence=stale_evidence,
        )


def test_capacity_result_rejects_semantically_tampered_assessment(
    outcome_authority_repo: tuple[Path, str],
) -> None:
    repo, scm_ref = outcome_authority_repo
    case = _positive_real_measured_b1_case(repo, scm_ref)
    tampered = deepcopy(case.result_value)
    tampered["stage_assessment"]["correctness_passed"] = False

    with pytest.raises(
        CapacityValidationError,
        match=("stage assessment must equal independently derived outcome predicates"),
    ):
        validate_capacity_result(
            tampered,
            repo,
            evaluation_policy=case.evaluation_policy,
            oracle_authority=case.chain.oracle,
            actor_set=case.actor_set,
            role_evidence=case.chain.evidence,
            expected_scm_ref=scm_ref,
        )


def test_capacity_result_rejects_raw_unvalidated_oracle_object(
    b2_capacity_case: CapacityCase,
) -> None:
    with pytest.raises(
        CapacityValidationError,
        match="validated independent oracle authority",
    ):
        validate_capacity_result(
            b2_capacity_case.result_value,
            b2_capacity_case.chain.repo,
            evaluation_policy=b2_capacity_case.evaluation_policy,
            oracle_authority=(  # type: ignore[arg-type]
                b2_capacity_case.chain.oracle.authority
            ),
            actor_set=b2_capacity_case.actor_set,
            role_evidence=b2_capacity_case.chain.evidence,
            expected_scm_ref=b2_capacity_case.chain.scm_ref,
        )


def test_b2_correlates_success_and_complete_atomic_refusal(
    b2_capacity_case: CapacityCase,
) -> None:
    result = b2_capacity_case.result
    refusal = b2_capacity_case.result_value["request_outcomes"][1]

    assert result.stage_passed is True
    assert result.outcome_kinds == (
        "vm-succeeded",
        "capacity-refused",
    )
    assert refusal["refusal_observation"]["final_escrow_scoped_call"] is True
    assert refusal["refusal_observation"]["aggregate_reservation_id"] is None
    assert refusal["capacity_reservation_id"] is None
    assert refusal["fulfillment_id"] is None
    assert all(
        attempt["response_kind"] == "routine-reservation-null"
        and attempt["observed"] is True
        and attempt["skipped"] is False
        and attempt["error_category"] is None
        for attempt in refusal["refusal_observation"]["site_attempts"]
    )


def test_success_allows_optional_diagnostic_ids_to_be_absent(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
) -> None:
    repo, scm_ref = outcome_authority_repo
    case = _measured_case(
        repo,
        scm_ref,
        "b2-s1-g1-measured",
        evaluation_policy=outcome_policy,
        wall_clock_minute=1,
        omit_success_diagnostic_ids=True,
    )
    success = case.result_value["request_outcomes"][0]

    assert success["allocation_id"] is None
    assert success["provisioning_job_id"] is None
    assert case.result.stage_passed is True


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            "swallowed-site-error",
            "not valid under any",
        ),
        (
            "non-final-soft-hold",
            "final_escrow_scoped_call",
        ),
    ],
)
def test_refusal_rejects_incomplete_atomic_scarcity_proof(
    b2_capacity_case: CapacityCase,
    mutation: str,
    message: str,
) -> None:
    value = deepcopy(b2_capacity_case.result_value)
    refusal = value["request_outcomes"][1]["refusal_observation"]
    if mutation == "swallowed-site-error":
        attempt = refusal["site_attempts"][0]
        attempt["response_kind"] = "error"
        attempt["error_category"] = "site-rpc-failed"
    else:
        refusal["final_escrow_scoped_call"] = False
        refusal["capacity_hold_unavailable_observed"] = True

    with pytest.raises(CapacityValidationError, match=message):
        _revalidate_case(b2_capacity_case, value)


def test_success_rejects_settlement_with_null_fulfillment(
    b2_capacity_case: CapacityCase,
) -> None:
    value = deepcopy(b2_capacity_case.result_value)
    value["request_outcomes"][0]["settlement_record"]["fulfillment_id"] = None

    with pytest.raises(
        CapacityValidationError,
        match="Settlement Record fulfillment",
    ):
        _revalidate_case(b2_capacity_case, value)


@pytest.mark.parametrize(
    ("terminal_offset_ns", "message"),
    [
        (410, "cannot precede its action wrapper terminal result"),
        (502, "must remain inside its buyer actor lifetime"),
    ],
)
def test_request_terminal_is_bounded_by_action_and_buyer_lifetime(
    b2_capacity_case: CapacityCase,
    terminal_offset_ns: int,
    message: str,
) -> None:
    value = deepcopy(b2_capacity_case.result_value)
    value["request_outcomes"][0]["terminal_offset_ns"] = terminal_offset_ns

    with pytest.raises(CapacityValidationError, match=message):
        _revalidate_case(b2_capacity_case, value)


def test_success_rejects_wrong_runtime_and_durable_join(
    b2_capacity_case: CapacityCase,
) -> None:
    wrong_runtime = deepcopy(b2_capacity_case.result_value)
    wrong_runtime["request_outcomes"][0]["deal_reference"]["runtime_binding"] = binding(
        RUNTIME_BINDING_DOMAIN, "wrong-listing"
    )
    with pytest.raises(CapacityValidationError, match="runtime_binding"):
        _revalidate_case(b2_capacity_case, wrong_runtime)

    wrong_join = deepcopy(b2_capacity_case.result_value)
    wrong_join["request_outcomes"][0]["success_observation"][
        "reservation_fulfillment_join"
    ]["provisioned_fulfillment_id"] = "wrong-fulfillment"
    with pytest.raises(CapacityValidationError, match="durable join"):
        _revalidate_case(b2_capacity_case, wrong_join)


@pytest.mark.parametrize(
    "field_name",
    [
        "capacity_reservation_id",
        "fulfillment_id",
        "provisioned_resource_id",
    ],
)
def test_success_rejects_missing_required_durable_identity(
    b2_capacity_case: CapacityCase,
    field_name: str,
) -> None:
    value = deepcopy(b2_capacity_case.result_value)
    value["request_outcomes"][0][field_name] = None

    with pytest.raises(
        CapacityValidationError,
        match=rf"vm-succeeded requires non-null {field_name}",
    ):
        _revalidate_case(b2_capacity_case, value)


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("seller_slot", "seller-99"),
        ("listing_slot", "listing-99"),
    ],
)
def test_success_rejects_wrong_logical_seller_or_listing_selection(
    b2_capacity_case: CapacityCase,
    field_name: str,
    replacement: str,
) -> None:
    value = deepcopy(b2_capacity_case.result_value)
    value["request_outcomes"][0]["deal_reference"][field_name] = replacement

    with pytest.raises(
        CapacityValidationError,
        match=(
            rf"deal_reference\.{field_name} does not match "
            "frozen request authority"
        ),
    ):
        _revalidate_case(b2_capacity_case, value)


def test_raw_private_identifier_digest_is_not_a_runtime_binding(
    b2_capacity_case: CapacityCase,
) -> None:
    value = deepcopy(b2_capacity_case.result_value)
    value["request_outcomes"][0]["deal_reference"]["runtime_binding"] = digest(
        "private-enumerable-runtime-id"
    )

    with pytest.raises(CapacityValidationError, match="runtime_binding"):
        _revalidate_case(b2_capacity_case, value)


def test_capacity_result_rejects_result_h1_topology_mismatch(
    b2_capacity_case: CapacityCase,
) -> None:
    value = deepcopy(b2_capacity_case.result_value)
    value["topology_authority_binding"] = binding(
        TOPOLOGY_BINDING_DOMAIN,
        "result-h1-topology-mismatch",
    )

    with pytest.raises(
        CapacityValidationError,
        match="capacity result topology does not match host authority",
    ):
        _revalidate_case(b2_capacity_case, value)


@pytest.mark.parametrize(
    "mutation",
    ["cross-variant-field", "unknown-top-level-field"],
)
def test_capacity_result_rejects_malformed_closed_input(
    b2_capacity_case: CapacityCase,
    mutation: str,
) -> None:
    value = deepcopy(b2_capacity_case.result_value)
    if mutation == "cross-variant-field":
        value["request_outcomes"][0]["refusal_observation"] = deepcopy(
            value["request_outcomes"][1]["refusal_observation"]
        )
    else:
        value["private_result_key"] = "must-not-enter-portable-evidence"

    with pytest.raises(
        CapacityValidationError,
        match="not valid under any|Additional properties",
    ):
        _revalidate_case(b2_capacity_case, value)


def test_half_open_overlap_releases_capacity_at_shared_boundary() -> None:
    assert maximum_half_open_overlap([(0, 10), (10, 20)]) == 1
    assert maximum_half_open_overlap([(0, 11), (10, 20)]) == 2


def test_cleanup_rejects_omission_and_unreported_residue(
    b2_capacity_case: CapacityCase,
) -> None:
    omitted = deepcopy(b2_capacity_case.result_value)
    omitted["cleanup"]["reversible_components"].pop()
    with pytest.raises(CapacityValidationError, match="reversible_components"):
        _revalidate_case(b2_capacity_case, omitted)

    residue = deepcopy(b2_capacity_case.result_value)
    residue["cleanup"]["residue_counts"]["vms"] = 1
    with pytest.raises(
        CapacityValidationError,
        match="ready_for_next_stage|stage assessment",
    ):
        _revalidate_case(b2_capacity_case, residue)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("wrong-offset", "timing does not match"),
        ("unrelated-binding", "exact independent observer evidence"),
        ("missing-request", "cover every exact request"),
    ],
)
def test_independent_request_timing_rejects_wrong_or_unrelated_evidence(
    b2_capacity_case: CapacityCase,
    mutation: str,
    message: str,
) -> None:
    value = deepcopy(b2_capacity_case.result_value)
    timings = value["aggregate_observation"]["request_timing_observations"]
    if mutation == "wrong-offset":
        timings[0]["terminal_offset_ns"] += 1
    elif mutation == "unrelated-binding":
        timings[0]["native_evidence_binding"] = binding(
            NATIVE_EVIDENCE_BINDING_DOMAIN,
            "unrelated-timing",
        )
    else:
        timings.pop()

    with pytest.raises(CapacityValidationError, match=message):
        _revalidate_case(b2_capacity_case, value)


def test_observer_receipt_seals_exact_request_outcome_bytes(
    b2_capacity_case: CapacityCase,
) -> None:
    value = deepcopy(b2_capacity_case.result_value)
    value["request_outcomes"][0]["allocation_id"] = (
        "semantically-plausible-but-unobserved-allocation"
    )

    with pytest.raises(
        CapacityValidationError,
        match="outcome bytes do not match the independent observer receipt",
    ):
        _revalidate_case(b2_capacity_case, value)


def test_observer_receipt_seals_exact_cleanup_bytes(
    b2_capacity_case: CapacityCase,
) -> None:
    value = deepcopy(b2_capacity_case.result_value)
    value["cleanup"]["native_evidence_bindings"].append(
        binding(
            NATIVE_EVIDENCE_BINDING_DOMAIN,
            "unobserved-cleanup-recomputation",
        )
    )

    with pytest.raises(
        CapacityValidationError,
        match="cleanup bytes do not match the independent observer receipt",
    ):
        _revalidate_case(b2_capacity_case, value)


def test_progression_readiness_is_final_h1_o1_evidence_completion(
    b2_capacity_case: CapacityCase,
) -> None:
    value = deepcopy(b2_capacity_case.result_value)
    value["progression_ready_at"] = value["cleanup_completed_at"]

    with pytest.raises(
        CapacityValidationError,
        match="final H1/O1 evidence completion",
    ):
        _revalidate_case(b2_capacity_case, value)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("deal-hash", "exact deal reference"),
        ("clock", "stage common clock"),
        ("outside-interval", "inside the request interval"),
        ("unrelated-site", "outside the eligible-site set"),
        ("duplicate-slot", "duplicate site slots"),
        ("duplicate-binding", "distinct private bindings"),
    ],
)
def test_partial_atomic_fault_rejects_forged_observation_authority(
    atomic_refusal_fault_case: CapacityCase,
    mutation: str,
    message: str,
) -> None:
    value = deepcopy(atomic_refusal_fault_case.result_value)
    fault = value["request_outcomes"][1]
    atomic = fault["fault_observation"]["atomic_reservation_observation"]
    if mutation == "deal-hash":
        atomic["deal_reference_sha256"] = "f" * 64
    elif mutation == "clock":
        atomic["clock_evidence_binding"] = binding(
            NATIVE_EVIDENCE_BINDING_DOMAIN,
            "wrong-atomic-clock",
        )
    elif mutation == "outside-interval":
        atomic["started_offset_ns"] = fault["invoked_offset_ns"] - 1
    elif mutation == "unrelated-site":
        atomic["site_attempts"][0]["site_slot"] = "site-2"
    elif mutation == "duplicate-slot":
        duplicate = deepcopy(atomic["site_attempts"][0])
        duplicate["site_binding"] = binding(
            NATIVE_EVIDENCE_BINDING_DOMAIN,
            "second-private-site-binding",
        )
        atomic["site_attempts"].append(duplicate)
    else:
        atomic["eligible_site_slots"].append("site-2")
        duplicate_binding = deepcopy(atomic["site_attempts"][0])
        duplicate_binding["site_slot"] = "site-2"
        atomic["site_attempts"].append(duplicate_binding)

    with pytest.raises(CapacityValidationError, match=message):
        _revalidate_case(atomic_refusal_fault_case, value)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("created-with-null-id", "contradictory reservation state"),
        ("error-with-null-category", "contradictory error state"),
        ("error-with-reservation", "contradictory error state"),
        ("routine-null-with-error", "contradictory routine-null state"),
        ("skipped-created", "skipped state must be recorded as missing"),
        ("missing-hidden-reservation", "contradictory missing state"),
    ],
)
def test_partial_atomic_fault_rejects_contradictory_site_response(
    atomic_refusal_fault_case: CapacityCase,
    mutation: str,
    message: str,
) -> None:
    value = deepcopy(atomic_refusal_fault_case.result_value)
    attempt = value["request_outcomes"][1]["fault_observation"][
        "atomic_reservation_observation"
    ]["site_attempts"][0]
    if mutation == "created-with-null-id":
        attempt["response_kind"] = "reservation-created"
        attempt["error_category"] = None
    elif mutation == "error-with-null-category":
        attempt["error_category"] = None
    elif mutation == "error-with-reservation":
        attempt["reservation_id"] = "hidden-reservation"
    elif mutation == "routine-null-with-error":
        attempt["response_kind"] = "routine-reservation-null"
    elif mutation == "skipped-created":
        attempt["response_kind"] = "reservation-created"
        attempt["reservation_id"] = "skipped-reservation"
        attempt["error_category"] = None
        attempt["observed"] = False
        attempt["skipped"] = True
    else:
        attempt["response_kind"] = "missing"
        attempt["reservation_id"] = "hidden-reservation"
        attempt["error_category"] = None
        attempt["observed"] = False

    with pytest.raises(CapacityValidationError, match=message):
        _revalidate_case(atomic_refusal_fault_case, value)


@pytest.mark.parametrize(
    ("variant", "failure_category"),
    [
        ("swallowed-site-error", "atomic-refusal-incomplete"),
        ("missing-site-response", "atomic-refusal-incomplete"),
        ("skipped-site-response", "atomic-refusal-incomplete"),
        (
            "reservation-created-site-response",
            "atomic-refusal-incomplete",
        ),
        ("nonterminal-complete-atomic", "uncompensated"),
        ("timeout", "timeout"),
        ("generic-failure", "generic-failure"),
        ("provisioning-error", "provisioning-error"),
        ("policy-denial", "policy-denial"),
        ("unknown-reason", "unknown-reason"),
        (
            "missing-durable-correlation",
            "missing-durable-correlation",
        ),
        ("cleanup-incomplete", "cleanup-incomplete"),
    ],
)
def test_typed_faults_remain_agent_evidence_but_fail_product_progression(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
    variant: str,
    failure_category: str,
) -> None:
    repo, scm_ref = outcome_authority_repo
    case = _measured_case(
        repo,
        scm_ref,
        "b2-s1-g1-measured",
        evaluation_policy=outcome_policy,
        outcome_kinds={
            "request-1": "vm-succeeded",
            "request-2": "fault",
        },
        fault_variants={"request-2": variant},
    )
    fault = case.result_value["request_outcomes"][1]

    assert fault["failure_category"] == failure_category
    assert case.result.stage_passed is False
    assert case.result.agent_capacity_evidence is True
    assert case.result.eligible_for_capacity_frontier is True
    assert case.result.correctness_passed is False


def test_swallowed_site_error_keeps_aggregate_reservation_null(
    atomic_refusal_fault_case: CapacityCase,
) -> None:
    atomic = atomic_refusal_fault_case.result_value["request_outcomes"][1][
        "fault_observation"
    ]["atomic_reservation_observation"]

    assert atomic["site_attempts"][0]["response_kind"] == "error"
    assert atomic["aggregate_reservation_id"] is None


def test_complete_routine_refusal_cannot_masquerade_as_fault(
    b2_capacity_case: CapacityCase,
) -> None:
    value = deepcopy(b2_capacity_case.result_value)
    refusal = value["request_outcomes"][1]
    atomic = refusal.pop("refusal_observation")
    refusal["outcome_kind"] = "fault"
    refusal["failure_category"] = "generic-failure"
    refusal["fault_observation"] = {
        "phase": "reservation",
        "timed_out": False,
        "atomic_reservation_observation": atomic,
        "diagnostic_code": "mislabeled-routine-refusal",
    }

    with pytest.raises(
        CapacityValidationError,
        match="complete routine atomic refusal cannot be mislabeled as a fault",
    ):
        _revalidate_case(b2_capacity_case, value)


def test_timeout_at_exact_frozen_deadline_is_typed_fault_evidence(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
) -> None:
    repo, scm_ref = outcome_authority_repo
    case = _measured_case(
        repo,
        scm_ref,
        "b2-s1-g1-measured",
        evaluation_policy=outcome_policy,
        outcome_kinds={
            "request-1": "vm-succeeded",
            "request-2": "fault",
        },
        fault_variants={"request-2": "timeout"},
    )
    timeout = case.result_value["request_outcomes"][1]

    assert (
        timeout["terminal_offset_ns"] - timeout["invoked_offset_ns"]
        == outcome_policy.terminal_observation_timeout_ns
    )
    assert timeout["failure_category"] == "timeout"
    assert timeout["fault_observation"]["timed_out"] is True


def test_timeout_before_frozen_deadline_is_rejected(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
) -> None:
    repo, scm_ref = outcome_authority_repo

    with pytest.raises(
        CapacityValidationError,
        match="timeout classification does not match",
    ):
        _measured_case(
            repo,
            scm_ref,
            "b2-s1-g1-measured",
            evaluation_policy=outcome_policy,
            outcome_kinds={
                "request-1": "vm-succeeded",
                "request-2": "fault",
            },
            fault_variants={"request-2": "timeout"},
            terminal_latency_ns={
                "request-2": (outcome_policy.terminal_observation_timeout_ns - 1),
            },
        )


@pytest.mark.parametrize(
    ("late_kind", "request_id"),
    [
        ("vm-succeeded", "request-1"),
        ("capacity-refused", "request-2"),
    ],
)
def test_non_timeout_outcome_at_frozen_deadline_is_rejected(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
    late_kind: str,
    request_id: str,
) -> None:
    repo, scm_ref = outcome_authority_repo
    outcome_kinds = {
        "request-1": "vm-succeeded",
        "request-2": "capacity-refused",
    }
    outcome_kinds[request_id] = late_kind

    with pytest.raises(
        CapacityValidationError,
        match="must be classified as a timeout fault",
    ):
        _measured_case(
            repo,
            scm_ref,
            "b2-s1-g1-measured",
            evaluation_policy=outcome_policy,
            outcome_kinds=outcome_kinds,
            terminal_latency_ns={
                request_id: outcome_policy.terminal_observation_timeout_ns,
            },
        )


def test_cleanup_failure_is_preserved_as_negative_capacity_evidence(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
) -> None:
    repo, scm_ref = outcome_authority_repo
    case = _measured_case(
        repo,
        scm_ref,
        "q0-b1-s1-g1-measured",
        evaluation_policy=outcome_policy,
        cleanup_failure=True,
    )

    assert case.actor_set.capacity_eligible is False
    assert case.result.cleanup_passed is False
    assert case.result.correctness_passed is False
    assert case.result.stage_passed is False
    assert case.result.agent_capacity_evidence is True


def test_generator_rejection_is_fault_evidence_not_frontier_evidence(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
) -> None:
    repo, scm_ref = outcome_authority_repo
    case = _measured_case(
        repo,
        scm_ref,
        "q0-b1-s1-g1-measured",
        evaluation_policy=outcome_policy,
        outcome_kinds={"request-1": "fault"},
        fault_variants={"request-1": "generator-rejection"},
        generator_rejection_request_id="request-1",
    )

    assert case.actor_set.load_generator_passed is False
    assert case.result.outcome_kinds == ("fault",)
    assert case.result.agent_capacity_evidence is True
    assert case.result.eligible_for_capacity_frontier is False
    assert case.result.stage_passed is False


def test_one_gpu_double_allocation_is_preserved_as_derived_fault(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
) -> None:
    repo, scm_ref = outcome_authority_repo
    case = _measured_case(
        repo,
        scm_ref,
        "b2-s1-g1-measured",
        evaluation_policy=outcome_policy,
        outcome_kinds={
            "request-1": "vm-succeeded",
            "request-2": "vm-succeeded",
        },
    )

    assert case.result.simultaneous_fulfillment_count == 2
    assert case.result.correctness_passed is False
    assert case.result.stage_passed is False
    assert case.result.agent_capacity_evidence is True
    assert case.result.derived_faults == ("double-allocation",)


def test_serialized_reuse_requires_ordered_distinct_clean_lifecycles(
    serialized_reuse_cases: tuple[CapacityCase, CapacityCase],
) -> None:
    reuse_a, reuse_b = serialized_reuse_cases

    validate_serialized_reuse(reuse_a.result, reuse_b.result)
    assert reuse_a.buyer_frontier is not None
    expected_frontier_authority = {
        "buyer_frontier_receipt_id": (reuse_a.buyer_frontier.frontier_receipt_id),
        "buyer_frontier_receipt_sha256": (reuse_a.buyer_frontier.canonical_sha256),
    }
    assert (
        reuse_a.result_value["buyer_frontier_authority"] == expected_frontier_authority
    )
    assert (
        reuse_b.result_value["buyer_frontier_authority"] == expected_frontier_authority
    )
    assert reuse_a.result.cleanup_passed is True
    assert reuse_b.result.cleanup_passed is True
    assert (
        reuse_a.result_value["request_outcomes"][0]["fulfillment_id"]
        != reuse_b.result_value["request_outcomes"][0]["fulfillment_id"]
    )


def test_qualification_reuse_preserves_a_to_b_without_buyer_frontier(
    qualification_reuse_cases: tuple[CapacityCase, CapacityCase],
) -> None:
    reuse_a, reuse_b = qualification_reuse_cases

    validate_serialized_reuse(reuse_a.result, reuse_b.result)
    assert reuse_a.result.execution_boundary == "real-qualification"
    assert reuse_b.result.execution_boundary == "real-qualification"
    assert reuse_a.result_value["buyer_frontier_authority"] is None
    assert reuse_b.result_value["buyer_frontier_authority"] is None
    assert (
        reuse_b.result_value["reuse_predecessor"]["result_sha256"]
        == reuse_a.result.canonical_sha256
    )


def test_reuse_a_requires_exact_completed_buyer_frontier_fence(
    serialized_reuse_cases: tuple[CapacityCase, CapacityCase],
) -> None:
    reuse_a, _reuse_b = serialized_reuse_cases
    assert reuse_a.buyer_frontier is not None

    stale = deepcopy(reuse_a.result_value)
    stale["buyer_frontier_authority"]["buyer_frontier_receipt_sha256"] = "f" * 64
    with pytest.raises(
        CapacityValidationError,
        match="exact buyer-frontier receipt",
    ):
        _revalidate_case(reuse_a, stale)

    unfenced = deepcopy(reuse_a.result_value)
    unfenced["started_at"] = reuse_a.buyer_frontier.receipt["completed_at"]
    with pytest.raises(
        CapacityValidationError,
        match="strictly after the buyer frontier",
    ):
        _revalidate_case(reuse_a, unfenced)

    with pytest.raises(
        CapacityValidationError,
        match="requires a validated buyer-frontier receipt",
    ):
        validate_capacity_result(
            reuse_a.result_value,
            reuse_a.chain.repo,
            evaluation_policy=reuse_a.evaluation_policy,
            oracle_authority=reuse_a.chain.oracle,
            actor_set=reuse_a.actor_set,
            role_evidence=reuse_a.chain.evidence,
            expected_scm_ref=reuse_a.chain.scm_ref,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "ordering",
        "predecessor-digest",
        "reservation-replay",
        "frontier-lineage",
        "result-id-replay",
    ],
)
def test_serialized_reuse_rejects_fence_and_identity_tampering(
    serialized_reuse_cases: tuple[CapacityCase, CapacityCase],
    mutation: str,
) -> None:
    reuse_a, reuse_b = serialized_reuse_cases
    value = deepcopy(reuse_b.result_value)
    if mutation == "ordering":
        value["started_at"] = reuse_a.result_value["progression_ready_at"]
    elif mutation == "predecessor-digest":
        value["reuse_predecessor"]["result_sha256"] = "f" * 64
    elif mutation == "frontier-lineage":
        value["buyer_frontier_authority"]["buyer_frontier_receipt_sha256"] = "f" * 64
    elif mutation == "result-id-replay":
        value["result_id"] = reuse_a.result.result_id
    else:
        replayed = reuse_a.result_value["request_outcomes"][0][
            "capacity_reservation_id"
        ]
        outcome = value["request_outcomes"][0]
        outcome["capacity_reservation_id"] = replayed
        outcome["settlement_record"]["capacity_reservation_id"] = replayed
        join = outcome["success_observation"]["reservation_fulfillment_join"]
        join["fulfillment_capacity_reservation_id"] = replayed
        join["settlement_capacity_reservation_id"] = replayed

    with pytest.raises(
        CapacityValidationError,
        match="serialized reuse|reuse B|distinct result IDs",
    ):
        _revalidate_case(
            reuse_b,
            value,
            predecessor=reuse_a.result,
        )


def test_serialized_reuse_accepts_clean_correctness_despite_request_slo_miss(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
) -> None:
    repo, scm_ref = outcome_authority_repo
    strict_policy = _evaluation_policy_with_request_slo(
        outcome_policy,
        50,
    )
    strict_buyer_cases = tuple(
        _measured_case(
            repo,
            scm_ref,
            stage_id,
            evaluation_policy=strict_policy,
            wall_clock_minute=minute,
        )
        for minute, stage_id in enumerate(
            (
                "q0-b1-s1-g1-measured",
                "b2-s1-g1-measured",
                "b4-s1-g1-measured",
                "b8-s1-g1-measured",
            )
        )
    )
    _strict_frontier_value, strict_frontier = _validated_buyer_frontier(
        strict_policy,
        [case.result for case in strict_buyer_cases],
    )
    reuse_a = _measured_case(
        repo,
        scm_ref,
        "serialized-reuse-a-measured",
        evaluation_policy=strict_policy,
        guest_fulfillment_ids={
            "request-1": "strict-reuse-a-fulfillment",
        },
        buyer_frontier=strict_frontier,
        wall_clock_minute=11,
    )
    reuse_b = _measured_case(
        repo,
        scm_ref,
        "serialized-reuse-b-measured",
        evaluation_policy=strict_policy,
        guest_fulfillment_ids={
            "request-1": "strict-reuse-b-fulfillment",
        },
        host_reversible_baseline_binding=reuse_a.result_value["cleanup"][
            "reversible_baseline_binding"
        ],
        predecessor=reuse_a.result,
        buyer_frontier=strict_frontier,
        wall_clock_minute=12,
    )

    assert reuse_a.result.request_processing_passed is False
    assert reuse_b.result.request_processing_passed is False
    assert reuse_a.result.correctness_passed is True
    assert reuse_b.result.correctness_passed is True
    validate_serialized_reuse(reuse_a.result, reuse_b.result)


def test_serialized_reuse_rejects_evaluation_policy_mismatch(
    serialized_reuse_cases: tuple[CapacityCase, CapacityCase],
) -> None:
    reuse_a, reuse_b = serialized_reuse_cases
    changed_policy = _evaluation_policy_with_request_slo(
        reuse_b.evaluation_policy,
        900,
    )
    value = deepcopy(reuse_b.result_value)
    value["evaluation_policy"] = {
        "evaluation_policy_id": changed_policy.policy_id,
        "evaluation_policy_sha256": changed_policy.canonical_sha256,
    }

    with pytest.raises(
        CapacityValidationError,
        match="one evaluation policy",
    ):
        _revalidate_case(
            reuse_b,
            value,
            evaluation_policy=changed_policy,
            predecessor=reuse_a.result,
        )


def test_qualification_reuse_rejects_topology_drift(
    qualification_reuse_cases: tuple[CapacityCase, CapacityCase],
) -> None:
    reuse_a, _reuse_b = qualification_reuse_cases
    alternate_topology = binding(
        TOPOLOGY_BINDING_DOMAIN,
        "qualification-reuse-b-drift",
    )

    with pytest.raises(
        CapacityValidationError,
        match="serialized reuse stages must bind one topology authority",
    ):
        _measured_case(
            reuse_a.chain.repo,
            reuse_a.chain.scm_ref,
            "serialized-reuse-b-qualification",
            evaluation_policy=reuse_a.evaluation_policy,
            guest_fulfillment_ids={
                "request-1": "qualification-reuse-b-drift-fulfillment",
            },
            topology_authority_binding=alternate_topology,
            host_reversible_baseline_binding=reuse_a.result_value["cleanup"][
                "reversible_baseline_binding"
            ],
            predecessor=reuse_a.result,
            wall_clock_minute=21,
        )


def test_measured_reuse_a_rejects_frontier_topology_mismatch(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
    lower_bound_buyer_frontier: tuple[
        tuple[CapacityCase, ...],
        dict[str, Any],
        ValidatedBuyerFrontierReceipt,
    ],
) -> None:
    repo, scm_ref = outcome_authority_repo
    _cases, _value, buyer_frontier = lower_bound_buyer_frontier

    with pytest.raises(
        CapacityValidationError,
        match=(
            "serialized reuse A does not preserve buyer-frontier topology authority"
        ),
    ):
        _measured_case(
            repo,
            scm_ref,
            "serialized-reuse-a-measured",
            evaluation_policy=outcome_policy,
            guest_fulfillment_ids={
                "request-1": "measured-reuse-a-topology-mismatch",
            },
            topology_authority_binding=binding(
                TOPOLOGY_BINDING_DOMAIN,
                "measured-reuse-a-topology-mismatch",
            ),
            buyer_frontier=buyer_frontier,
            wall_clock_minute=11,
        )


def test_initial_buyer_search_reports_only_a_validated_lower_bound(
    lower_bound_buyer_frontier: tuple[
        tuple[CapacityCase, ...],
        dict[str, Any],
        ValidatedBuyerFrontierReceipt,
    ],
) -> None:
    _cases, value, receipt = lower_bound_buyer_frontier

    assert value["refinement_stage_ids"] == []
    assert value["retained_buyer_counts"] == [2, 4, 8]
    assert receipt.classification == "lower-bound"
    assert receipt.correctness_frontier == 8
    assert value["progression"]["lower_bound_reason"] == ("frozen-envelope-ended")


def test_buyer_frontier_topology_property_is_an_immutable_snapshot(
    lower_bound_buyer_frontier: tuple[
        tuple[CapacityCase, ...],
        dict[str, Any],
        ValidatedBuyerFrontierReceipt,
    ],
) -> None:
    _cases, value, receipt = lower_bound_buyer_frontier
    expected = value["topology_authority_binding"]
    leaked = receipt.topology_authority_binding
    leaked["value"] = "f" * 64

    assert receipt.topology_authority_binding == expected
    assert receipt.receipt["topology_authority_binding"] == expected


def test_buyer_frontier_rejects_mixed_result_topology(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
    lower_bound_buyer_frontier: tuple[
        tuple[CapacityCase, ...],
        dict[str, Any],
        ValidatedBuyerFrontierReceipt,
    ],
) -> None:
    repo, scm_ref = outcome_authority_repo
    cases, value, _receipt = lower_bound_buyer_frontier
    alternate_b8 = _measured_case(
        repo,
        scm_ref,
        "b8-s1-g1-measured",
        evaluation_policy=outcome_policy,
        topology_authority_binding=binding(
            TOPOLOGY_BINDING_DOMAIN,
            "alternate-buyer-topology",
        ),
        wall_clock_minute=3,
    )

    with pytest.raises(
        CapacityValidationError,
        match="buyer frontier results must bind one topology authority",
    ):
        validate_buyer_frontier_receipt(
            value,
            repo,
            evaluation_policy=outcome_policy,
            results=[
                *(case.result for case in cases[:3]),
                alternate_b8.result,
            ],
            expected_scm_ref=scm_ref,
        )


def test_buyer_frontier_rejects_payload_topology_mismatch(
    lower_bound_buyer_frontier: tuple[
        tuple[CapacityCase, ...],
        dict[str, Any],
        ValidatedBuyerFrontierReceipt,
    ],
) -> None:
    cases, original, _receipt = lower_bound_buyer_frontier
    value = deepcopy(original)
    value["topology_authority_binding"] = binding(
        TOPOLOGY_BINDING_DOMAIN,
        "forged-frontier-topology",
    )

    with pytest.raises(
        CapacityValidationError,
        match="does not bind the results' exact topology authority",
    ):
        validate_buyer_frontier_receipt(
            value,
            cases[0].chain.repo,
            evaluation_policy=cases[0].evaluation_policy,
            results=[case.result for case in cases],
            expected_scm_ref=cases[0].chain.scm_ref,
        )


def test_buyer_frontier_reports_non_adjacent_generator_limit(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
    b2_capacity_case: CapacityCase,
) -> None:
    repo, scm_ref = outcome_authority_repo
    cases = [
        _measured_case(
            repo,
            scm_ref,
            "q0-b1-s1-g1-measured",
            evaluation_policy=outcome_policy,
        ),
        b2_capacity_case,
    ]
    for buyer_count, minute in ((4, 2), (8, 3)):
        cases.append(
            _measured_case(
                repo,
                scm_ref,
                f"b{buyer_count}-s1-g1-measured",
                evaluation_policy=outcome_policy,
                outcome_kinds={
                    "request-1": "fault",
                    **{
                        f"request-{number}": "capacity-refused"
                        for number in range(2, buyer_count + 1)
                    },
                },
                fault_variants={
                    "request-1": "generator-rejection",
                },
                generator_rejection_request_id="request-1",
                wall_clock_minute=minute,
            )
        )
    value, receipt = _validated_buyer_frontier(
        outcome_policy,
        [case.result for case in cases],
    )

    assert value["frontiers"]["load_generator"] == {
        "greatest_passing_buyer_count": 2,
        "classification": "lower-bound",
        "limit_reason": "load-generator-ended-first",
    }
    assert receipt.classification == "lower-bound"
    assert value["progression"]["lower_bound_reason"] == ("load-generator-ended-first")


def test_buyer_frontier_reports_no_clean_shape(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
) -> None:
    repo, scm_ref = outcome_authority_repo
    strict_policy = _evaluation_policy_with_request_slo(
        outcome_policy,
        50,
    )
    cases = [
        _measured_case(
            repo,
            scm_ref,
            stage_id,
            evaluation_policy=strict_policy,
            wall_clock_minute=minute,
        )
        for stage_id, minute in (
            ("q0-b1-s1-g1-measured", 0),
            ("b2-s1-g1-measured", 1),
            ("b4-s1-g1-measured", 2),
            ("b8-s1-g1-measured", 3),
        )
    ]
    value, receipt = _validated_buyer_frontier(
        strict_policy,
        [case.result for case in cases],
    )

    assert receipt.classification == "no-clean-shape"
    assert receipt.correctness_frontier == 8
    assert value["progression"] == {
        "selection_predicate": (
            "request-processing-and-provisioning-and-correctness-"
            "with-load-generator-censoring"
        ),
        "largest_clean_buyer_count": 0,
        "classification": "no-clean-shape",
        "lower_bound_reason": None,
        "completed_before_reuse": True,
    }
    assert value["frontiers"]["request_processing"] == {
        "greatest_passing_buyer_count": 0,
        "classification": "not-observed",
        "limit_reason": "no-passing-shape",
    }


def test_buyer_frontier_rejects_unclean_final_result(
    outcome_authority_repo: tuple[Path, str],
    outcome_policy: ValidatedEvaluationPolicy,
    lower_bound_buyer_frontier: tuple[
        tuple[CapacityCase, ...],
        dict[str, Any],
        ValidatedBuyerFrontierReceipt,
    ],
) -> None:
    repo, scm_ref = outcome_authority_repo
    cases, value, _receipt = lower_bound_buyer_frontier
    unclean_final = _measured_case(
        repo,
        scm_ref,
        "b8-s1-g1-measured",
        evaluation_policy=outcome_policy,
        cleanup_failure=True,
        wall_clock_minute=3,
    )

    with pytest.raises(
        CapacityValidationError,
        match="cannot authorize reuse after unclean final state",
    ):
        validate_buyer_frontier_receipt(
            value,
            repo,
            evaluation_policy=outcome_policy,
            results=[
                *(case.result for case in cases[:3]),
                unclean_final.result,
            ],
            expected_scm_ref=scm_ref,
        )


def test_exact_buyer_frontier_requires_the_frozen_b3_refinement(
    exact_buyer_frontier: tuple[
        tuple[CapacityCase, ...],
        dict[str, Any],
        ValidatedBuyerFrontierReceipt,
    ],
) -> None:
    _cases, value, receipt = exact_buyer_frontier

    assert value["refinement_stage_ids"] == ["b3-s1-g1-measured"]
    assert value["retained_buyer_counts"] == [2, 3, 4]
    assert receipt.classification == "exact-bound"
    assert receipt.correctness_frontier == 3
    assert value["frontiers"]["request_processing"] == {
        "greatest_passing_buyer_count": 3,
        "classification": "exact-bound",
        "limit_reason": "observed-failure",
    }


def test_buyer_frontier_rejects_duplicate_result_identity(
    lower_bound_buyer_frontier: tuple[
        tuple[CapacityCase, ...],
        dict[str, Any],
        ValidatedBuyerFrontierReceipt,
    ],
) -> None:
    cases, value, _receipt = lower_bound_buyer_frontier
    duplicate_value = deepcopy(cases[2].result_value)
    duplicate_value["result_id"] = cases[1].result.result_id
    duplicate_result = _revalidate_case(cases[2], duplicate_value)

    with pytest.raises(
        CapacityValidationError,
        match="buyer frontier results must have distinct result IDs",
    ):
        validate_buyer_frontier_receipt(
            value,
            cases[0].chain.repo,
            evaluation_policy=cases[0].evaluation_policy,
            results=(
                cases[0].result,
                cases[1].result,
                duplicate_result,
                cases[3].result,
            ),
            expected_scm_ref=cases[0].chain.scm_ref,
        )


def test_buyer_frontier_rejects_duplicate_profile_stage(
    outcome_authority_repo: tuple[Path, str],
    exact_buyer_frontier: tuple[
        tuple[CapacityCase, ...],
        dict[str, Any],
        ValidatedBuyerFrontierReceipt,
    ],
) -> None:
    repo, scm_ref = outcome_authority_repo
    cases, value, _receipt = exact_buyer_frontier
    duplicate_case = _measured_case(
        repo,
        scm_ref,
        "b3-s1-g1-measured",
        evaluation_policy=cases[0].evaluation_policy,
        wall_clock_minute=5,
    )
    duplicate_value = deepcopy(duplicate_case.result_value)
    duplicate_value["result_id"] = "b3-s1-g1-measured-duplicate-result"
    duplicate_result = _revalidate_case(
        duplicate_case,
        duplicate_value,
    )

    with pytest.raises(
        CapacityValidationError,
        match="buyer frontier cannot contain duplicate profile stages",
    ):
        validate_buyer_frontier_receipt(
            value,
            repo,
            evaluation_policy=cases[0].evaluation_policy,
            results=(
                *(case.result for case in cases),
                duplicate_result,
            ),
            expected_scm_ref=scm_ref,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "ordered-result",
        "initial-stage",
        "retained-count",
        "stage-observation",
    ],
)
def test_buyer_frontier_receipt_rejects_duplicate_closed_entries(
    lower_bound_buyer_frontier: tuple[
        tuple[CapacityCase, ...],
        dict[str, Any],
        ValidatedBuyerFrontierReceipt,
    ],
    mutation: str,
) -> None:
    cases, original, _receipt = lower_bound_buyer_frontier
    value = deepcopy(original)
    if mutation == "ordered-result":
        value["ordered_results"][1] = deepcopy(value["ordered_results"][0])
    elif mutation == "initial-stage":
        value["initial_stage_ids"][1] = value["initial_stage_ids"][0]
    elif mutation == "retained-count":
        value["retained_buyer_counts"][1] = value["retained_buyer_counts"][0]
    else:
        value["stage_observations"][1] = deepcopy(value["stage_observations"][0])

    with pytest.raises(CapacityValidationError, match="buyer frontier"):
        validate_buyer_frontier_receipt(
            value,
            cases[0].chain.repo,
            evaluation_policy=cases[0].evaluation_policy,
            results=[case.result for case in cases],
            expected_scm_ref=cases[0].chain.scm_ref,
        )


@pytest.mark.parametrize(
    "mutation",
    ["result-digest", "refinement", "frontier", "lower-bound"],
)
def test_buyer_frontier_rejects_forged_derivations(
    exact_buyer_frontier: tuple[
        tuple[CapacityCase, ...],
        dict[str, Any],
        ValidatedBuyerFrontierReceipt,
    ],
    mutation: str,
) -> None:
    cases, original, _receipt = exact_buyer_frontier
    value = deepcopy(original)
    if mutation == "result-digest":
        value["ordered_results"][0]["result_sha256"] = "f" * 64
    elif mutation == "refinement":
        value["refinement_stage_ids"] = []
    elif mutation == "frontier":
        value["frontiers"]["correctness"]["greatest_passing_buyer_count"] = 4
    else:
        value["progression"]["classification"] = "lower-bound"
        value["progression"]["lower_bound_reason"] = "frozen-envelope-ended"

    with pytest.raises(CapacityValidationError, match="buyer frontier"):
        validate_buyer_frontier_receipt(
            value,
            cases[0].chain.repo,
            evaluation_policy=cases[0].evaluation_policy,
            results=[case.result for case in cases],
            expected_scm_ref=cases[0].chain.scm_ref,
        )


def test_seller_scaling_is_fenced_by_validated_buyer_frontier(
    lower_bound_buyer_frontier: tuple[
        tuple[CapacityCase, ...],
        dict[str, Any],
        ValidatedBuyerFrontierReceipt,
    ],
    serialized_reuse_cases: tuple[CapacityCase, CapacityCase],
    seller_progression_cases: tuple[CapacityCase, CapacityCase],
) -> None:
    _cases, _value, receipt = lower_bound_buyer_frontier
    _reuse_a, reuse_b = serialized_reuse_cases
    seller_b2, seller_b4 = seller_progression_cases

    assert select_seller_stages_from_results(
        receipt,
        reuse_baseline=reuse_b.result,
    ) == ("b2-s2-g1-measured",)
    assert select_seller_stages_from_results(
        receipt,
        reuse_baseline=reuse_b.result,
        seller_results=(seller_b2.result,),
    ) == (
        "b2-s2-g1-measured",
        "b4-s2-g1-measured",
    )
    assert (
        seller_b4.result_value["seller_progression_authority"][
            "prior_seller_result_sha256"
        ]
        == seller_b2.result.canonical_sha256
    )
    assert (
        len(
            {
                reuse_b.result.result_id,
                seller_b2.result.result_id,
                seller_b4.result.result_id,
            }
        )
        == 3
    )
    with pytest.raises(
        CapacityValidationError,
        match="validated buyer-frontier",
    ):
        select_seller_stages_from_results(
            None,  # type: ignore[arg-type]
            reuse_baseline=reuse_b.result,
        )


def test_seller_stage_rejects_topology_drift(
    seller_progression_cases: tuple[CapacityCase, CapacityCase],
) -> None:
    seller_b2, _seller_b4 = seller_progression_cases
    assert seller_b2.buyer_frontier is not None
    assert seller_b2.reuse_baseline is not None

    with pytest.raises(
        CapacityValidationError,
        match="seller result does not match buyer-frontier authority",
    ):
        _measured_case(
            seller_b2.chain.repo,
            seller_b2.chain.scm_ref,
            "b2-s2-g1-measured",
            evaluation_policy=seller_b2.evaluation_policy,
            topology_authority_binding=binding(
                TOPOLOGY_BINDING_DOMAIN,
                "seller-stage-topology-drift",
            ),
            buyer_frontier=seller_b2.buyer_frontier,
            reuse_baseline=seller_b2.reuse_baseline,
            wall_clock_minute=13,
        )


@pytest.mark.parametrize(
    ("stage_index", "field", "replacement", "message"),
    [
        (
            0,
            "buyer_frontier_receipt_sha256",
            "f" * 64,
            "exact frontier",
        ),
        (
            0,
            "reuse_baseline_result_sha256",
            "f" * 64,
            "exact frontier",
        ),
        (
            1,
            "prior_seller_result_sha256",
            "f" * 64,
            "exact frontier",
        ),
    ],
)
def test_seller_progression_rejects_forged_lineage(
    seller_progression_cases: tuple[CapacityCase, CapacityCase],
    stage_index: int,
    field: str,
    replacement: str,
    message: str,
) -> None:
    case = seller_progression_cases[stage_index]
    value = deepcopy(case.result_value)
    value["seller_progression_authority"][field] = replacement

    with pytest.raises(CapacityValidationError, match=message):
        _revalidate_case(case, value)


def test_seller_progression_rejects_temporal_fence_replay(
    seller_progression_cases: tuple[CapacityCase, CapacityCase],
) -> None:
    seller_b2, _seller_b4 = seller_progression_cases
    assert seller_b2.reuse_baseline is not None
    value = deepcopy(seller_b2.result_value)
    value["started_at"] = seller_b2.reuse_baseline.result["progression_ready_at"]

    with pytest.raises(
        CapacityValidationError,
        match="strictly after its progression fence",
    ):
        _revalidate_case(seller_b2, value)


def test_seller_progression_rejects_inflated_derived_topology(
    seller_progression_cases: tuple[CapacityCase, CapacityCase],
) -> None:
    seller_b2, _seller_b4 = seller_progression_cases
    value = deepcopy(seller_b2.result_value)
    authority = value["seller_progression_authority"]
    authority["distinct_seller_identities"] = 3
    authority["distinct_service_instances"] = 3

    with pytest.raises(
        CapacityValidationError,
        match="exact frontier, topology",
    ):
        _revalidate_case(seller_b2, value)


def test_seller_progression_rejects_unknown_caller_topology_field(
    seller_progression_cases: tuple[CapacityCase, CapacityCase],
) -> None:
    seller_b2, _seller_b4 = seller_progression_cases
    value = deepcopy(seller_b2.result_value)
    value["seller_progression_authority"]["caller_claimed_seller_identities"] = 4

    with pytest.raises(
        CapacityValidationError,
        match="not valid under any|Additional properties",
    ):
        _revalidate_case(seller_b2, value)


@pytest.mark.parametrize("stage_index", [0, 1])
def test_seller_progression_rejects_replayed_result_identity(
    seller_progression_cases: tuple[CapacityCase, CapacityCase],
    stage_index: int,
) -> None:
    seller_b2, seller_b4 = seller_progression_cases
    case = seller_progression_cases[stage_index]
    value = deepcopy(case.result_value)
    value["result_id"] = (
        case.reuse_baseline.result_id
        if stage_index == 0 and case.reuse_baseline is not None
        else seller_b2.result.result_id
    )

    with pytest.raises(
        CapacityValidationError,
        match="seller progression must use distinct result IDs",
    ):
        _revalidate_case(case, value)


def test_seller_selection_rejects_typed_but_forked_prior_chain(
    seller_progression_cases: tuple[CapacityCase, CapacityCase],
) -> None:
    seller_b2_a, seller_b4_after_a = seller_progression_cases
    assert seller_b2_a.buyer_frontier is not None
    assert seller_b2_a.reuse_baseline is not None
    fork_value = deepcopy(seller_b2_a.result_value)
    fork_value["result_id"] = "b2-s2-g1-measured-fork-b-result"
    seller_b2_b = _revalidate_case(seller_b2_a, fork_value)

    with pytest.raises(
        CapacityValidationError,
        match=(
            "does not bind its exact frontier, reuse baseline, topology, "
            "and prior result"
        ),
    ):
        select_seller_stages_from_results(
            seller_b2_a.buyer_frontier,
            reuse_baseline=seller_b2_a.reuse_baseline,
            seller_results=(seller_b2_b, seller_b4_after_a.result),
        )


def test_reuse_b_host_admission_cannot_be_inflated_after_observation(
    serialized_reuse_cases: tuple[CapacityCase, CapacityCase],
) -> None:
    _reuse_a, reuse_b = serialized_reuse_cases
    host = next(
        item for item in reuse_b.chain.evidence if item.plan.role == "host-operator"
    )
    receipt_value = host.receipt.receipt
    admission = receipt_value["role_evidence"]["seller_scaling_admission"]
    admission["distinct_seller_identities"] += 1
    admission["distinct_service_instances"] += 1

    with pytest.raises(
        CapacityValidationError,
        match="does not match the host plan",
    ):
        validate_role_receipt(receipt_value, host.plan)
