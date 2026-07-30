from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping, Sequence

from issue_discovery.capacity import (
    CAPACITY_PROFILE_PATH,
    CapacityValidationError,
    canonical_json_bytes,
    canonical_sha256,
    resolve_pinned_profile_registry,
    resolve_pinned_profile_stage,
    retained_buyer_refinement_counts,
    select_buyer_refinement_counts,
    select_seller_stage_ids,
)
from issue_discovery.capacity_roles import (
    BASELINE_EQUIVALENCE_BINDING_DOMAIN,
    CUDA_RESULT_CHECKSUM,
    CUDA_SOURCE_PATH,
    CUDA_SUCCESS_MARKER,
    CUDA_WRAPPER_PATH,
    NATIVE_EVIDENCE_BINDING_DOMAIN,
    REVERSIBLE_BASELINE_BINDING_DOMAIN,
    RUNTIME_BINDING_DOMAIN,
    TOPOLOGY_BINDING_DOMAIN,
    SubstantiveRoleEvidence,
    ValidatedActorSet,
    ValidatedOracleAuthority,
    ValidatedRolePlan,
    _VALIDATED_ACTOR_SET_TOKEN,
    _VALIDATED_ORACLE_TOKEN,
    _VALIDATED_ROLE_PLAN_TOKEN,
    _load_pinned_schema,
    _parse_timestamp,
    _raise_errors,
    _schema_errors,
    _validate_exact_commit,
    _validate_tracked_content,
    validate_privacy_preserving_binding,
    validate_substantive_role_evidence,
)


EVALUATION_POLICY_SCHEMA = PurePosixPath(
    "tools/issue-discovery/schemas/capacity-evaluation-policy.schema.json"
)
CAPACITY_RESULT_SCHEMA = PurePosixPath(
    "tools/issue-discovery/schemas/capacity-result.schema.json"
)
REFERENCE_POLICY_SCHEMA = PurePosixPath(
    "tools/issue-discovery/schemas/capacity-reference-policy.schema.json"
)
BUYER_FRONTIER_SCHEMA = PurePosixPath(
    "tools/issue-discovery/schemas/capacity-buyer-frontier-receipt.schema.json"
)

INITIAL_BUYER_STAGES = (
    "q0-b1-s1-g1-measured",
    "b2-s1-g1-measured",
    "b4-s1-g1-measured",
    "b8-s1-g1-measured",
)
BUYER_REFINEMENT_STAGES = frozenset(
    {
        "b3-s1-g1-measured",
        "b5-s1-g1-measured",
        "b6-s1-g1-measured",
        "b7-s1-g1-measured",
    }
)
SELLER_MEASURED_STAGES = frozenset(
    {
        "b2-s2-g1-measured",
        "b4-s2-g1-measured",
        "b4-s3-g1-measured",
        "b4-s4-g1-measured",
    }
)
REVERSIBLE_COMPONENTS = frozenset(
    {
        "capacity-reservations-and-leases",
        "settlement-resources",
        "fulfillment-provider-jobs",
        "vms",
        "disks",
        "networks",
        "ansible-processes",
        "gpu-assignments",
        "listing-service-set",
    }
)
ACCOUNTING_DELTA_CATEGORIES = frozenset(
    {
        "deal-history",
        "settlement-history",
        "request-history",
        "escrow-claim-history",
        "transaction-fees",
        "wallet-accounting",
    }
)
RESIDUE_FIELDS = (
    "capacity_reservations",
    "settlement_resources",
    "fulfillment_provider_jobs",
    "vms",
    "disks",
    "networks",
    "ansible_processes",
    "gpu_assignments",
    "active_claims",
    "active_locks",
)

_VALIDATED_EVALUATION_POLICY_TOKEN = object()
_VALIDATED_REFERENCE_POLICY_TOKEN = object()
_VALIDATED_CAPACITY_RESULT_TOKEN = object()
_VALIDATED_BUYER_FRONTIER_TOKEN = object()
_BUYER_STAGE_RE = re.compile(r"^(?:q0-)?b([1-8])-s1-g1-measured$")


@dataclass(frozen=True, slots=True)
class ValidatedEvaluationPolicy:
    policy_id: str
    scm_ref: str
    profile_registry_sha256: str
    profile_registry_raw_sha256: str
    frozen_at: datetime
    request_processing_slo_ns: int
    provisioning_queue_slo_ns: int
    ansible_service_slo_ns: int
    terminal_observation_timeout_ns: int
    canonical_sha256: str
    repo_root: Path
    _canonical_bytes: bytes = field(repr=False)
    _validation_token: object = field(repr=False, compare=False)

    @property
    def policy(self) -> dict[str, Any]:
        return _snapshot_object(self._canonical_bytes, "evaluation policy")


@dataclass(frozen=True, slots=True)
class ValidatedReferencePolicy:
    policy_id: str
    scm_ref: str
    profile_stage_id: str
    profile_stage_sha256: str
    scenario_id: str
    scenario_sha256: str
    release_id: str
    frozen_at: datetime
    request_schedule: tuple[tuple[str, int], ...]
    canonical_sha256: str
    repo_root: Path
    _canonical_bytes: bytes = field(repr=False)
    _validation_token: object = field(repr=False, compare=False)

    @property
    def policy(self) -> dict[str, Any]:
        return _snapshot_object(
            self._canonical_bytes,
            "reference execution policy",
        )

    @property
    def clock_evidence_binding(self) -> dict[str, str]:
        binding = self.policy["clock_evidence_binding"]
        return dict(binding)


@dataclass(frozen=True, slots=True)
class ValidatedCapacityResult:
    result_id: str
    scm_ref: str
    profile_stage_id: str
    profile_stage_sha256: str
    scenario_id: str
    scenario_sha256: str
    execution_boundary: str
    actor_trigger: str
    canonical_sha256: str
    started_at: datetime
    terminal_observed_at: datetime
    cleanup_completed_at: datetime
    progression_ready_at: datetime
    request_processing_passed: bool
    simultaneous_fulfillment_count: int
    provisioning_passed: bool
    correctness_passed: bool
    load_generator_passed: bool
    cleanup_passed: bool
    stage_passed: bool
    agent_capacity_evidence: bool
    eligible_for_capacity_frontier: bool
    derived_faults: tuple[str, ...]
    outcome_kinds: tuple[str, ...]
    admitted_seller_identities: int | None
    admitted_service_instances: int | None
    repo_root: Path
    _canonical_bytes: bytes = field(repr=False)
    _validation_token: object = field(repr=False, compare=False)

    @property
    def result(self) -> dict[str, Any]:
        return _snapshot_object(self._canonical_bytes, "capacity result")

    @property
    def buyer_count(self) -> int:
        stage_match = _BUYER_STAGE_RE.fullmatch(self.profile_stage_id)
        if stage_match is None:
            raise CapacityValidationError(
                "capacity result is not a measured S1 buyer stage"
            )
        return int(stage_match.group(1))

    @property
    def progression_passed(self) -> bool:
        return (
            self.request_processing_passed
            and self.provisioning_passed
            and self.correctness_passed
            and self.load_generator_passed
        )


@dataclass(frozen=True, slots=True)
class ValidatedBuyerFrontierReceipt:
    frontier_receipt_id: str
    scm_ref: str
    evaluation_policy_sha256: str
    ordered_result_sha256s: tuple[str, ...]
    correctness_frontier: int
    load_generator_frontier: int
    largest_clean_buyer_count: int
    classification: str
    canonical_sha256: str
    completed_at: datetime
    _canonical_bytes: bytes = field(repr=False)
    _validation_token: object = field(repr=False, compare=False)

    @property
    def receipt(self) -> dict[str, Any]:
        return _snapshot_object(self._canonical_bytes, "buyer frontier receipt")

    @property
    def topology_authority_binding(self) -> dict[str, str]:
        binding = self.receipt["topology_authority_binding"]
        return dict(binding)


def _snapshot_object(content: bytes, label: str) -> dict[str, Any]:
    import json

    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict):
        raise CapacityValidationError(f"validated {label} snapshot is not an object")
    return value


def _require_policy(
    policy: ValidatedEvaluationPolicy,
) -> dict[str, Any]:
    if (
        not isinstance(policy, ValidatedEvaluationPolicy)
        or policy._validation_token is not _VALIDATED_EVALUATION_POLICY_TOKEN
    ):
        raise CapacityValidationError(
            "capacity outcome requires a validated pre-Q0 evaluation policy"
        )
    reproduced = validate_evaluation_policy(
        policy.policy,
        policy.repo_root,
        expected_scm_ref=policy.scm_ref,
    )
    if reproduced.canonical_sha256 != policy.canonical_sha256:
        raise CapacityValidationError("evaluation policy changed after validation")
    return policy.policy


def _parse_utc(value: object, *, field_name: str) -> datetime:
    return _parse_timestamp(value, field_name=field_name)


def validate_evaluation_policy(
    value: dict[str, Any],
    repo_root: Path,
    *,
    expected_scm_ref: str | None = None,
) -> ValidatedEvaluationPolicy:
    scm_ref = value.get("scm_ref")
    root = _validate_exact_commit(repo_root, scm_ref)
    assert isinstance(scm_ref, str)
    schema = _load_pinned_schema(root, scm_ref, EVALUATION_POLICY_SCHEMA)
    errors = _schema_errors(value, schema)
    if expected_scm_ref is not None and scm_ref != expected_scm_ref:
        errors.append(
            "evaluation-policy SCM ref does not match the selected campaign ref"
        )

    registry_value = value.get("profile_registry")
    try:
        if not isinstance(registry_value, dict):
            raise CapacityValidationError(
                "evaluation policy must bind the pinned profile registry"
            )
        registry = resolve_pinned_profile_registry(
            root,
            scm_ref,
            registry_value.get("path", ""),
            expected_sha256=registry_value.get("canonical_sha256"),
        )
        if registry.raw_sha256 != registry_value.get("raw_sha256"):
            errors.append(
                "evaluation policy profile-registry raw digest does not match"
            )
    except CapacityValidationError as error:
        errors.append(str(error))
        registry = None

    try:
        frozen_at = _parse_utc(value.get("frozen_at"), field_name="frozen_at")
    except CapacityValidationError as error:
        errors.append(str(error))
        frozen_at = datetime.min.replace(tzinfo=UTC)
    try:
        validate_privacy_preserving_binding(
            value.get("clock_evidence_binding"),
            expected_domain=NATIVE_EVIDENCE_BINDING_DOMAIN,
            field_name="clock_evidence_binding",
        )
    except CapacityValidationError as error:
        errors.append(str(error))
    request_slo = value.get("request_processing_slo_ns")
    terminal_timeout = value.get("terminal_observation_timeout_ns")
    if (
        type(request_slo) is int
        and type(terminal_timeout) is int
        and terminal_timeout < request_slo
    ):
        errors.append(
            "terminal observation timeout cannot be shorter than the "
            "request-processing SLO"
        )

    _raise_errors("capacity evaluation policy", errors)
    assert registry is not None
    return ValidatedEvaluationPolicy(
        policy_id=value["evaluation_policy_id"],
        scm_ref=scm_ref,
        profile_registry_sha256=registry.canonical_sha256,
        profile_registry_raw_sha256=registry.raw_sha256,
        frozen_at=frozen_at,
        request_processing_slo_ns=value["request_processing_slo_ns"],
        provisioning_queue_slo_ns=value["provisioning_queue_slo_ns"],
        ansible_service_slo_ns=value["ansible_service_slo_ns"],
        terminal_observation_timeout_ns=value["terminal_observation_timeout_ns"],
        canonical_sha256=canonical_sha256(value),
        repo_root=root,
        _canonical_bytes=canonical_json_bytes(value),
        _validation_token=_VALIDATED_EVALUATION_POLICY_TOKEN,
    )


def validate_reference_policy(
    value: dict[str, Any],
    repo_root: Path,
    *,
    evaluation_policy: ValidatedEvaluationPolicy,
    observer_plan: ValidatedRolePlan,
    host_plan: ValidatedRolePlan,
    expected_scm_ref: str | None = None,
) -> ValidatedReferencePolicy:
    policy_value = _require_policy(evaluation_policy)
    for plan, role in (
        (observer_plan, "observer"),
        (host_plan, "host-operator"),
    ):
        if (
            not isinstance(plan, ValidatedRolePlan)
            or plan._validation_token is not _VALIDATED_ROLE_PLAN_TOKEN
            or plan.role != role
        ):
            raise CapacityValidationError(
                "reference policy requires validated O1 and H1 role plans"
            )
    scm_ref = value.get("scm_ref")
    root = _validate_exact_commit(repo_root, scm_ref)
    assert isinstance(scm_ref, str)
    schema = _load_pinned_schema(root, scm_ref, REFERENCE_POLICY_SCHEMA)
    _raise_errors("reference policy", _schema_errors(value, schema))
    errors: list[str] = []
    if expected_scm_ref is not None and scm_ref != expected_scm_ref:
        errors.append("reference-policy SCM ref does not match selected campaign ref")
    try:
        stage = resolve_pinned_profile_stage(
            root,
            scm_ref,
            value.get("profile_stage_id", ""),
            expected_sha256=value.get("profile_stage_sha256"),
        )
    except CapacityValidationError as error:
        errors.append(str(error))
        stage = None
    if stage is not None:
        if (
            stage.stage.get("execution_boundary") != "real-reference"
            or stage.stage.get("actor_trigger") != "controller-driven"
            or stage.scenario is None
        ):
            errors.append(
                "reference policy requires the pinned controller reference stage"
            )
        else:
            if (
                value.get("scenario_id") != stage.scenario.scenario_id
                or value.get("scenario_sha256") != stage.scenario.scenario_sha256
            ):
                errors.append("reference policy does not bind the exact scenario")
    if (
        root != evaluation_policy.repo_root
        or scm_ref != evaluation_policy.scm_ref
        or value.get("evaluation_policy")
        != {
            "evaluation_policy_id": evaluation_policy.policy_id,
            "evaluation_policy_sha256": evaluation_policy.canonical_sha256,
        }
    ):
        errors.append("reference policy does not bind the evaluation-policy authority")
    for plan in (observer_plan, host_plan):
        if (
            plan.repo_root != root
            or plan.scm_ref != scm_ref
            or plan.profile_stage_id != value.get("profile_stage_id")
            or plan.profile_stage_sha256 != value.get("profile_stage_sha256")
            or plan.scenario_id != value.get("scenario_id")
            or plan.scenario_sha256 != value.get("scenario_sha256")
        ):
            errors.append(
                "reference role plan does not bind the reference-policy stage"
            )
    reference_plans = (observer_plan, host_plan)
    if len({plan.plan_id for plan in reference_plans}) != 2:
        errors.append("reference O1 and H1 plans must use distinct plan IDs")
    if (
        len(
            {plan.plan.get("isolated_identity_fingerprint") for plan in reference_plans}
        )
        != 2
    ):
        errors.append("reference O1 and H1 plans must use distinct isolated identities")
    if (
        len(
            {
                _binding_identity(plan.plan.get("actor_invocation_capability_binding"))
                for plan in reference_plans
            }
        )
        != 2
    ):
        errors.append(
            "reference O1 and H1 plans must use distinct invocation capabilities"
        )
    if value.get("observer_plan") != {
        "plan_id": observer_plan.plan_id,
        "plan_sha256": observer_plan.canonical_sha256,
    }:
        errors.append("reference policy does not bind exact O1 plan")
    if value.get("host_plan") != {
        "plan_id": host_plan.plan_id,
        "plan_sha256": host_plan.canonical_sha256,
    }:
        errors.append("reference policy does not bind exact H1 plan")
    if value.get("clock_evidence_binding") != policy_value.get(
        "clock_evidence_binding"
    ):
        errors.append(
            "reference policy clock does not match the evaluation-policy clock"
        )
    schedule_values = value.get("request_schedule")
    schedule: list[tuple[str, int]] = []
    if isinstance(schedule_values, list):
        for item in schedule_values:
            if not isinstance(item, dict):
                continue
            request_id = item.get("request_id")
            invoked = item.get("invoked_offset_ns")
            if isinstance(request_id, str) and type(invoked) is int:
                schedule.append((request_id, invoked))
    scenario_requests = (
        {
            request.get("request_id")
            for request in stage.scenario.scenario.get("requests", ())
            if isinstance(request, dict)
        }
        if stage is not None and stage.scenario is not None
        else set()
    )
    if (
        len(schedule) != len(set(request_id for request_id, _ in schedule))
        or {request_id for request_id, _ in schedule} != scenario_requests
    ):
        errors.append("reference policy schedule must cover every exact request once")
    try:
        frozen_at = _parse_utc(
            value.get("frozen_at"),
            field_name="reference policy frozen_at",
        )
        if frozen_at <= evaluation_policy.frozen_at:
            errors.append(
                "reference policy must freeze after the campaign evaluation policy"
            )
    except CapacityValidationError as error:
        errors.append(str(error))
        frozen_at = datetime.min.replace(tzinfo=UTC)
    _raise_errors("reference policy", errors)
    assert stage is not None and stage.scenario is not None
    return ValidatedReferencePolicy(
        policy_id=value["reference_policy_id"],
        scm_ref=scm_ref,
        profile_stage_id=stage.stage_id,
        profile_stage_sha256=stage.canonical_sha256,
        scenario_id=stage.scenario.scenario_id,
        scenario_sha256=stage.scenario.scenario_sha256,
        release_id=value["release_id"],
        frozen_at=frozen_at,
        request_schedule=tuple(schedule),
        canonical_sha256=canonical_sha256(value),
        repo_root=root,
        _canonical_bytes=canonical_json_bytes(value),
        _validation_token=_VALIDATED_REFERENCE_POLICY_TOKEN,
    )


