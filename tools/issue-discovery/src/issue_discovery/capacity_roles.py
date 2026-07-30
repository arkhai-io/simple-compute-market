from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

from jsonschema import Draft202012Validator, FormatChecker

from issue_discovery.capacity import (
    CapacityValidationError,
    PinnedScenario,
    ValidatedProfileStage,
    _checked_pinned_worktree_blob,
    _run_git,
    _strict_json_object,
    _validate_repo_root,
    canonical_json_bytes,
    canonical_sha256,
    require_pinned_profile_stage,
    resolve_pinned_profile_stage,
)


ROLE_PLAN_SCHEMA = PurePosixPath(
    "tools/issue-discovery/schemas/capacity-role-plan.schema.json"
)
ROLE_RECEIPT_SCHEMA = PurePosixPath(
    "tools/issue-discovery/schemas/capacity-role-receipt.schema.json"
)
FROZEN_ACTION_SCHEMA = PurePosixPath(
    "tools/issue-discovery/schemas/capacity-frozen-action.schema.json"
)
ACTION_RESULT_SCHEMA = PurePosixPath(
    "tools/issue-discovery/schemas/capacity-action-result.schema.json"
)
PROFILE_STAGE_SCHEMA = PurePosixPath(
    "tools/issue-discovery/schemas/capacity-profile-stage.schema.json"
)
ACTOR_SET_SCHEMA = PurePosixPath(
    "tools/issue-discovery/schemas/capacity-actor-set.schema.json"
)
ACTION_PAYLOAD_SCHEMA = PurePosixPath(
    "tools/issue-discovery/schemas/capacity-action-payload.schema.json"
)
ORACLE_AUTHORITY_SCHEMA = PurePosixPath(
    "tools/issue-discovery/schemas/capacity-oracle-authority.schema.json"
)
CONCURRENCY_POLICY_SCHEMA = PurePosixPath(
    "tools/issue-discovery/schemas/capacity-concurrency-policy.schema.json"
)
MOCK_CAPTURE_SCHEMA = PurePosixPath(
    "tools/issue-discovery/schemas/capacity-mock-capture.schema.json"
)

RUNTIME_BINDING_DOMAIN = "scm.capacity.runtime-binding.v1"
TOPOLOGY_BINDING_DOMAIN = "scm.capacity.topology-authority.v1"
REVERSIBLE_BASELINE_BINDING_DOMAIN = "scm.capacity.reversible-baseline.v1"
BASELINE_EQUIVALENCE_BINDING_DOMAIN = "scm.capacity.baseline-equivalence.v1"
NATIVE_EVIDENCE_BINDING_DOMAIN = "scm.capacity.native-evidence.v1"
ACTOR_INVOCATION_BINDING_DOMAIN = "scm.capacity.actor-invocation.v1"
CONCRETE_PAYLOAD_BINDING_DOMAIN = "scm.capacity.concrete-payload.v1"

BUYER_INSTRUCTION_PATH = "docs/buyer-quickstart.md"
SELLER_INSTRUCTION_PATH = "docs/seller-quickstart.md"
HOST_OPERATOR_INSTRUCTION_PATH = (
    "tools/issue-discovery/instructions/capacity/host-operator.md"
)
OBSERVER_INSTRUCTION_PATH = (
    "tools/issue-discovery/instructions/capacity/observer.md"
)

CUDA_WRAPPER_PATH = "tools/issue-discovery/workloads/cuda/run-vector-add.sh"
CUDA_SOURCE_PATH = "tools/issue-discovery/workloads/cuda/vector_add.cu"
CUDA_SUCCESS_MARKER = "SCM_CUDA_VECTOR_ADD_OK"
CUDA_RESULT_CHECKSUM = (
    "98d4c5327244975c7c054483ef7a1a1d95645858abde350e5926dfaa3a265d7e"
)

BUYER_REQUEST_WRAPPER_PATH = (
    "tools/issue-discovery/wrappers/emit-buyer-request.sh"
)
SELLER_SERVICE_WRAPPER_PATH = (
    "tools/issue-discovery/wrappers/start-seller-service.sh"
)
SELLER_PUBLICATION_WRAPPER_PATH = (
    "tools/issue-discovery/wrappers/publish-listing.sh"
)

BUYER_PRE_RELEASE_STEPS = (
    "install-build",
    "wallet-preparation",
    "ssh-preparation",
    "endpoint-check",
    "balance-check",
    "listing-discovery",
    "request-preparation",
)
BUYER_GUEST_STEPS = ("guest-ssh-resume", "cuda-vector-add")
SELLER_STEPS = (
    "install-build",
    "configuration",
    "wallet-preparation",
    "publication-preparation",
    "service-start",
    "listing-publication",
    "observation-liveness",
)
HOST_OPERATOR_STEPS = (
    "instruction-inspection",
    "topology-authority",
    "reversible-baseline",
    "kvm-ansible-readiness",
    "observation-plan",
    "teardown-plan",
    "baseline-equivalence",
    "cleanup",
)
OBSERVER_STEPS = (
    "instruction-inspection",
    "independent-observation",
)

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ROLE_INSTRUCTION_PATHS = {
    "buyer": BUYER_INSTRUCTION_PATH,
    "seller": SELLER_INSTRUCTION_PATH,
    "host-operator": HOST_OPERATOR_INSTRUCTION_PATH,
    "observer": OBSERVER_INSTRUCTION_PATH,
}
_ACTION_WRAPPER_PATHS = {
    "buyer-request": BUYER_REQUEST_WRAPPER_PATH,
    "seller-service-start": SELLER_SERVICE_WRAPPER_PATH,
    "seller-listing-publication": SELLER_PUBLICATION_WRAPPER_PATH,
}
_ACTOR_COLLECTIONS = {
    "buyer": "buyers",
    "seller": "sellers",
    "host-operator": "host_operators",
    "observer": "observers",
}
_VALIDATED_ROLE_PLAN_TOKEN = object()
_VALIDATED_ORACLE_TOKEN = object()
_VALIDATED_ACTION_TOKEN = object()
_VALIDATED_RESULT_TOKEN = object()
_VALIDATED_RECEIPT_TOKEN = object()
_VALIDATED_POLICY_TOKEN = object()
_VALIDATED_ACTOR_SET_TOKEN = object()
_VALIDATED_MOCK_CAPTURE_TOKEN = object()


@dataclass(frozen=True, slots=True)
class ValidatedRolePlan:
    plan_id: str
    role: str
    actor_slot: str
    profile_stage_id: str
    profile_stage_sha256: str
    scenario_id: str | None
    scenario_sha256: str | None
    scm_ref: str
    canonical_sha256: str
    repo_root: Path
    profile_stage: ValidatedProfileStage = field(repr=False)
    _canonical_bytes: bytes = field(repr=False)
    _validation_token: object = field(repr=False, compare=False)

    @property
    def plan(self) -> dict[str, Any]:
        return _object_from_snapshot(self._canonical_bytes, "role plan")


@dataclass(frozen=True, slots=True)
class ValidatedFrozenAction:
    action_id: str
    action_kind: str
    actor_slot: str
    release_id: str
    scm_ref: str
    canonical_sha256: str
    repo_root: Path
    _canonical_bytes: bytes = field(repr=False)
    _validation_token: object = field(repr=False, compare=False)

    @property
    def action(self) -> dict[str, Any]:
        return _object_from_snapshot(self._canonical_bytes, "frozen action")


@dataclass(frozen=True, slots=True)
class ValidatedActionResult:
    action_result_id: str
    action_id: str
    actor_slot: str
    result_kind: str
    invoked_at: datetime
    terminal_at: datetime
    canonical_sha256: str
    _canonical_bytes: bytes = field(repr=False)
    _validation_token: object = field(repr=False, compare=False)

    @property
    def result(self) -> dict[str, Any]:
        return _object_from_snapshot(self._canonical_bytes, "action result")


@dataclass(frozen=True, slots=True)
class ValidatedRoleReceipt:
    receipt_id: str
    role: str
    actor_slot: str
    canonical_sha256: str
    started_at: datetime
    prepared_at: datetime
    barrier_observed_at: datetime
    completed_at: datetime
    _canonical_bytes: bytes = field(repr=False)
    _validation_token: object = field(repr=False, compare=False)

    @property
    def receipt(self) -> dict[str, Any]:
        return _object_from_snapshot(self._canonical_bytes, "role receipt")


@dataclass(frozen=True, slots=True)
class SubstantiveRoleEvidence:
    plan: ValidatedRolePlan
    receipt: ValidatedRoleReceipt
    actions: tuple[ValidatedFrozenAction, ...]
    results: tuple[ValidatedActionResult, ...]


@dataclass(frozen=True, slots=True)
class ValidatedActorSet:
    actor_set_id: str
    profile_stage_id: str
    scenario_id: str
    actor_slots: tuple[str, ...]
    runtime_service_bindings: tuple[dict[str, Any], ...]
    runtime_listing_bindings: tuple[dict[str, Any], ...]
    buyer_invocation_skew_ns: int
    publication_invocation_skew_ns: int
    concurrency_policy_sha256: str
    canonical_sha256: str
    _canonical_bytes: bytes = field(repr=False)
    _validation_token: object = field(repr=False, compare=False)

    @property
    def actor_set(self) -> dict[str, Any]:
        return _object_from_snapshot(self._canonical_bytes, "actor set")


@dataclass(frozen=True, slots=True)
class ValidatedOracleAuthority:
    oracle_authority_id: str
    scm_ref: str
    profile_stage_id: str
    canonical_sha256: str
    repo_root: Path
    _canonical_bytes: bytes = field(repr=False)
    _validation_token: object = field(repr=False, compare=False)

    @property
    def authority(self) -> dict[str, Any]:
        return _object_from_snapshot(
            self._canonical_bytes,
            "oracle authority",
        )


@dataclass(frozen=True, slots=True)
class ValidatedConcurrencyPolicy:
    policy_id: str
    scm_ref: str
    profile_stage_id: str
    release_id: str
    canonical_sha256: str
    repo_root: Path
    frozen_at: datetime
    _canonical_bytes: bytes = field(repr=False)
    _validation_token: object = field(repr=False, compare=False)

    @property
    def policy(self) -> dict[str, Any]:
        return _object_from_snapshot(
            self._canonical_bytes,
            "concurrency policy",
        )


@dataclass(frozen=True, slots=True)
class ValidatedMockCapture:
    capture_id: str
    scm_ref: str
    canonical_sha256: str
    _canonical_bytes: bytes = field(repr=False)
    _validation_token: object = field(repr=False, compare=False)

    @property
    def capture(self) -> dict[str, Any]:
        return _object_from_snapshot(self._canonical_bytes, "mock capture")


@dataclass(frozen=True, slots=True)
class CapturedMockAction:
    """Owner-only capture result produced by one agent-invoked mock action."""

    result: ValidatedActionResult
    record_path: Path | None
    result_path: Path
    recovered: bool


def _object_from_snapshot(content: bytes, label: str) -> dict[str, Any]:
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict):
        raise CapacityValidationError(f"validated {label} snapshot is not an object")
    return value


def _raise_errors(label: str, errors: Iterable[str]) -> None:
    unique = list(dict.fromkeys(errors))
    if unique:
        raise CapacityValidationError(
            f"{label} validation failed:\n- " + "\n- ".join(unique)
        )


def _validate_exact_commit(repo_root: Path, scm_ref: object) -> Path:
    root = _validate_repo_root(repo_root)
    if not isinstance(scm_ref, str) or not _COMMIT_RE.fullmatch(scm_ref):
        raise CapacityValidationError(
            "SCM ref must be an exact lowercase 40-character commit"
        )
    object_type = _run_git(root, "cat-file", "-t", scm_ref).decode("ascii").strip()
    if object_type != "commit":
        raise CapacityValidationError("SCM ref must identify a Git commit")
    return root


def _load_pinned_schema(
    repo_root: Path,
    scm_ref: str,
    relative_path: PurePosixPath,
) -> dict[str, Any]:
    content = _checked_pinned_worktree_blob(repo_root, scm_ref, relative_path)
    return _strict_json_object(
        content,
        source=f"{scm_ref}:{relative_path.as_posix()}",
    )


def _schema_errors(
    value: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> list[str]:
    validator = Draft202012Validator(
        dict(schema),
        format_checker=FormatChecker(),
    )
    errors: list[str] = []
    for error in sorted(
        validator.iter_errors(value),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    ):
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        errors.append(f"{location}: {error.message}")
    return errors


def _normalized_relative_path(raw: object, *, field_name: str) -> PurePosixPath:
    if (
        not isinstance(raw, str)
        or not raw
        or "\0" in raw
        or "\\" in raw
    ):
        raise CapacityValidationError(
            f"{field_name} must be a non-empty repository-relative POSIX path"
        )
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or path.as_posix() != raw
        or "." in path.parts
        or ".." in path.parts
    ):
        raise CapacityValidationError(
            f"{field_name} must be normalized and cannot escape the repository"
        )
    return path


def _validate_tracked_content(
    authority: object,
    repo_root: Path,
    scm_ref: str,
    *,
    field_name: str,
    expected_path: str | None = None,
) -> bytes:
    if not isinstance(authority, dict):
        raise CapacityValidationError(f"{field_name} must be a tracked-content object")
    path = _normalized_relative_path(
        authority.get("path"),
        field_name=f"{field_name}.path",
    )
    if expected_path is not None and path.as_posix() != expected_path:
        raise CapacityValidationError(
            f"{field_name}.path must be the pinned public path {expected_path}"
        )
    declared_digest = authority.get("sha256")
    if not isinstance(declared_digest, str) or not _SHA256_RE.fullmatch(
        declared_digest
    ):
        raise CapacityValidationError(
            f"{field_name}.sha256 must be 64 lowercase hexadecimal characters"
        )
    content = _checked_pinned_worktree_blob(repo_root, scm_ref, path)
    if hashlib.sha256(content).hexdigest() != declared_digest:
        raise CapacityValidationError(
            f"{field_name}.sha256 does not match the Git-pinned content bytes"
        )
    return content


def validate_privacy_preserving_binding(
    binding: object,
    *,
    expected_domain: str,
    field_name: str,
) -> dict[str, str]:
    if not isinstance(binding, dict) or set(binding) != {
        "method",
        "domain",
        "value",
    }:
        raise CapacityValidationError(
            f"{field_name} must contain exactly method, domain, and value"
        )
    method = binding.get("method")
    if method not in {"hmac-sha256-v1", "opaque-random-v1"}:
        raise CapacityValidationError(
            f"{field_name}.method must identify a privacy-preserving binding"
        )
    if binding.get("domain") != expected_domain:
        raise CapacityValidationError(
            f"{field_name}.domain must equal {expected_domain}"
        )
    value = binding.get("value")
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise CapacityValidationError(
            f"{field_name}.value must be 64 lowercase hexadecimal characters"
        )
    return {
        "method": method,
        "domain": expected_domain,
        "value": value,
    }