def _require_reference_policy(
    policy: ValidatedReferencePolicy,
) -> dict[str, Any]:
    if (
        not isinstance(policy, ValidatedReferencePolicy)
        or policy._validation_token is not _VALIDATED_REFERENCE_POLICY_TOKEN
    ):
        raise CapacityValidationError(
            "controller reference requires a validated pre-release policy"
        )
    return policy.policy


def _require_oracle(
    oracle: ValidatedOracleAuthority,
    *,
    scm_ref: str,
    profile_stage_id: str,
) -> dict[str, Any]:
    if (
        not isinstance(oracle, ValidatedOracleAuthority)
        or oracle._validation_token is not _VALIDATED_ORACLE_TOKEN
    ):
        raise CapacityValidationError(
            "capacity result requires a validated independent oracle authority"
        )
    if oracle.scm_ref != scm_ref or oracle.profile_stage_id != profile_stage_id:
        raise CapacityValidationError(
            "oracle authority does not bind the capacity-result stage"
        )
    authority = oracle.authority
    if (
        authority.get("oracle_kind") != "independent-vm-capacity"
        or authority.get("real_oracle_allowed") is not True
        or not isinstance(authority.get("observer_plan_sha256"), str)
    ):
        raise CapacityValidationError(
            "capacity result requires the real independent VM oracle"
        )
    return authority


def _require_actor_observation(
    actor_set: ValidatedActorSet,
) -> dict[str, Any]:
    if (
        not isinstance(actor_set, ValidatedActorSet)
        or actor_set._validation_token is not _VALIDATED_ACTOR_SET_TOKEN
    ):
        raise CapacityValidationError(
            "agent-driven capacity result requires a validated actor observation"
        )
    return actor_set.actor_set


def _validated_role_evidence(
    role_evidence: Sequence[SubstantiveRoleEvidence],
) -> tuple[SubstantiveRoleEvidence, ...]:
    validated: list[SubstantiveRoleEvidence] = []
    for item in role_evidence:
        if not isinstance(item, SubstantiveRoleEvidence):
            raise CapacityValidationError(
                "capacity result requires substantive role evidence"
            )
        validated.append(
            validate_substantive_role_evidence(
                item.plan,
                item.receipt,
                item.actions,
                item.results,
                allow_rejected_observation=True,
            )
        )
    return tuple(validated)


def _binding_identity(binding: object) -> tuple[object, object, object]:
    if not isinstance(binding, Mapping):
        return (None, None, None)
    return (
        binding.get("method"),
        binding.get("domain"),
        binding.get("value"),
    )


def _listing_runtime_map(
    actor_set: Mapping[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    entries = actor_set.get("runtime_listing_bindings")
    if not isinstance(entries, list):
        return result
    for item in entries:
        if not isinstance(item, dict):
            continue
        seller = item.get("seller_slot")
        listing = item.get("listing_slot")
        runtime = item.get("runtime_binding")
        if (
            isinstance(seller, str)
            and isinstance(listing, str)
            and isinstance(runtime, dict)
        ):
            result[(seller, listing)] = runtime
    return result


def _buyer_action_map(
    role_evidence: Sequence[SubstantiveRoleEvidence],
) -> dict[str, tuple[SubstantiveRoleEvidence, Any, Any]]:
    records: dict[str, tuple[SubstantiveRoleEvidence, Any, Any]] = {}
    for item in role_evidence:
        if item.plan.role != "buyer":
            continue
        request_id = item.plan.plan["role_plan"].get("request_id")
        actions = [
            action for action in item.actions if action.action_kind == "buyer-request"
        ]
        results = {result.action_id: result for result in item.results}
        if (
            not isinstance(request_id, str)
            or len(actions) != 1
            or actions[0].action_id not in results
            or request_id in records
        ):
            raise CapacityValidationError(
                "buyer evidence does not provide one exact request action"
            )
        records[request_id] = (item, actions[0], results[actions[0].action_id])
    return records


def _host_evidence(
    role_evidence: Sequence[SubstantiveRoleEvidence],
) -> SubstantiveRoleEvidence:
    hosts = [item for item in role_evidence if item.plan.role == "host-operator"]
    if len(hosts) != 1:
        raise CapacityValidationError(
            "capacity result requires one exact host-operator observation"
        )
    return hosts[0]


def _observer_evidence(
    role_evidence: Sequence[SubstantiveRoleEvidence],
    *,
    observer_plan_sha256: str,
) -> SubstantiveRoleEvidence:
    observers = [
        item
        for item in role_evidence
        if item.plan.role == "observer"
        and item.plan.canonical_sha256 == observer_plan_sha256
    ]
    if len(observers) != 1:
        raise CapacityValidationError(
            "capacity result requires the exact independent observer evidence"
        )
    return observers[0]


def _require_binding(
    binding: object,
    *,
    domain: str,
    field_name: str,
) -> dict[str, str]:
    return validate_privacy_preserving_binding(
        binding,
        expected_domain=domain,
        field_name=field_name,
    )


def _commercial_is_clean(value: object) -> bool:
    return isinstance(value, dict) and all(
        value.get(field) is True
        for field in (
            "zero_active_claims",
            "zero_active_locks",
            "zero_run_owned_funds",
        )
    )


def _validate_common_request(
    outcome: Mapping[str, Any],
    request: Mapping[str, Any],
    runtime_binding: Mapping[str, Any],
    errors: list[str],
) -> None:
    request_id = request.get("request_id")
    deal_reference = outcome.get("deal_reference")
    if outcome.get("request_id") != request_id:
        errors.append("request outcome identity does not match its scenario request")
    if not isinstance(deal_reference, dict):
        return
    expected = {
        "request_id": request_id,
        "seller_slot": request.get("seller_slot"),
        "listing_slot": request.get("listing_slot"),
        "runtime_binding": dict(runtime_binding),
    }
    for key, value in expected.items():
        if deal_reference.get(key) != value:
            errors.append(
                f"deal_reference.{key} does not match frozen request authority"
            )
    invoked = outcome.get("invoked_offset_ns")
    terminal = outcome.get("terminal_offset_ns")
    if (
        type(invoked) is not int
        or type(terminal) is not int
        or invoked < 0
        or terminal <= invoked
    ):
        errors.append("request terminal offset must follow invocation")
    bindings = outcome.get("independent_observation_bindings")
    if isinstance(bindings, list):
        for index, binding in enumerate(bindings):
            try:
                _require_binding(
                    binding,
                    domain=NATIVE_EVIDENCE_BINDING_DOMAIN,
                    field_name=f"independent_observation_bindings[{index}]",
                )
            except CapacityValidationError as error:
                errors.append(str(error))


def _validate_settlement_consistency(
    outcome: Mapping[str, Any],
    errors: list[str],
) -> None:
    reservation = outcome.get("capacity_reservation_id")
    fulfillment = outcome.get("fulfillment_id")
    record = outcome.get("settlement_record")
    if record is None:
        return
    if not isinstance(record, dict):
        errors.append("settlement_record must be a closed observation")
        return
    if record.get("capacity_reservation_id") != reservation:
        errors.append("Settlement Record must be keyed by capacity_reservation_id")
    record_fulfillment = record.get("fulfillment_id")
    if fulfillment is not None and record_fulfillment != fulfillment:
        errors.append("Settlement Record fulfillment does not match")
    selected = record.get("selected_resource_binding")
    if selected is not None:
        try:
            _require_binding(
                selected,
                domain=NATIVE_EVIDENCE_BINDING_DOMAIN,
                field_name="settlement_record.selected_resource_binding",
            )
        except CapacityValidationError as error:
            errors.append(str(error))


def _validate_success(
    outcome: Mapping[str, Any],
    *,
    repo_root: Path,
    scm_ref: str,
    buyer: SubstantiveRoleEvidence | None,
    buyer_required: bool,
    common_clock_binding: Mapping[str, Any],
    errors: list[str],
) -> tuple[int, int] | None:
    deal = outcome.get("deal_reference")
    if not isinstance(deal, dict) or any(
        deal.get(field) is None
        for field in (
            "negotiation_reference_sha256",
            "escrow_reference_sha256",
        )
    ):
        errors.append(
            "vm-succeeded requires storefront negotiation and escrow references"
        )
    for field_name in (
        "capacity_reservation_id",
        "fulfillment_id",
        "provisioned_resource_id",
    ):
        if outcome.get(field_name) is None:
            errors.append(f"vm-succeeded requires non-null {field_name}")
    record = outcome.get("settlement_record")
    if not isinstance(record, dict):
        errors.append("vm-succeeded requires the Settlement Record aggregate")
    else:
        if record.get("state") != "torn_down":
            errors.append(
                "vm-succeeded requires Settlement Record terminal torn_down state"
            )
        if record.get("selected_resource_binding") is None:
            errors.append(
                "vm-succeeded requires the selected Settlement Resource proof"
            )
        if record.get("active_claim") is not False:
            errors.append("vm-succeeded Settlement Record cannot retain a claim")
    _validate_settlement_consistency(outcome, errors)

    observation = outcome.get("success_observation")
    if not isinstance(observation, dict):
        return None
    join = observation.get("reservation_fulfillment_join")
    if isinstance(join, dict):
        reservation = outcome.get("capacity_reservation_id")
        fulfillment = outcome.get("fulfillment_id")
        expected = {
            "fulfillment_capacity_reservation_id": reservation,
            "settlement_capacity_reservation_id": reservation,
            "settlement_fulfillment_id": fulfillment,
            "provisioned_fulfillment_id": fulfillment,
        }
        for key, value in expected.items():
            if join.get(key) != value:
                errors.append(f"success durable join {key} does not match")
    provisioning = observation.get("provisioning")
    if not isinstance(provisioning, dict):
        errors.append("vm-succeeded requires provisioning observation")
    elif (
        provisioning.get("provisioning_kind") != "real-kvm-ansible"
        or provisioning.get("gpu_assignment") != "whole-device-passthrough"
        or provisioning.get("output_observed") is not True
    ):
        errors.append("vm-succeeded requires real KVM/Ansible whole-device output")

    exercise = observation.get("gpu_exercise")
    if not isinstance(exercise, dict):
        errors.append("vm-succeeded requires pinned guest GPU exercise")
    else:
        if exercise.get("fulfillment_id") != outcome.get("fulfillment_id"):
            errors.append("guest exercise does not bind the fulfillment")
        try:
            _validate_tracked_content(
                exercise.get("wrapper"),
                repo_root,
                scm_ref,
                field_name="gpu_exercise.wrapper",
                expected_path=CUDA_WRAPPER_PATH,
            )
            _validate_tracked_content(
                exercise.get("source"),
                repo_root,
                scm_ref,
                field_name="gpu_exercise.source",
                expected_path=CUDA_SOURCE_PATH,
            )
        except CapacityValidationError as error:
            errors.append(str(error))
        if (
            exercise.get("ssh_resumed") is not True
            or exercise.get("visible_gpus") != 1
            or exercise.get("compiled") is not True
            or exercise.get("device_kernel_executed") is not True
            or exercise.get("success_marker") != CUDA_SUCCESS_MARKER
            or exercise.get("result_checksum") != CUDA_RESULT_CHECKSUM
        ):
            errors.append("vm-succeeded requires the exact compiled CUDA device result")
        try:
            _require_binding(
                exercise.get("native_evidence_binding"),
                domain=NATIVE_EVIDENCE_BINDING_DOMAIN,
                field_name="gpu_exercise.native_evidence_binding",
            )
        except CapacityValidationError as error:
            errors.append(str(error))
    if buyer is None and buyer_required:
        errors.append("vm-succeeded lacks buyer-owned guest evidence")
    elif buyer is not None:
        guest = buyer.receipt.receipt["role_evidence"].get("guest_verification")
        if (
            not isinstance(guest, dict)
            or guest.get("fulfillment_id") != outcome.get("fulfillment_id")
            or guest.get("ssh_resumed") is not True
            or guest.get("visible_gpus") != 1
            or guest.get("success_marker") != CUDA_SUCCESS_MARKER
            or guest.get("result_checksum") != CUDA_RESULT_CHECKSUM
        ):
            errors.append("vm-succeeded does not match buyer-owned guest verification")

    interval = observation.get("active_interval")
    if not isinstance(interval, dict):
        return None
    start = interval.get("start_offset_ns")
    end = interval.get("end_offset_ns")
    invoked = outcome.get("invoked_offset_ns")
    terminal = outcome.get("terminal_offset_ns")
    if (
        type(start) is not int
        or type(end) is not int
        or type(invoked) is not int
        or type(terminal) is not int
        or start < invoked
        or end <= start
        or end > terminal
    ):
        errors.append("successful VM active interval is invalid")
        return None
    if interval.get("clock_evidence_binding") != common_clock_binding:
        errors.append("successful VM interval must use the aggregate common clock")
    cleanup = outcome.get("request_cleanup")
    if not isinstance(cleanup, dict) or not (
        cleanup.get("teardown_complete") is True
        and cleanup.get("zero_active_residue") is True
    ):
        errors.append("vm-succeeded requires request teardown and zero residue")
    commercial = outcome.get("commercial_resolution")
    if (
        not isinstance(commercial, dict)
        or commercial.get("deal_state") != "fulfilled-terminal"
        or commercial.get("escrow_state") != "released"
        or commercial.get("failure_policy_state") != "not-applicable"
        or not _commercial_is_clean(commercial)
    ):
        errors.append("vm-succeeded commercial state is not terminal and clean")
    return (start, end)


def _validate_atomic_observation_authority(
    observation: object,
    *,
    deal_reference: Mapping[str, Any] | None,
    common_clock_binding: Mapping[str, Any],
    errors: list[str],
    invoked_offset_ns: object = None,
    terminal_offset_ns: object = None,
) -> tuple[set[str], list[str], list[Mapping[str, Any]]]:
    if not isinstance(observation, dict):
        errors.append("atomic reservation evidence must be a structured observation")
        return set(), [], []

    if deal_reference is None or observation.get(
        "deal_reference_sha256"
    ) != canonical_sha256(dict(deal_reference)):
        errors.append(
            "atomic reservation observation does not bind the exact deal reference"
        )
    started = observation.get("started_offset_ns")
    completed = observation.get("completed_offset_ns")
    if (
        type(started) is not int
        or type(completed) is not int
        or started < 0
        or completed <= started
    ):
        errors.append("atomic reservation interval is invalid")
    elif (invoked_offset_ns is not None or terminal_offset_ns is not None) and (
        type(invoked_offset_ns) is not int
        or type(terminal_offset_ns) is not int
        or started < invoked_offset_ns
        or completed > terminal_offset_ns
    ):
        errors.append(
            "atomic reservation observation must fall inside the request interval"
        )
    if observation.get("clock_evidence_binding") != common_clock_binding:
        errors.append("atomic reservation interval must use the stage common clock")
    try:
        _require_binding(
            observation.get("eligible_site_set_binding"),
            domain=NATIVE_EVIDENCE_BINDING_DOMAIN,
            field_name="eligible_site_set_binding",
        )
    except CapacityValidationError as error:
        errors.append(str(error))

    eligible = observation.get("eligible_site_slots")
    if (
        not isinstance(eligible, list)
        or not eligible
        or any(not isinstance(item, str) for item in eligible)
    ):
        errors.append("eligible-site set must be non-empty")
        eligible_set = {
            item
            for item in eligible
            if isinstance(eligible, list) and isinstance(item, str)
        }
    else:
        eligible_set = set(eligible)
        if len(eligible_set) != len(eligible):
            errors.append("eligible-site set contains duplicates")

    attempts = observation.get("site_attempts")
    attempt_values: list[Mapping[str, Any]] = []
    attempt_slots: list[str] = []
    binding_ids: list[tuple[object, object, object]] = []
    if not isinstance(attempts, list) or not attempts:
        errors.append("atomic reservation observation requires a site attempt")
    else:
        for index, attempt in enumerate(attempts):
            if not isinstance(attempt, dict):
                errors.append(f"site_attempts[{index}] is not an observation")
                continue
            attempt_values.append(attempt)
            attempt_slot = attempt.get("site_slot")
            if isinstance(attempt_slot, str):
                attempt_slots.append(attempt_slot)
                if attempt_slot not in eligible_set:
                    errors.append(
                        f"site_attempts[{index}] is outside the eligible-site set"
                    )
            else:
                errors.append(f"site_attempts[{index}] lacks a valid site slot")
            try:
                binding = _require_binding(
                    attempt.get("site_binding"),
                    domain=NATIVE_EVIDENCE_BINDING_DOMAIN,
                    field_name=f"site_attempts[{index}].site_binding",
                )
                binding_ids.append(_binding_identity(binding))
            except CapacityValidationError as error:
                errors.append(str(error))
            response_kind = attempt.get("response_kind")
            reservation_id = attempt.get("reservation_id")
            error_category = attempt.get("error_category")
            observed = attempt.get("observed")
            skipped = attempt.get("skipped")
            if response_kind == "routine-reservation-null" and (
                reservation_id is not None
                or error_category is not None
                or observed is not True
                or skipped is not False
            ):
                errors.append(
                    f"site_attempts[{index}] has contradictory routine-null state"
                )
            elif response_kind == "reservation-created" and (
                not isinstance(reservation_id, str)
                or error_category is not None
                or observed is not True
                or skipped is not False
            ):
                errors.append(
                    f"site_attempts[{index}] has contradictory reservation state"
                )
            elif response_kind == "error" and (
                reservation_id is not None
                or not isinstance(error_category, str)
                or observed is not True
                or skipped is not False
            ):
                errors.append(f"site_attempts[{index}] has contradictory error state")
            elif response_kind == "missing" and (
                reservation_id is not None
                or error_category is not None
                or (observed, skipped)
                not in {
                    (True, False),
                    (False, True),
                }
            ):
                errors.append(f"site_attempts[{index}] has contradictory missing state")
            elif response_kind == "non-routine" and (
                reservation_id is not None
                or not isinstance(error_category, str)
                or observed is not True
                or skipped is not False
            ):
                errors.append(
                    f"site_attempts[{index}] has contradictory non-routine state"
                )
            if skipped is True and response_kind != "missing":
                errors.append(
                    f"site_attempts[{index}] skipped state must be recorded as missing"
                )
    if len(attempt_slots) != len(set(attempt_slots)):
        errors.append("site attempts contain duplicate site slots")
    if len(binding_ids) != len(set(binding_ids)):
        errors.append("eligible sites must use distinct private bindings")
    return eligible_set, attempt_slots, attempt_values


def _atomic_observation_is_routine_refusal(
    observation: object,
    *,
    deal_reference: Mapping[str, Any] | None,
    common_clock_binding: Mapping[str, Any],
    errors: list[str] | None = None,
    invoked_offset_ns: object = None,
    terminal_offset_ns: object = None,
) -> bool:
    local_errors: list[str] = []
    eligible_set, attempt_slots, attempts = _validate_atomic_observation_authority(
        observation,
        deal_reference=deal_reference,
        common_clock_binding=common_clock_binding,
        errors=local_errors,
        invoked_offset_ns=invoked_offset_ns,
        terminal_offset_ns=terminal_offset_ns,
    )
    if isinstance(observation, dict):
        if observation.get("final_escrow_scoped_call") is not True:
            local_errors.append(
                "capacity refusal must use the final escrow-scoped call"
            )
        for attempt in attempts:
            if (
                attempt.get("response_kind") != "routine-reservation-null"
                or attempt.get("reservation_id") is not None
                or attempt.get("error_category") is not None
                or attempt.get("observed") is not True
                or attempt.get("skipped") is not False
            ):
                local_errors.append(
                    "every eligible site must return one routine reservation null"
                )
        if set(attempt_slots) != eligible_set or len(attempt_slots) != len(
            eligible_set
        ):
            local_errors.append(
                "site attempts do not enumerate the complete eligible-site set exactly once"
            )
        if observation.get("aggregate_reservation_id") is not None:
            local_errors.append("capacity-refused aggregate reservation must be null")
    if errors is not None:
        errors.extend(local_errors)
    return not local_errors


def _validate_refusal(
    outcome: Mapping[str, Any],
    *,
    common_clock_binding: Mapping[str, Any],
    errors: list[str],
) -> tuple[int, int] | None:
    deal = outcome.get("deal_reference")
    if not isinstance(deal, dict) or any(
        deal.get(field) is None
        for field in (
            "negotiation_reference_sha256",
            "escrow_reference_sha256",
        )
    ):
        errors.append("capacity-refused requires negotiation and escrow authority")
        deal = None
    for field_name in (
        "capacity_reservation_id",
        "fulfillment_id",
        "settlement_record",
        "provisioned_resource_id",
        "allocation_id",
        "provisioning_job_id",
    ):
        if outcome.get(field_name) is not None:
            errors.append(f"capacity-refused requires null {field_name}")
    observation = outcome.get("refusal_observation")
    _atomic_observation_is_routine_refusal(
        observation,
        deal_reference=deal,
        common_clock_binding=common_clock_binding,
        errors=errors,
        invoked_offset_ns=outcome.get("invoked_offset_ns"),
        terminal_offset_ns=outcome.get("terminal_offset_ns"),
    )
    terminal = outcome.get("terminal_offset_ns")
    interval: tuple[int, int] | None = None
    if isinstance(observation, dict):
        started = observation.get("started_offset_ns")
        completed = observation.get("completed_offset_ns")
        invoked = outcome.get("invoked_offset_ns")
        if (
            type(started) is int
            and type(completed) is int
            and type(invoked) is int
            and type(terminal) is int
            and started >= invoked
            and completed <= terminal
        ):
            interval = (started, completed)
        else:
            errors.append(
                "atomic refusal observation must complete before terminal observation"
            )
    commercial = outcome.get("commercial_resolution")
    if (
        not isinstance(commercial, dict)
        or commercial.get("deal_state") != "refused-terminal"
        or commercial.get("escrow_state") not in {"refunded", "compensated"}
        or commercial.get("failure_policy_state") != "compensated"
        or not _commercial_is_clean(commercial)
    ):
        errors.append("capacity-refused requires terminal compensated commercial state")
    cleanup = outcome.get("request_cleanup")
    if not isinstance(cleanup, dict) or not (
        cleanup.get("teardown_complete") is True
        and cleanup.get("zero_active_residue") is True
    ):
        errors.append("capacity-refused requires teardown-equivalent zero residue")
    return interval


def _validate_fault(
    outcome: Mapping[str, Any],
    *,
    common_clock_binding: Mapping[str, Any],
    errors: list[str],
) -> None:
    category = outcome.get("failure_category")
    observation = outcome.get("fault_observation")
    if not isinstance(category, str) or not isinstance(observation, dict):
        return
    timed_out = observation.get("timed_out")
    if (category == "timeout") != (timed_out is True):
        errors.append("timeout fault category and observation must agree")
    if (
        category == "atomic-refusal-incomplete"
        and observation.get("atomic_reservation_observation") is None
    ):
        errors.append(
            "atomic-refusal-incomplete fault requires the partial site observation"
        )
    if category == "generator-failure" and observation.get("phase") not in {
        "pre-emission",
        "load-generation",
    }:
        errors.append(
            "generator-failure must identify pre-emission or load-generation phase"
        )
    if category == "cleanup-incomplete":
        request_cleanup = outcome.get("request_cleanup")
        if isinstance(request_cleanup, dict) and (
            request_cleanup.get("teardown_complete") is True
            and request_cleanup.get("zero_active_residue") is True
        ):
            errors.append(
                "cleanup-incomplete fault cannot claim clean request teardown"
            )
    partial_atomic = observation.get("atomic_reservation_observation")
    deal = outcome.get("deal_reference")
    commercial = outcome.get("commercial_resolution")
    cleanup = outcome.get("request_cleanup")
    if partial_atomic is not None:
        _validate_atomic_observation_authority(
            partial_atomic,
            deal_reference=(deal if isinstance(deal, dict) else None),
            common_clock_binding=common_clock_binding,
            errors=errors,
            invoked_offset_ns=outcome.get("invoked_offset_ns"),
            terminal_offset_ns=outcome.get("terminal_offset_ns"),
        )
    if _atomic_observation_is_routine_refusal(
        partial_atomic,
        deal_reference=(deal if isinstance(deal, dict) else None),
        common_clock_binding=common_clock_binding,
        invoked_offset_ns=outcome.get("invoked_offset_ns"),
        terminal_offset_ns=outcome.get("terminal_offset_ns"),
    ) and (
        all(
            outcome.get(field) is None
            for field in (
                "capacity_reservation_id",
                "fulfillment_id",
                "settlement_record",
                "provisioned_resource_id",
                "allocation_id",
                "provisioning_job_id",
            )
        )
        and isinstance(commercial, dict)
        and commercial.get("deal_state") == "refused-terminal"
        and commercial.get("escrow_state") in {"refunded", "compensated"}
        and commercial.get("failure_policy_state") == "compensated"
        and _commercial_is_clean(commercial)
        and isinstance(cleanup, dict)
        and cleanup.get("teardown_complete") is True
        and cleanup.get("zero_active_residue") is True
    ):
        errors.append("complete routine atomic refusal cannot be mislabeled as a fault")
    _validate_settlement_consistency(outcome, errors)


def maximum_half_open_overlap(
    intervals: Sequence[tuple[int, int]],
) -> int:
    """Return the exact maximum overlap for half-open monotonic intervals."""
    events: list[tuple[int, int]] = []
    for start, end in intervals:
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            raise CapacityValidationError(
                "active VM intervals must be non-negative, increasing integers"
            )
        # End events sort before start events at one boundary, implementing [a,b).
        events.append((start, 1))
        events.append((end, -1))
    active = 0
    maximum = 0
    for _offset, delta in sorted(events, key=lambda item: (item[0], item[1])):
        active += delta
        if active < 0:
            raise CapacityValidationError("active VM interval sweep is inconsistent")
        maximum = max(maximum, active)
    return maximum


def _cleanup_assessment(
    cleanup: object,
    *,
    host: SubstantiveRoleEvidence | None,
    errors: list[str],
) -> bool:
    if not isinstance(cleanup, dict):
        return False
    try:
        baseline = _require_binding(
            cleanup.get("reversible_baseline_binding"),
            domain=REVERSIBLE_BASELINE_BINDING_DOMAIN,
            field_name="cleanup.reversible_baseline_binding",
        )
        equivalence = _require_binding(
            cleanup.get("baseline_equivalence_binding"),
            domain=BASELINE_EQUIVALENCE_BINDING_DOMAIN,
            field_name="cleanup.baseline_equivalence_binding",
        )
    except CapacityValidationError as error:
        errors.append(str(error))
        baseline = {}
        equivalence = {}
    if host is not None:
        host_evidence = host.receipt.receipt["role_evidence"]
        if host_evidence.get("reversible_baseline_binding") != baseline:
            errors.append("cleanup baseline does not match host authority")
        if host_evidence.get("baseline_equivalence_binding") != equivalence:
            errors.append("cleanup equivalence does not match host authority")

    residue = cleanup.get("residue_counts")
    residue_clean = isinstance(residue, dict) and all(
        residue.get(field) == 0 for field in RESIDUE_FIELDS
    )
    components = cleanup.get("reversible_components")
    component_names: list[str] = []
    components_clean = isinstance(components, list)
    if isinstance(components, list):
        for index, component in enumerate(components):
            if not isinstance(component, dict):
                components_clean = False
                continue
            component_name = component.get("component")
            if isinstance(component_name, str):
                component_names.append(component_name)
            else:
                components_clean = False
            if component.get("exactly_equal") is not True:
                components_clean = False
            try:
                _require_binding(
                    component.get("native_evidence_binding"),
                    domain=NATIVE_EVIDENCE_BINDING_DOMAIN,
                    field_name=(
                        f"cleanup.reversible_components[{index}]."
                        "native_evidence_binding"
                    ),
                )
            except CapacityValidationError as error:
                errors.append(str(error))
                components_clean = False
    if set(component_names) != REVERSIBLE_COMPONENTS or len(component_names) != len(
        REVERSIBLE_COMPONENTS
    ):
        errors.append("cleanup must enumerate every reversible component exactly once")
        components_clean = False

    deltas = cleanup.get("accounting_deltas")
    delta_names: list[str] = []
    accounting_clean = isinstance(deltas, list)
    if isinstance(deltas, list):
        for index, delta in enumerate(deltas):
            if not isinstance(delta, dict):
                accounting_clean = False
                continue
            delta_name = delta.get("category")
            if isinstance(delta_name, str):
                delta_names.append(delta_name)
            else:
                accounting_clean = False
            if (
                delta.get("reconciled") is not True
                or delta.get("active_lock") is not False
                or delta.get("unexplained_value") is not False
            ):
                accounting_clean = False
            for field_name in (
                "expected_delta_binding",
                "observed_delta_binding",
            ):
                try:
                    _require_binding(
                        delta.get(field_name),
                        domain=NATIVE_EVIDENCE_BINDING_DOMAIN,
                        field_name=(f"cleanup.accounting_deltas[{index}].{field_name}"),
                    )
                except CapacityValidationError as error:
                    errors.append(str(error))
                    accounting_clean = False
    if set(delta_names) != ACCOUNTING_DELTA_CATEGORIES or len(delta_names) != len(
        ACCOUNTING_DELTA_CATEGORIES
    ):
        errors.append(
            "cleanup must enumerate every accounting delta category exactly once"
        )
        accounting_clean = False
    native_bindings = cleanup.get("native_evidence_bindings")
    if isinstance(native_bindings, list):
        for index, binding in enumerate(native_bindings):
            try:
                _require_binding(
                    binding,
                    domain=NATIVE_EVIDENCE_BINDING_DOMAIN,
                    field_name=f"cleanup.native_evidence_bindings[{index}]",
                )
            except CapacityValidationError as error:
                errors.append(str(error))

    clean = (
        cleanup.get("terminal_correlations_complete") is True
        and cleanup.get("teardown_complete") is True
        and residue_clean
        and components_clean
        and accounting_clean
    )
    if cleanup.get("ready_for_next_stage") is not clean:
        errors.append(
            "cleanup ready_for_next_stage must equal the derived clean-state result"
        )
    if host is not None:
        host_outcome = host.receipt.receipt["role_evidence"]
        if host_outcome.get("cleanup_complete") is not clean:
            errors.append(
                "derived cleanup state does not match host-operator observation"
            )
        baseline_equivalent = host_outcome.get("baseline_equivalent")
        if baseline_equivalent is not None and baseline_equivalent is not (
            components_clean and accounting_clean and residue_clean
        ):
            errors.append(
                "derived baseline state does not match host-operator observation"
            )
    return clean


def _exact_execution_authority(
    value: Mapping[str, Any],
    *,
    actor_set: ValidatedActorSet | None,
    reference_policy: ValidatedReferencePolicy | None,
    execution_boundary: str,
    errors: list[str],
) -> tuple[dict[str, Any] | None, datetime | None]:
    authority = value.get("execution_authority")
    if not isinstance(authority, dict):
        return None, None
    if execution_boundary == "real-reference":
        if actor_set is not None:
            errors.append("real-reference cannot bind an agent actor set")
        validated_reference_policy: ValidatedReferencePolicy | None = None
        try:
            reference_policy_value = _require_reference_policy(reference_policy)
        except CapacityValidationError as error:
            errors.append(str(error))
            reference_policy_value = {}
        else:
            validated_reference_policy = reference_policy
        if (
            authority.get("kind") != "controller-reference"
            or authority.get("controller_is_counted") is not False
        ):
            errors.append("real-reference requires non-counted controller authority")
        if validated_reference_policy is not None:
            expected_policy_authority = {
                "reference_policy_id": validated_reference_policy.policy_id,
                "reference_policy_sha256": (
                    validated_reference_policy.canonical_sha256
                ),
                "release_id": validated_reference_policy.release_id,
                "clock_evidence_binding": (
                    validated_reference_policy.clock_evidence_binding
                ),
                "controller_is_counted": False,
            }
            for field_name, expected in expected_policy_authority.items():
                if authority.get(field_name) != expected:
                    errors.append(
                        "reference execution does not bind the validated "
                        f"policy {field_name}"
                    )
            for field_name in (
                "scm_ref",
                "profile_stage_id",
                "profile_stage_sha256",
                "scenario_id",
                "scenario_sha256",
            ):
                if reference_policy_value.get(field_name) != value.get(field_name):
                    errors.append("reference policy does not bind the result stage")
                    break
        for field_name in (
            "reference_execution_binding",
            "clock_evidence_binding",
        ):
            try:
                _require_binding(
                    authority.get(field_name),
                    domain=NATIVE_EVIDENCE_BINDING_DOMAIN,
                    field_name=field_name,
                )
            except CapacityValidationError as error:
                errors.append(str(error))
        try:
            released_at = _parse_utc(
                authority.get("released_at"),
                field_name="execution_authority.released_at",
            )
        except CapacityValidationError as error:
            errors.append(str(error))
            released_at = None
        if (
            released_at is not None
            and validated_reference_policy is not None
            and validated_reference_policy.frozen_at >= released_at
        ):
            errors.append("reference policy must be frozen before controller release")
        return None, released_at

    if reference_policy is not None:
        errors.append("only real-reference execution may supply a reference policy")
    if actor_set is None:
        errors.append("agent-driven result requires an actor-set observation")
        return None, None
    actor_value = _require_actor_observation(actor_set)
    for field_name in (
        "scm_ref",
        "profile_stage_id",
        "profile_stage_sha256",
        "scenario_id",
        "scenario_sha256",
        "execution_boundary",
        "actor_trigger",
    ):
        if actor_value.get(field_name) != value.get(field_name):
            errors.append(f"actor observation {field_name} does not match the result")
    expected = {
        "kind": "agent-actor-set",
        "actor_set_id": actor_set.actor_set_id,
        "actor_set_sha256": actor_set.canonical_sha256,
        "release_id": actor_value.get("release_id"),
        "concurrency_policy_id": actor_value.get("concurrency_policy_id"),
        "concurrency_policy_sha256": actor_value.get("concurrency_policy_sha256"),
    }
    if authority != expected:
        errors.append(
            "result execution authority does not match the exact actor observation"
        )
    try:
        released_at = _parse_utc(
            actor_value.get("release_observed_at"),
            field_name="actor_set.release_observed_at",
        )
    except CapacityValidationError as error:
        errors.append(str(error))
        released_at = None
    return actor_value, released_at


def _expected_stage_assessment(
    *,
    outcomes_match: bool,
    maximum_latency_ns: int,
    maximum_overlap: int,
    physical_gpu_count: int,
    provisioning_queue_passed: bool,
    ansible_service_passed: bool,
    cleanup_passed: bool,
    load_generator_passed: bool,
    execution_boundary: str,
    policy: ValidatedEvaluationPolicy,
) -> dict[str, Any]:
    request_processing = (
        outcomes_match
        and maximum_latency_ns <= policy.request_processing_slo_ns
        and maximum_latency_ns < policy.terminal_observation_timeout_ns
        and (execution_boundary == "real-reference" or load_generator_passed)
    )
    provisioning = provisioning_queue_passed and ansible_service_passed
    correctness = (
        outcomes_match and maximum_overlap <= physical_gpu_count and cleanup_passed
    )
    derived_faults = (
        ["double-allocation"] if maximum_overlap > physical_gpu_count else []
    )
    if execution_boundary == "real-reference":
        stage_passed = request_processing and provisioning and correctness
        agent_evidence = False
        frontier_eligible = False
    else:
        stage_passed = (
            request_processing
            and provisioning
            and correctness
            and load_generator_passed
        )
        agent_evidence = True
        frontier_eligible = (
            execution_boundary == "real-measured" and load_generator_passed
        )
    return {
        "outcomes_match_expected": outcomes_match,
        "request_processing_passed": request_processing,
        "simultaneous_fulfillment_count": maximum_overlap,
        "provisioning_passed": provisioning,
        "correctness_passed": correctness,
        "load_generator_passed": load_generator_passed,
        "cleanup_passed": cleanup_passed,
        "stage_passed": stage_passed,
        "agent_capacity_evidence": agent_evidence,
        "eligible_for_capacity_frontier": frontier_eligible,
        "derived_faults": derived_faults,
    }


def _expected_frontier_observation(
    *,
    buyer_count: int,
    maximum_latency_ns: int,
    maximum_overlap: int,
    maximum_queue_wait_ns: int,
    maximum_ansible_service_ns: int,
    assessment: Mapping[str, Any],
    policy: ValidatedEvaluationPolicy,
) -> dict[str, Any]:
    return {
        "offered_buyers": buyer_count,
        "request_processing": {
            "passed": assessment["request_processing_passed"],
            "observed_max_ns": maximum_latency_ns,
            "slo_ns": policy.request_processing_slo_ns,
        },
        "simultaneous_fulfillment": {
            "max_overlapping_whole_gpu_vms": maximum_overlap,
        },
        "provisioning_queue": {
            "passed": (
                maximum_queue_wait_ns <= policy.provisioning_queue_slo_ns
                and assessment["simultaneous_fulfillment_count"] > 0
            ),
            "observed_max_ns": maximum_queue_wait_ns,
            "slo_ns": policy.provisioning_queue_slo_ns,
        },
        "ansible_service": {
            "passed": (
                maximum_ansible_service_ns <= policy.ansible_service_slo_ns
                and assessment["simultaneous_fulfillment_count"] > 0
            ),
            "observed_max_ns": maximum_ansible_service_ns,
            "slo_ns": policy.ansible_service_slo_ns,
        },
        "correctness_passed": assessment["correctness_passed"],
        "load_generator_passed": assessment["load_generator_passed"],
    }


def validate_capacity_result(
    value: dict[str, Any],
    repo_root: Path,
    *,
    evaluation_policy: ValidatedEvaluationPolicy,
    oracle_authority: ValidatedOracleAuthority,
    actor_set: ValidatedActorSet | None = None,
    reference_policy: ValidatedReferencePolicy | None = None,
    role_evidence: Sequence[SubstantiveRoleEvidence] = (),
    predecessor: ValidatedCapacityResult | None = None,
    buyer_frontier: ValidatedBuyerFrontierReceipt | None = None,
    reuse_baseline: ValidatedCapacityResult | None = None,
    prior_seller_results: Sequence[ValidatedCapacityResult] = (),
    expected_scm_ref: str | None = None,
) -> ValidatedCapacityResult:
    policy_value = _require_policy(evaluation_policy)
    scm_ref = value.get("scm_ref")
    root = _validate_exact_commit(repo_root, scm_ref)
    assert isinstance(scm_ref, str)
    errors: list[str] = []
    if root != evaluation_policy.repo_root:
        errors.append(
            "capacity result and evaluation policy use different repositories"
        )
    if scm_ref != evaluation_policy.scm_ref:
        errors.append("capacity result and evaluation policy use different SCM refs")
    if expected_scm_ref is not None and scm_ref != expected_scm_ref:
        errors.append(
            "capacity-result SCM ref does not match the selected campaign ref"
        )
    schema = _load_pinned_schema(root, scm_ref, CAPACITY_RESULT_SCHEMA)
    schema_errors = _schema_errors(value, schema)
    _raise_errors("capacity result", schema_errors)

    try:
        stage = resolve_pinned_profile_stage(
            root,
            scm_ref,
            value.get("profile_stage_id"),
            expected_sha256=value.get("profile_stage_sha256"),
        )
    except CapacityValidationError as error:
        errors.append(str(error))
        stage = None
        stage_value: dict[str, Any] = {}
        scenario: dict[str, Any] = {}
        scenario_sha256 = None
    else:
        stage_value = stage.stage
        if stage.scenario is None:
            errors.append("real capacity result requires a request-bearing scenario")
            scenario = {}
            scenario_sha256 = None
        else:
            scenario = stage.scenario.scenario
            scenario_sha256 = stage.scenario.scenario_sha256
        for field, expected in (
            ("scenario_id", scenario.get("scenario_id")),
            ("scenario_sha256", scenario_sha256),
            ("execution_boundary", stage_value.get("execution_boundary")),
            ("actor_trigger", stage_value.get("actor_trigger")),
        ):
            if value.get(field) != expected:
                errors.append(
                    f"capacity result {field} does not match pinned profile stage"
                )
    boundary = value.get("execution_boundary")
    aggregate_value = value.get("aggregate_observation")
    if not isinstance(aggregate_value, dict):
        aggregate_value = {}
    if boundary not in {
        "real-reference",
        "real-qualification",
        "real-measured",
    }:
        errors.append(
            "real capacity result cannot represent readiness or mock evidence"
        )

    try:
        oracle_value = _require_oracle(
            oracle_authority,
            scm_ref=scm_ref,
            profile_stage_id=value.get("profile_stage_id", ""),
        )
    except CapacityValidationError as error:
        errors.append(str(error))
        oracle_value = {}
    expected_oracle = {
        "oracle_authority_id": getattr(
            oracle_authority,
            "oracle_authority_id",
            None,
        ),
        "oracle_authority_sha256": getattr(
            oracle_authority,
            "canonical_sha256",
            None,
        ),
        "observer_plan_sha256": oracle_value.get("observer_plan_sha256"),
    }
    if value.get("oracle_authority") != expected_oracle:
        errors.append(
            "capacity result does not bind its exact independent oracle authority"
        )
    expected_policy = {
        "evaluation_policy_id": evaluation_policy.policy_id,
        "evaluation_policy_sha256": evaluation_policy.canonical_sha256,
    }
    if value.get("evaluation_policy") != expected_policy:
        errors.append("capacity result does not bind its exact evaluation policy")

    validated_reference_policy: ValidatedReferencePolicy | None = None
    if reference_policy is not None:
        try:
            _require_reference_policy(reference_policy)
        except CapacityValidationError as error:
            errors.append(str(error))
        else:
            validated_reference_policy = reference_policy
    actor_value, released_at = _exact_execution_authority(
        value,
        actor_set=actor_set,
        reference_policy=validated_reference_policy,
        execution_boundary=boundary,
        errors=errors,
    )
    try:
        started_at = _parse_utc(value.get("started_at"), field_name="started_at")
        terminal_at = _parse_utc(
            value.get("terminal_observed_at"),
            field_name="terminal_observed_at",
        )
        cleanup_at = _parse_utc(
            value.get("cleanup_completed_at"),
            field_name="cleanup_completed_at",
        )
        declared_progression_ready_at = _parse_utc(
            value.get("progression_ready_at"),
            field_name="progression_ready_at",
        )
    except CapacityValidationError as error:
        errors.append(str(error))
        started_at = terminal_at = cleanup_at = declared_progression_ready_at = (
            datetime.min.replace(tzinfo=UTC)
        )
    if not (started_at < terminal_at <= cleanup_at <= declared_progression_ready_at):
        errors.append(
            "capacity result timestamps must order start, terminal, cleanup, "
            "and progression readiness"
        )
    if released_at is not None:
        if evaluation_policy.frozen_at >= released_at:
            errors.append("evaluation policy must be frozen before stage release")
        if released_at < started_at or released_at > terminal_at:
            errors.append("stage release must fall inside the observed lifecycle")

    evidence = _validated_role_evidence(role_evidence)
    if any(
        item.plan.scm_ref != scm_ref
        or item.plan.profile_stage_id != value.get("profile_stage_id")
        or item.plan.profile_stage_sha256 != value.get("profile_stage_sha256")
        or item.plan.scenario_id != value.get("scenario_id")
        or item.plan.scenario_sha256 != value.get("scenario_sha256")
        for item in evidence
    ):
        errors.append("role evidence does not bind the result stage")
    if boundary == "real-reference":
        if {item.plan.role for item in evidence} != {
            "host-operator",
            "observer",
        } or len(evidence) != 2:
            errors.append(
                "controller reference requires exactly one independent "
                "observer and one host-operator receipt"
            )
        if any(item.actions or item.results for item in evidence):
            errors.append(
                "reference observer and host evidence cannot author market actions"
            )
        authority = value.get("execution_authority")
        authority_value = authority if isinstance(authority, dict) else {}
        expected_run_authority = {
            "release_id": authority_value.get("release_id"),
            "concurrency_policy_id": authority_value.get("reference_policy_id"),
            "concurrency_policy_sha256": authority_value.get("reference_policy_sha256"),
        }
        if any(
            item.receipt.receipt.get("run_authority") != expected_run_authority
            for item in evidence
        ):
            errors.append(
                "reference observer and host receipts must bind the exact "
                "controller reference policy and release"
            )
        buyer_actions: dict[str, tuple[SubstantiveRoleEvidence, Any, Any]] = {}
        try:
            host = _host_evidence(evidence)
            observer = _observer_evidence(
                evidence,
                observer_plan_sha256=oracle_value.get(
                    "observer_plan_sha256",
                    "",
                ),
            )
        except CapacityValidationError as error:
            errors.append(str(error))
            host = None
            observer = None
        if host is not None and observer is not None:
            reference_policy_value = (
                validated_reference_policy.policy
                if validated_reference_policy is not None
                else {}
            )
            for evidence_item, policy_field in (
                (observer, "observer_plan"),
                (host, "host_plan"),
            ):
                expected_plan_authority = reference_policy_value.get(policy_field)
                actual_plan_authority = {
                    "plan_id": evidence_item.plan.plan_id,
                    "plan_sha256": evidence_item.plan.canonical_sha256,
                }
                if expected_plan_authority != actual_plan_authority:
                    errors.append(
                        "reference role evidence does not match the exact "
                        f"policy-bound {policy_field}"
                    )
            if host.receipt.receipt_id == observer.receipt.receipt_id:
                errors.append(
                    "reference O1 and H1 receipts must use distinct receipt IDs"
                )
            host_liveness = host.receipt.receipt.get("provenance", {}).get(
                "actor_liveness_binding"
            )
            observer_liveness = observer.receipt.receipt.get("provenance", {}).get(
                "actor_liveness_binding"
            )
            if _binding_identity(host_liveness) == _binding_identity(observer_liveness):
                errors.append(
                    "reference O1 and H1 receipts must use distinct liveness evidence"
                )
            expected_receipts = {
                "observer_receipt_id": observer.receipt.receipt_id,
                "observer_receipt_sha256": (observer.receipt.canonical_sha256),
                "host_receipt_id": host.receipt.receipt_id,
                "host_receipt_sha256": host.receipt.canonical_sha256,
            }
            for field_name, expected in expected_receipts.items():
                if authority_value.get(field_name) != expected:
                    errors.append(
                        f"reference execution does not bind the exact {field_name}"
                    )
        listing_map: dict[tuple[str, str], dict[str, Any]] = {}
        common_clock = authority_value.get("clock_evidence_binding", {})
        if aggregate_value.get("common_clock_binding") != common_clock:
            errors.append(
                "reference aggregate must bind the controller policy's "
                "independent common clock"
            )
        load_generator_passed = False
        timing_values = authority_value.get("request_timing_observations")
        reference_timing_map: dict[str, dict[str, Any]] = {}
        if isinstance(timing_values, list):
            for timing in timing_values:
                if not isinstance(timing, dict):
                    continue
                request_id = timing.get("request_id")
                if (
                    not isinstance(request_id, str)
                    or request_id in reference_timing_map
                ):
                    errors.append(
                        "reference timing observations require unique request IDs"
                    )
                    continue
                reference_timing_map[request_id] = timing
                try:
                    _require_binding(
                        timing.get("native_evidence_binding"),
                        domain=NATIVE_EVIDENCE_BINDING_DOMAIN,
                        field_name=("execution_authority.request_timing_observations"),
                    )
                except CapacityValidationError as error:
                    errors.append(str(error))
        if validated_reference_policy is not None:
            scheduled = dict(validated_reference_policy.request_schedule)
            if {
                request_id: timing.get("invoked_offset_ns")
                for request_id, timing in reference_timing_map.items()
            } != scheduled:
                errors.append(
                    "reference timings do not match the frozen request schedule"
                )
    else:
        reference_timing_map = {}
        if actor_value is None:
            buyer_actions = {}
            host = None
            observer = None
            listing_map = {}
            common_clock = {}
            load_generator_passed = False
        else:
            actor_receipts = {
                (
                    entry.get("actor_slot"),
                    entry.get("receipt_sha256"),
                )
                for entry in actor_value.get("actors", ())
                if isinstance(entry, dict)
            }
            evidence_receipts = {
                (item.plan.actor_slot, item.receipt.canonical_sha256)
                for item in evidence
            }
            if actor_receipts != evidence_receipts:
                errors.append(
                    "role evidence does not match the exact actor observation"
                )
            buyer_actions = _buyer_action_map(evidence)
            try:
                host = _host_evidence(evidence)
                observer = _observer_evidence(
                    evidence,
                    observer_plan_sha256=oracle_value.get("observer_plan_sha256", ""),
                )
            except CapacityValidationError as error:
                errors.append(str(error))
                host = None
                observer = None
            listing_map = _listing_runtime_map(actor_value)
            common_clock = actor_value.get("clock_evidence_binding")
            load_generator_passed = bool(
                getattr(actor_set, "load_generator_passed", True)
            )
            if aggregate_value.get("common_clock_binding") != common_clock:
                errors.append("aggregate result must use the actor set's common clock")
            action_oracles = {
                action.action["expected_result"].get(
                    "independent_oracle_authority_sha256"
                )
                for item in evidence
                for action in item.actions
            }
            if action_oracles != {expected_oracle["oracle_authority_sha256"]}:
                errors.append(
                    "every stage action must bind the one exact result oracle"
                )

    if common_clock != policy_value.get("clock_evidence_binding"):
        errors.append(
            "stage common clock does not match the pre-Q0 evaluation-policy "
            "clock authority"
        )

    try:
        topology_binding = _require_binding(
            value.get("topology_authority_binding"),
            domain=TOPOLOGY_BINDING_DOMAIN,
            field_name="topology_authority_binding",
        )
    except CapacityValidationError as error:
        errors.append(str(error))
        topology_binding = {}
    if host is not None and (
        host.receipt.receipt["role_evidence"].get("topology_authority_binding")
        != topology_binding
    ):
        errors.append("capacity result topology does not match host authority")
    if host is not None and cleanup_at > host.receipt.barrier_observed_at:
        errors.append(
            "cleanup completion must precede the host-operator cleanup barrier"
        )
    seller_admission = (
        host.receipt.receipt["role_evidence"].get("seller_scaling_admission")
        if host is not None
        else None
    )
    if value.get("scenario_id") == "serialized-reuse-b":
        if not isinstance(seller_admission, dict):
            errors.append("serialized reuse B lacks host-attested seller admission")
            admitted_seller_identities = None
            admitted_service_instances = None
        else:
            admitted_seller_identities = seller_admission.get(
                "distinct_seller_identities"
            )
            admitted_service_instances = seller_admission.get(
                "distinct_service_instances"
            )
            if (
                type(admitted_seller_identities) is not int
                or type(admitted_service_instances) is not int
            ):
                errors.append(
                    "serialized reuse B seller admission cardinalities are invalid"
                )
    else:
        admitted_seller_identities = None
        admitted_service_instances = None
        if seller_admission is not None:
            errors.append("seller admission may only be carried by serialized reuse B")
    evidence_completion_times = [
        item.receipt.completed_at for item in (host, observer) if item is not None
    ]
    derived_progression_ready_at = max(
        evidence_completion_times,
        default=cleanup_at,
    )
    if derived_progression_ready_at < cleanup_at:
        errors.append("progression readiness cannot precede cleanup completion")
    if declared_progression_ready_at != derived_progression_ready_at:
        errors.append(
            "progression_ready_at must equal the final H1/O1 evidence completion"
        )

    expected_outcomes = scenario.get("expected_outcomes")
    if value.get("expected_outcomes") != expected_outcomes:
        errors.append("capacity result expected outcomes do not match scenario")
    request_values = scenario.get("requests")
    scenario_requests = (
        {
            item.get("request_id"): item
            for item in request_values
            if isinstance(request_values, list) and isinstance(item, dict)
        }
        if isinstance(request_values, list)
        else {}
    )
    observer_request_map: dict[str, dict[str, Any]] = {}
    observer_cleanup_observation: dict[str, Any] | None = None
    if observer is not None:
        observer_role_evidence = observer.receipt.receipt.get("role_evidence")
        if isinstance(observer_role_evidence, dict):
            observer_request_values = observer_role_evidence.get("request_observations")
            if isinstance(observer_request_values, list):
                for observation in observer_request_values:
                    if not isinstance(observation, dict):
                        continue
                    request_id = observation.get("request_id")
                    if (
                        not isinstance(request_id, str)
                        or request_id in observer_request_map
                    ):
                        errors.append(
                            "observer request observations require unique request IDs"
                        )
                        continue
                    observer_request_map[request_id] = observation
            cleanup_observation = observer_role_evidence.get("cleanup_observation")
            if isinstance(cleanup_observation, dict):
                observer_cleanup_observation = cleanup_observation
    if set(observer_request_map) != set(scenario_requests):
        errors.append("independent observer must seal every exact request outcome")
    if observer_cleanup_observation is None:
        errors.append("independent observer must seal the cleanup snapshot")
    outcomes = value.get("request_outcomes")
    outcome_by_request: dict[str, dict[str, Any]] = {}
    if isinstance(outcomes, list):
        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue
            request_id = outcome.get("request_id")
            if isinstance(request_id, str) and request_id in outcome_by_request:
                errors.append("request outcomes must have unique request IDs")
            elif isinstance(request_id, str):
                outcome_by_request[request_id] = outcome
    if set(outcome_by_request) != set(scenario_requests):
        errors.append("request outcomes must cover every exact scenario request once")
    if boundary == "real-reference" and set(reference_timing_map) != set(
        scenario_requests
    ):
        errors.append("reference timing observations must cover every exact request")

    aggregate = aggregate_value
    if aggregate.get("observer_plan_sha256") != oracle_value.get(
        "observer_plan_sha256"
    ):
        errors.append("aggregate observation does not bind the observer plan")
    observed_request_ids = aggregate.get("observed_request_ids")
    observed_request_id_set = (
        {item for item in observed_request_ids if isinstance(item, str)}
        if isinstance(observed_request_ids, list)
        else set()
    )
    if (
        not isinstance(observed_request_ids, list)
        or len(observed_request_id_set) != len(observed_request_ids)
        or observed_request_id_set != set(scenario_requests)
    ):
        errors.append("aggregate observation must enumerate every request exactly once")
    aggregate_observed_at: datetime | None = None
    try:
        aggregate_observed_at = _parse_utc(
            aggregate.get("observed_at"),
            field_name="aggregate_observation.observed_at",
        )
        if not started_at <= aggregate_observed_at <= terminal_at:
            errors.append("aggregate observation must fall inside the stage lifecycle")
    except CapacityValidationError as error:
        errors.append(str(error))
    if observer is not None:
        expected_native = observer.receipt.receipt["role_evidence"].get(
            "native_evidence_bindings"
        )
        if aggregate.get("native_evidence_bindings") != expected_native:
            errors.append("aggregate observation does not bind exact observer evidence")
        if aggregate_observed_at is not None and not (
            observer.receipt.barrier_observed_at
            <= aggregate_observed_at
            <= observer.receipt.completed_at
        ):
            errors.append(
                "aggregate observation must fall inside the independent "
                "observer receipt lifecycle"
            )
        if cleanup_at > observer.receipt.completed_at:
            errors.append(
                "cleanup completion must fall inside the observer receipt lifecycle"
            )
    aggregate_native_bindings = aggregate.get("native_evidence_bindings")
    timing_values = aggregate.get("request_timing_observations")
    aggregate_timing_map: dict[str, dict[str, Any]] = {}
    if isinstance(timing_values, list):
        for timing in timing_values:
            if not isinstance(timing, dict):
                continue
            request_id = timing.get("request_id")
            if not isinstance(request_id, str) or request_id in aggregate_timing_map:
                errors.append("aggregate request timings require unique request IDs")
                continue
            aggregate_timing_map[request_id] = timing
            try:
                timing_binding = _require_binding(
                    timing.get("native_evidence_binding"),
                    domain=NATIVE_EVIDENCE_BINDING_DOMAIN,
                    field_name=("aggregate_observation.request_timing_observations"),
                )
            except CapacityValidationError as error:
                errors.append(str(error))
            else:
                if (
                    not isinstance(aggregate_native_bindings, list)
                    or timing_binding not in aggregate_native_bindings
                ):
                    errors.append(
                        "every request timing must bind exact independent "
                        "observer evidence"
                    )
    if set(aggregate_timing_map) != set(scenario_requests):
        errors.append("aggregate request timings must cover every exact request")

    active_intervals: list[tuple[int, int]] = []
    outcome_kinds: list[str] = []
    queue_waits: list[int] = []
    ansible_services: list[int] = []
    maximum_latency_ns = 0
    durable_fields = (
        "capacity_reservation_id",
        "fulfillment_id",
        "provisioned_resource_id",
        "allocation_id",
        "provisioning_job_id",
    )
    seen_durable: dict[str, set[str]] = {field: set() for field in durable_fields}
    commercial_references: dict[str, set[str]] = {
        "negotiation_reference_sha256": set(),
        "escrow_reference_sha256": set(),
    }
    for request_id, request in scenario_requests.items():
        outcome = outcome_by_request.get(request_id)
        if outcome is None:
            continue
        selection = (request.get("seller_slot"), request.get("listing_slot"))
        runtime = listing_map.get(selection)
        if boundary == "real-reference":
            deal = outcome.get("deal_reference")
            runtime = deal.get("runtime_binding") if isinstance(deal, dict) else None
            try:
                runtime = _require_binding(
                    runtime,
                    domain=RUNTIME_BINDING_DOMAIN,
                    field_name=f"{request_id}.runtime_binding",
                )
            except CapacityValidationError as error:
                errors.append(str(error))
                runtime = {}
        if runtime is None:
            errors.append(
                f"{request_id} lacks its sealed seller/listing runtime binding"
            )
            runtime = {}
        _validate_common_request(outcome, request, runtime, errors)
        outcome_kind = outcome.get("outcome_kind")
        if isinstance(outcome_kind, str):
            outcome_kinds.append(outcome_kind)
        invoked = outcome.get("invoked_offset_ns")
        terminal = outcome.get("terminal_offset_ns")
        aggregate_timing = aggregate_timing_map.get(request_id)
        if (
            not isinstance(aggregate_timing, dict)
            or aggregate_timing.get("invoked_offset_ns") != invoked
            or aggregate_timing.get("terminal_offset_ns") != terminal
        ):
            errors.append(
                f"{request_id} timing does not match its independent observer timing"
            )
        else:
            outcome_bindings = outcome.get("independent_observation_bindings")
            observer_request = observer_request_map.get(request_id)
            if (
                not isinstance(outcome_bindings, list)
                or aggregate_timing.get("native_evidence_binding")
                not in outcome_bindings
                or not isinstance(observer_request, dict)
                or aggregate_timing.get("native_evidence_binding")
                != observer_request.get("native_evidence_binding")
            ):
                errors.append(
                    f"{request_id} does not bind its independent timing observation"
                )
        observer_request = observer_request_map.get(request_id)
        if not isinstance(observer_request, dict) or observer_request.get(
            "request_outcome_sha256"
        ) != canonical_sha256(outcome):
            errors.append(
                f"{request_id} outcome bytes do not match the independent "
                "observer receipt"
            )
        if boundary == "real-reference":
            timing = reference_timing_map.get(request_id)
            if (
                not isinstance(timing, dict)
                or timing.get("invoked_offset_ns") != invoked
                or timing.get("terminal_offset_ns") != terminal
            ):
                errors.append(
                    f"{request_id} timing does not match the independently "
                    "bound controller-reference observation"
                )
        if type(invoked) is int and type(terminal) is int and terminal > invoked:
            request_latency_ns = terminal - invoked
            maximum_latency_ns = max(maximum_latency_ns, request_latency_ns)
            reached_terminal_timeout = (
                request_latency_ns >= evaluation_policy.terminal_observation_timeout_ns
            )
            if outcome_kind == "fault":
                timeout_fault = (
                    outcome.get("failure_category") == "timeout"
                    and isinstance(outcome.get("fault_observation"), dict)
                    and outcome["fault_observation"].get("timed_out") is True
                )
                if timeout_fault is not reached_terminal_timeout:
                    errors.append(
                        f"{request_id} timeout classification does not match "
                        "the frozen terminal-observation deadline"
                    )
            elif reached_terminal_timeout:
                errors.append(
                    f"{request_id} reached the frozen terminal-observation "
                    "deadline and must be classified as a timeout fault"
                )

        buyer_record = buyer_actions.get(request_id)
        buyer = buyer_record[0] if buyer_record is not None else None
        if buyer_record is not None and actor_value is not None:
            _buyer, action, action_result = buyer_record
            action_entries = [
                entry
                for entry in actor_value.get("actions", ())
                if isinstance(entry, dict)
                and entry.get("action_id") == action.action_id
            ]
            actor_entries = [
                entry
                for entry in actor_value.get("actors", ())
                if isinstance(entry, dict)
                and entry.get("actor_slot") == action.actor_slot
            ]
            if (
                len(action_entries) != 1
                or action_entries[0].get("invoked_offset_ns") != invoked
            ):
                errors.append(f"{request_id} does not bind its exact buyer invocation")
            elif type(terminal) is not int or terminal < action_entries[0].get(
                "terminal_offset_ns", terminal + 1
            ):
                errors.append(
                    f"{request_id} market outcome cannot precede its action "
                    "wrapper terminal result"
                )
            if (
                len(actor_entries) != 1
                or type(terminal) is not int
                or terminal
                > actor_entries[0].get(
                    "completed_offset_ns",
                    -1,
                )
            ):
                errors.append(
                    f"{request_id} market outcome must remain inside its "
                    "buyer actor lifetime"
                )
            emitted = action_result.result_kind == "emitted"
            is_generator_fault = (
                outcome_kind == "fault"
                and outcome.get("failure_category") == "generator-failure"
            )
            if emitted == is_generator_fault:
                errors.append(
                    f"{request_id} action emission and outcome classification disagree"
                )
            if action.action.get("runtime_binding") != runtime:
                errors.append(
                    f"{request_id} runtime binding differs from frozen action"
                )

        if outcome_kind == "vm-succeeded":
            interval = _validate_success(
                outcome,
                repo_root=root,
                scm_ref=scm_ref,
                buyer=buyer,
                buyer_required=boundary != "real-reference",
                common_clock_binding=(
                    common_clock if isinstance(common_clock, Mapping) else {}
                ),
                errors=errors,
            )
            if interval is not None:
                active_intervals.append(interval)
            observation = outcome.get("success_observation")
            provisioning = (
                observation.get("provisioning")
                if isinstance(observation, dict)
                else None
            )
            if isinstance(provisioning, dict):
                queue = provisioning.get("queue_wait_ns")
                service = provisioning.get("ansible_service_ns")
                if type(queue) is int:
                    queue_waits.append(queue)
                if type(service) is int:
                    ansible_services.append(service)
        elif outcome_kind == "capacity-refused":
            _validate_refusal(
                outcome,
                common_clock_binding=(
                    common_clock if isinstance(common_clock, Mapping) else {}
                ),
                errors=errors,
            )
            if buyer is not None and (
                buyer.receipt.receipt["role_evidence"].get("guest_verification")
                is not None
            ):
                errors.append("capacity-refused buyer cannot claim guest GPU success")
        elif outcome_kind == "fault":
            _validate_fault(
                outcome,
                common_clock_binding=(
                    common_clock if isinstance(common_clock, Mapping) else {}
                ),
                errors=errors,
            )

        for field_name in durable_fields:
            identity = outcome.get(field_name)
            if isinstance(identity, str):
                if identity in seen_durable[field_name]:
                    errors.append(
                        f"{field_name} cannot be reused across request outcomes"
                    )
                seen_durable[field_name].add(identity)
        deal = outcome.get("deal_reference")
        if isinstance(deal, dict):
            for field_name in (
                "negotiation_reference_sha256",
                "escrow_reference_sha256",
            ):
                identity = deal.get(field_name)
                if isinstance(identity, str):
                    if identity in commercial_references[field_name]:
                        errors.append(
                            "commercial references cannot be reused across requests"
                        )
                    commercial_references[field_name].add(identity)

    maximum_overlap = maximum_half_open_overlap(active_intervals)
    if aggregate.get("max_overlapping_whole_gpu_vms") != maximum_overlap:
        errors.append(
            "aggregate simultaneous-fulfillment count was not independently derived"
        )
    physical = scenario.get("physical_capacity")
    physical_gpu_count = (
        physical.get("independently_assignable_gpus")
        if isinstance(physical, dict)
        else 0
    )
    if type(physical_gpu_count) is not int:
        physical_gpu_count = 0
    observed_counts = {
        "vm-succeeded": outcome_kinds.count("vm-succeeded"),
        "capacity-refused": outcome_kinds.count("capacity-refused"),
        "fault": outcome_kinds.count("fault"),
    }
    if value.get("observed_outcomes") != observed_counts:
        errors.append("observed outcome counts must be recomputed from requests")
    outcomes_match = observed_counts == expected_outcomes
    cleanup_passed = _cleanup_assessment(
        value.get("cleanup"),
        host=host,
        errors=errors,
    )
    cleanup_value = value.get("cleanup")
    cleanup_native_bindings = (
        cleanup_value.get("native_evidence_bindings")
        if isinstance(cleanup_value, dict)
        else None
    )
    if (
        observer_cleanup_observation is None
        or not isinstance(cleanup_value, dict)
        or observer_cleanup_observation.get("cleanup_sha256")
        != canonical_sha256(cleanup_value)
        or observer_cleanup_observation.get("clock_evidence_binding") != common_clock
        or not isinstance(cleanup_native_bindings, list)
        or observer_cleanup_observation.get("native_evidence_binding")
        not in cleanup_native_bindings
    ):
        errors.append("cleanup bytes do not match the independent observer receipt")
    elif observer_cleanup_observation is not None:
        try:
            sealed_started_at = _parse_utc(
                observer_cleanup_observation.get("stage_started_at"),
                field_name="observer cleanup stage_started_at",
            )
            sealed_terminal_at = _parse_utc(
                observer_cleanup_observation.get("terminal_observed_at"),
                field_name="observer cleanup terminal_observed_at",
            )
            sealed_cleanup_at = _parse_utc(
                observer_cleanup_observation.get("cleanup_completed_at"),
                field_name="observer cleanup cleanup_completed_at",
            )
            if (
                sealed_started_at != started_at
                or sealed_terminal_at != terminal_at
                or sealed_cleanup_at != cleanup_at
            ):
                errors.append(
                    "result lifecycle timestamps do not match the independent "
                    "observer receipt"
                )
        except CapacityValidationError as error:
            errors.append(str(error))
    maximum_queue_wait_ns = max(queue_waits, default=0)
    maximum_ansible_service_ns = max(ansible_services, default=0)
    provisioning_queue_passed = bool(queue_waits) and (
        maximum_queue_wait_ns <= evaluation_policy.provisioning_queue_slo_ns
    )
    ansible_service_passed = bool(ansible_services) and (
        maximum_ansible_service_ns <= evaluation_policy.ansible_service_slo_ns
    )
    assessment = _expected_stage_assessment(
        outcomes_match=outcomes_match,
        maximum_latency_ns=maximum_latency_ns,
        maximum_overlap=maximum_overlap,
        physical_gpu_count=physical_gpu_count,
        provisioning_queue_passed=provisioning_queue_passed,
        ansible_service_passed=ansible_service_passed,
        cleanup_passed=cleanup_passed,
        load_generator_passed=load_generator_passed,
        execution_boundary=boundary,
        policy=evaluation_policy,
    )
    if value.get("stage_assessment") != assessment:
        errors.append(
            "stage assessment must equal independently derived outcome predicates"
        )
    if boundary == "real-measured":
        actor_counts = scenario.get("actor_counts")
        buyer_count = (
            actor_counts.get("buyers") if isinstance(actor_counts, dict) else 0
        )
        frontier = _expected_frontier_observation(
            buyer_count=buyer_count,
            maximum_latency_ns=maximum_latency_ns,
            maximum_overlap=maximum_overlap,
            maximum_queue_wait_ns=maximum_queue_wait_ns,
            maximum_ansible_service_ns=maximum_ansible_service_ns,
            assessment=assessment,
            policy=evaluation_policy,
        )
        if value.get("frontier_observation") != frontier:
            errors.append(
                "measured frontier observation was not derived from result evidence"
            )
    elif value.get("frontier_observation") is not None:
        errors.append(
            "reference and qualification results cannot claim measured frontiers"
        )

    predecessor_value = value.get("reuse_predecessor")
    try:
        _validate_buyer_frontier_authority(
            value,
            started_at=started_at,
            buyer_frontier=buyer_frontier,
            predecessor=predecessor,
        )
    except CapacityValidationError as error:
        errors.append(str(error))
    if value.get("scenario_id") == "serialized-reuse-b":
        if predecessor is None:
            errors.append("reuse B requires its exact validated reuse A result")
        else:
            try:
                _validate_reuse_authority(predecessor, value, predecessor_value)
            except CapacityValidationError as error:
                errors.append(str(error))
    elif predecessor is not None or predecessor_value is not None:
        errors.append("only serialized reuse B may bind a predecessor result")
    try:
        _validate_seller_progression_authority(
            value,
            started_at=started_at,
            buyer_frontier=buyer_frontier,
            reuse_baseline=reuse_baseline,
            prior_seller_results=prior_seller_results,
        )
    except CapacityValidationError as error:
        errors.append(str(error))

    _raise_errors("capacity result", errors)
    assert stage is not None
    return ValidatedCapacityResult(
        result_id=value["result_id"],
        scm_ref=scm_ref,
        profile_stage_id=stage.stage_id,
        profile_stage_sha256=stage.canonical_sha256,
        scenario_id=value["scenario_id"],
        scenario_sha256=value["scenario_sha256"],
        execution_boundary=boundary,
        actor_trigger=value["actor_trigger"],
        canonical_sha256=canonical_sha256(value),
        started_at=started_at,
        terminal_observed_at=terminal_at,
        cleanup_completed_at=cleanup_at,
        progression_ready_at=declared_progression_ready_at,
        request_processing_passed=assessment["request_processing_passed"],
        simultaneous_fulfillment_count=maximum_overlap,
        provisioning_passed=assessment["provisioning_passed"],
        correctness_passed=assessment["correctness_passed"],
        load_generator_passed=assessment["load_generator_passed"],
        cleanup_passed=assessment["cleanup_passed"],
        stage_passed=assessment["stage_passed"],
        agent_capacity_evidence=assessment["agent_capacity_evidence"],
        eligible_for_capacity_frontier=assessment["eligible_for_capacity_frontier"],
        derived_faults=tuple(assessment["derived_faults"]),
        outcome_kinds=tuple(outcome_kinds),
        admitted_seller_identities=admitted_seller_identities,
        admitted_service_instances=admitted_service_instances,
        repo_root=root,
        _canonical_bytes=canonical_json_bytes(value),
        _validation_token=_VALIDATED_CAPACITY_RESULT_TOKEN,
    )


def require_validated_capacity_result(
    result: ValidatedCapacityResult,
) -> dict[str, Any]:
    if (
        not isinstance(result, ValidatedCapacityResult)
        or result._validation_token is not _VALIDATED_CAPACITY_RESULT_TOKEN
    ):
        raise CapacityValidationError("operation requires a validated capacity result")
    if canonical_sha256(result.result) != result.canonical_sha256:
        raise CapacityValidationError(
            "capacity-result snapshot changed after validation"
        )
    return result.result


def _first_request_outcome(value: Mapping[str, Any]) -> dict[str, Any]:
    outcomes = value.get("request_outcomes")
    if (
        not isinstance(outcomes, list)
        or len(outcomes) != 1
        or not isinstance(outcomes[0], dict)
    ):
        raise CapacityValidationError(
            "serialized reuse requires exactly one request outcome"
        )
    return outcomes[0]


def _validate_reuse_authority(
    predecessor: ValidatedCapacityResult,
    current_value: Mapping[str, Any],
    predecessor_value: object,
) -> None:
    prior = require_validated_capacity_result(predecessor)
    errors: list[str] = []
    if predecessor.scenario_id != "serialized-reuse-a":
        errors.append("reuse B predecessor must be serialized reuse A")
    if current_value.get("scenario_id") != "serialized-reuse-b":
        errors.append("reuse predecessor is valid only for serialized reuse B")
    if predecessor.result_id == current_value.get("result_id"):
        errors.append("serialized reuse A and B must use distinct result IDs")
    if predecessor.scm_ref != current_value.get("scm_ref"):
        errors.append("serialized reuse stages must bind one SCM ref")
    if predecessor.execution_boundary != current_value.get("execution_boundary"):
        errors.append("serialized reuse stages must use one execution boundary")
    if predecessor.actor_trigger != current_value.get("actor_trigger"):
        errors.append("serialized reuse stages must use one actor trigger")
    if (
        predecessor.cleanup_passed is not True
        or predecessor.correctness_passed is not True
        or predecessor.outcome_kinds != ("vm-succeeded",)
    ):
        errors.append(
            "reuse A must prove one correct successful lifecycle, teardown, "
            "and baseline equivalence before B"
        )
    if prior.get("evaluation_policy") != current_value.get("evaluation_policy"):
        errors.append("serialized reuse stages must bind one evaluation policy")
    if prior.get("topology_authority_binding") != current_value.get(
        "topology_authority_binding"
    ):
        errors.append("serialized reuse stages must bind one topology authority")
    try:
        current_started = _parse_utc(
            current_value.get("started_at"),
            field_name="reuse B started_at",
        )
    except CapacityValidationError as error:
        errors.append(str(error))
    else:
        if current_started <= predecessor.progression_ready_at:
            errors.append(
                "reuse B must start strictly after reuse A clean verification"
            )

    prior_cleanup = prior.get("cleanup")
    current_cleanup = current_value.get("cleanup")
    if not isinstance(prior_cleanup, dict) or not isinstance(current_cleanup, dict):
        errors.append("serialized reuse requires complete cleanup authorities")
    else:
        if prior_cleanup.get("reversible_baseline_binding") != current_cleanup.get(
            "reversible_baseline_binding"
        ):
            errors.append("serialized reuse A and B must bind one baseline")
    expected_predecessor = {
        "result_id": predecessor.result_id,
        "result_sha256": predecessor.canonical_sha256,
        "progression_ready_at": prior.get("progression_ready_at"),
        "baseline_equivalence_binding": (
            prior_cleanup.get("baseline_equivalence_binding")
            if isinstance(prior_cleanup, dict)
            else None
        ),
    }
    if predecessor_value != expected_predecessor:
        errors.append("reuse B does not bind the exact reuse A result and baseline")

    prior_outcome = _first_request_outcome(prior)
    current_outcome = _first_request_outcome(current_value)
    if (
        prior_outcome.get("outcome_kind") != "vm-succeeded"
        or current_outcome.get("outcome_kind") != "vm-succeeded"
    ):
        errors.append("serialized reuse A and B must each be successful lifecycles")
    if canonical_sha256(prior_outcome.get("deal_reference", {})) == canonical_sha256(
        current_outcome.get("deal_reference", {})
    ):
        errors.append("reuse B must create a distinct deal reference")
    for field_name in (
        "capacity_reservation_id",
        "fulfillment_id",
        "provisioned_resource_id",
    ):
        prior_id = prior_outcome.get(field_name)
        current_id = current_outcome.get(field_name)
        if prior_id is None or current_id is None or prior_id == current_id:
            errors.append(f"reuse B must create a distinct {field_name}")
    for field_name in (
        "negotiation_reference_sha256",
        "escrow_reference_sha256",
    ):
        prior_deal = prior_outcome.get("deal_reference")
        current_deal = current_outcome.get("deal_reference")
        if (
            not isinstance(prior_deal, dict)
            or not isinstance(current_deal, dict)
            or prior_deal.get(field_name) is None
            or prior_deal.get(field_name) == current_deal.get(field_name)
        ):
            errors.append(f"reuse B must create a distinct {field_name}")
    _raise_errors("serialized reuse", errors)


def validate_serialized_reuse(
    reuse_a: ValidatedCapacityResult,
    reuse_b: ValidatedCapacityResult,
) -> None:
    current = require_validated_capacity_result(reuse_b)
    _validate_reuse_authority(
        reuse_a,
        current,
        current.get("reuse_predecessor"),
    )
    if (
        reuse_b.cleanup_passed is not True
        or reuse_b.correctness_passed is not True
        or reuse_b.outcome_kinds != ("vm-succeeded",)
    ):
        raise CapacityValidationError(
            "reuse B must prove one correct lifecycle and restore the "
            "declared baseline before reuse passes"
        )


def _buyer_stage_count(stage_id: str) -> int:
    match = _BUYER_STAGE_RE.fullmatch(stage_id)
    if match is None:
        raise CapacityValidationError(f"not a measured S1 buyer stage: {stage_id}")
    return int(match.group(1))


def _pure_request_processing_passed(
    result: ValidatedCapacityResult,
    policy: ValidatedEvaluationPolicy,
) -> bool:
    value = require_validated_capacity_result(result)
    assessment = value["stage_assessment"]
    frontier = value["frontier_observation"]
    return bool(
        assessment["outcomes_match_expected"]
        and isinstance(frontier, dict)
        and frontier["request_processing"]["observed_max_ns"]
        <= policy.request_processing_slo_ns
        and frontier["request_processing"]["observed_max_ns"]
        < policy.terminal_observation_timeout_ns
    )


def _product_progression_passed(
    result: ValidatedCapacityResult,
    policy: ValidatedEvaluationPolicy,
) -> bool:
    return bool(
        _pure_request_processing_passed(result, policy)
        and result.provisioning_passed
        and result.correctness_passed
    )


def _derived_shape_frontier(
    results: Sequence[ValidatedCapacityResult],
    *,
    passed: Mapping[int, bool],
    load_is_censor: bool = True,
) -> dict[str, Any]:
    load_by_count = {
        result.buyer_count: result.load_generator_passed for result in results
    }
    observed_counts = sorted(load_by_count)
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
            for count, is_passing in load_by_count.items()
            if count > greatest and not is_passing
        )
        if load_is_censor
        else []
    )
    if not load_is_censor and valid_failures:
        reason = "load-generator-ended-first"
    elif generator_failures:
        reason = "load-generator-ended-first"
    elif greatest == 8 and greatest == max(observed_counts):
        reason = "frozen-envelope-ended"
    elif valid_failures:
        # A non-adjacent per-frontier failure was observed, but this frontier
        # was not the progression predicate and therefore was not refined.
        reason = "frozen-envelope-ended"
    else:
        reason = "frozen-envelope-ended"
    return {
        "greatest_passing_buyer_count": greatest,
        "classification": "lower-bound",
        "limit_reason": reason,
    }