def _validate_binding_collection(
    bindings: object,
    *,
    expected_domain: str,
    field_name: str,
) -> tuple[dict[str, str], ...]:
    if not isinstance(bindings, list) or not bindings:
        raise CapacityValidationError(f"{field_name} must be a non-empty array")
    validated = tuple(
        validate_privacy_preserving_binding(
            binding,
            expected_domain=expected_domain,
            field_name=f"{field_name}[{index}]",
        )
        for index, binding in enumerate(bindings)
    )
    identities = {
        (item["method"], item["domain"], item["value"]) for item in validated
    }
    if len(identities) != len(validated):
        raise CapacityValidationError(f"{field_name} must contain distinct bindings")
    return validated


def prepared_authority_sha256(role_plan: Mapping[str, Any]) -> str:
    """Hash the closed nested role-specific plan without creating a digest cycle."""
    if role_plan.get("kind") not in {
        "buyer",
        "seller",
        "host-operator",
        "observer",
    }:
        raise CapacityValidationError(
            "prepared authority cannot be derived for an unknown role"
        )
    return canonical_sha256(dict(role_plan))


_PREPARED_ACTION_FIELDS = (
    "schema_version",
    "action_id",
    "action_kind",
    "scm_ref",
    "scenario_id",
    "scenario_sha256",
    "profile_stage_id",
    "profile_stage_sha256",
    "actor_slot",
    "role_plan_id",
    "isolated_identity_fingerprint",
    "actor_invocation_capability_binding",
    "logical_selection",
    "runtime_binding",
    "concrete_payload_binding",
    "payload_sha256",
    "wrapper",
    "expected_result",
)


def prepared_action_sha256(action: Mapping[str, Any]) -> str:
    """Hash the exact pre-release action intent without release-policy fields."""
    missing = [field for field in _PREPARED_ACTION_FIELDS if field not in action]
    if missing:
        raise CapacityValidationError(
            "prepared action lacks required fields: " + ", ".join(missing)
        )
    projection = {field: action[field] for field in _PREPARED_ACTION_FIELDS}
    return canonical_sha256(projection)


def validate_role_plan(
    plan: dict[str, Any],
    repo_root: Path,
    *,
    expected_scm_ref: str | None = None,
) -> ValidatedRolePlan:
    scm_ref = plan.get("scm_ref")
    root = _validate_exact_commit(repo_root, scm_ref)
    assert isinstance(scm_ref, str)
    schema = _load_pinned_schema(root, scm_ref, ROLE_PLAN_SCHEMA)
    errors = _schema_errors(plan, schema)
    if expected_scm_ref is not None and scm_ref != expected_scm_ref:
        errors.append("role plan SCM ref does not match the selected campaign ref")

    role = plan.get("role")
    profile_stage_id = plan.get("profile_stage_id")
    profile_stage: ValidatedProfileStage | None
    try:
        profile_stage = resolve_pinned_profile_stage(
            root,
            scm_ref,
            profile_stage_id,
            expected_sha256=plan.get("profile_stage_sha256"),
        )
        require_pinned_profile_stage(profile_stage)
    except CapacityValidationError as error:
        errors.append(str(error))
        profile_stage = None
    pinned_scenario = profile_stage.scenario if profile_stage is not None else None
    scenario = pinned_scenario.scenario if pinned_scenario is not None else None
    expected_scenario_id = (
        pinned_scenario.scenario_id if pinned_scenario is not None else None
    )
    expected_scenario_sha256 = (
        pinned_scenario.scenario_sha256 if pinned_scenario is not None else None
    )
    if plan.get("scenario_id") != expected_scenario_id:
        errors.append("role plan scenario identity does not match its profile stage")
    if plan.get("scenario_sha256") != expected_scenario_sha256:
        errors.append("role plan scenario digest does not match its profile stage")

    instruction_path = _ROLE_INSTRUCTION_PATHS.get(role)
    if instruction_path is None:
        errors.append("role plan must use a known substantive role")
    else:
        try:
            _validate_tracked_content(
                plan.get("instruction"),
                root,
                scm_ref,
                field_name="instruction",
                expected_path=instruction_path,
            )
        except CapacityValidationError as error:
            errors.append(str(error))

    try:
        validate_privacy_preserving_binding(
            plan.get("actor_invocation_capability_binding"),
            expected_domain=ACTOR_INVOCATION_BINDING_DOMAIN,
            field_name="actor_invocation_capability_binding",
        )
    except CapacityValidationError as error:
        errors.append(str(error))

    stage_id = plan.get("profile_stage_id")
    scenario_id = plan.get("scenario_id")
    if scenario is None:
        if stage_id != "observer-probe":
            errors.append("only observer-probe may omit scenario authority")
        if role not in {"host-operator", "observer"}:
            errors.append("observer-probe admits only host-operator and observer roles")
        expected_actor_slots = {
            "host-operator": "host-operator-1",
            "observer": "observer-1",
        }
        if plan.get("actor_slot") != expected_actor_slots.get(role):
            errors.append("observer-probe role slot is invalid")
    elif isinstance(scenario, dict):
        collection = _ACTOR_COLLECTIONS.get(role)
        slots = scenario.get("actor_slots")
        allowed_slots = (
            slots.get(collection, ())
            if isinstance(slots, dict) and collection is not None
            else ()
        )
        if plan.get("actor_slot") not in allowed_slots:
            errors.append("role plan actor slot is not declared by the scenario")

    role_plan = plan.get("role_plan")
    if isinstance(role_plan, dict):
        if role == "buyer":
            if not isinstance(scenario, dict):
                errors.append("buyer role plan requires a scenario")
            else:
                request = _scenario_request_by_id(
                    scenario,
                    role_plan.get("request_id"),
                )
                if request is None or request.get("buyer_slot") != plan.get(
                    "actor_slot"
                ):
                    errors.append(
                        "buyer role plan must own exactly one declared request"
                    )
            guest_exercise = role_plan.get("guest_exercise")
            if isinstance(guest_exercise, dict):
                for key, expected_path in (
                    ("wrapper", CUDA_WRAPPER_PATH),
                    ("source", CUDA_SOURCE_PATH),
                ):
                    try:
                        _validate_tracked_content(
                            guest_exercise.get(key),
                            root,
                            scm_ref,
                            field_name=f"role_plan.guest_exercise.{key}",
                            expected_path=expected_path,
                        )
                    except CapacityValidationError as error:
                        errors.append(str(error))
        elif role == "seller":
            if not isinstance(scenario, dict):
                errors.append("seller role plan requires a scenario")
            else:
                seller = _scenario_seller_by_slot(
                    scenario,
                    plan.get("actor_slot"),
                )
                if seller is None:
                    errors.append("seller role plan is absent from scenario topology")
                else:
                    if role_plan.get("service_slot") != seller.get("service_slot"):
                        errors.append(
                            "seller role plan service slot does not match topology"
                        )
                    if role_plan.get("listing_slots") != seller.get("listing_slots"):
                        errors.append(
                            "seller role plan listing slots do not match topology"
                        )
            publication_ids = role_plan.get("publication_action_ids")
            listing_slots = role_plan.get("listing_slots")
            if (
                isinstance(publication_ids, list)
                and isinstance(listing_slots, list)
                and len(publication_ids) != len(listing_slots)
            ):
                errors.append(
                    "seller plan must name one publication action per listing"
                )
            action_ids = [
                role_plan.get("service_start_action_id"),
                *(publication_ids if isinstance(publication_ids, list) else ()),
            ]
            if len(action_ids) != len(set(action_ids)):
                errors.append("seller plan action IDs must be globally distinct")
            publication_intents = role_plan.get(
                "publication_prepared_action_sha256s"
            )
            if (
                isinstance(publication_intents, list)
                and isinstance(listing_slots, list)
                and len(publication_intents) != len(listing_slots)
            ):
                errors.append(
                    "seller plan must bind one prepared action per listing"
                )
        elif role == "host-operator":
            for key, domain in (
                ("topology_authority_binding", TOPOLOGY_BINDING_DOMAIN),
                (
                    "reversible_baseline_binding",
                    REVERSIBLE_BASELINE_BINDING_DOMAIN,
                ),
                (
                    "baseline_equivalence_binding",
                    BASELINE_EQUIVALENCE_BINDING_DOMAIN,
                ),
            ):
                try:
                    validate_privacy_preserving_binding(
                        role_plan.get(key),
                        expected_domain=domain,
                        field_name=f"role_plan.{key}",
                    )
                except CapacityValidationError as error:
                    errors.append(str(error))
        elif role == "observer":
            try:
                _validate_binding_collection(
                    role_plan.get("native_evidence_bindings"),
                    expected_domain=NATIVE_EVIDENCE_BINDING_DOMAIN,
                    field_name="role_plan.native_evidence_bindings",
                )
            except CapacityValidationError as error:
                errors.append(str(error))
        try:
            expected_prepared_authority = prepared_authority_sha256(role_plan)
        except CapacityValidationError as error:
            errors.append(str(error))
        else:
            if (
                plan.get("prepared_authority_sha256")
                != expected_prepared_authority
            ):
                errors.append(
                    "prepared_authority_sha256 does not match its exact public referent"
                )

    _raise_errors("role plan", errors)
    assert isinstance(role, str)
    assert isinstance(plan["actor_slot"], str)
    assert isinstance(stage_id, str)
    assert profile_stage is not None
    assert scenario_id is None or isinstance(scenario_id, str)
    return ValidatedRolePlan(
        plan_id=plan["plan_id"],
        role=role,
        actor_slot=plan["actor_slot"],
        profile_stage_id=stage_id,
        profile_stage_sha256=plan["profile_stage_sha256"],
        scenario_id=scenario_id,
        scenario_sha256=plan["scenario_sha256"],
        scm_ref=scm_ref,
        canonical_sha256=canonical_sha256(plan),
        repo_root=root,
        profile_stage=profile_stage,
        _canonical_bytes=canonical_json_bytes(plan),
        _validation_token=_VALIDATED_ROLE_PLAN_TOKEN,
    )


def _parse_timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CapacityValidationError(f"{field_name} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise CapacityValidationError(
            f"{field_name} must be a valid UTC timestamp"
        ) from error
    if parsed.tzinfo != UTC:
        raise CapacityValidationError(f"{field_name} must be a UTC timestamp")
    return parsed


def _step_ids(receipt: Mapping[str, Any]) -> tuple[str, ...]:
    outcomes = receipt.get("step_outcomes")
    if not isinstance(outcomes, list):
        return ()
    return tuple(
        outcome.get("step_id")
        for outcome in outcomes
        if isinstance(outcome, dict) and isinstance(outcome.get("step_id"), str)
    )


def _expected_receipt_steps(receipt: Mapping[str, Any]) -> tuple[str, ...]:
    role = receipt.get("role")
    evidence = receipt.get("role_evidence")
    if role == "buyer":
        has_guest = (
            isinstance(evidence, dict)
            and evidence.get("guest_verification") is not None
        )
        return BUYER_PRE_RELEASE_STEPS + (BUYER_GUEST_STEPS if has_guest else ())
    if role == "seller":
        return SELLER_STEPS
    if role == "host-operator":
        return HOST_OPERATOR_STEPS
    if role == "observer":
        return OBSERVER_STEPS
    return ()


def validate_role_receipt(
    receipt: dict[str, Any],
    plan: ValidatedRolePlan,
) -> ValidatedRoleReceipt:
    if (
        not isinstance(plan, ValidatedRolePlan)
        or plan._validation_token is not _VALIDATED_ROLE_PLAN_TOKEN
    ):
        raise CapacityValidationError(
            "role receipt requires a validated role-plan authority"
        )
    require_pinned_profile_stage(plan.profile_stage)
    schema = _load_pinned_schema(plan.repo_root, plan.scm_ref, ROLE_RECEIPT_SCHEMA)
    errors = _schema_errors(receipt, schema)
    expected_common = {
        "plan_id": plan.plan_id,
        "plan_sha256": plan.canonical_sha256,
        "role": plan.role,
        "actor_slot": plan.actor_slot,
        "profile_stage_id": plan.profile_stage_id,
        "profile_stage_sha256": plan.profile_stage_sha256,
        "scenario_id": plan.scenario_id,
        "scenario_sha256": plan.scenario_sha256,
        "scm_ref": plan.scm_ref,
        "instruction": plan.plan["instruction"],
        "isolated_identity_fingerprint": plan.plan[
            "isolated_identity_fingerprint"
        ],
        "prepared_authority_sha256": plan.plan["prepared_authority_sha256"],
    }
    for key, expected in expected_common.items():
        if receipt.get(key) != expected:
            errors.append(f"{key} does not match the validated role plan")
    provenance = receipt.get("provenance")
    if isinstance(provenance, dict):
        if provenance.get(
            "actor_invocation_capability_binding"
        ) != plan.plan.get("actor_invocation_capability_binding"):
            errors.append(
                "receipt actor invocation capability does not match the role plan"
            )
        try:
            validate_privacy_preserving_binding(
                provenance.get("actor_invocation_capability_binding"),
                expected_domain=ACTOR_INVOCATION_BINDING_DOMAIN,
                field_name=(
                    "provenance.actor_invocation_capability_binding"
                ),
            )
        except CapacityValidationError as error:
            errors.append(str(error))
        try:
            validate_privacy_preserving_binding(
                provenance.get("actor_liveness_binding"),
                expected_domain=NATIVE_EVIDENCE_BINDING_DOMAIN,
                field_name="provenance.actor_liveness_binding",
            )
        except CapacityValidationError as error:
            errors.append(str(error))
        if provenance.get("producer") != "actor-process":
            errors.append("role receipt must be authored by the role process")
        if provenance.get("controller_authored") is not False:
            errors.append("controller-authored role evidence is invalid")

    lifecycle = receipt.get("lifecycle")
    timestamps: list[datetime] = []
    if isinstance(lifecycle, dict):
        for key in (
            "started_at",
            "prepared_at",
            "barrier_observed_at",
            "completed_at",
        ):
            try:
                timestamps.append(
                    _parse_timestamp(
                        lifecycle.get(key),
                        field_name=f"lifecycle.{key}",
                    )
                )
            except CapacityValidationError as error:
                errors.append(str(error))
    if len(timestamps) == 4 and not all(
        earlier < later for earlier, later in zip(timestamps, timestamps[1:])
    ):
        errors.append("role lifecycle timestamps must be strictly ordered")

    barrier = receipt.get("barrier")
    expected_barrier_kind = {
        "buyer": "release",
        "seller": "observation",
        "host-operator": "cleanup",
        "observer": "observation",
    }.get(plan.role)
    if isinstance(barrier, dict):
        if barrier.get("barrier_kind") != expected_barrier_kind:
            errors.append(
                f"{plan.role} receipt must use the {expected_barrier_kind} barrier"
            )
        if barrier.get("actor_alive_at_barrier") is not True:
            errors.append("actor must remain alive through its declared barrier")

    actual_steps = _step_ids(receipt)
    expected_steps = _expected_receipt_steps(receipt)
    if actual_steps != expected_steps:
        errors.append(
            "step_outcomes must prove the exact ordered substantive role steps"
        )

    role_evidence = receipt.get("role_evidence")
    role_plan = plan.plan["role_plan"]
    run_authority = receipt.get("run_authority")
    boundary = plan.profile_stage.stage.get("execution_boundary")
    if isinstance(run_authority, dict):
        if boundary == "mock" or plan.scenario_id is None:
            if (
                run_authority.get("concurrency_policy_id") is not None
                or run_authority.get("concurrency_policy_sha256") is not None
            ):
                errors.append(
                    "mock role receipt concurrency-policy authority must be null"
                )
        elif (
            not isinstance(run_authority.get("concurrency_policy_id"), str)
            or not isinstance(
                run_authority.get("concurrency_policy_sha256"),
                str,
            )
        ):
            errors.append(
                "real role receipt requires exact concurrency-policy authority"
            )
    if isinstance(role_evidence, dict):
        if plan.role == "buyer":
            guest = role_evidence.get("guest_verification")
            if isinstance(guest, dict):
                workload_sha256 = canonical_sha256(role_plan["guest_exercise"])
                if guest.get("workload_sha256") != workload_sha256:
                    errors.append(
                        "buyer guest workload digest must bind the pinned CUDA files"
                    )
                if guest.get("success_marker") != CUDA_SUCCESS_MARKER:
                    errors.append(
                        f"buyer guest success marker must equal {CUDA_SUCCESS_MARKER}"
                    )
                if guest.get("result_checksum") != CUDA_RESULT_CHECKSUM:
                    errors.append(
                        "buyer CUDA checksum does not match the pinned workload"
                    )
        elif plan.role == "host-operator":
            for key in (
                "topology_authority_binding",
                "reversible_baseline_binding",
                "baseline_equivalence_binding",
            ):
                if role_evidence.get(key) != role_plan.get(key):
                    errors.append(
                        f"role_evidence.{key} does not match the host plan"
                    )
            if role_evidence.get("kvm_ansible_ready") is not True:
                errors.append("host receipt must prove KVM/Ansible readiness")
            if role_evidence.get("cleanup_complete") is not True:
                errors.append("substantive host receipt must prove cleanup completion")
        elif plan.role == "observer":
            if role_evidence.get("independent_source") is not True:
                errors.append("observer receipt must prove an independent source")
            if role_evidence.get("controller_source") is not False:
                errors.append("observer source cannot be controller-owned")
            if role_evidence.get("release_observed") is not True:
                errors.append("observer must capture the release observation")
            if role_evidence.get("terminal_observed") is not True:
                errors.append("observer must capture terminal observation")
            if role_evidence.get("native_evidence_bindings") != role_plan.get(
                "native_evidence_bindings"
            ):
                errors.append(
                    "observer evidence bindings do not match the observer plan"
                )

    _raise_errors("role receipt", errors)
    assert len(timestamps) == 4
    return ValidatedRoleReceipt(
        receipt_id=receipt["receipt_id"],
        role=plan.role,
        actor_slot=plan.actor_slot,
        canonical_sha256=canonical_sha256(receipt),
        started_at=timestamps[0],
        prepared_at=timestamps[1],
        barrier_observed_at=timestamps[2],
        completed_at=timestamps[3],
        _canonical_bytes=canonical_json_bytes(receipt),
        _validation_token=_VALIDATED_RECEIPT_TOKEN,
    )