def _expected_buyer_frontier(
    results: Sequence[ValidatedCapacityResult],
    policy: ValidatedEvaluationPolicy,
) -> tuple[
    tuple[str, ...],
    tuple[int, ...],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
]:
    by_stage = {result.profile_stage_id: result for result in results}
    if len(by_stage) != len(results):
        raise CapacityValidationError(
            "buyer frontier cannot contain duplicate profile stages"
        )
    missing_initial = [
        stage_id for stage_id in INITIAL_BUYER_STAGES if stage_id not in by_stage
    ]
    if missing_initial:
        raise CapacityValidationError(
            f"buyer frontier is missing initial stage {missing_initial[0]}"
        )

    product_passes = {
        result.buyer_count: _product_progression_passed(result, policy)
        for result in results
    }
    load_passes = {
        result.buyer_count: result.load_generator_passed for result in results
    }
    initial_generator_failure = any(
        not by_stage[stage_id].load_generator_passed
        for stage_id in INITIAL_BUYER_STAGES
    )
    if initial_generator_failure:
        expected_refinement: tuple[str, ...] = ()
        censored = True
    else:
        stage_passes = {
            stage_id: _product_progression_passed(result, policy)
            for stage_id, result in by_stage.items()
            if result.load_generator_passed
        }
        selected_counts = select_buyer_refinement_counts(stage_passes)
        expected_refinement = tuple(
            f"b{count}-s1-g1-measured" for count in selected_counts
        )
        censored = any(
            stage_id in by_stage and not by_stage[stage_id].load_generator_passed
            for stage_id in expected_refinement
        )
    actual_refinement = tuple(result.profile_stage_id for result in results[4:])
    if actual_refinement != expected_refinement:
        raise CapacityValidationError(
            "buyer refinement does not follow frozen integer bisection"
        )

    clean_counts = sorted(
        count
        for count in product_passes
        if product_passes[count] and load_passes[count]
    )
    if censored:
        retained = tuple(clean_counts[-3:])
    else:
        stage_passes = {
            result.profile_stage_id: product_passes[result.buyer_count]
            for result in results
        }
        retained = retained_buyer_refinement_counts(stage_passes)

    observations = [
        {
            "profile_stage_id": result.profile_stage_id,
            "buyer_count": result.buyer_count,
            "request_processing_passed": _pure_request_processing_passed(
                result,
                policy,
            ),
            "provisioning_passed": result.provisioning_passed,
            "correctness_passed": result.correctness_passed,
            "load_generator_passed": result.load_generator_passed,
            "progression_passed": (
                product_passes[result.buyer_count] and load_passes[result.buyer_count]
            ),
        }
        for result in results
    ]
    request_passes = {
        result.buyer_count: _pure_request_processing_passed(result, policy)
        for result in results
    }
    provisioning_passes = {
        result.buyer_count: result.provisioning_passed for result in results
    }
    correctness_passes = {
        result.buyer_count: result.correctness_passed for result in results
    }
    frontier_value = {
        "request_processing": _derived_shape_frontier(
            results,
            passed=request_passes,
        ),
        "simultaneous_fulfillment": {
            "maximum_whole_gpu_vms": max(
                (result.simultaneous_fulfillment_count for result in results),
                default=0,
            ),
            "classification": "exact-observation",
        },
        "provisioning": _derived_shape_frontier(
            results,
            passed=provisioning_passes,
        ),
        "correctness": _derived_shape_frontier(
            results,
            passed=correctness_passes,
        ),
        "load_generator": _derived_shape_frontier(
            results,
            passed=load_passes,
            load_is_censor=False,
        ),
    }

    largest_clean = max(clean_counts, default=0)
    product_failures = sorted(
        count
        for count, passes in product_passes.items()
        if not passes and load_passes[count]
    )
    if not clean_counts:
        classification = "no-clean-shape"
        lower_bound_reason = None
    elif censored:
        classification = "lower-bound"
        lower_bound_reason = "load-generator-ended-first"
    else:
        higher_product_failures = [
            count for count in product_failures if count > largest_clean
        ]
        if (
            higher_product_failures
            and min(higher_product_failures) == largest_clean + 1
        ):
            classification = "exact-bound"
            lower_bound_reason = None
        else:
            classification = "lower-bound"
            lower_bound_reason = "frozen-envelope-ended"
    progression = {
        "selection_predicate": (
            "request-processing-and-provisioning-and-correctness-"
            "with-load-generator-censoring"
        ),
        "largest_clean_buyer_count": largest_clean,
        "classification": classification,
        "lower_bound_reason": lower_bound_reason,
        "completed_before_reuse": True,
    }
    return (
        expected_refinement,
        retained,
        observations,
        frontier_value,
        progression,
    )


def validate_buyer_frontier_receipt(
    value: dict[str, Any],
    repo_root: Path,
    *,
    evaluation_policy: ValidatedEvaluationPolicy,
    results: Sequence[ValidatedCapacityResult],
    expected_scm_ref: str | None = None,
) -> ValidatedBuyerFrontierReceipt:
    policy_value = _require_policy(evaluation_policy)
    result_values = tuple(results)
    if len(result_values) < 4:
        raise CapacityValidationError(
            "buyer frontier requires B1, B2, B4, and B8 results"
        )
    for result in result_values:
        require_validated_capacity_result(result)
        if (
            result.repo_root != evaluation_policy.repo_root
            or result.scm_ref != evaluation_policy.scm_ref
            or result.execution_boundary != "real-measured"
            or result.actor_trigger != "agent-triggered"
            or _BUYER_STAGE_RE.fullmatch(result.profile_stage_id) is None
        ):
            raise CapacityValidationError(
                "buyer frontier accepts only one policy's measured S1 buyer results"
            )
        result_policy = result.result.get("evaluation_policy")
        if result_policy != {
            "evaluation_policy_id": evaluation_policy.policy_id,
            "evaluation_policy_sha256": evaluation_policy.canonical_sha256,
        }:
            raise CapacityValidationError(
                "buyer result does not bind the frontier evaluation policy"
            )
    topology_authorities = [
        result.result.get("topology_authority_binding") for result in result_values
    ]
    if len({_binding_identity(authority) for authority in topology_authorities}) != 1:
        raise CapacityValidationError(
            "buyer frontier results must bind one topology authority"
        )
    topology_authority = _require_binding(
        topology_authorities[0],
        domain=TOPOLOGY_BINDING_DOMAIN,
        field_name="buyer frontier topology_authority_binding",
    )
    expected_order_prefix = tuple(
        result.profile_stage_id for result in result_values[:4]
    )
    if expected_order_prefix != INITIAL_BUYER_STAGES:
        raise CapacityValidationError(
            "buyer frontier must begin with exact B1/B2/B4/B8 order"
        )
    result_ids = [result.result_id for result in result_values]
    if len(result_ids) != len(set(result_ids)):
        raise CapacityValidationError(
            "buyer frontier results must have distinct result IDs"
        )
    for prior, current in zip(
        result_values,
        result_values[1:],
    ):
        if prior.cleanup_passed is not True:
            raise CapacityValidationError(
                "buyer progression cannot advance after unclean state"
            )
        if current.started_at <= prior.progression_ready_at:
            raise CapacityValidationError(
                "buyer stages must start strictly after prior cleanup"
            )
    if result_values[-1].cleanup_passed is not True:
        raise CapacityValidationError(
            "buyer frontier cannot authorize reuse after unclean final state"
        )

    scm_ref = value.get("scm_ref")
    root = _validate_exact_commit(repo_root, scm_ref)
    assert isinstance(scm_ref, str)
    errors = _schema_errors(
        value,
        _load_pinned_schema(root, scm_ref, BUYER_FRONTIER_SCHEMA),
    )
    if expected_scm_ref is not None and scm_ref != expected_scm_ref:
        errors.append("buyer-frontier SCM ref does not match selected campaign ref")
    if root != evaluation_policy.repo_root or scm_ref != evaluation_policy.scm_ref:
        errors.append("buyer frontier and evaluation policy use different authority")
    registry = resolve_pinned_profile_registry(root, scm_ref)
    expected_registry = {
        "path": CAPACITY_PROFILE_PATH.as_posix(),
        "canonical_sha256": registry.canonical_sha256,
        "raw_sha256": registry.raw_sha256,
    }
    if value.get("profile_registry") != expected_registry:
        errors.append("buyer frontier does not bind the pinned profile registry")
    if value.get("evaluation_policy") != {
        "evaluation_policy_id": evaluation_policy.policy_id,
        "evaluation_policy_sha256": evaluation_policy.canonical_sha256,
    }:
        errors.append("buyer frontier does not bind the evaluation policy")
    if value.get("clock_evidence_binding") != policy_value.get(
        "clock_evidence_binding"
    ):
        errors.append(
            "buyer frontier clock does not match the evaluation-policy campaign clock"
        )
    if value.get("topology_authority_binding") != topology_authority:
        errors.append(
            "buyer frontier does not bind the results' exact topology authority"
        )
    expected_results = [
        {
            "profile_stage_id": result.profile_stage_id,
            "result_id": result.result_id,
            "result_sha256": result.canonical_sha256,
        }
        for result in result_values
    ]
    if value.get("ordered_results") != expected_results:
        errors.append("buyer frontier does not bind exact ordered results")
    if value.get("initial_stage_ids") != list(INITIAL_BUYER_STAGES):
        errors.append("buyer frontier initial stages are not exact")
    try:
        (
            refinements,
            retained,
            observations,
            frontiers,
            progression,
        ) = _expected_buyer_frontier(result_values, evaluation_policy)
    except CapacityValidationError as error:
        errors.append(str(error))
        refinements = ()
        retained = ()
        observations = []
        frontiers = {}
        progression = {}
    expected_fields = {
        "refinement_stage_ids": list(refinements),
        "retained_buyer_counts": list(retained),
        "stage_observations": observations,
        "frontiers": frontiers,
        "progression": progression,
    }
    for field_name, expected in expected_fields.items():
        if value.get(field_name) != expected:
            errors.append(f"buyer frontier {field_name} is not independently derived")
    try:
        completed_at = _parse_utc(
            value.get("completed_at"),
            field_name="buyer frontier completed_at",
        )
        if completed_at <= max(result.progression_ready_at for result in result_values):
            errors.append("buyer frontier must complete after every bound result")
    except CapacityValidationError as error:
        errors.append(str(error))
        completed_at = datetime.min.replace(tzinfo=UTC)
    _raise_errors("buyer frontier receipt", errors)
    return ValidatedBuyerFrontierReceipt(
        frontier_receipt_id=value["frontier_receipt_id"],
        scm_ref=scm_ref,
        evaluation_policy_sha256=evaluation_policy.canonical_sha256,
        ordered_result_sha256s=tuple(
            result.canonical_sha256 for result in result_values
        ),
        correctness_frontier=frontiers["correctness"]["greatest_passing_buyer_count"],
        load_generator_frontier=frontiers["load_generator"][
            "greatest_passing_buyer_count"
        ],
        largest_clean_buyer_count=progression["largest_clean_buyer_count"],
        classification=progression["classification"],
        canonical_sha256=canonical_sha256(value),
        completed_at=completed_at,
        _canonical_bytes=canonical_json_bytes(value),
        _validation_token=_VALIDATED_BUYER_FRONTIER_TOKEN,
    )