def _scenario_request_by_id(
    scenario: Mapping[str, Any],
    request_id: object,
) -> Mapping[str, Any] | None:
    requests = scenario.get("requests")
    if not isinstance(requests, list):
        return None
    matches = [
        request
        for request in requests
        if isinstance(request, dict) and request.get("request_id") == request_id
    ]
    return matches[0] if len(matches) == 1 else None


def _scenario_seller_by_slot(
    scenario: Mapping[str, Any],
    seller_slot: object,
) -> Mapping[str, Any] | None:
    topology = scenario.get("listing_topology")
    sellers = topology.get("sellers") if isinstance(topology, dict) else None
    if not isinstance(sellers, list):
        return None
    matches = [
        seller
        for seller in sellers
        if isinstance(seller, dict) and seller.get("seller_slot") == seller_slot
    ]
    return matches[0] if len(matches) == 1 else None


def validate_oracle_authority(
    authority: dict[str, Any],
    repo_root: Path,
    *,
    observer_plan: ValidatedRolePlan | None = None,
) -> ValidatedOracleAuthority:
    scm_ref = authority.get("scm_ref")
    root = _validate_exact_commit(repo_root, scm_ref)
    assert isinstance(scm_ref, str)
    schema = _load_pinned_schema(root, scm_ref, ORACLE_AUTHORITY_SCHEMA)
    errors = _schema_errors(authority, schema)
    try:
        stage = resolve_pinned_profile_stage(
            root,
            scm_ref,
            authority.get("profile_stage_id"),
            expected_sha256=authority.get("profile_stage_sha256"),
        )
        stage_value = require_pinned_profile_stage(stage)
    except CapacityValidationError as error:
        errors.append(str(error))
        stage = None
        stage_value = {}

    for key in ("execution_boundary", "actor_trigger"):
        if authority.get(key) != stage_value.get(key):
            errors.append(f"oracle authority {key} does not match its profile stage")

    is_mock = stage_value.get("execution_boundary") == "mock"
    expected_schema_path = (
        "tools/issue-discovery/schemas/capacity-mock-capture.schema.json"
        if is_mock
        else "tools/issue-discovery/schemas/capacity-result.schema.json"
    )
    try:
        _validate_tracked_content(
            authority.get("result_schema"),
            root,
            scm_ref,
            field_name="result_schema",
            expected_path=expected_schema_path,
        )
    except CapacityValidationError as error:
        errors.append(str(error))

    if is_mock:
        if observer_plan is not None:
            errors.append("capture-only oracle authority cannot bind an observer plan")
        if authority.get("observer_plan_sha256") is not None:
            errors.append("capture-only oracle authority must omit observer authority")
        if authority.get("real_oracle_allowed") is not False:
            errors.append("capture-only oracle authority must deny the real oracle")
    else:
        if (
            not isinstance(observer_plan, ValidatedRolePlan)
            or observer_plan._validation_token is not _VALIDATED_ROLE_PLAN_TOKEN
        ):
            errors.append(
                "real oracle authority requires a validated independent-observer plan"
            )
        else:
            if observer_plan.role != "observer":
                errors.append("real oracle authority must bind an observer role")
            if observer_plan.scm_ref != scm_ref:
                errors.append("oracle and observer plans must bind one SCM ref")
            if stage is not None and (
                observer_plan.profile_stage_id != stage.stage_id
                or observer_plan.profile_stage_sha256 != stage.canonical_sha256
            ):
                errors.append("oracle observer plan does not bind the same stage")
            if (
                authority.get("observer_plan_sha256")
                != observer_plan.canonical_sha256
            ):
                errors.append(
                    "oracle authority does not bind the exact observer plan"
                )
        if authority.get("real_oracle_allowed") is not True:
            errors.append("real stage oracle authority must allow its real oracle")

    _raise_errors("oracle authority", errors)
    assert stage is not None
    return ValidatedOracleAuthority(
        oracle_authority_id=authority["oracle_authority_id"],
        scm_ref=scm_ref,
        profile_stage_id=stage.stage_id,
        canonical_sha256=canonical_sha256(authority),
        repo_root=root,
        _canonical_bytes=canonical_json_bytes(authority),
        _validation_token=_VALIDATED_ORACLE_TOKEN,
    )