def require_validated_buyer_frontier(
    receipt: ValidatedBuyerFrontierReceipt,
) -> dict[str, Any]:
    if (
        not isinstance(receipt, ValidatedBuyerFrontierReceipt)
        or receipt._validation_token is not _VALIDATED_BUYER_FRONTIER_TOKEN
    ):
        raise CapacityValidationError(
            "seller scaling requires a validated buyer-frontier receipt"
        )
    return receipt.receipt


def _validate_buyer_frontier_authority(
    result_value: Mapping[str, Any],
    *,
    started_at: datetime,
    buyer_frontier: ValidatedBuyerFrontierReceipt | None,
    predecessor: ValidatedCapacityResult | None,
) -> None:
    scenario_id = result_value.get("scenario_id")
    measured = result_value.get("execution_boundary") == "real-measured"
    authority = result_value.get("buyer_frontier_authority")
    if not measured or scenario_id not in {
        "serialized-reuse-a",
        "serialized-reuse-b",
    }:
        if authority is not None:
            raise CapacityValidationError(
                "only measured serialized reuse may bind buyer-frontier authority"
            )
        if (
            buyer_frontier is not None
            and result_value.get("profile_stage_id") not in SELLER_MEASURED_STAGES
        ):
            raise CapacityValidationError(
                "buyer-frontier context is only valid for reuse A or seller stages"
            )
        return
    if scenario_id == "serialized-reuse-b":
        if predecessor is None:
            raise CapacityValidationError(
                "serialized reuse B requires validated reuse A frontier lineage"
            )
        prior = require_validated_capacity_result(predecessor)
        if authority != prior.get("buyer_frontier_authority"):
            raise CapacityValidationError(
                "serialized reuse B does not preserve reuse A buyer-frontier lineage"
            )
        if result_value.get("topology_authority_binding") != prior.get(
            "topology_authority_binding"
        ):
            raise CapacityValidationError(
                "serialized reuse B does not preserve reuse A topology authority"
            )
        return
    if buyer_frontier is None:
        raise CapacityValidationError(
            "serialized reuse A requires a validated buyer-frontier receipt"
        )
    require_validated_buyer_frontier(buyer_frontier)
    result_policy = result_value.get("evaluation_policy")
    if (
        result_value.get("scm_ref") != buyer_frontier.scm_ref
        or not isinstance(result_policy, Mapping)
        or result_policy.get("evaluation_policy_sha256")
        != buyer_frontier.evaluation_policy_sha256
    ):
        raise CapacityValidationError(
            "serialized reuse A does not match buyer-frontier authority"
        )
    expected = {
        "buyer_frontier_receipt_id": buyer_frontier.frontier_receipt_id,
        "buyer_frontier_receipt_sha256": buyer_frontier.canonical_sha256,
    }
    if authority != expected:
        raise CapacityValidationError(
            "serialized reuse A does not bind the exact buyer-frontier receipt"
        )
    if (
        result_value.get("topology_authority_binding")
        != buyer_frontier.topology_authority_binding
    ):
        raise CapacityValidationError(
            "serialized reuse A does not preserve buyer-frontier topology authority"
        )
    if started_at <= buyer_frontier.completed_at:
        raise CapacityValidationError(
            "serialized reuse A must start strictly after the buyer frontier"
        )


def _validate_seller_progression_authority(
    result_value: Mapping[str, Any],
    *,
    started_at: datetime,
    buyer_frontier: ValidatedBuyerFrontierReceipt | None,
    reuse_baseline: ValidatedCapacityResult | None,
    prior_seller_results: Sequence[ValidatedCapacityResult],
) -> None:
    stage_id = result_value.get("profile_stage_id")
    authority = result_value.get("seller_progression_authority")
    prior_results = tuple(prior_seller_results)
    if stage_id not in SELLER_MEASURED_STAGES:
        if authority is not None or reuse_baseline is not None or prior_results:
            raise CapacityValidationError(
                "only measured seller stages may bind seller progression"
            )
        return
    if buyer_frontier is None:
        raise CapacityValidationError(
            "measured seller result requires a validated buyer frontier"
        )
    require_validated_buyer_frontier(buyer_frontier)
    if reuse_baseline is None:
        raise CapacityValidationError(
            "measured seller result requires validated serialized reuse B"
        )
    require_validated_capacity_result(reuse_baseline)
    if (
        reuse_baseline.scenario_id != "serialized-reuse-b"
        or reuse_baseline.scm_ref != buyer_frontier.scm_ref
        or reuse_baseline.cleanup_passed is not True
        or reuse_baseline.correctness_passed is not True
        or reuse_baseline.outcome_kinds != ("vm-succeeded",)
    ):
        raise CapacityValidationError(
            "seller progression requires correct, clean serialized reuse B"
        )
    reuse_policy = reuse_baseline.result.get("evaluation_policy")
    reuse_frontier = reuse_baseline.result.get("buyer_frontier_authority")
    reuse_topology = reuse_baseline.result.get("topology_authority_binding")
    expected_frontier = {
        "buyer_frontier_receipt_id": buyer_frontier.frontier_receipt_id,
        "buyer_frontier_receipt_sha256": buyer_frontier.canonical_sha256,
    }
    if (
        not isinstance(reuse_policy, Mapping)
        or reuse_policy.get("evaluation_policy_sha256")
        != buyer_frontier.evaluation_policy_sha256
        or reuse_frontier != expected_frontier
        or reuse_topology != buyer_frontier.topology_authority_binding
    ):
        raise CapacityValidationError(
            "serialized reuse B does not match buyer-frontier authority"
        )
    if not isinstance(authority, Mapping):
        raise CapacityValidationError(
            "measured seller result lacks seller progression authority"
        )
    result_policy = result_value.get("evaluation_policy")
    if (
        result_value.get("scm_ref") != buyer_frontier.scm_ref
        or not isinstance(result_policy, Mapping)
        or result_policy.get("evaluation_policy_sha256")
        != buyer_frontier.evaluation_policy_sha256
        or result_value.get("topology_authority_binding") != reuse_topology
    ):
        raise CapacityValidationError(
            "seller result does not match buyer-frontier authority"
        )
    distinct_sellers = reuse_baseline.admitted_seller_identities
    distinct_services = reuse_baseline.admitted_service_instances
    current_result_id = result_value.get("result_id")
    lineage_result_ids = {
        reuse_baseline.result_id,
        *(result.result_id for result in prior_results),
    }
    if current_result_id in lineage_result_ids:
        raise CapacityValidationError("seller progression must use distinct result IDs")
    if type(distinct_sellers) is not int or type(distinct_services) is not int:
        raise CapacityValidationError(
            "seller progression requires host-attested topology cardinalities"
        )
    selected = select_seller_stages_from_results(
        buyer_frontier,
        reuse_baseline=reuse_baseline,
        seller_results=prior_results,
    )
    next_index = len(prior_results)
    if next_index >= len(selected) or selected[next_index] != stage_id:
        raise CapacityValidationError(
            "seller result stage was not the next admitted progression stage"
        )
    prior = prior_results[-1] if prior_results else None
    expected = {
        "buyer_frontier_receipt_id": (buyer_frontier.frontier_receipt_id),
        "buyer_frontier_receipt_sha256": (buyer_frontier.canonical_sha256),
        "reuse_baseline_result_id": reuse_baseline.result_id,
        "reuse_baseline_result_sha256": reuse_baseline.canonical_sha256,
        "prior_seller_result_id": (prior.result_id if prior is not None else None),
        "prior_seller_result_sha256": (
            prior.canonical_sha256 if prior is not None else None
        ),
        "distinct_seller_identities": distinct_sellers,
        "distinct_service_instances": distinct_services,
    }
    if dict(authority) != expected:
        raise CapacityValidationError(
            "seller result does not bind the exact frontier, topology, and "
            "prior seller result"
        )
    fence_time = (
        prior.progression_ready_at
        if prior is not None
        else reuse_baseline.progression_ready_at
    )
    if started_at <= fence_time:
        raise CapacityValidationError(
            "seller result must start strictly after its progression fence"
        )