def _validate_action_payload(
    payload_bytes: bytes,
    action: Mapping[str, Any],
    repo_root: Path,
    scm_ref: str,
) -> dict[str, Any]:
    payload = _strict_json_object(payload_bytes, source="frozen action payload")
    if payload_bytes != canonical_json_bytes(payload):
        raise CapacityValidationError(
            "frozen action payload must use exact canonical JSON bytes"
        )
    schema = _load_pinned_schema(repo_root, scm_ref, ACTION_PAYLOAD_SCHEMA)
    errors = _schema_errors(payload, schema)
    expected = {
        "action_id": action.get("action_id"),
        "action_kind": action.get("action_kind"),
        "actor_slot": action.get("actor_slot"),
        "logical_selection": action.get("logical_selection"),
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            errors.append(f"payload {key} does not match the frozen action")
    _raise_errors("action payload", errors)
    return payload


def validate_frozen_action(
    action: dict[str, Any],
    plan: ValidatedRolePlan,
    *,
    payload_bytes: bytes,
    oracle_authority: ValidatedOracleAuthority,
    concurrency_policy: ValidatedConcurrencyPolicy | None = None,
) -> ValidatedFrozenAction:
    if (
        not isinstance(plan, ValidatedRolePlan)
        or plan._validation_token is not _VALIDATED_ROLE_PLAN_TOKEN
    ):
        raise CapacityValidationError(
            "frozen action requires a validated role-plan authority"
        )
    if (
        not isinstance(oracle_authority, ValidatedOracleAuthority)
        or oracle_authority._validation_token is not _VALIDATED_ORACLE_TOKEN
    ):
        raise CapacityValidationError(
            "frozen action requires validated oracle authority"
        )
    require_pinned_profile_stage(plan.profile_stage)
    pinned_scenario = plan.profile_stage.scenario
    if pinned_scenario is None:
        raise CapacityValidationError("market actions require a scenario-bound stage")
    scenario = pinned_scenario.scenario
    schema = _load_pinned_schema(plan.repo_root, plan.scm_ref, FROZEN_ACTION_SCHEMA)
    errors = _schema_errors(action, schema)
    if oracle_authority.scm_ref != plan.scm_ref:
        errors.append("oracle authority and action must bind one SCM ref")
    if oracle_authority.profile_stage_id != plan.profile_stage_id:
        errors.append("oracle authority and action must bind one profile stage")
    scenario_sha256 = pinned_scenario.scenario_sha256
    profile_stage_sha256 = plan.profile_stage_sha256

    expected_common = {
        "scm_ref": plan.scm_ref,
        "scenario_id": plan.scenario_id,
        "scenario_sha256": scenario_sha256,
        "profile_stage_id": plan.profile_stage_id,
        "profile_stage_sha256": profile_stage_sha256,
        "actor_slot": plan.actor_slot,
        "role_plan_id": plan.plan_id,
        "role_plan_sha256": plan.canonical_sha256,
        "isolated_identity_fingerprint": plan.plan[
            "isolated_identity_fingerprint"
        ],
        "actor_invocation_capability_binding": plan.plan[
            "actor_invocation_capability_binding"
        ],
    }
    for key, expected in expected_common.items():
        if action.get(key) != expected:
            errors.append(f"{key} does not match the validated role authority")
    boundary = plan.profile_stage.stage.get("execution_boundary")
    if boundary == "mock":
        if concurrency_policy is not None:
            errors.append("capture-only mock actions cannot bind a real concurrency policy")
        if (
            action.get("concurrency_policy_id") is not None
            or action.get("concurrency_policy_sha256") is not None
        ):
            errors.append("capture-only action concurrency authority must be null")
    else:
        if (
            not isinstance(concurrency_policy, ValidatedConcurrencyPolicy)
            or concurrency_policy._validation_token is not _VALIDATED_POLICY_TOKEN
        ):
            errors.append("real agent-triggered action requires frozen concurrency policy")
        else:
            policy = concurrency_policy.policy
            expected_policy = {
                "concurrency_policy_id": concurrency_policy.policy_id,
                "concurrency_policy_sha256": concurrency_policy.canonical_sha256,
                "release_id": concurrency_policy.release_id,
            }
            for key, expected in expected_policy.items():
                if action.get(key) != expected:
                    errors.append(f"action {key} does not match concurrency policy")
            if action.get("actor_slot") not in policy.get("actor_slots", ()):
                errors.append("action actor is absent from concurrency policy")
            if action.get("action_id") not in policy.get("action_ids", ()):
                errors.append("action ID is absent from concurrency policy")
            role_authority = {
                "plan_id": plan.plan_id,
                "plan_sha256": plan.canonical_sha256,
            }
            if role_authority not in policy.get("role_plan_authorities", ()):
                errors.append(
                    "action role plan was not frozen by the concurrency policy"
                )
            observer_plan_sha256 = oracle_authority.authority.get(
                "observer_plan_sha256"
            )
            matching_observer_authorities = [
                item
                for item in policy.get("role_plan_authorities", ())
                if isinstance(item, dict)
                and item.get("plan_sha256") == observer_plan_sha256
            ]
            if len(matching_observer_authorities) != 1:
                errors.append(
                    "action oracle observer was not frozen exactly once by "
                    "the concurrency policy"
                )
    expected_result = action.get("expected_result")
    if isinstance(expected_result, dict):
        if (
            expected_result.get("oracle_authority_id")
            != oracle_authority.oracle_authority_id
            or expected_result.get("independent_oracle_authority_sha256")
            != oracle_authority.canonical_sha256
        ):
            errors.append(
                "action does not bind the selected independent oracle authority"
            )
        try:
            _validate_tracked_content(
                expected_result.get("action_result_schema"),
                plan.repo_root,
                plan.scm_ref,
                field_name="expected_result.action_result_schema",
                expected_path=ACTION_RESULT_SCHEMA.as_posix(),
            )
        except CapacityValidationError as error:
            errors.append(str(error))
    try:
        _validate_action_payload(
            payload_bytes,
            action,
            plan.repo_root,
            plan.scm_ref,
        )
    except CapacityValidationError as error:
        errors.append(str(error))
    if action.get("payload_sha256") != hashlib.sha256(payload_bytes).hexdigest():
        errors.append("payload_sha256 does not match exact canonical payload bytes")

    action_kind = action.get("action_kind")
    expected_wrapper = _ACTION_WRAPPER_PATHS.get(action_kind)
    if expected_wrapper is None:
        errors.append("action kind does not identify a public one-shot wrapper")
    else:
        try:
            _validate_tracked_content(
                action.get("wrapper"),
                plan.repo_root,
                plan.scm_ref,
                field_name="wrapper",
                expected_path=expected_wrapper,
            )
        except CapacityValidationError as error:
            errors.append(str(error))

    try:
        validate_privacy_preserving_binding(
            action.get("runtime_binding"),
            expected_domain=RUNTIME_BINDING_DOMAIN,
            field_name="runtime_binding",
        )
    except CapacityValidationError as error:
        errors.append(str(error))
    try:
        validate_privacy_preserving_binding(
            action.get("actor_invocation_capability_binding"),
            expected_domain=ACTOR_INVOCATION_BINDING_DOMAIN,
            field_name="actor_invocation_capability_binding",
        )
    except CapacityValidationError as error:
        errors.append(str(error))
    try:
        validate_privacy_preserving_binding(
            action.get("concrete_payload_binding"),
            expected_domain=CONCRETE_PAYLOAD_BINDING_DOMAIN,
            field_name="concrete_payload_binding",
        )
    except CapacityValidationError as error:
        errors.append(str(error))

    selection = action.get("logical_selection")
    role_plan = plan.plan["role_plan"]
    if isinstance(selection, dict):
        if action_kind == "buyer-request":
            if plan.role != "buyer" or action.get("action_id") != role_plan.get(
                "action_id"
            ):
                errors.append("buyer action is not authorized by the buyer role plan")
            request = _scenario_request_by_id(scenario, selection.get("request_id"))
            if request is None:
                errors.append("buyer action must select exactly one scenario request")
            else:
                for key in ("seller_slot", "listing_slot"):
                    if selection.get(key) != request.get(key):
                        errors.append(
                            f"buyer action {key} does not match the scenario request"
                        )
                if request.get("buyer_slot") != plan.actor_slot:
                    errors.append(
                        "buyer action request is not owned by the planned buyer"
                    )
            if selection.get("request_id") != role_plan.get("request_id"):
                errors.append("buyer action request does not match the role plan")
        elif action_kind == "seller-service-start":
            if (
                plan.role != "seller"
                or action.get("action_id")
                != role_plan.get("service_start_action_id")
            ):
                errors.append(
                    "service-start action is not authorized by the seller role plan"
                )
            seller = _scenario_seller_by_slot(scenario, selection.get("seller_slot"))
            if seller is None or seller.get("service_slot") != selection.get(
                "service_slot"
            ):
                errors.append(
                    "service-start selection does not match the scenario seller"
                )
            if selection.get("seller_slot") != plan.actor_slot:
                errors.append("seller action is not owned by the planned seller")
            if selection.get("service_slot") != role_plan.get("service_slot"):
                errors.append("seller service does not match the role plan")
        elif action_kind == "seller-listing-publication":
            publication_ids = role_plan.get("publication_action_ids", ())
            planned_listing_slots = role_plan.get("listing_slots", ())
            if plan.role != "seller" or action.get("action_id") not in publication_ids:
                errors.append(
                    "listing-publication action is not authorized by the seller plan"
                )
            elif (
                not isinstance(publication_ids, list)
                or not isinstance(planned_listing_slots, list)
            ):
                errors.append(
                    "seller publication actions require ordered listing authority"
                )
            else:
                action_index = publication_ids.index(action["action_id"])
                if (
                    action_index >= len(planned_listing_slots)
                    or selection.get("listing_slot")
                    != planned_listing_slots[action_index]
                ):
                    errors.append(
                        "publication action ID does not match its planned "
                        "listing position"
                    )
            seller = _scenario_seller_by_slot(scenario, selection.get("seller_slot"))
            if seller is None:
                errors.append("publication must select one scenario seller")
            else:
                if selection.get("service_slot") != seller.get("service_slot"):
                    errors.append(
                        "publication service does not match the scenario seller"
                    )
                if selection.get("listing_slot") not in seller.get(
                    "listing_slots", ()
                ):
                    errors.append(
                        "publication listing does not belong to the scenario seller"
                    )
            if selection.get("seller_slot") != plan.actor_slot:
                errors.append("seller publication is not owned by the planned seller")
            if selection.get("service_slot") != role_plan.get("service_slot"):
                errors.append("publication service does not match the role plan")
            if selection.get("listing_slot") not in planned_listing_slots:
                errors.append("publication listing does not match the role plan")

    if action.get("attempt") != 1:
        errors.append("frozen action attempt must be exactly one")
    try:
        computed_prepared_action = prepared_action_sha256(action)
    except CapacityValidationError as error:
        errors.append(str(error))
        computed_prepared_action = None
    if action.get("prepared_action_sha256") != computed_prepared_action:
        errors.append(
            "prepared_action_sha256 does not match the exact pre-release intent"
        )
    planned_prepared_action: object = None
    if action_kind == "buyer-request":
        planned_prepared_action = role_plan.get("prepared_action_sha256")
    elif action_kind == "seller-service-start":
        planned_prepared_action = role_plan.get(
            "service_start_prepared_action_sha256"
        )
    elif action_kind == "seller-listing-publication":
        publication_ids = role_plan.get("publication_action_ids")
        publication_intents = role_plan.get(
            "publication_prepared_action_sha256s"
        )
        if (
            isinstance(publication_ids, list)
            and isinstance(publication_intents, list)
            and action.get("action_id") in publication_ids
        ):
            index = publication_ids.index(action["action_id"])
            if index < len(publication_intents):
                planned_prepared_action = publication_intents[index]
    if action.get("prepared_action_sha256") != planned_prepared_action:
        errors.append(
            "frozen action does not match the prepared intent in its role plan"
        )
    if concurrency_policy is not None:
        prepared_authority = {
            "action_id": action.get("action_id"),
            "prepared_action_sha256": action.get("prepared_action_sha256"),
        }
        if prepared_authority not in concurrency_policy.policy.get(
            "prepared_action_authorities",
            (),
        ):
            errors.append(
                "prepared action was not frozen by the concurrency policy"
            )
    _raise_errors("frozen action", errors)
    assert isinstance(action_kind, str)
    return ValidatedFrozenAction(
        action_id=action["action_id"],
        action_kind=action_kind,
        actor_slot=plan.actor_slot,
        release_id=action["release_id"],
        scm_ref=plan.scm_ref,
        canonical_sha256=canonical_sha256(action),
        repo_root=plan.repo_root,
        _canonical_bytes=canonical_json_bytes(action),
        _validation_token=_VALIDATED_ACTION_TOKEN,
    )


def validate_action_result(
    result: dict[str, Any],
    action: ValidatedFrozenAction,
) -> ValidatedActionResult:
    if (
        not isinstance(action, ValidatedFrozenAction)
        or action._validation_token is not _VALIDATED_ACTION_TOKEN
    ):
        raise CapacityValidationError(
            "action result requires validated frozen-action authority"
        )
    schema = _load_pinned_schema(
        action.repo_root,
        action.scm_ref,
        ACTION_RESULT_SCHEMA,
    )
    errors = _schema_errors(result, schema)
    expected = {
        "action_id": action.action_id,
        "action_sha256": action.canonical_sha256,
        "actor_slot": action.actor_slot,
        "release_id": action.release_id,
    }
    for key, value in expected.items():
        if result.get(key) != value:
            errors.append(f"{key} does not match the frozen action")
    timestamps: list[datetime] = []
    for key in ("invoked_at", "terminal_at"):
        try:
            timestamps.append(
                _parse_timestamp(result.get(key), field_name=key)
            )
        except CapacityValidationError as error:
            errors.append(str(error))
    if len(timestamps) == 2 and not timestamps[0] < timestamps[1]:
        errors.append("action result timestamps must be strictly ordered")

    action_value = action.action
    result_kind = result.get("result_kind")
    failure_code = result.get("failure_code")
    checks = result.get("pre_emission_checks")
    all_checks = {
        "authority_unchanged": True,
        "payload_unchanged": True,
        "selection_unchanged": True,
        "runtime_binding_unchanged": True,
        "wrapper_unchanged": True,
    }
    check_failures = {
        "authority-changed": "authority_unchanged",
        "payload-changed": "payload_unchanged",
        "selection-changed": "selection_unchanged",
        "runtime-binding-changed": "runtime_binding_unchanged",
        "wrapper-changed": "wrapper_unchanged",
    }
    if result_kind == "emitted":
        if result.get("attempt") != action_value.get("attempt"):
            errors.append("emitted result attempt does not match frozen attempt one")
        if result.get("release_claim_count") != 1:
            errors.append("emitted result must claim the release exactly once")
        if result.get("actor_alive_at_invocation") is not True:
            errors.append("emitted action requires a live initiating actor")
        if checks != all_checks:
            errors.append("emitted action requires every pre-emission check")
        if result.get("terminal_payload_sha256") != action_value.get(
            "payload_sha256"
        ):
            errors.append("emitted terminal payload does not match frozen bytes")
    elif result_kind == "rejected-before-emission":
        if result.get("emission_count") != 0:
            errors.append("rejected action cannot emit")
        if result.get("terminal_payload_sha256") is not None:
            errors.append("rejected action cannot publish a terminal payload")
        if failure_code == "unauthorized-retry":
            if not isinstance(result.get("attempt"), int) or result["attempt"] <= 1:
                errors.append("unauthorized retry must preserve attempted value > 1")
        elif (
            failure_code != "duplicate-release"
            and result.get("attempt") != action_value.get("attempt")
        ):
            errors.append("non-retry rejection must preserve frozen attempt one")
        if failure_code == "duplicate-release":
            if (
                not isinstance(result.get("release_claim_count"), int)
                or result["release_claim_count"] <= 1
            ):
                errors.append("duplicate release must preserve claim count > 1")
        elif result.get("release_claim_count") != 1:
            errors.append("non-duplicate rejection must have one release claim")
        if failure_code == "actor-exited":
            if result.get("actor_alive_at_invocation") is not False:
                errors.append("actor-exited rejection must record failed liveness")
        elif (
            failure_code
            not in {"unauthorized-retry", "duplicate-release"}
            and result.get("actor_alive_at_invocation") is not True
        ):
            errors.append("non-liveness rejection requires a live initiating actor")
        failed_check = check_failures.get(failure_code)
        if failed_check is not None:
            if not isinstance(checks, dict) or checks.get(failed_check) is not False:
                errors.append(
                    "rejection failure code contradicts its designated failed check"
                )
        elif checks != all_checks:
            errors.append(
                "retry, duplicate, liveness, and emission failures require unchanged inputs"
            )
    _raise_errors("action result", errors)
    assert len(timestamps) == 2
    return ValidatedActionResult(
        action_result_id=result["action_result_id"],
        action_id=action.action_id,
        actor_slot=action.actor_slot,
        result_kind=result["result_kind"],
        invoked_at=timestamps[0],
        terminal_at=timestamps[1],
        canonical_sha256=canonical_sha256(result),
        _canonical_bytes=canonical_json_bytes(result),
        _validation_token=_VALIDATED_RESULT_TOKEN,
    )


def validate_unauthorized_retry_rejection(
    result: dict[str, Any],
    action: ValidatedFrozenAction,
) -> ValidatedActionResult:
    """Validate the one terminal receipt for a release rejected as a retry.

    The receipt preserves the attempted value greater than one and emits
    nothing; the frozen action itself remains the sole attempt-one authority.
    """
    authority = validate_action_result(result, action)
    value = authority.result
    if (
        authority.result_kind != "rejected-before-emission"
        or value.get("failure_code") != "unauthorized-retry"
        or value.get("emission_count") != 0
        or value.get("attempt", 0) <= 1
    ):
        raise CapacityValidationError(
            "unauthorized retry must be a zero-emission typed rejection"
        )
    return authority


def validate_substantive_role_evidence(
    plan: ValidatedRolePlan,
    receipt: ValidatedRoleReceipt,
    actions: Sequence[ValidatedFrozenAction],
    results: Sequence[ValidatedActionResult],
) -> SubstantiveRoleEvidence:
    errors: list[str] = []
    if plan._validation_token is not _VALIDATED_ROLE_PLAN_TOKEN:
        errors.append("role evidence plan is not validated authority")
    if receipt._validation_token is not _VALIDATED_RECEIPT_TOKEN:
        errors.append("role evidence receipt is not validated authority")
    if any(
        action._validation_token is not _VALIDATED_ACTION_TOKEN
        for action in actions
    ):
        errors.append("role evidence contains an unvalidated action")
    if any(
        result._validation_token is not _VALIDATED_RESULT_TOKEN
        for result in results
    ):
        errors.append("role evidence contains an unvalidated result")
    if receipt.role != plan.role or receipt.actor_slot != plan.actor_slot:
        errors.append("receipt does not belong to the validated role plan")
    receipt_value = receipt.receipt
    if (
        receipt_value.get("plan_id") != plan.plan_id
        or receipt_value.get("plan_sha256") != plan.canonical_sha256
    ):
        errors.append("receipt does not bind the exact validated role plan")
    if len(actions) != len(results):
        errors.append("every frozen action must have exactly one action result")
    if len({action.action_id for action in actions}) != len(actions):
        errors.append("role evidence cannot contain duplicate frozen actions")
    if len({result.action_result_id for result in results}) != len(results):
        errors.append("role evidence cannot contain duplicate action results")

    result_by_action = {result.action_id: result for result in results}
    if set(result_by_action) != {action.action_id for action in actions}:
        errors.append("action and terminal-result identities must match exactly")
    for action in actions:
        action_value = action.action
        expected_plan_authority = {
            "scm_ref": plan.scm_ref,
            "scenario_id": plan.scenario_id,
            "scenario_sha256": plan.scenario_sha256,
            "profile_stage_id": plan.profile_stage_id,
            "profile_stage_sha256": plan.profile_stage_sha256,
            "actor_slot": plan.actor_slot,
            "role_plan_id": plan.plan_id,
            "role_plan_sha256": plan.canonical_sha256,
            "isolated_identity_fingerprint": plan.plan[
                "isolated_identity_fingerprint"
            ],
            "actor_invocation_capability_binding": plan.plan[
                "actor_invocation_capability_binding"
            ],
        }
        if any(
            action_value.get(key) != value
            for key, value in expected_plan_authority.items()
        ):
            errors.append(
                f"action {action.action_id} does not bind the exact role plan"
            )
        run_authority = receipt_value.get("run_authority")
        if not isinstance(run_authority, dict) or (
            run_authority.get("release_id") != action.release_id
            or run_authority.get("concurrency_policy_id")
            != action_value.get("concurrency_policy_id")
            or run_authority.get("concurrency_policy_sha256")
            != action_value.get("concurrency_policy_sha256")
        ):
            errors.append(
                f"receipt run authority does not match action "
                f"{action.action_id}"
            )
        result = result_by_action.get(action.action_id)
        if result is None:
            errors.append(f"action {action.action_id} lacks its terminal result")
            continue
        result_value = result.result
        if (
            result_value.get("action_sha256") != action.canonical_sha256
            or result_value.get("release_id") != action.release_id
        ):
            errors.append(
                f"result for {action.action_id} does not bind the exact "
                "supplied frozen action"
            )
        if result.actor_slot != plan.actor_slot:
            errors.append("action result actor does not match the role actor")
        if result.result_kind != "emitted":
            errors.append(
                "rejected-before-emission cannot satisfy substantive role evidence"
            )
        if plan.role == "buyer":
            if not (
                receipt.barrier_observed_at
                <= result.invoked_at
                < result.terminal_at
                <= receipt.completed_at
            ):
                errors.append(
                    "buyer must remain alive from release through invocation and terminal result"
                )
        elif plan.role == "seller":
            if not (
                receipt.prepared_at
                <= result.invoked_at
                < result.terminal_at
                <= receipt.barrier_observed_at
            ):
                errors.append(
                    "seller must invoke its actions while alive before its observation barrier"
                )

    if plan.role == "buyer":
        if len(actions) != 1 or actions[0].action_kind != "buyer-request":
            errors.append("buyer evidence requires exactly one owned request action")
        evidence = receipt.receipt["role_evidence"]
        if len(results) == 1 and evidence.get(
            "action_result_sha256"
        ) != results[0].canonical_sha256:
            errors.append(
                "buyer receipt does not bind its exact action-result digest"
            )
        if actions and receipt.receipt["barrier"].get("barrier_id") != actions[
            0
        ].release_id:
            errors.append("buyer release barrier does not match its frozen action")
    elif plan.role == "seller":
        role_plan = plan.plan["role_plan"]
        expected_action_ids = {
            role_plan["service_start_action_id"],
            *role_plan["publication_action_ids"],
        }
        if {action.action_id for action in actions} != expected_action_ids:
            errors.append(
                "seller evidence must cover service start and every publication action"
            )
        evidence = receipt.receipt["role_evidence"]
        service_result = result_by_action.get(
            role_plan["service_start_action_id"]
        )
        publication_results = [
            result_by_action[action_id].canonical_sha256
            for action_id in role_plan["publication_action_ids"]
            if action_id in result_by_action
        ]
        if (
            service_result is None
            or service_result.canonical_sha256
            != evidence.get("service_start_result_sha256")
        ):
            errors.append("seller receipt does not bind its service-start result")
        if publication_results != evidence.get(
            "publication_result_sha256s",
            (),
        ):
            errors.append(
                "seller receipt must bind publication results in planned listing order"
            )
    elif actions or results:
        errors.append(f"{plan.role} role evidence cannot author market actions")

    _raise_errors("substantive role evidence", errors)
    return SubstantiveRoleEvidence(
        plan=plan,
        receipt=receipt,
        actions=tuple(actions),
        results=tuple(results),
    )


def _planned_action_ids(plans: Sequence[ValidatedRolePlan]) -> tuple[str, ...]:
    action_ids: list[str] = []
    for plan in plans:
        role_plan = plan.plan["role_plan"]
        if plan.role == "buyer":
            action_ids.append(role_plan["action_id"])
        elif plan.role == "seller":
            action_ids.append(role_plan["service_start_action_id"])
            action_ids.extend(role_plan["publication_action_ids"])
    return tuple(action_ids)


def _planned_prepared_action_authorities(
    plans: Sequence[ValidatedRolePlan],
) -> tuple[dict[str, str], ...]:
    authorities: list[dict[str, str]] = []
    for plan in plans:
        role_plan = plan.plan["role_plan"]
        if plan.role == "buyer":
            authorities.append(
                {
                    "action_id": role_plan["action_id"],
                    "prepared_action_sha256": role_plan[
                        "prepared_action_sha256"
                    ],
                }
            )
        elif plan.role == "seller":
            authorities.append(
                {
                    "action_id": role_plan["service_start_action_id"],
                    "prepared_action_sha256": role_plan[
                        "service_start_prepared_action_sha256"
                    ],
                }
            )
            try:
                pairs = zip(
                    role_plan["publication_action_ids"],
                    role_plan["publication_prepared_action_sha256s"],
                    strict=True,
                )
                authorities.extend(
                    {
                        "action_id": action_id,
                        "prepared_action_sha256": prepared_sha256,
                    }
                    for action_id, prepared_sha256 in pairs
                )
            except ValueError as error:
                raise CapacityValidationError(
                    "seller publication actions and prepared intents must align"
                ) from error
    return tuple(authorities)


def _scenario_actor_slots(scenario: Mapping[str, Any]) -> tuple[str, ...]:
    slots = scenario.get("actor_slots")
    if not isinstance(slots, dict):
        return ()
    return tuple(
        slot
        for collection in _ACTOR_COLLECTIONS.values()
        for slot in slots.get(collection, ())
        if isinstance(slot, str)
    )


def _window_map(
    value: object,
    *,
    errors: list[str],
) -> dict[str, tuple[int, int, int]]:
    windows: dict[str, tuple[int, int, int]] = {}
    if not isinstance(value, list):
        errors.append("invocation_windows must be an array")
        return windows
    for index, window in enumerate(value):
        if not isinstance(window, dict):
            errors.append(f"invocation_windows[{index}] must be an object")
            continue
        kind = window.get("action_kind")
        opened = window.get("opened_offset_ns")
        closed = window.get("closed_offset_ns")
        skew = window.get("max_emission_skew_ns")
        if not all(type(item) is int for item in (opened, closed, skew)):
            errors.append(
                f"invocation_windows[{index}] offsets and skew must be integers"
            )
            continue
        assert isinstance(opened, int)
        assert isinstance(closed, int)
        assert isinstance(skew, int)
        if opened >= closed:
            errors.append("invocation window must open before it closes")
        if not isinstance(kind, str) or kind in windows:
            errors.append("invocation window action kinds must be unique")
            continue
        windows[kind] = (opened, closed, skew)
    if set(windows) != set(_ACTION_WRAPPER_PATHS):
        errors.append("exactly one window is required for every action kind")
    if set(windows) == set(_ACTION_WRAPPER_PATHS):
        service = windows["seller-service-start"]
        publication = windows["seller-listing-publication"]
        buyer = windows["buyer-request"]
        if service[1] > publication[0] or publication[1] > buyer[0]:
            errors.append(
                "concurrency windows must order service start, publication, then buyer request"
            )
    return windows


def validate_concurrency_policy(
    policy: dict[str, Any],
    repo_root: Path,
    role_plans: Sequence[ValidatedRolePlan],
) -> ValidatedConcurrencyPolicy:
    scm_ref = policy.get("scm_ref")
    root = _validate_exact_commit(repo_root, scm_ref)
    assert isinstance(scm_ref, str)
    schema = _load_pinned_schema(root, scm_ref, CONCURRENCY_POLICY_SCHEMA)
    errors = _schema_errors(policy, schema)
    try:
        stage = resolve_pinned_profile_stage(
            root,
            scm_ref,
            policy.get("profile_stage_id"),
            expected_sha256=policy.get("profile_stage_sha256"),
        )
        stage_value = require_pinned_profile_stage(stage)
    except CapacityValidationError as error:
        errors.append(str(error))
        stage = None
        stage_value = {}
    scenario_authority = stage.scenario if stage is not None else None
    scenario = (
        scenario_authority.scenario if scenario_authority is not None else None
    )
    if stage_value.get("execution_boundary") not in {
        "real-qualification",
        "real-measured",
    } or stage_value.get("actor_trigger") != "agent-triggered":
        errors.append(
            "concurrency policy is valid only for a real agent-triggered stage"
        )
    if scenario_authority is None:
        errors.append("concurrency policy requires a scenario-bound stage")
    else:
        if policy.get("scenario_id") != scenario_authority.scenario_id:
            errors.append("concurrency policy scenario identity does not match")
        if policy.get("scenario_sha256") != scenario_authority.scenario_sha256:
            errors.append("concurrency policy scenario digest does not match")

    try:
        frozen_at = _parse_timestamp(
            policy.get("frozen_at"),
            field_name="frozen_at",
        )
    except CapacityValidationError as error:
        errors.append(str(error))
        frozen_at = datetime.min.replace(tzinfo=UTC)
    try:
        validate_privacy_preserving_binding(
            policy.get("clock_evidence_binding"),
            expected_domain=NATIVE_EVIDENCE_BINDING_DOMAIN,
            field_name="clock_evidence_binding",
        )
    except CapacityValidationError as error:
        errors.append(str(error))
    _window_map(policy.get("invocation_windows"), errors=errors)

    plans = tuple(role_plans)
    if not plans:
        errors.append("concurrency policy requires every declared role plan")
    if any(
        plan._validation_token is not _VALIDATED_ROLE_PLAN_TOKEN for plan in plans
    ):
        errors.append("concurrency policy contains an unvalidated role plan")
    if any(
        plan.scm_ref != scm_ref
        or plan.profile_stage_id != policy.get("profile_stage_id")
        or plan.profile_stage_sha256 != policy.get("profile_stage_sha256")
        for plan in plans
    ):
        errors.append("all role plans must bind the concurrency-policy stage")
    actual_actor_slots = tuple(sorted(plan.actor_slot for plan in plans))
    if len(actual_actor_slots) != len(set(actual_actor_slots)):
        errors.append("concurrency policy role plans contain duplicate actor slots")
    expected_actor_slots = (
        tuple(sorted(_scenario_actor_slots(scenario)))
        if isinstance(scenario, dict)
        else ()
    )
    if actual_actor_slots != expected_actor_slots:
        errors.append("concurrency policy must freeze every exact scenario actor")
    plan_ids = [plan.plan_id for plan in plans]
    if len(plan_ids) != len(set(plan_ids)):
        errors.append("concurrency policy role-plan IDs must be globally unique")
    if tuple(sorted(policy.get("actor_slots", ()))) != expected_actor_slots:
        errors.append("concurrency policy actor slots do not match role plans")

    fingerprints = [
        plan.plan["isolated_identity_fingerprint"] for plan in plans
    ]
    if len(fingerprints) != len(set(fingerprints)):
        errors.append("concurrency policy role plans contain duplicate identities")
    capabilities = [
        _binding_identity(
            plan.plan["actor_invocation_capability_binding"]
        )
        for plan in plans
    ]
    if len(capabilities) != len(set(capabilities)):
        errors.append(
            "concurrency policy role plans contain duplicate invocation capabilities"
        )
    expected_role_authorities = sorted(
        (
            {
                "plan_id": plan.plan_id,
                "plan_sha256": plan.canonical_sha256,
            }
            for plan in plans
        ),
        key=lambda item: item["plan_id"],
    )
    if policy.get("role_plan_authorities") != expected_role_authorities:
        errors.append(
            "concurrency policy must freeze every exact role-plan authority"
        )

    action_ids = _planned_action_ids(plans)
    if len(action_ids) != len(set(action_ids)):
        errors.append("concurrency policy action IDs must be globally unique")
    if tuple(sorted(policy.get("action_ids", ()))) != tuple(sorted(action_ids)):
        errors.append("concurrency policy must freeze every planned action ID")
    try:
        expected_prepared_authorities = sorted(
            _planned_prepared_action_authorities(plans),
            key=lambda item: item["action_id"],
        )
    except CapacityValidationError as error:
        errors.append(str(error))
        expected_prepared_authorities = []
    if (
        policy.get("prepared_action_authorities")
        != expected_prepared_authorities
    ):
        errors.append(
            "concurrency policy must freeze every exact prepared action"
        )
    if policy.get("deny_local_queue") is not True:
        errors.append("concurrency policy must deny a local actor queue")
    if policy.get("deny_controller_throttle") is not True:
        errors.append("concurrency policy must deny controller throttling")

    _raise_errors("concurrency policy", errors)
    assert stage is not None
    return ValidatedConcurrencyPolicy(
        policy_id=policy["policy_id"],
        scm_ref=scm_ref,
        profile_stage_id=stage.stage_id,
        release_id=policy["release_id"],
        canonical_sha256=canonical_sha256(policy),
        repo_root=root,
        frozen_at=frozen_at,
        _canonical_bytes=canonical_json_bytes(policy),
        _validation_token=_VALIDATED_POLICY_TOKEN,
    )


def _binding_identity(binding: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    return (
        binding.get("method"),
        binding.get("domain"),
        binding.get("value"),
    )


def validate_invocation_offsets(
    offsets: Sequence[int],
    *,
    max_emission_skew_ns: int,
    label: str,
) -> int:
    """Return exact integer skew or reject a serialized/constrained wave."""
    if (
        not offsets
        or any(type(offset) is not int for offset in offsets)
        or type(max_emission_skew_ns) is not int
        or max_emission_skew_ns < 0
    ):
        raise CapacityValidationError(
            f"{label} invocation offsets and skew bound must be exact integers"
        )
    skew = max(offsets) - min(offsets)
    if skew > max_emission_skew_ns:
        raise CapacityValidationError(
            f"{label} invocation skew exceeds frozen bound"
        )
    return skew


def validate_substantive_actor_set(
    actor_set: dict[str, Any],
    concurrency_policy: ValidatedConcurrencyPolicy,
    role_evidence: Sequence[SubstantiveRoleEvidence],
) -> ValidatedActorSet:
    if (
        not isinstance(concurrency_policy, ValidatedConcurrencyPolicy)
        or concurrency_policy._validation_token is not _VALIDATED_POLICY_TOKEN
    ):
        raise CapacityValidationError(
            "actor set requires validated pre-release concurrency policy"
        )
    policy = concurrency_policy.policy
    repo_root = concurrency_policy.repo_root
    scm_ref = concurrency_policy.scm_ref
    schema = _load_pinned_schema(repo_root, scm_ref, ACTOR_SET_SCHEMA)
    errors = _schema_errors(actor_set, schema)
    stage = resolve_pinned_profile_stage(
        repo_root,
        scm_ref,
        concurrency_policy.profile_stage_id,
        expected_sha256=policy["profile_stage_sha256"],
    )
    stage_value = require_pinned_profile_stage(stage)
    if stage.scenario is None:
        errors.append("substantive actor set requires a scenario-bound stage")
        scenario: dict[str, Any] = {}
    else:
        scenario = stage.scenario.scenario

    raw_evidence = tuple(role_evidence)
    evidence = tuple(
        validate_substantive_role_evidence(
            item.plan,
            item.receipt,
            item.actions,
            item.results,
        )
        for item in raw_evidence
        if isinstance(item, SubstantiveRoleEvidence)
    )
    if len(evidence) != len(raw_evidence):
        raise CapacityValidationError(
            "actor set requires validated substantive role evidence"
        )
    plans = tuple(item.plan for item in evidence)
    receipt_ids = [item.receipt.receipt_id for item in evidence]
    if len(receipt_ids) != len(set(receipt_ids)):
        errors.append("aggregate role receipts must have globally unique IDs")
    actor_slots = [plan.actor_slot for plan in plans]
    if len(actor_slots) != len(set(actor_slots)):
        errors.append("aggregate role evidence contains duplicate actor slots")
    fingerprints = [
        plan.plan["isolated_identity_fingerprint"] for plan in plans
    ]
    if len(fingerprints) != len(set(fingerprints)):
        errors.append("aggregate role evidence contains duplicate identities")
    expected_slots = set(_scenario_actor_slots(scenario))
    if set(actor_slots) != expected_slots:
        errors.append("aggregate actor cardinality does not match the scenario")
    for role, collection in _ACTOR_COLLECTIONS.items():
        scenario_slots = scenario.get("actor_slots", {}).get(collection, ())
        actual = {plan.actor_slot for plan in plans if plan.role == role}
        if actual != set(scenario_slots):
            errors.append(f"aggregate {role} slots do not match the scenario")
    if any(
        plan.scm_ref != scm_ref
        or plan.profile_stage_id != stage.stage_id
        or plan.profile_stage_sha256 != stage.canonical_sha256
        or plan.scenario_id != scenario.get("scenario_id")
        or plan.scenario_sha256
        != (stage.scenario.scenario_sha256 if stage.scenario else None)
        for plan in plans
    ):
        errors.append("all role evidence must bind one exact stage and scenario")
    evidence_role_authorities = sorted(
        (
            {
                "plan_id": plan.plan_id,
                "plan_sha256": plan.canonical_sha256,
            }
            for plan in plans
        ),
        key=lambda item: item["plan_id"],
    )
    if (
        evidence_role_authorities
        != policy.get("role_plan_authorities")
    ):
        errors.append(
            "actor-set evidence does not match the policy's exact role plans"
        )
    try:
        evidence_prepared_authorities = sorted(
            _planned_prepared_action_authorities(plans),
            key=lambda item: item["action_id"],
        )
    except CapacityValidationError as error:
        errors.append(str(error))
        evidence_prepared_authorities = []
    if (
        evidence_prepared_authorities
        != policy.get("prepared_action_authorities")
    ):
        errors.append(
            "actor-set evidence does not match the policy's prepared actions"
        )

    common = {
        "scm_ref": scm_ref,
        "scenario_id": scenario.get("scenario_id"),
        "scenario_sha256": (
            stage.scenario.scenario_sha256 if stage.scenario else None
        ),
        "profile_stage_id": stage.stage_id,
        "profile_stage_sha256": stage.canonical_sha256,
        "execution_boundary": stage_value.get("execution_boundary"),
        "actor_trigger": stage_value.get("actor_trigger"),
        "release_id": concurrency_policy.release_id,
        "concurrency_policy_id": concurrency_policy.policy_id,
        "concurrency_policy_sha256": concurrency_policy.canonical_sha256,
        "clock_evidence_binding": policy.get("clock_evidence_binding"),
        "invocation_windows": policy.get("invocation_windows"),
    }
    for key, value in common.items():
        if actor_set.get(key) != value:
            errors.append(f"actor set {key} does not match frozen authority")
    expected_run_authority = {
        "release_id": concurrency_policy.release_id,
        "concurrency_policy_id": concurrency_policy.policy_id,
        "concurrency_policy_sha256": concurrency_policy.canonical_sha256,
    }
    if any(
        item.receipt.receipt.get("run_authority")
        != expected_run_authority
        for item in evidence
    ):
        errors.append(
            "every role receipt must bind the actor set's exact run authority"
        )
    if actor_set.get("controller_observation") != {
        "role_receipts_authored": False,
        "local_queue_detected": False,
        "throttle_detected": False,
    }:
        errors.append("actor set controller observation is not clean")

    try:
        release_observed_at = _parse_timestamp(
            actor_set.get("release_observed_at"),
            field_name="release_observed_at",
        )
    except CapacityValidationError as error:
        errors.append(str(error))
        release_observed_at = concurrency_policy.frozen_at
    if release_observed_at <= concurrency_policy.frozen_at:
        errors.append("concurrency policy must be frozen before release")

    action_records: list[
        tuple[ValidatedFrozenAction, ValidatedActionResult]
    ] = []
    for item in evidence:
        result_by_action = {
            result.action_id: result for result in item.results
        }
        for action in item.actions:
            result = result_by_action.get(action.action_id)
            if result is not None:
                action_records.append((action, result))
    action_ids = [action.action_id for action, _ in action_records]
    result_ids = [result.action_result_id for _, result in action_records]
    if len(action_ids) != len(set(action_ids)):
        errors.append("actor set action IDs must be globally unique")
    if len(result_ids) != len(set(result_ids)):
        errors.append("actor set result IDs must be globally unique")
    if set(action_ids) != set(policy.get("action_ids", ())):
        errors.append("actor set actions do not match the frozen policy")
    if any(
        action.release_id != concurrency_policy.release_id
        for action, _ in action_records
    ):
        errors.append("every action must bind the one frozen release")
    if any(
        action.action.get("concurrency_policy_id")
        != concurrency_policy.policy_id
        or action.action.get("concurrency_policy_sha256")
        != concurrency_policy.canonical_sha256
        for action, _ in action_records
    ):
        errors.append("every action must bind the exact concurrency policy")
    actual_prepared_authorities = sorted(
        (
            {
                "action_id": action.action_id,
                "prepared_action_sha256": action.action.get(
                    "prepared_action_sha256"
                ),
            }
            for action, _ in action_records
        ),
        key=lambda item: item["action_id"],
    )
    if actual_prepared_authorities != policy.get(
        "prepared_action_authorities"
    ):
        errors.append(
            "actor-set actions do not match the policy's prepared actions"
        )
    if any(
        result.invoked_at <= concurrency_policy.frozen_at
        for _, result in action_records
    ):
        errors.append("every action invocation must follow policy freeze")

    actor_entries = actor_set.get("actors")
    actor_by_slot: dict[str, dict[str, Any]] = {}
    if isinstance(actor_entries, list):
        for entry in actor_entries:
            if isinstance(entry, dict) and isinstance(entry.get("actor_slot"), str):
                if entry["actor_slot"] in actor_by_slot:
                    errors.append("actor set contains duplicate actor entries")
                actor_by_slot[entry["actor_slot"]] = entry
    if set(actor_by_slot) != expected_slots:
        errors.append("actor set actors do not cover every declared role")

    windows = _window_map(actor_set.get("invocation_windows"), errors=errors)
    if windows:
        earliest_open = min(item[0] for item in windows.values())
        latest_close = max(item[1] for item in windows.values())
    else:
        earliest_open = latest_close = 0
    for item in evidence:
        entry = actor_by_slot.get(item.plan.actor_slot)
        if entry is None:
            continue
        expected = {
            "role": item.plan.role,
            "plan_sha256": item.plan.canonical_sha256,
            "receipt_sha256": item.receipt.canonical_sha256,
        }
        for key, value in expected.items():
            if entry.get(key) != value:
                errors.append(
                    f"actor entry {item.plan.actor_slot} {key} does not match"
                )
        started = entry.get("started_offset_ns")
        completed = entry.get("completed_offset_ns")
        if (
            type(started) is not int
            or type(completed) is not int
            or started > earliest_open
            or completed < latest_close
        ):
            errors.append(
                "every declared actor must overlap every invocation window"
            )

    action_entries = actor_set.get("actions")
    entry_by_action: dict[str, dict[str, Any]] = {}
    if isinstance(action_entries, list):
        for entry in action_entries:
            if isinstance(entry, dict) and isinstance(entry.get("action_id"), str):
                if entry["action_id"] in entry_by_action:
                    errors.append("actor set contains duplicate action entries")
                entry_by_action[entry["action_id"]] = entry
    if set(entry_by_action) != set(action_ids):
        errors.append("actor set action entries do not cover exact terminal actions")

    offsets_by_kind: dict[str, list[int]] = {
        kind: [] for kind in _ACTION_WRAPPER_PATHS
    }
    for action, result in action_records:
        entry = entry_by_action.get(action.action_id)
        if entry is None:
            continue
        expected = {
            "action_kind": action.action_kind,
            "actor_slot": action.actor_slot,
            "action_sha256": action.canonical_sha256,
            "action_result_sha256": result.canonical_sha256,
        }
        for key, value in expected.items():
            if entry.get(key) != value:
                errors.append(f"action entry {action.action_id} {key} does not match")
        invoked = entry.get("invoked_offset_ns")
        terminal = entry.get("terminal_offset_ns")
        if type(invoked) is not int or type(terminal) is not int:
            errors.append("action offsets must be exact integers")
            continue
        if invoked >= terminal:
            errors.append("action terminal offset must follow invocation")
        owner = actor_by_slot.get(action.actor_slot)
        if owner is not None:
            owner_started = owner.get("started_offset_ns")
            owner_completed = owner.get("completed_offset_ns")
            if (
                type(owner_started) is not int
                or type(owner_completed) is not int
                or not (
                    owner_started
                    <= invoked
                    < terminal
                    <= owner_completed
                )
            ):
                errors.append(
                    f"action {action.action_id} must remain inside its "
                    "owning actor lifetime"
                )
        window = windows.get(action.action_kind)
        if window is not None and not window[0] <= invoked <= window[1]:
            errors.append(
                f"{action.action_kind} invocation falls outside frozen window"
            )
        offsets_by_kind[action.action_kind].append(invoked)

    skews: dict[str, int] = {}
    for kind, offsets in offsets_by_kind.items():
        window = windows.get(kind)
        if window is None:
            skews[kind] = 0
            continue
        try:
            skews[kind] = validate_invocation_offsets(
                offsets,
                max_emission_skew_ns=window[2],
                label=kind,
            )
        except CapacityValidationError as error:
            errors.append(str(error))
            skews[kind] = (
                max(offsets) - min(offsets) if offsets else 0
            )

    topology = scenario.get("listing_topology")
    sellers = topology.get("sellers") if isinstance(topology, dict) else []
    expected_services = {
        (seller.get("seller_slot"), seller.get("service_slot"))
        for seller in sellers
        if isinstance(seller, dict)
    }
    expected_listings = {
        (seller.get("seller_slot"), listing)
        for seller in sellers
        if isinstance(seller, dict)
        for listing in seller.get("listing_slots", ())
    }
    service_entries = actor_set.get("runtime_service_bindings")
    listing_entries = actor_set.get("runtime_listing_bindings")
    service_map: dict[tuple[Any, Any], dict[str, Any]] = {}
    listing_map: dict[tuple[Any, Any], dict[str, Any]] = {}
    for value, target, key_names, label in (
        (
            service_entries,
            service_map,
            ("seller_slot", "service_slot"),
            "runtime service",
        ),
        (
            listing_entries,
            listing_map,
            ("seller_slot", "listing_slot"),
            "runtime listing",
        ),
    ):
        if not isinstance(value, list):
            errors.append(f"{label} bindings must be an array")
            continue
        for entry in value:
            if not isinstance(entry, dict):
                continue
            key = (entry.get(key_names[0]), entry.get(key_names[1]))
            if key in target:
                errors.append(f"{label} bindings contain duplicate logical slots")
            try:
                binding = validate_privacy_preserving_binding(
                    entry.get("runtime_binding"),
                    expected_domain=RUNTIME_BINDING_DOMAIN,
                    field_name=f"{label}.runtime_binding",
                )
            except CapacityValidationError as error:
                errors.append(str(error))
                continue
            target[key] = binding
    if set(service_map) != expected_services:
        errors.append("runtime service map does not match seller topology")
    if set(listing_map) != expected_listings:
        errors.append("runtime listing map does not match seller/listing topology")
    all_binding_ids = [
        _binding_identity(binding)
        for binding in (*service_map.values(), *listing_map.values())
    ]
    if len(all_binding_ids) != len(set(all_binding_ids)):
        errors.append("runtime service and listing bindings must be one-to-one")

    request_ids: list[str] = []
    publication_pairs: list[tuple[Any, Any]] = []
    service_pairs: list[tuple[Any, Any]] = []
    for action, _ in action_records:
        selection = action.action["logical_selection"]
        binding = action.action["runtime_binding"]
        if action.action_kind == "seller-service-start":
            key = (selection.get("seller_slot"), selection.get("service_slot"))
            service_pairs.append(key)
            if service_map.get(key) != binding:
                errors.append("service action binding does not match service map")
        elif action.action_kind == "seller-listing-publication":
            key = (selection.get("seller_slot"), selection.get("listing_slot"))
            publication_pairs.append(key)
            if listing_map.get(key) != binding:
                errors.append("publication binding does not match listing map")
        else:
            request_ids.append(selection.get("request_id"))
            key = (selection.get("seller_slot"), selection.get("listing_slot"))
            if listing_map.get(key) != binding:
                errors.append("buyer binding does not match sealed listing map")
    expected_request_ids = [
        request["request_id"] for request in scenario.get("requests", ())
    ]
    if sorted(request_ids) != sorted(expected_request_ids):
        errors.append("buyer actions must cover each request exactly once")
    if sorted(publication_pairs) != sorted(expected_listings):
        errors.append("seller actions must publish each listing exactly once")
    if sorted(service_pairs) != sorted(expected_services):
        errors.append("seller actions must start each service exactly once")

    for seller_slot, listing_slot in expected_listings:
        publication = [
            entry_by_action[action.action_id]
            for action, _ in action_records
            if action.action_kind == "seller-listing-publication"
            and action.action["logical_selection"].get("seller_slot") == seller_slot
            and action.action["logical_selection"].get("listing_slot") == listing_slot
            and action.action_id in entry_by_action
        ]
        service = [
            entry_by_action[action.action_id]
            for action, _ in action_records
            if action.action_kind == "seller-service-start"
            and action.action["logical_selection"].get("seller_slot") == seller_slot
            and action.action_id in entry_by_action
        ]
        buyers = [
            entry_by_action[action.action_id]
            for action, _ in action_records
            if action.action_kind == "buyer-request"
            and action.action["logical_selection"].get("seller_slot") == seller_slot
            and action.action["logical_selection"].get("listing_slot") == listing_slot
            and action.action_id in entry_by_action
        ]
        if (
            len(publication) != 1
            or len(service) != 1
            or service[0]["terminal_offset_ns"]
            > publication[0]["invoked_offset_ns"]
        ):
            errors.append("seller service must start before exact publication")
        if len(publication) == 1 and any(
            publication[0]["terminal_offset_ns"] > buyer["invoked_offset_ns"]
            for buyer in buyers
        ):
            errors.append("listing publication must finish before buyer request")

    _raise_errors("actor set", errors)
    return ValidatedActorSet(
        actor_set_id=actor_set["actor_set_id"],
        profile_stage_id=stage.stage_id,
        scenario_id=scenario["scenario_id"],
        actor_slots=tuple(sorted(actor_slots)),
        runtime_service_bindings=tuple(service_entries),
        runtime_listing_bindings=tuple(listing_entries),
        buyer_invocation_skew_ns=skews["buyer-request"],
        publication_invocation_skew_ns=skews[
            "seller-listing-publication"
        ],
        concurrency_policy_sha256=concurrency_policy.canonical_sha256,
        canonical_sha256=canonical_sha256(actor_set),
        _canonical_bytes=canonical_json_bytes(actor_set),
        _validation_token=_VALIDATED_ACTOR_SET_TOKEN,
    )


def validate_mock_capture(
    capture: dict[str, Any],
    role_evidence: Sequence[SubstantiveRoleEvidence],
) -> ValidatedMockCapture:
    raw_evidence = tuple(role_evidence)
    evidence: tuple[SubstantiveRoleEvidence, ...] = tuple(
        validate_substantive_role_evidence(
            item.plan,
            item.receipt,
            item.actions,
            item.results,
        )
        for item in raw_evidence
        if isinstance(item, SubstantiveRoleEvidence)
    )
    if len(evidence) != len(raw_evidence):
        raise CapacityValidationError(
            "mock capture requires validated substantive role evidence"
        )
    if not evidence:
        raise CapacityValidationError("mock capture requires buyer and seller evidence")
    plans = tuple(item.plan for item in evidence)
    scm_refs = {plan.scm_ref for plan in plans}
    repo_roots = {plan.repo_root for plan in plans}
    if len(scm_refs) != 1 or len(repo_roots) != 1:
        raise CapacityValidationError("mock evidence must bind one SCM authority")
    scm_ref = next(iter(scm_refs))
    repo_root = next(iter(repo_roots))
    schema = _load_pinned_schema(repo_root, scm_ref, MOCK_CAPTURE_SCHEMA)
    errors = _schema_errors(capture, schema)
    stage = resolve_pinned_profile_stage(
        repo_root,
        scm_ref,
        "b1-s1-g1-mock",
        expected_sha256=capture.get("profile_stage_sha256"),
    )
    stage_value = require_pinned_profile_stage(stage)
    if stage.scenario is None:
        errors.append("mock capture stage lacks its pinned scenario")
        scenario_id = None
        scenario_sha256 = None
    else:
        scenario_id = stage.scenario.scenario_id
        scenario_sha256 = stage.scenario.scenario_sha256
    common = {
        "scm_ref": scm_ref,
        "scenario_id": scenario_id,
        "scenario_sha256": scenario_sha256,
        "profile_stage_id": stage.stage_id,
        "profile_stage_sha256": stage.canonical_sha256,
        "execution_boundary": "mock",
        "actor_trigger": "agent-triggered",
    }
    for key, value in common.items():
        if capture.get(key) != value:
            errors.append(f"mock capture {key} does not match pinned authority")
    if stage_value.get("expected_outcomes") is not None:
        errors.append("mock stage must not carry real outcome authority")
    roles = [plan.role for plan in plans]
    if set(roles) != {"buyer", "seller"}:
        errors.append("capture-only composition contains only buyer and seller roles")
    if len(roles) != 2:
        errors.append("B1 capture requires exactly one buyer and one seller")
    if any(plan.profile_stage_id != stage.stage_id for plan in plans):
        errors.append("mock role plans must bind the standalone mock stage")
    buyer_receipts = sorted(
        item.receipt.canonical_sha256
        for item in evidence
        if item.plan.role == "buyer"
    )
    seller_receipts = sorted(
        item.receipt.canonical_sha256
        for item in evidence
        if item.plan.role == "seller"
    )
    if sorted(capture.get("buyer_receipt_sha256s", ())) != buyer_receipts:
        errors.append("mock capture buyer receipts do not match")
    if sorted(capture.get("seller_receipt_sha256s", ())) != seller_receipts:
        errors.append("mock capture seller receipts do not match")
    fingerprints = [
        plan.plan["isolated_identity_fingerprint"] for plan in plans
    ]
    if len(fingerprints) != len(set(fingerprints)):
        errors.append("mock capture actor identities must be distinct")
    plan_ids = [plan.plan_id for plan in plans]
    receipt_ids = [item.receipt.receipt_id for item in evidence]
    if len(plan_ids) != len(set(plan_ids)):
        errors.append("mock role-plan IDs must be globally unique")
    if len(receipt_ids) != len(set(receipt_ids)):
        errors.append("mock role-receipt IDs must be globally unique")

    action_records: list[
        tuple[ValidatedFrozenAction, ValidatedActionResult]
    ] = []
    for item in evidence:
        result_by_action = {
            result.action_id: result for result in item.results
        }
        for action in item.actions:
            result = result_by_action.get(action.action_id)
            if result is None:
                errors.append(
                    f"mock action {action.action_id} lacks a terminal result"
                )
                continue
            action_records.append((action, result))
    action_ids = [action.action_id for action, _ in action_records]
    result_ids = [result.action_result_id for _, result in action_records]
    if len(action_ids) != len(set(action_ids)):
        errors.append("mock capture action IDs must be globally unique")
    if len(result_ids) != len(set(result_ids)):
        errors.append("mock capture result IDs must be globally unique")
    if any(result.result_kind != "emitted" for _, result in action_records):
        errors.append("mock composition requires successful one-shot captures")
    releases = {action.release_id for action, _ in action_records}
    if len(releases) != 1 or capture.get("release_id") not in releases:
        errors.append("mock capture must bind one common action release")
    expected_mock_run_authority = {
        "release_id": capture.get("release_id"),
        "concurrency_policy_id": None,
        "concurrency_policy_sha256": None,
    }
    if any(
        item.receipt.receipt.get("run_authority")
        != expected_mock_run_authority
        for item in evidence
    ):
        errors.append(
            "every mock role receipt must bind the exact capture release"
        )
    oracle_pairs = {
        (
            action.action["expected_result"]["oracle_authority_id"],
            action.action["expected_result"][
                "independent_oracle_authority_sha256"
            ],
        )
        for action, _ in action_records
    }
    if len(oracle_pairs) != 1:
        errors.append("mock actions must bind one exact capture oracle")
    else:
        oracle_id, oracle_sha256 = next(iter(oracle_pairs))
        if (
            capture.get("oracle_authority_id") != oracle_id
            or capture.get("oracle_authority_sha256") != oracle_sha256
        ):
            errors.append("mock capture oracle authority does not match actions")
    expected_action_sha256s = sorted(
        action.canonical_sha256 for action, _ in action_records
    )
    if sorted(capture.get("action_sha256s", ())) != expected_action_sha256s:
        errors.append("mock capture frozen actions do not match")
    expected_prepared_sha256s = sorted(
        action.action["prepared_action_sha256"]
        for action, _ in action_records
    )
    if (
        sorted(capture.get("prepared_action_sha256s", ()))
        != expected_prepared_sha256s
    ):
        errors.append("mock capture prepared actions do not match")
    expected_results = sorted(
        result.canonical_sha256 for _, result in action_records
    )
    if sorted(capture.get("action_result_sha256s", ())) != expected_results:
        errors.append("mock capture action results do not match")
    expected_payloads = sorted(
        (
            action.action_id,
            action.action_kind,
            action.actor_slot,
            action.release_id,
            action.canonical_sha256,
            action.action["prepared_action_sha256"],
            action.action["payload_sha256"],
            _binding_identity(action.action["runtime_binding"]),
            _binding_identity(action.action["concrete_payload_binding"]),
        )
        for action, _ in action_records
    )
    actual_payloads = sorted(
        (
            item.get("action_id"),
            item.get("action_kind"),
            item.get("actor_slot"),
            item.get("release_id"),
            item.get("action_sha256"),
            item.get("prepared_action_sha256"),
            item.get("payload_sha256"),
            _binding_identity(item.get("runtime_binding", {})),
            _binding_identity(item.get("concrete_payload_binding", {})),
        )
        for item in capture.get("captured_payloads", ())
        if isinstance(item, dict)
    )
    if actual_payloads != expected_payloads:
        errors.append("mock capture payload ledger does not match exact actions")

    scenario = stage.scenario.scenario if stage.scenario is not None else {}
    topology = scenario.get("listing_topology")
    sellers = topology.get("sellers") if isinstance(topology, dict) else []
    expected_services = {
        (seller.get("seller_slot"), seller.get("service_slot"))
        for seller in sellers
        if isinstance(seller, dict)
    }
    expected_listings = {
        (seller.get("seller_slot"), listing)
        for seller in sellers
        if isinstance(seller, dict)
        for listing in seller.get("listing_slots", ())
    }
    service_map: dict[tuple[Any, Any], dict[str, str]] = {}
    listing_map: dict[tuple[Any, Any], dict[str, str]] = {}
    for values, target, logical_key, label in (
        (
            capture.get("runtime_service_bindings"),
            service_map,
            "service_slot",
            "mock service",
        ),
        (
            capture.get("runtime_listing_bindings"),
            listing_map,
            "listing_slot",
            "mock listing",
        ),
    ):
        if not isinstance(values, list):
            errors.append(f"{label} bindings must be an array")
            continue
        for entry in values:
            if not isinstance(entry, dict):
                continue
            key = (entry.get("seller_slot"), entry.get(logical_key))
            if key in target:
                errors.append(f"{label} bindings contain duplicate slots")
                continue
            try:
                target[key] = validate_privacy_preserving_binding(
                    entry.get("runtime_binding"),
                    expected_domain=RUNTIME_BINDING_DOMAIN,
                    field_name=f"{label}.runtime_binding",
                )
            except CapacityValidationError as error:
                errors.append(str(error))
    if set(service_map) != expected_services:
        errors.append("mock service map does not match seller topology")
    if set(listing_map) != expected_listings:
        errors.append("mock listing map does not match listing topology")
    binding_ids = [
        _binding_identity(value)
        for value in (*service_map.values(), *listing_map.values())
    ]
    if len(binding_ids) != len(set(binding_ids)):
        errors.append("mock service and listing bindings must be distinct")
    for action, _ in action_records:
        selection = action.action["logical_selection"]
        runtime = action.action["runtime_binding"]
        if action.action_kind == "seller-service-start":
            key = (selection["seller_slot"], selection["service_slot"])
            expected_runtime = service_map.get(key)
        else:
            key = (selection["seller_slot"], selection["listing_slot"])
            expected_runtime = listing_map.get(key)
        if runtime != expected_runtime:
            errors.append(
                "mock action does not bind the exact service/listing map"
            )

    expected_capabilities = sorted(
        (
            plan.actor_slot,
            _binding_identity(
                plan.plan["actor_invocation_capability_binding"]
            ),
        )
        for plan in plans
    )
    if len(
        {capability for _, capability in expected_capabilities}
    ) != len(expected_capabilities):
        errors.append(
            "mock actors must have distinct invocation capabilities"
        )
    actual_capabilities = sorted(
        (
            item.get("actor_slot"),
            _binding_identity(item.get("binding", {})),
        )
        for item in capture.get("actor_invocation_capabilities", ())
        if isinstance(item, dict)
    )
    if actual_capabilities != expected_capabilities:
        errors.append("mock capture invocation capabilities do not match actors")
    if (
        capture.get("agent_ownership_proof_scope")
        != "portable-binding-only"
        or capture.get("private_actor_ownership_verified") is not False
    ):
        errors.append(
            "public mock capture cannot claim private process authentication"
        )
    buyers = [item for item in evidence if item.plan.role == "buyer"]
    if any(
        item.receipt.receipt["role_evidence"].get("guest_verification")
        is not None
        for item in buyers
    ):
        errors.append("mock buyer cannot claim guest or CUDA success")
    if (
        capture.get("live_resource_ledger") != []
        or capture.get("complete_stage_actor_set_claimed") is not False
        or capture.get("registry_admission_claimed") is not False
        or capture.get("real_oracle_claimed") is not False
        or capture.get("capacity_claimed") is not False
    ):
        errors.append("mock capture exceeds its preparation-only boundary")

    by_kind = {
        kind: [
            result
            for action, result in action_records
            if action.action_kind == kind
        ]
        for kind in _ACTION_WRAPPER_PATHS
    }
    if any(len(values) != 1 for values in by_kind.values()):
        errors.append("B1 mock capture requires exactly three owned actions")
    elif not (
        by_kind["seller-service-start"][0].terminal_at
        <= by_kind["seller-listing-publication"][0].invoked_at
        and by_kind["seller-listing-publication"][0].terminal_at
        <= by_kind["buyer-request"][0].invoked_at
    ):
        errors.append(
            "mock capture must order service start, publication, then purchase"
        )

    try:
        completed_at = _parse_timestamp(
            capture.get("completed_at"),
            field_name="completed_at",
        )
    except CapacityValidationError as error:
        errors.append(str(error))
    else:
        terminal_times = [
            result.terminal_at for _, result in action_records
        ] + [item.receipt.completed_at for item in evidence]
        if terminal_times and completed_at < max(terminal_times):
            errors.append(
                "mock capture completion must follow every action and role"
            )

    _raise_errors("mock capture", errors)
    return ValidatedMockCapture(
        capture_id=capture["capture_id"],
        scm_ref=scm_ref,
        canonical_sha256=canonical_sha256(capture),
        _canonical_bytes=canonical_json_bytes(capture),
        _validation_token=_VALIDATED_MOCK_CAPTURE_TOKEN,
    )


def _owner_only_directory(path: Path, *, label: str) -> Path:
    directory = path.expanduser().absolute()
    try:
        metadata = directory.lstat()
    except FileNotFoundError:
        try:
            directory.mkdir(mode=0o700)
        except OSError as error:
            raise CapacityValidationError(
                f"{label} could not be created as an owner-only directory"
            ) from error
        metadata = directory.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise CapacityValidationError(
            f"{label} must be a real directory, not a symlink"
        )
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise CapacityValidationError(
            f"{label} must be owned by the current user with mode 0700 or stricter"
        )
    return directory


def _exclusive_owner_only_write(path: Path, content: bytes, *, label: str) -> None:
    parent = _owner_only_directory(path.parent, label=f"{label} parent")
    target = parent / path.name
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(target, flags, 0o600)
    except FileExistsError:
        raise
    except OSError as error:
        raise CapacityValidationError(
            f"{label} could not be created exclusively"
        ) from error
    try:
        view = memoryview(content)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise OSError("short owner-only artifact write")
            written += count
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise CapacityValidationError(
                f"{label} was not created as an owner-only regular file"
            )
    finally:
        os.close(descriptor)
    directory_descriptor = os.open(
        parent,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _atomic_install_owner_only(
    path: Path,
    content: bytes,
    *,
    label: str,
) -> None:
    """Install complete bytes with no replace and an fsynced directory entry."""
    parent = _owner_only_directory(path.parent, label=f"{label} parent")
    target = parent / path.name
    temporary = parent / (
        f".{path.name}.tmp-{os.getpid()}-{os.urandom(8).hex()}"
    )
    try:
        _exclusive_owner_only_write(
            temporary,
            content,
            label=f"{label} temporary record",
        )
        os.link(temporary, target, follow_symlinks=False)
        directory_descriptor = os.open(
            parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_owner_only_file(path: Path, *, label: str) -> bytes:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as error:
        raise CapacityValidationError(f"{label} is unavailable") from error
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise CapacityValidationError(
                f"{label} must be an owner-only regular file, not a symlink"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo != UTC:
        raise CapacityValidationError("capture clock must return UTC timestamps")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _action_result_value(
    action: ValidatedFrozenAction,
    *,
    invoked_at: datetime,
    terminal_at: datetime,
    attempt: int,
    actor_alive_at_invocation: bool,
    release_claim_count: int,
    checks: Mapping[str, bool],
    result_kind: str,
    failure_code: str | None,
) -> dict[str, Any]:
    identity = canonical_sha256(
        {
            "action_sha256": action.canonical_sha256,
            "attempt": attempt,
            "failure_code": failure_code,
            "invoked_at": _utc_timestamp(invoked_at),
            "release_claim_count": release_claim_count,
        }
    )[:24]
    emitted = result_kind == "emitted"
    return {
        "schema_version": 2,
        "action_result_id": f"action-result-{identity}",
        "action_id": action.action_id,
        "action_sha256": action.canonical_sha256,
        "actor_slot": action.actor_slot,
        "release_id": action.release_id,
        "attempt": attempt,
        "invoked_at": _utc_timestamp(invoked_at),
        "terminal_at": _utc_timestamp(terminal_at),
        "actor_alive_at_invocation": actor_alive_at_invocation,
        "release_claim_count": release_claim_count,
        "pre_emission_checks": dict(checks),
        "result_kind": result_kind,
        "emission_count": 1 if emitted else 0,
        "terminal_payload_sha256": (
            action.action["payload_sha256"] if emitted else None
        ),
        "failure_code": failure_code,
    }


_CAPTURE_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "release_id",
        "action_id",
        "action_sha256",
        "prepared_action_sha256",
        "actor_slot",
        "payload_sha256",
        "payload",
        "result_output",
        "first_result",
    }
)


def _validate_capture_record(
    content: bytes,
    *,
    action: ValidatedFrozenAction,
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], ValidatedActionResult, Path]:
    record = _strict_json_object(
        content,
        source="existing atomic action capture record",
    )
    errors: list[str] = []
    if content != canonical_json_bytes(record):
        errors.append("capture record must use exact canonical JSON bytes")
    if set(record) != _CAPTURE_RECORD_KEYS:
        errors.append("capture record fields are not the exact closed contract")
    expected = {
        "schema_version": 1,
        "release_id": action.release_id,
        "action_id": action.action_id,
        "action_sha256": action.canonical_sha256,
        "prepared_action_sha256": action.action[
            "prepared_action_sha256"
        ],
        "actor_slot": action.actor_slot,
        "payload_sha256": action.action["payload_sha256"],
        "payload": dict(payload),
    }
    for key, value in expected.items():
        if record.get(key) != value:
            errors.append(f"capture record {key} does not match the action")
    output_value = record.get("result_output")
    if (
        not isinstance(output_value, str)
        or not output_value
        or not Path(output_value).is_absolute()
    ):
        errors.append("capture record result_output must be an absolute path")
        recorded_output = Path("/")
    else:
        recorded_output = Path(output_value)
    first_result = record.get("first_result")
    validated_first: ValidatedActionResult | None = None
    if not isinstance(first_result, dict):
        errors.append("capture record lacks its first terminal result")
    else:
        try:
            validated_first = validate_action_result(first_result, action)
        except CapacityValidationError as error:
            errors.append(str(error))
    _raise_errors("atomic action capture record", errors)
    assert validated_first is not None
    return record, validated_first, recorded_output


def _require_exact_owner_only_file(
    path: Path,
    expected: bytes,
    *,
    label: str,
) -> None:
    content = _read_owner_only_file(path, label=label)
    if content != expected:
        raise CapacityValidationError(
            f"{label} does not match the durable first result"
        )


def action_capture(
    action: ValidatedFrozenAction,
    plan: ValidatedRolePlan,
    *,
    payload_bytes: bytes,
    oracle_authority: ValidatedOracleAuthority,
    concurrency_policy: ValidatedConcurrencyPolicy | None,
    expected_action_kind: str,
    current_runtime_binding: Mapping[str, Any],
    current_concrete_payload_binding: Mapping[str, Any],
    current_actor_invocation_capability: Mapping[str, Any],
    actor_alive_at_invocation: bool,
    claim_ledger: Path,
    result_output: Path,
    attempt: int = 1,
    current_action: Mapping[str, Any] | None = None,
    current_plan: Mapping[str, Any] | None = None,
    current_oracle_authority: Mapping[str, Any] | None = None,
    current_payload_bytes: bytes | None = None,
    clock: Callable[[], datetime] | None = None,
) -> CapturedMockAction:
    """Capture one validated mock action without touching a live market.

    The action, role plan, oracle authority, logical payload, and current
    runtime binding are rechecked immediately before an exclusive
    ``(release_id, action_id)`` claim.  The public adapter deliberately admits
    only the standalone mock boundary; private infrastructure supplies the
    live adapter for real qualification and measured runs.
    """

    if (
        not isinstance(action, ValidatedFrozenAction)
        or action._validation_token is not _VALIDATED_ACTION_TOKEN
        or not isinstance(plan, ValidatedRolePlan)
        or plan._validation_token is not _VALIDATED_ROLE_PLAN_TOKEN
        or not isinstance(oracle_authority, ValidatedOracleAuthority)
        or oracle_authority._validation_token is not _VALIDATED_ORACLE_TOKEN
    ):
        raise CapacityValidationError(
            "action capture requires validated action, plan, and oracle authorities"
        )
    if concurrency_policy is not None:
        raise CapacityValidationError(
            "public action capture is mock-only and cannot consume a real policy"
        )
    if plan.profile_stage.stage.get("execution_boundary") != "mock":
        raise CapacityValidationError(
            "public action capture cannot execute real qualification or measured actions"
        )
    if oracle_authority.authority.get("oracle_kind") != "capture-only":
        raise CapacityValidationError(
            "public action capture requires the capture-only oracle"
        )

    ledger = _owner_only_directory(claim_ledger, label="claim ledger")
    result_parent = _owner_only_directory(
        result_output.parent,
        label="result output parent",
    )
    result_path = result_parent / result_output.name
    claim_name = hashlib.sha256(
        f"{action.release_id}\0{action.action_id}".encode("utf-8")
    ).hexdigest()
    record_path = ledger / f"{claim_name}.capture-record.json"

    now = clock or (lambda: datetime.now(UTC))
    invoked_at = now()
    if invoked_at.tzinfo != UTC:
        raise CapacityValidationError("capture clock must return UTC timestamps")

    all_checks = {
        "authority_unchanged": True,
        "payload_unchanged": True,
        "selection_unchanged": True,
        "runtime_binding_unchanged": True,
        "wrapper_unchanged": True,
    }
    checks = dict(all_checks)
    frozen_action_value = action.action
    frozen_plan_value = plan.plan
    frozen_oracle_value = oracle_authority.authority
    observed_payload = (
        payload_bytes if current_payload_bytes is None else current_payload_bytes
    )

    if (
        (current_action is not None and dict(current_action) != frozen_action_value)
        or (current_plan is not None and dict(current_plan) != frozen_plan_value)
        or (
            current_oracle_authority is not None
            and dict(current_oracle_authority) != frozen_oracle_value
        )
    ):
        checks["authority_unchanged"] = False

    try:
        refreshed_plan = validate_role_plan(
            frozen_plan_value,
            plan.repo_root,
            expected_scm_ref=plan.scm_ref,
        )
        refreshed_oracle = validate_oracle_authority(
            frozen_oracle_value,
            plan.repo_root,
        )
    except (CapacityValidationError, json.JSONDecodeError, OSError):
        checks["authority_unchanged"] = False
        refreshed_plan = plan
        refreshed_oracle = oracle_authority

    wrapper_path = _ACTION_WRAPPER_PATHS.get(action.action_kind)
    try:
        if wrapper_path is None:
            raise CapacityValidationError("unknown one-shot wrapper")
        _validate_tracked_content(
            frozen_action_value.get("wrapper"),
            plan.repo_root,
            plan.scm_ref,
            field_name="wrapper",
            expected_path=wrapper_path,
        )
    except (CapacityValidationError, json.JSONDecodeError, OSError):
        checks["wrapper_unchanged"] = False

    try:
        validate_frozen_action(
            frozen_action_value,
            refreshed_plan,
            payload_bytes=payload_bytes,
            oracle_authority=refreshed_oracle,
            concurrency_policy=None,
        )
    except (CapacityValidationError, json.JSONDecodeError, OSError):
        if checks["wrapper_unchanged"]:
            checks["authority_unchanged"] = False

    observed_payload_value: dict[str, Any] | None
    try:
        observed_payload_value = _strict_json_object(
            observed_payload,
            source="current action payload",
        )
        if observed_payload != canonical_json_bytes(observed_payload_value):
            raise CapacityValidationError(
                "current action payload is not exact canonical JSON"
            )
    except (CapacityValidationError, json.JSONDecodeError, UnicodeDecodeError):
        observed_payload_value = None
        checks["payload_unchanged"] = False
        checks["selection_unchanged"] = False
    else:
        if hashlib.sha256(observed_payload).hexdigest() != frozen_action_value.get(
            "payload_sha256"
        ):
            checks["payload_unchanged"] = False
        if observed_payload_value.get(
            "logical_selection"
        ) != frozen_action_value.get("logical_selection"):
            checks["selection_unchanged"] = False
    if expected_action_kind != action.action_kind:
        checks["selection_unchanged"] = False
    try:
        validated_binding = validate_privacy_preserving_binding(
            dict(current_runtime_binding),
            expected_domain=RUNTIME_BINDING_DOMAIN,
            field_name="current_runtime_binding",
        )
    except CapacityValidationError:
        checks["runtime_binding_unchanged"] = False
    else:
        if validated_binding != frozen_action_value.get("runtime_binding"):
            checks["runtime_binding_unchanged"] = False
    try:
        validated_concrete_binding = validate_privacy_preserving_binding(
            dict(current_concrete_payload_binding),
            expected_domain=CONCRETE_PAYLOAD_BINDING_DOMAIN,
            field_name="current_concrete_payload_binding",
        )
    except CapacityValidationError:
        checks["payload_unchanged"] = False
    else:
        if validated_concrete_binding != frozen_action_value.get(
            "concrete_payload_binding"
        ):
            checks["payload_unchanged"] = False
    try:
        validated_capability = validate_privacy_preserving_binding(
            dict(current_actor_invocation_capability),
            expected_domain=ACTOR_INVOCATION_BINDING_DOMAIN,
            field_name="current_actor_invocation_capability",
        )
    except CapacityValidationError:
        checks["authority_unchanged"] = False
    else:
        if validated_capability != frozen_action_value.get(
            "actor_invocation_capability_binding"
        ):
            checks["authority_unchanged"] = False

    failure_code: str | None = None
    release_claim_count = 1
    recovered = False
    if type(attempt) is not int or attempt < 1:
        raise CapacityValidationError("action capture attempt must be a positive integer")
    if attempt > 1:
        checks = dict(all_checks)
        failure_code = "unauthorized-retry"
    elif not actor_alive_at_invocation:
        checks = dict(all_checks)
        failure_code = "actor-exited"
    else:
        failure_precedence = (
            ("authority_unchanged", "authority-changed"),
            ("wrapper_unchanged", "wrapper-changed"),
            ("payload_unchanged", "payload-changed"),
            ("selection_unchanged", "selection-changed"),
            ("runtime_binding_unchanged", "runtime-binding-changed"),
        )
        failure_code = next(
            (
                code
                for check, code in failure_precedence
                if checks[check] is False
            ),
            None,
        )

    terminal_at = now()
    if terminal_at.tzinfo != UTC:
        raise CapacityValidationError("capture clock must return UTC timestamps")
    if terminal_at <= invoked_at:
        terminal_at = invoked_at + timedelta(microseconds=1)
    result_kind = "emitted" if failure_code is None else "rejected-before-emission"
    result_value = _action_result_value(
        action,
        invoked_at=invoked_at,
        terminal_at=terminal_at,
        attempt=attempt,
        actor_alive_at_invocation=actor_alive_at_invocation,
        release_claim_count=release_claim_count,
        checks=checks,
        result_kind=result_kind,
        failure_code=failure_code,
    )
    validated_result = validate_action_result(result_value, action)

    record_exists = False
    skip_materialize_existing_duplicate = False
    payload_value = _strict_json_object(
        payload_bytes,
        source="captured logical payload",
    )
    record_value = {
        "schema_version": 1,
        "release_id": action.release_id,
        "action_id": action.action_id,
        "action_sha256": action.canonical_sha256,
        "prepared_action_sha256": action.action[
            "prepared_action_sha256"
        ],
        "actor_slot": action.actor_slot,
        "payload_sha256": action.action["payload_sha256"],
        "payload": payload_value,
        "result_output": str(result_path),
        "first_result": result_value,
    }

    def consume_existing_record() -> tuple[
        ValidatedActionResult,
        dict[str, Any],
        bool,
        bool,
    ]:
        existing_bytes = _read_owner_only_file(
            record_path,
            label="existing atomic action capture record",
        )
        (
            _,
            first_result,
            recorded_output,
        ) = _validate_capture_record(
            existing_bytes,
            action=action,
            payload=payload_value,
        )
        if recorded_output == result_path:
            try:
                result_path.lstat()
            except FileNotFoundError:
                return first_result, first_result.result, True, False
            _require_exact_owner_only_file(
                result_path,
                first_result._canonical_bytes,
                label="existing action result output",
            )
            skip_existing_output = True
        else:
            skip_existing_output = False
        duplicate_value = _action_result_value(
            action,
            invoked_at=invoked_at,
            terminal_at=terminal_at,
            attempt=attempt,
            actor_alive_at_invocation=actor_alive_at_invocation,
            release_claim_count=2,
            checks=all_checks,
            result_kind="rejected-before-emission",
            failure_code="duplicate-release",
        )
        return (
            validate_action_result(duplicate_value, action),
            duplicate_value,
            False,
            skip_existing_output,
        )

    try:
        _atomic_install_owner_only(
            record_path,
            canonical_json_bytes(record_value),
            label="atomic action capture record",
        )
    except FileExistsError:
        (
            validated_result,
            result_value,
            recovered,
            skip_materialize_existing_duplicate,
        ) = consume_existing_record()
        record_exists = True
    except (CapacityValidationError, OSError) as install_error:
        try:
            record_path.lstat()
        except FileNotFoundError:
            raise CapacityValidationError(
                "atomic action claim could not be durably installed"
            ) from install_error
        else:
            (
                validated_result,
                result_value,
                recovered,
                skip_materialize_existing_duplicate,
            ) = consume_existing_record()
            record_exists = True
    else:
        record_exists = True

    should_materialize = not skip_materialize_existing_duplicate
    if should_materialize:
        intended_result_bytes = canonical_json_bytes(result_value)
        try:
            _atomic_install_owner_only(
                result_path,
                intended_result_bytes,
                label="action result",
            )
        except FileExistsError:
            _require_exact_owner_only_file(
                result_path,
                intended_result_bytes,
                label="existing action result output",
            )
        except (CapacityValidationError, OSError) as install_error:
            try:
                _require_exact_owner_only_file(
                    result_path,
                    intended_result_bytes,
                    label="post-error action result output",
                )
            except CapacityValidationError:
                raise install_error
    return CapturedMockAction(
        result=validated_result,
        record_path=record_path if record_exists else None,
        result_path=result_path,
        recovered=recovered,
    )