def select_seller_stages_from_results(
    buyer_frontier: ValidatedBuyerFrontierReceipt,
    *,
    reuse_baseline: ValidatedCapacityResult,
    seller_results: Sequence[ValidatedCapacityResult] = (),
) -> tuple[str, ...]:
    require_validated_buyer_frontier(buyer_frontier)
    require_validated_capacity_result(reuse_baseline)
    if (
        reuse_baseline.scenario_id != "serialized-reuse-b"
        or reuse_baseline.scm_ref != buyer_frontier.scm_ref
        or reuse_baseline.cleanup_passed is not True
        or reuse_baseline.correctness_passed is not True
        or reuse_baseline.outcome_kinds != ("vm-succeeded",)
    ):
        raise CapacityValidationError(
            "seller selection requires correct, clean serialized reuse B"
        )
    if (
        type(reuse_baseline.admitted_seller_identities) is not int
        or type(reuse_baseline.admitted_service_instances) is not int
    ):
        raise CapacityValidationError(
            "seller selection requires host-attested topology cardinalities"
        )
    reuse_policy = reuse_baseline.result.get("evaluation_policy")
    reuse_frontier = reuse_baseline.result.get("buyer_frontier_authority")
    reuse_topology = reuse_baseline.result.get("topology_authority_binding")
    if (
        not isinstance(reuse_policy, Mapping)
        or reuse_policy.get("evaluation_policy_sha256")
        != buyer_frontier.evaluation_policy_sha256
        or reuse_frontier
        != {
            "buyer_frontier_receipt_id": (buyer_frontier.frontier_receipt_id),
            "buyer_frontier_receipt_sha256": (buyer_frontier.canonical_sha256),
        }
        or reuse_topology != buyer_frontier.topology_authority_binding
    ):
        raise CapacityValidationError(
            "seller selection reuse baseline does not match buyer frontier"
        )
    stage_passes: dict[str, bool] = {}
    ordered_stage_ids: list[str] = []
    seen_result_ids = {reuse_baseline.result_id}
    previous_result: ValidatedCapacityResult | None = None
    for result in seller_results:
        require_validated_capacity_result(result)
        if result.result_id in seen_result_ids:
            raise CapacityValidationError(
                "seller progression must use distinct result IDs"
            )
        seen_result_ids.add(result.result_id)
        if (
            result.scm_ref != buyer_frontier.scm_ref
            or result.result.get("evaluation_policy", {}).get(
                "evaluation_policy_sha256"
            )
            != buyer_frontier.evaluation_policy_sha256
            or result.execution_boundary != "real-measured"
            or result.profile_stage_id
            not in {
                "b2-s2-g1-measured",
                "b4-s2-g1-measured",
                "b4-s3-g1-measured",
                "b4-s4-g1-measured",
            }
            or result.result.get("topology_authority_binding") != reuse_topology
        ):
            raise CapacityValidationError(
                "seller progression result does not match buyer-frontier authority"
            )
        seller_authority = result.result.get("seller_progression_authority")
        expected_seller_authority = {
            "buyer_frontier_receipt_id": buyer_frontier.frontier_receipt_id,
            "buyer_frontier_receipt_sha256": (buyer_frontier.canonical_sha256),
            "reuse_baseline_result_id": reuse_baseline.result_id,
            "reuse_baseline_result_sha256": reuse_baseline.canonical_sha256,
            "prior_seller_result_id": (
                previous_result.result_id if previous_result is not None else None
            ),
            "prior_seller_result_sha256": (
                previous_result.canonical_sha256
                if previous_result is not None
                else None
            ),
            "distinct_seller_identities": (reuse_baseline.admitted_seller_identities),
            "distinct_service_instances": (reuse_baseline.admitted_service_instances),
        }
        if (
            not isinstance(seller_authority, Mapping)
            or dict(seller_authority) != expected_seller_authority
        ):
            raise CapacityValidationError(
                "seller progression result does not bind its exact frontier, "
                "reuse baseline, topology, and prior result"
            )
        if result.profile_stage_id in stage_passes:
            raise CapacityValidationError(
                "seller progression cannot contain duplicate stage results"
            )
        if previous_result is None:
            if result.started_at <= reuse_baseline.progression_ready_at:
                raise CapacityValidationError(
                    "seller scaling must start after serialized reuse B cleanup"
                )
        else:
            if previous_result.cleanup_passed is not True:
                raise CapacityValidationError(
                    "seller scaling cannot advance after unclean state"
                )
            if result.started_at <= previous_result.progression_ready_at:
                raise CapacityValidationError(
                    "seller stages must be ordered after prior cleanup"
                )
        stage_passes[result.profile_stage_id] = result.stage_passed
        ordered_stage_ids.append(result.profile_stage_id)
        previous_result = result
    selected = select_seller_stage_ids(
        buyer_frontier_receipt_sha256=buyer_frontier.canonical_sha256,
        buyer_correctness_frontier=buyer_frontier.correctness_frontier,
        load_generator_frontier=buyer_frontier.load_generator_frontier,
        distinct_seller_identities=(reuse_baseline.admitted_seller_identities),
        distinct_service_instances=(reuse_baseline.admitted_service_instances),
        stage_passes=stage_passes,
    )
    if tuple(ordered_stage_ids) != selected[: len(ordered_stage_ids)]:
        raise CapacityValidationError(
            "seller results do not follow the admitted progression order"
        )
    return selected
