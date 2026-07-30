from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from issue_discovery import capacity_roles
from issue_discovery.artifacts import ArtifactStore, utc_now_iso
from issue_discovery.clean_room import (
    CleanRoomSequence,
    load_clean_room_sequence,
    render_clean_room_script,
    render_step_command,
)
from issue_discovery.capacity import (
    CapacityValidationError,
    ingest_finding,
    resolve_pinned_scenario,
)
from issue_discovery.collectors import CollectorRunner, load_collectors
from issue_discovery.commands import CommandResult, run_shell_command
from issue_discovery.config import ToolPaths, load_yaml
from issue_discovery.issues import IssuePacketGenerator, IssueRepository
from issue_discovery.phases import CommandSpec, PhaseFile, PhaseSpec, load_phase_file
from issue_discovery.redaction import Redactor
from issue_discovery.workarounds import WorkaroundSpec, load_workarounds


def _strict_capacity_object(path: Path, *, label: str) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite number {value!r} is not valid")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate object key {key!r}")
            result[key] = value
        return result

    try:
        content = path.read_bytes()
    except OSError as exc:
        raise CapacityValidationError(f"{label} input is unavailable") from exc
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CapacityValidationError(f"{label} is not strict JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CapacityValidationError(f"{label} must be a JSON object")
    return value


def _capacity_bytes(path: Path, *, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise CapacityValidationError(f"{label} input is unavailable") from exc


def _capacity_success(
    *,
    artifact_kind: str,
    operation: str,
    sha256: str,
    identity: dict[str, object],
) -> int:
    print(
        json.dumps(
            {
                "artifact_kind": artifact_kind,
                **identity,
                "operation": operation,
                "sha256": sha256,
                "status": "valid",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


def _capacity_failure(artifact_kind: str, exc: BaseException) -> int:
    print(
        json.dumps(
            {
                "artifact_kind": artifact_kind,
                "error": str(exc),
                "status": "invalid",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 1


def _require_expected_scm_ref(
    actual: str,
    expected: str | None,
    *,
    label: str,
) -> None:
    if expected is not None and actual != expected:
        raise CapacityValidationError(
            f"{label} SCM ref does not match the selected campaign ref"
        )


def _validated_role_plan(
    path: Path,
    repo_root: Path,
    *,
    expected_scm_ref: str | None,
) -> capacity_roles.ValidatedRolePlan:
    return capacity_roles.validate_role_plan(
        _strict_capacity_object(path, label="role plan"),
        repo_root,
        expected_scm_ref=expected_scm_ref,
    )


def _validated_role_plans(
    paths: Sequence[Path],
    repo_root: Path,
    *,
    expected_scm_ref: str | None,
) -> tuple[capacity_roles.ValidatedRolePlan, ...]:
    plans: dict[str, capacity_roles.ValidatedRolePlan] = {}
    for path in paths:
        plan = _validated_role_plan(
            path,
            repo_root,
            expected_scm_ref=expected_scm_ref,
        )
        prior = plans.get(plan.plan_id)
        if prior is not None and prior.canonical_sha256 != plan.canonical_sha256:
            raise CapacityValidationError(
                f"role plan ID {plan.plan_id!r} resolves to changed bytes"
            )
        plans[plan.plan_id] = plan
    if not plans:
        raise CapacityValidationError("at least one role plan is required")
    return tuple(plans.values())


def _merge_role_plans(
    owner: capacity_roles.ValidatedRolePlan,
    others: Sequence[capacity_roles.ValidatedRolePlan],
) -> tuple[capacity_roles.ValidatedRolePlan, ...]:
    plans = {owner.plan_id: owner}
    for plan in others:
        prior = plans.get(plan.plan_id)
        if prior is not None and prior.canonical_sha256 != plan.canonical_sha256:
            raise CapacityValidationError(
                f"role plan ID {plan.plan_id!r} resolves to changed bytes"
            )
        plans[plan.plan_id] = plan
    return tuple(plans.values())


@dataclass(frozen=True, slots=True)
class _ValidatedActionContext:
    plan: capacity_roles.ValidatedRolePlan
    oracle_authority: capacity_roles.ValidatedOracleAuthority
    concurrency_policy: capacity_roles.ValidatedConcurrencyPolicy | None
    action: capacity_roles.ValidatedFrozenAction
    payload_bytes: bytes


def _validated_action_context(
    *,
    repo_root: Path,
    frozen_action: Path,
    role_plan: Path,
    payload: Path,
    oracle_authority: Path,
    observer_plan: Path | None,
    concurrency_policy: Path | None,
    policy_role_plans: Sequence[Path],
    expected_scm_ref: str | None,
) -> _ValidatedActionContext:
    owner = _validated_role_plan(
        role_plan,
        repo_root,
        expected_scm_ref=expected_scm_ref,
    )
    observer = (
        _validated_role_plan(
            observer_plan,
            repo_root,
            expected_scm_ref=expected_scm_ref,
        )
        if observer_plan is not None
        else None
    )
    oracle = capacity_roles.validate_oracle_authority(
        _strict_capacity_object(
            oracle_authority,
            label="oracle authority",
        ),
        repo_root,
        observer_plan=observer,
    )
    _require_expected_scm_ref(
        oracle.scm_ref,
        expected_scm_ref,
        label="oracle authority",
    )
    policy = None
    if concurrency_policy is not None:
        policy_plans = _validated_role_plans(
            policy_role_plans,
            repo_root,
            expected_scm_ref=expected_scm_ref,
        ) if policy_role_plans else ()
        policy = capacity_roles.validate_concurrency_policy(
            _strict_capacity_object(
                concurrency_policy,
                label="concurrency policy",
            ),
            repo_root,
            _merge_role_plans(owner, policy_plans),
        )
        _require_expected_scm_ref(
            policy.scm_ref,
            expected_scm_ref,
            label="concurrency policy",
        )
    payload_bytes = _capacity_bytes(payload, label="action payload")
    action = capacity_roles.validate_frozen_action(
        _strict_capacity_object(frozen_action, label="frozen action"),
        owner,
        payload_bytes=payload_bytes,
        oracle_authority=oracle,
        concurrency_policy=policy,
    )
    _require_expected_scm_ref(
        action.scm_ref,
        expected_scm_ref,
        label="frozen action",
    )
    return _ValidatedActionContext(
        plan=owner,
        oracle_authority=oracle,
        concurrency_policy=policy,
        action=action,
        payload_bytes=payload_bytes,
    )


def _unique_capacity_objects(
    paths: Sequence[Path],
    *,
    label: str,
    identity_field: str,
) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for path in paths:
        value = _strict_capacity_object(path, label=label)
        identity = value.get(identity_field)
        if not isinstance(identity, str) or not identity:
            raise CapacityValidationError(
                f"{label} lacks string {identity_field}"
            )
        if identity in values:
            raise CapacityValidationError(
                f"duplicate {label} {identity_field} {identity!r}"
            )
        values[identity] = value
    return values


@dataclass(frozen=True, slots=True)
class _ValidatedEvidenceBundle:
    evidence: tuple[capacity_roles.SubstantiveRoleEvidence, ...]
    concurrency_policy: capacity_roles.ValidatedConcurrencyPolicy | None


def _validated_evidence_bundle(
    *,
    repo_root: Path,
    role_plans: Sequence[Path],
    role_receipts: Sequence[Path],
    frozen_actions: Sequence[Path],
    payloads: Sequence[Path],
    oracle_authorities: Sequence[Path],
    action_results: Sequence[Path],
    concurrency_policy: Path | None,
    expected_scm_ref: str | None,
) -> _ValidatedEvidenceBundle:
    plans = _validated_role_plans(
        role_plans,
        repo_root,
        expected_scm_ref=expected_scm_ref,
    )
    plans_by_id = {plan.plan_id: plan for plan in plans}
    plans_by_sha256 = {plan.canonical_sha256: plan for plan in plans}

    policy = None
    if concurrency_policy is not None:
        policy = capacity_roles.validate_concurrency_policy(
            _strict_capacity_object(
                concurrency_policy,
                label="concurrency policy",
            ),
            repo_root,
            plans,
        )
        _require_expected_scm_ref(
            policy.scm_ref,
            expected_scm_ref,
            label="concurrency policy",
        )

    oracle_values = _unique_capacity_objects(
        oracle_authorities,
        label="oracle authority",
        identity_field="oracle_authority_id",
    )
    oracles: dict[str, capacity_roles.ValidatedOracleAuthority] = {}
    for authority_id, value in oracle_values.items():
        observer_digest = value.get("observer_plan_sha256")
        observer = (
            plans_by_sha256.get(observer_digest)
            if isinstance(observer_digest, str)
            else None
        )
        oracle = capacity_roles.validate_oracle_authority(
            value,
            repo_root,
            observer_plan=observer,
        )
        _require_expected_scm_ref(
            oracle.scm_ref,
            expected_scm_ref,
            label="oracle authority",
        )
        oracles[authority_id] = oracle

    payload_values = _unique_capacity_objects(
        payloads,
        label="action payload",
        identity_field="action_id",
    )
    payload_bytes = {
        action_id: _capacity_bytes(path, label="action payload")
        for action_id, path in (
            (
                _strict_capacity_object(
                    payload_path,
                    label="action payload",
                ).get("action_id"),
                payload_path,
            )
            for payload_path in payloads
        )
        if isinstance(action_id, str)
    }
    if set(payload_values) != set(payload_bytes):
        raise CapacityValidationError("action payload identities are incomplete")

    action_values = _unique_capacity_objects(
        frozen_actions,
        label="frozen action",
        identity_field="action_id",
    )
    actions: dict[str, capacity_roles.ValidatedFrozenAction] = {}
    for action_id, value in action_values.items():
        plan = plans_by_id.get(value.get("role_plan_id"))
        if plan is None:
            raise CapacityValidationError(
                f"frozen action {action_id!r} has no supplied role plan"
            )
        expected_result = value.get("expected_result")
        oracle_id = (
            expected_result.get("oracle_authority_id")
            if isinstance(expected_result, dict)
            else None
        )
        oracle = oracles.get(oracle_id)
        if oracle is None:
            raise CapacityValidationError(
                f"frozen action {action_id!r} has no supplied oracle authority"
            )
        action = capacity_roles.validate_frozen_action(
            value,
            plan,
            payload_bytes=payload_bytes.get(action_id, b""),
            oracle_authority=oracle,
            concurrency_policy=policy,
        )
        actions[action_id] = action
    if set(payload_values) != set(actions):
        raise CapacityValidationError(
            "payload inputs must cover the exact frozen action set"
        )
    referenced_oracles = {
        value["expected_result"]["oracle_authority_id"]
        for value in action_values.values()
    }
    if referenced_oracles != set(oracles):
        raise CapacityValidationError(
            "oracle inputs must cover the exact frozen action authority set"
        )

    result_values = _unique_capacity_objects(
        action_results,
        label="action result",
        identity_field="action_result_id",
    )
    results: dict[str, capacity_roles.ValidatedActionResult] = {}
    for value in result_values.values():
        action_id = value.get("action_id")
        action = actions.get(action_id)
        if action is None:
            raise CapacityValidationError(
                "action result has no supplied frozen action"
            )
        if action_id in results:
            raise CapacityValidationError(
                f"more than one action result claims {action_id!r}"
            )
        results[action_id] = capacity_roles.validate_action_result(value, action)
    if set(results) != set(actions):
        raise CapacityValidationError(
            "result inputs must cover the exact frozen action set"
        )

    receipt_values = _unique_capacity_objects(
        role_receipts,
        label="role receipt",
        identity_field="receipt_id",
    )
    receipts: dict[str, capacity_roles.ValidatedRoleReceipt] = {}
    for value in receipt_values.values():
        plan_id = value.get("plan_id")
        plan = plans_by_id.get(plan_id)
        if plan is None:
            raise CapacityValidationError(
                "role receipt has no supplied role plan"
            )
        if plan_id in receipts:
            raise CapacityValidationError(
                f"more than one role receipt claims {plan_id!r}"
            )
        receipts[plan_id] = capacity_roles.validate_role_receipt(value, plan)
    if set(receipts) != set(plans_by_id):
        raise CapacityValidationError(
            "receipt inputs must cover the exact role-plan set"
        )

    evidence: list[capacity_roles.SubstantiveRoleEvidence] = []
    for plan in plans:
        owned_actions = tuple(
            action
            for action_id, action in actions.items()
            if action_values[action_id].get("role_plan_id") == plan.plan_id
        )
        owned_results = tuple(results[action.action_id] for action in owned_actions)
        evidence.append(
            capacity_roles.validate_substantive_role_evidence(
                plan,
                receipts[plan.plan_id],
                owned_actions,
                owned_results,
            )
        )
    return _ValidatedEvidenceBundle(
        evidence=tuple(evidence),
        concurrency_policy=policy,
    )


@dataclass
class RunState:
    phase_status: dict[str, str] = field(default_factory=dict)
    failed_phases: list[str] = field(default_factory=list)
    skipped_phases: list[str] = field(default_factory=list)
    blocking_failure: str | None = None

    @property
    def failed(self) -> bool:
        return bool(self.failed_phases or self.blocking_failure)


class DiscoveryRunner:
    def __init__(self, repo_root: Path, output_dir: Path | None = None, dry_run: bool = False) -> None:
        self.repo_root = repo_root.resolve()
        self.output_dir = output_dir.resolve() if output_dir is not None else None
        self.dry_run = dry_run
        self.paths = ToolPaths(self.repo_root)

    def run_strict(self) -> int:
        phase_path = self.paths.config_dir / "phases" / "local.yaml"
        return self._run_phase_file(
            mode="strict",
            phase_path=phase_path,
            selected_phase_ids=None,
            workaround=None,
        )

    def run_continue(self, workaround_ids: tuple[str, ...]) -> int:
        if not workaround_ids:
            print("at least one workaround is required")
            return 2
        available = load_workarounds(self.paths.config_dir / "workarounds.yaml")
        missing = [workaround_id for workaround_id in workaround_ids if workaround_id not in available]
        if missing:
            print(f"unknown workaround: {', '.join(missing)}")
            print("available workarounds:")
            for key in sorted(available):
                print(f"  - {key}")
            return 2
        specs = tuple(available[workaround_id] for workaround_id in workaround_ids)
        phase_path = self.paths.config_dir / "phases" / "local.yaml"
        return self._run_phase_file(
            mode="continue",
            phase_path=phase_path,
            selected_phase_ids=None,
            workaround=specs,
        )

    def run_profile(self, name: str) -> int:
        profiles = load_yaml(self.paths.config_dir / "profiles.yaml").get("profiles", [])
        selected = next((item for item in profiles if item.get("id") == name), None)
        if selected is None:
            print(f"unknown profile: {name}")
            print("available profiles:")
            for item in profiles:
                print(f"  - {item['id']}")
            return 2
        phase_path = self.paths.config_dir / str(selected["phase_file"])
        phase_ids = tuple(str(item) for item in selected.get("phases", []))
        profile_env = {str(key): str(value) for key, value in (selected.get("env") or {}).items()}
        return self._run_phase_file(
            mode=f"profile:{name}",
            phase_path=phase_path,
            selected_phase_ids=phase_ids,
            workaround=None,
            profile_env=profile_env,
        )

    def issue_list(self, run_dir: Path) -> int:
        repository = IssueRepository(run_dir.resolve(), repo_root=self.repo_root)
        for candidate in repository.list():
            labels = ",".join(candidate.get("labels", []))
            print(
                f"{candidate['fingerprint']}\t{candidate.get('state', 'unknown')}\t"
                f"{candidate['classification']}\t"
                f"{candidate['phase']}\t{labels}\t{candidate['title']}"
            )
        return 0

    def issue_show(self, run_dir: Path, fingerprint: str) -> int:
        repository = IssueRepository(run_dir.resolve(), repo_root=self.repo_root)
        body_path = repository.body_path(fingerprint)
        print(body_path.read_text(encoding="utf-8"), end="")
        return 0

    def issue_create(
        self,
        run_dir: Path,
        fingerprint: str,
        dry_run: bool,
        force: bool = False,
        destination_repo_root: Path | None = None,
    ) -> int:
        repository = IssueRepository(
            run_dir.resolve(),
            repo_root=(destination_repo_root or self.repo_root),
            policy_root=self.repo_root,
        )
        return repository.create(fingerprint, dry_run=dry_run, force=force)

    def issue_propose_fix(self, run_dir: Path, fingerprint: str, head_branch: str) -> int:
        repository = IssueRepository(run_dir.resolve(), repo_root=self.repo_root)
        try:
            path = repository.propose_fix(fingerprint, head_branch)
        except (KeyError, ValueError) as exc:
            print(str(exc))
            return 2
        print(path)
        return 0

    def issue_transition(self, run_dir: Path, fingerprint: str, state: str, detail: str) -> int:
        repository = IssueRepository(run_dir.resolve(), repo_root=self.repo_root)
        try:
            repository.transition(fingerprint, state, detail)
        except (KeyError, ValueError) as exc:
            print(str(exc))
            return 2
        print(f"capacity finding lifecycle: {fingerprint} -> {state}")
        return 0

    def capacity_scenario_validate(
        self,
        scenario: str,
        *,
        scm_ref: str,
        expected_sha256: str,
    ) -> int:
        try:
            resolved = resolve_pinned_scenario(
                self.repo_root,
                scm_ref,
                scenario,
                expected_sha256=expected_sha256,
            )
        except (CapacityValidationError, json.JSONDecodeError, OSError) as exc:
            print(f"capacity scenario invalid: {exc}")
            return 1
        print(
            json.dumps(
                {
                    "scenario_id": resolved.scenario_id,
                    "scenario_sha256": resolved.scenario_sha256,
                    "scm_ref": resolved.scm_ref,
                    "relative_path": resolved.relative_path,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0

    def capacity_scenario_sha256(self, scenario: str, *, scm_ref: str) -> int:
        try:
            resolved = resolve_pinned_scenario(
                self.repo_root,
                scm_ref,
                scenario,
            )
        except (CapacityValidationError, json.JSONDecodeError, OSError) as exc:
            print(f"capacity scenario invalid: {exc}")
            return 1
        print(resolved.scenario_sha256)
        return 0

    def capacity_finding_ingest(self, run_dir: Path, finding: Path) -> int:
        try:
            ingested = ingest_finding(
                run_dir.resolve(),
                finding.resolve(),
                self.repo_root,
            )
        except (CapacityValidationError, json.JSONDecodeError, OSError) as exc:
            print(f"capacity finding invalid: {exc}")
            return 1
        print(f"capacity finding ingested: {ingested['finding_id']}")
        return 0

    def capacity_role_plan_validate(
        self,
        role_plan: Path,
        *,
        expected_scm_ref: str | None = None,
    ) -> int:
        return self.capacity_role_plan(
            role_plan,
            operation="validate",
            expected_scm_ref=expected_scm_ref,
        )

    def capacity_role_plan_sha256(
        self,
        role_plan: Path,
        *,
        expected_scm_ref: str | None = None,
    ) -> int:
        return self.capacity_role_plan(
            role_plan,
            operation="sha256",
            expected_scm_ref=expected_scm_ref,
        )

    def capacity_role_plan(
        self,
        role_plan: Path,
        *,
        operation: str,
        expected_scm_ref: str | None = None,
    ) -> int:
        try:
            plan = _validated_role_plan(
                role_plan,
                self.repo_root,
                expected_scm_ref=expected_scm_ref,
            )
        except CapacityValidationError as exc:
            return _capacity_failure("role-plan", exc)
        return _capacity_success(
            artifact_kind="role-plan",
            operation=operation,
            sha256=plan.canonical_sha256,
            identity={
                "actor_slot": plan.actor_slot,
                "plan_id": plan.plan_id,
                "role": plan.role,
                "scm_ref": plan.scm_ref,
            },
        )

    def capacity_role_receipt_validate(
        self,
        role_receipt: Path,
        *,
        role_plan: Path,
        expected_scm_ref: str | None = None,
    ) -> int:
        return self.capacity_role_receipt(
            role_receipt,
            role_plan=role_plan,
            operation="validate",
            expected_scm_ref=expected_scm_ref,
        )

    def capacity_role_receipt_sha256(
        self,
        role_receipt: Path,
        *,
        role_plan: Path,
        expected_scm_ref: str | None = None,
    ) -> int:
        return self.capacity_role_receipt(
            role_receipt,
            role_plan=role_plan,
            operation="sha256",
            expected_scm_ref=expected_scm_ref,
        )

    def capacity_role_receipt(
        self,
        role_receipt: Path,
        *,
        role_plan: Path,
        operation: str,
        expected_scm_ref: str | None = None,
    ) -> int:
        try:
            plan = _validated_role_plan(
                role_plan,
                self.repo_root,
                expected_scm_ref=expected_scm_ref,
            )
            receipt = capacity_roles.validate_role_receipt(
                _strict_capacity_object(
                    role_receipt,
                    label="role receipt",
                ),
                plan,
            )
        except CapacityValidationError as exc:
            return _capacity_failure("role-receipt", exc)
        return _capacity_success(
            artifact_kind="role-receipt",
            operation=operation,
            sha256=receipt.canonical_sha256,
            identity={
                "actor_slot": receipt.actor_slot,
                "receipt_id": receipt.receipt_id,
                "role": receipt.role,
            },
        )

    def capacity_oracle_authority_validate(
        self,
        oracle_authority: Path,
        *,
        observer_plan: Path | None,
        expected_scm_ref: str | None = None,
    ) -> int:
        return self.capacity_oracle_authority(
            oracle_authority,
            observer_plan=observer_plan,
            operation="validate",
            expected_scm_ref=expected_scm_ref,
        )

    def capacity_oracle_authority_sha256(
        self,
        oracle_authority: Path,
        *,
        observer_plan: Path | None,
        expected_scm_ref: str | None = None,
    ) -> int:
        return self.capacity_oracle_authority(
            oracle_authority,
            observer_plan=observer_plan,
            operation="sha256",
            expected_scm_ref=expected_scm_ref,
        )

    def capacity_oracle_authority(
        self,
        oracle_authority: Path,
        *,
        observer_plan: Path | None,
        operation: str,
        expected_scm_ref: str | None = None,
    ) -> int:
        try:
            observer = (
                _validated_role_plan(
                    observer_plan,
                    self.repo_root,
                    expected_scm_ref=expected_scm_ref,
                )
                if observer_plan is not None
                else None
            )
            oracle = capacity_roles.validate_oracle_authority(
                _strict_capacity_object(
                    oracle_authority,
                    label="oracle authority",
                ),
                self.repo_root,
                observer_plan=observer,
            )
            _require_expected_scm_ref(
                oracle.scm_ref,
                expected_scm_ref,
                label="oracle authority",
            )
        except CapacityValidationError as exc:
            return _capacity_failure("oracle-authority", exc)
        return _capacity_success(
            artifact_kind="oracle-authority",
            operation=operation,
            sha256=oracle.canonical_sha256,
            identity={
                "oracle_authority_id": oracle.oracle_authority_id,
                "profile_stage_id": oracle.profile_stage_id,
                "scm_ref": oracle.scm_ref,
            },
        )

    def capacity_concurrency_policy_validate(
        self,
        concurrency_policy: Path,
        *,
        role_plans: Sequence[Path],
        expected_scm_ref: str | None = None,
    ) -> int:
        return self.capacity_concurrency_policy(
            concurrency_policy,
            role_plans=role_plans,
            operation="validate",
            expected_scm_ref=expected_scm_ref,
        )

    def capacity_concurrency_policy_sha256(
        self,
        concurrency_policy: Path,
        *,
        role_plans: Sequence[Path],
        expected_scm_ref: str | None = None,
    ) -> int:
        return self.capacity_concurrency_policy(
            concurrency_policy,
            role_plans=role_plans,
            operation="sha256",
            expected_scm_ref=expected_scm_ref,
        )

    def capacity_concurrency_policy(
        self,
        concurrency_policy: Path,
        *,
        role_plans: Sequence[Path],
        operation: str,
        expected_scm_ref: str | None = None,
    ) -> int:
        try:
            plans = _validated_role_plans(
                role_plans,
                self.repo_root,
                expected_scm_ref=expected_scm_ref,
            )
            policy = capacity_roles.validate_concurrency_policy(
                _strict_capacity_object(
                    concurrency_policy,
                    label="concurrency policy",
                ),
                self.repo_root,
                plans,
            )
            _require_expected_scm_ref(
                policy.scm_ref,
                expected_scm_ref,
                label="concurrency policy",
            )
        except CapacityValidationError as exc:
            return _capacity_failure("concurrency-policy", exc)
        return _capacity_success(
            artifact_kind="concurrency-policy",
            operation=operation,
            sha256=policy.canonical_sha256,
            identity={
                "policy_id": policy.policy_id,
                "profile_stage_id": policy.profile_stage_id,
                "release_id": policy.release_id,
                "scm_ref": policy.scm_ref,
            },
        )

    def capacity_frozen_action_validate(
        self,
        **context: Any,
    ) -> int:
        return self.capacity_frozen_action(
            **context,
            operation="validate",
        )

    def capacity_frozen_action_sha256(
        self,
        **context: Any,
    ) -> int:
        return self.capacity_frozen_action(
            **context,
            operation="sha256",
        )

    def capacity_frozen_action(
        self,
        *,
        frozen_action: Path,
        role_plan: Path,
        payload: Path,
        oracle_authority: Path,
        observer_plan: Path | None,
        concurrency_policy: Path | None,
        policy_role_plans: Sequence[Path],
        operation: str,
        expected_scm_ref: str | None = None,
    ) -> int:
        try:
            context = _validated_action_context(
                repo_root=self.repo_root,
                frozen_action=frozen_action,
                role_plan=role_plan,
                payload=payload,
                oracle_authority=oracle_authority,
                observer_plan=observer_plan,
                concurrency_policy=concurrency_policy,
                policy_role_plans=policy_role_plans,
                expected_scm_ref=expected_scm_ref,
            )
        except CapacityValidationError as exc:
            return _capacity_failure("frozen-action", exc)
        action = context.action
        return _capacity_success(
            artifact_kind="frozen-action",
            operation=operation,
            sha256=action.canonical_sha256,
            identity={
                "action_id": action.action_id,
                "action_kind": action.action_kind,
                "actor_slot": action.actor_slot,
                "release_id": action.release_id,
                "scm_ref": action.scm_ref,
            },
        )

    def capacity_action_result_validate(
        self,
        action_result: Path,
        **context: Any,
    ) -> int:
        return self.capacity_action_result(
            action_result,
            **context,
            operation="validate",
        )

    def capacity_action_result_sha256(
        self,
        action_result: Path,
        **context: Any,
    ) -> int:
        return self.capacity_action_result(
            action_result,
            **context,
            operation="sha256",
        )

    def capacity_action_result(
        self,
        action_result: Path,
        *,
        frozen_action: Path,
        role_plan: Path,
        payload: Path,
        oracle_authority: Path,
        observer_plan: Path | None,
        concurrency_policy: Path | None,
        policy_role_plans: Sequence[Path],
        operation: str,
        expected_scm_ref: str | None = None,
    ) -> int:
        try:
            context = _validated_action_context(
                repo_root=self.repo_root,
                frozen_action=frozen_action,
                role_plan=role_plan,
                payload=payload,
                oracle_authority=oracle_authority,
                observer_plan=observer_plan,
                concurrency_policy=concurrency_policy,
                policy_role_plans=policy_role_plans,
                expected_scm_ref=expected_scm_ref,
            )
            result = capacity_roles.validate_action_result(
                _strict_capacity_object(
                    action_result,
                    label="action result",
                ),
                context.action,
            )
        except CapacityValidationError as exc:
            return _capacity_failure("action-result", exc)
        return _capacity_success(
            artifact_kind="action-result",
            operation=operation,
            sha256=result.canonical_sha256,
            identity={
                "action_id": result.action_id,
                "action_result_id": result.action_result_id,
                "actor_slot": result.actor_slot,
                "result_kind": result.result_kind,
            },
        )

    def capacity_actor_set_validate(
        self,
        actor_set: Path,
        **context: Any,
    ) -> int:
        return self.capacity_actor_set(
            actor_set,
            **context,
            operation="validate",
        )

    def capacity_actor_set_sha256(
        self,
        actor_set: Path,
        **context: Any,
    ) -> int:
        return self.capacity_actor_set(
            actor_set,
            **context,
            operation="sha256",
        )

    def capacity_actor_set(
        self,
        actor_set: Path,
        *,
        concurrency_policy: Path,
        role_plans: Sequence[Path],
        role_receipts: Sequence[Path],
        frozen_actions: Sequence[Path],
        payloads: Sequence[Path],
        oracle_authorities: Sequence[Path],
        action_results: Sequence[Path],
        operation: str,
        expected_scm_ref: str | None = None,
    ) -> int:
        try:
            bundle = _validated_evidence_bundle(
                repo_root=self.repo_root,
                role_plans=role_plans,
                role_receipts=role_receipts,
                frozen_actions=frozen_actions,
                payloads=payloads,
                oracle_authorities=oracle_authorities,
                action_results=action_results,
                concurrency_policy=concurrency_policy,
                expected_scm_ref=expected_scm_ref,
            )
            if bundle.concurrency_policy is None:  # pragma: no cover - type guard
                raise CapacityValidationError(
                    "actor set requires a validated concurrency policy"
                )
            aggregate = capacity_roles.validate_substantive_actor_set(
                _strict_capacity_object(actor_set, label="actor set"),
                bundle.concurrency_policy,
                bundle.evidence,
            )
        except CapacityValidationError as exc:
            return _capacity_failure("actor-set", exc)
        return _capacity_success(
            artifact_kind="actor-set",
            operation=operation,
            sha256=aggregate.canonical_sha256,
            identity={
                "actor_set_id": aggregate.actor_set_id,
                "profile_stage_id": aggregate.profile_stage_id,
                "scenario_id": aggregate.scenario_id,
            },
        )

    def capacity_mock_capture_validate(
        self,
        mock_capture: Path,
        **context: Any,
    ) -> int:
        return self.capacity_mock_capture(
            mock_capture,
            **context,
            operation="validate",
        )

    def capacity_mock_capture_sha256(
        self,
        mock_capture: Path,
        **context: Any,
    ) -> int:
        return self.capacity_mock_capture(
            mock_capture,
            **context,
            operation="sha256",
        )

    def capacity_mock_capture(
        self,
        mock_capture: Path,
        *,
        role_plans: Sequence[Path],
        role_receipts: Sequence[Path],
        frozen_actions: Sequence[Path],
        payloads: Sequence[Path],
        oracle_authorities: Sequence[Path],
        action_results: Sequence[Path],
        operation: str,
        expected_scm_ref: str | None = None,
    ) -> int:
        try:
            bundle = _validated_evidence_bundle(
                repo_root=self.repo_root,
                role_plans=role_plans,
                role_receipts=role_receipts,
                frozen_actions=frozen_actions,
                payloads=payloads,
                oracle_authorities=oracle_authorities,
                action_results=action_results,
                concurrency_policy=None,
                expected_scm_ref=expected_scm_ref,
            )
            capture = capacity_roles.validate_mock_capture(
                _strict_capacity_object(
                    mock_capture,
                    label="mock capture",
                ),
                bundle.evidence,
            )
        except CapacityValidationError as exc:
            return _capacity_failure("mock-capture", exc)
        return _capacity_success(
            artifact_kind="mock-capture",
            operation=operation,
            sha256=capture.canonical_sha256,
            identity={
                "capture_id": capture.capture_id,
                "scm_ref": capture.scm_ref,
            },
        )

    def capacity_action_capture(
        self,
        *,
        frozen_action: Path,
        role_plan: Path,
        payload: Path,
        oracle_authority: Path,
        observer_plan: Path | None,
        concurrency_policy: Path | None,
        policy_role_plans: Sequence[Path],
        expected_scm_ref: str | None,
        expected_action_kind: str,
        current_runtime_binding: Path,
        current_concrete_payload_binding: Path,
        current_actor_invocation_capability: Path,
        actor_alive_at_invocation: bool,
        claim_ledger: Path,
        result_output: Path,
        current_action: Path | None = None,
        current_plan: Path | None = None,
        current_payload: Path | None = None,
        current_oracle_authority: Path | None = None,
    ) -> int:
        try:
            context = _validated_action_context(
                repo_root=self.repo_root,
                frozen_action=frozen_action,
                role_plan=role_plan,
                payload=payload,
                oracle_authority=oracle_authority,
                observer_plan=observer_plan,
                concurrency_policy=concurrency_policy,
                policy_role_plans=policy_role_plans,
                expected_scm_ref=expected_scm_ref,
            )
            if (
                context.plan.profile_stage.stage.get("execution_boundary")
                != "mock"
                or context.concurrency_policy is not None
            ):
                raise CapacityValidationError(
                    "public action-capture accepts capture-only mock actions"
                )
            runtime_binding = _strict_capacity_object(
                current_runtime_binding,
                label="current runtime binding",
            )
            concrete_payload_binding = _strict_capacity_object(
                current_concrete_payload_binding,
                label="current concrete-payload binding",
            )
            actor_invocation_capability = _strict_capacity_object(
                current_actor_invocation_capability,
                label="current actor-invocation capability",
            )
            current_action_value = (
                _strict_capacity_object(
                    current_action,
                    label="current frozen action",
                )
                if current_action is not None
                else None
            )
            current_plan_value = (
                _strict_capacity_object(
                    current_plan,
                    label="current role plan",
                )
                if current_plan is not None
                else None
            )
            current_payload_bytes = (
                _capacity_bytes(
                    current_payload,
                    label="current action payload",
                )
                if current_payload is not None
                else None
            )
            current_oracle_value = (
                _strict_capacity_object(
                    current_oracle_authority,
                    label="current oracle authority",
                )
                if current_oracle_authority is not None
                else None
            )
            captured = capacity_roles.action_capture(
                context.action,
                context.plan,
                payload_bytes=context.payload_bytes,
                oracle_authority=context.oracle_authority,
                concurrency_policy=context.concurrency_policy,
                expected_action_kind=expected_action_kind,
                current_runtime_binding=runtime_binding,
                current_concrete_payload_binding=(
                    concrete_payload_binding
                ),
                current_actor_invocation_capability=(
                    actor_invocation_capability
                ),
                current_action=current_action_value,
                current_plan=current_plan_value,
                current_payload_bytes=current_payload_bytes,
                current_oracle_authority=current_oracle_value,
                actor_alive_at_invocation=actor_alive_at_invocation,
                claim_ledger=claim_ledger,
                result_output=result_output,
            )
            result = captured.result
        except (CapacityValidationError, OSError) as exc:
            return _capacity_failure("action-capture", exc)
        status = _capacity_success(
            artifact_kind="action-result",
            operation="capture",
            sha256=result.canonical_sha256,
            identity={
                "action_id": result.action_id,
                "action_result_id": result.action_result_id,
                "actor_slot": result.actor_slot,
                "failure_code": result.result.get("failure_code"),
                "result_kind": result.result_kind,
            },
        )
        return status if result.result_kind == "emitted" else 1

    def clean_room_plan(self, sequence_name: str) -> int:
        sequence = self._load_clean_room_sequence(sequence_name)
        if sequence is None:
            return 2
        print(f"clean-room sequence: {sequence.id}")
        for index, step in enumerate(sequence.steps, start=1):
            print(f"{index}. {step.id}: {shlex.join(render_step_command(step))}")
        return 0

    def clean_room_script(self, sequence_name: str) -> int:
        sequence = self._load_clean_room_sequence(sequence_name)
        if sequence is None:
            return 2
        print(render_clean_room_script(sequence), end="")
        return 0

    def _run_phase_file(
        self,
        *,
        mode: str,
        phase_path: Path,
        selected_phase_ids: tuple[str, ...] | None,
        workaround: WorkaroundSpec | tuple[WorkaroundSpec, ...] | None,
        profile_env: dict[str, str] | None = None,
    ) -> int:
        phase_file = load_phase_file(phase_path)
        workarounds = _normalize_workarounds(workaround)
        phase_scope_start = _earliest_start_phase(phase_file, workarounds)
        if selected_phase_ids is None and phase_scope_start is not None:
            phases, assumed_phase_ids = _select_phases_from_start(phase_file, phase_scope_start)
        else:
            phases = _select_phases(phase_file, selected_phase_ids)
            assumed_phase_ids = ()
        profile_env = profile_env or {}
        env = {**profile_env, **_merged_workaround_env(workarounds)}
        skip_phases = {phase_id for spec in workarounds for phase_id in spec.skip_phases}

        if self.dry_run:
            self._print_plan(
                mode,
                phase_path,
                phases,
                workarounds,
                skip_phases,
                phase_scope_start,
                assumed_phase_ids,
                profile_env,
            )
            return 0

        store = self._create_store()
        git_identity = _git_identity(self.repo_root)
        redactor = Redactor.from_file(self.paths.config_dir / "redactions.yaml")
        collectors = CollectorRunner(
            repo_root=self.repo_root,
            store=store,
            collectors=load_collectors(self.paths.config_dir / "collectors.yaml"),
            redactor=redactor,
            env=env,
        )
        manifest = {
            "schema_version": 1,
            "run_id": store.run_id,
            "mode": mode,
            "status": "running",
            "repo_root": str(self.repo_root),
            "working_branch": git_identity["branch"],
            "observed_ref": git_identity["ref"],
            "phase_file": self._display_path(phase_path),
            "selected_phases": [phase.id for phase in phases],
            "phase_scope_start": phase_scope_start,
            "assumed_passed_phases": list(assumed_phase_ids),
            "profile_env": profile_env,
            "workaround": _workaround_json(workarounds[0]) if len(workarounds) == 1 else None,
            "workarounds": [_workaround_json(spec) for spec in workarounds],
            "output_dir": str(store.run_dir),
            "started_at": utc_now_iso(),
        }
        store.write_json("manifest.json", redactor.redact_mapping(manifest))
        print(f"issue-discovery run: {store.run_id}")
        print(f"artifacts: {store.run_dir}")

        collectors.collect_many(["git_status", "tool_versions"], reason="run_start")

        state = RunState()
        for spec in workarounds:
            if not self._apply_workaround(spec, store, redactor, env):
                state.blocking_failure = f"workaround:{spec.id}"
                break
        if state.blocking_failure is None:
            self._record_assumed_phases(phase_file, assumed_phase_ids, store, state)
            self._run_phases(phases, store, redactor, collectors, state, env, skip_phases)

        status = "failed" if state.failed else "passed"
        manifest.update(
            {
                "status": status,
                "completed_at": utc_now_iso(),
                "failed_phases": state.failed_phases,
                "skipped_phases": state.skipped_phases,
                "blocking_failure": state.blocking_failure,
            }
        )
        store.write_json("manifest.json", redactor.redact_mapping(manifest))
        candidates = IssuePacketGenerator(store.run_dir).generate()
        print(f"issue candidates: {len(candidates)}")
        print(f"status: {status}")
        return 1 if state.failed else 0

    def _run_phases(
        self,
        phases: tuple[PhaseSpec, ...],
        store: ArtifactStore,
        redactor: Redactor,
        collectors: CollectorRunner,
        state: RunState,
        env: dict[str, str],
        skip_phases: set[str],
    ) -> None:
        normal_phases = tuple(phase for phase in phases if not phase.always_run)
        always_phases = tuple(phase for phase in phases if phase.always_run)

        for phase in normal_phases:
            if state.blocking_failure is not None:
                self._record_skip(store, state, phase, "blocked")
                continue
            self._run_one_phase(phase, store, redactor, collectors, state, env, skip_phases)

        for phase in always_phases:
            self._run_one_phase(phase, store, redactor, collectors, state, env, set())

    def _run_one_phase(
        self,
        phase: PhaseSpec,
        store: ArtifactStore,
        redactor: Redactor,
        collectors: CollectorRunner,
        state: RunState,
        env: dict[str, str],
        skip_phases: set[str],
    ) -> None:
        if phase.id in skip_phases:
            self._record_skip(store, state, phase, "workaround_skip")
            return
        missing = [
            required
            for required in phase.requires
            if not _dependency_satisfied(state.phase_status.get(required))
        ]
        if missing and not phase.always_run:
            self._record_skip(store, state, phase, "dependency_not_passed", {"missing": missing})
            return

        print(f"phase: {phase.id}")
        command_results: list[CommandResult] = []
        failed_commands: list[CommandResult] = []
        started_at = utc_now_iso()
        for command in phase.commands:
            result = self._run_command(store, redactor, phase.id, command, env)
            command_results.append(result)
            if not result.ok:
                failed_commands.append(result)
                if phase.blocking:
                    break

        first_failed_command = failed_commands[0] if failed_commands else None
        status = "failed" if failed_commands else "passed"
        state.phase_status[phase.id] = status
        if status == "failed":
            state.failed_phases.append(phase.id)
            collectors.collect_many(phase.collect_on_failure, reason=f"phase_failed:{phase.id}")
            if phase.blocking and not phase.always_run:
                state.blocking_failure = phase.id
        else:
            collectors.collect_many(phase.collect_on_success, reason=f"phase_passed:{phase.id}")

        record = {
            "id": phase.id,
            "name": phase.name,
            "category": phase.category,
            "blocking": phase.blocking,
            "status": status,
            "started_at": started_at,
            "completed_at": utc_now_iso(),
            "commands": [result.to_json(store.run_dir) for result in command_results],
            "failed_command": first_failed_command.id if first_failed_command else None,
            "failed_commands": [result.id for result in failed_commands],
            "classifiers": phase.classifiers if status == "failed" else (),
        }
        store.append_jsonl("phases.jsonl", redactor.redact_mapping(record))

    def _record_assumed_phases(
        self,
        phase_file: PhaseFile,
        assumed_phase_ids: tuple[str, ...],
        store: ArtifactStore,
        state: RunState,
    ) -> None:
        if not assumed_phase_ids:
            return
        assumed = set(assumed_phase_ids)
        for phase in phase_file.phases:
            if phase.id not in assumed:
                continue
            state.phase_status[phase.id] = "assumed_passed"
            store.append_jsonl(
                "phases.jsonl",
                {
                    "id": phase.id,
                    "name": phase.name,
                    "category": phase.category,
                    "blocking": phase.blocking,
                    "status": "assumed_passed",
                    "reason": "continuation_scope",
                    "commands": [],
                    "completed_at": utc_now_iso(),
                },
            )

    def _run_command(
        self,
        store: ArtifactStore,
        redactor: Redactor,
        phase_id: str,
        command: CommandSpec,
        env: dict[str, str],
    ) -> CommandResult:
        cwd = (self.repo_root / command.workdir).resolve()
        return run_shell_command(
            command_id=command.id,
            command=command.run,
            cwd=cwd,
            output_dir=store.path("commands") / phase_id,
            env=env,
            timeout_seconds=command.timeout_seconds,
            redactor=redactor,
        )

    def _apply_workaround(
        self,
        workaround: WorkaroundSpec,
        store: ArtifactStore,
        redactor: Redactor,
        env: dict[str, str],
    ) -> bool:
        print(f"workaround: {workaround.id}")
        results = []
        ok = True
        for command in workaround.commands:
            result = self._run_command(store, redactor, f"workaround_{workaround.id}", command, env)
            results.append(result.to_json(store.run_dir))
            ok = ok and result.ok
            if not result.ok:
                break
        store.append_jsonl(
            "workarounds.jsonl",
            redactor.redact_mapping(
                {
                    "id": workaround.id,
                    "status": "passed" if ok else "failed",
                    "reason": workaround.reason,
                    "removal_condition": workaround.removal_condition,
                    "start_phase": workaround.start_phase,
                    "commands": results,
                    "env": env,
                    "skip_phases": workaround.skip_phases,
                    "completed_at": utc_now_iso(),
                }
            ),
        )
        return ok

    def _record_skip(
        self,
        store: ArtifactStore,
        state: RunState,
        phase: PhaseSpec,
        reason: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        state.phase_status[phase.id] = "skipped"
        state.skipped_phases.append(phase.id)
        record: dict[str, Any] = {
            "id": phase.id,
            "name": phase.name,
            "category": phase.category,
            "blocking": phase.blocking,
            "status": "skipped",
            "reason": reason,
            "commands": [],
            "completed_at": utc_now_iso(),
        }
        if extra:
            record.update(extra)
        store.append_jsonl("phases.jsonl", record)

    def _create_store(self) -> ArtifactStore:
        if self.output_dir is not None:
            return ArtifactStore.use_exact_dir(self.output_dir)
        return ArtifactStore.create(self.paths.default_output_root)

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.paths.config_dir))
        except ValueError:
            return str(path)

    def _load_clean_room_sequence(self, sequence_name: str) -> CleanRoomSequence | None:
        sequence_dir = self.paths.config_dir / "clean-room"
        sequence_path = sequence_dir / f"{sequence_name}.yaml"
        if not sequence_path.exists():
            print(f"unknown clean-room sequence: {sequence_name}")
            available = sorted(path.stem for path in sequence_dir.glob("*.yaml"))
            if available:
                print("available clean-room sequences:")
                for name in available:
                    print(f"  - {name}")
            return None
        try:
            return load_clean_room_sequence(sequence_path, sequence_name)
        except KeyError:
            print(f"unknown clean-room sequence: {sequence_name}")
            return None

    def _print_plan(
        self,
        mode: str,
        phase_path: Path,
        phases: tuple[PhaseSpec, ...],
        workarounds: tuple[WorkaroundSpec, ...],
        skip_phases: set[str],
        phase_scope_start: str | None,
        assumed_phase_ids: tuple[str, ...],
        profile_env: dict[str, str],
    ) -> None:
        output = self.output_dir if self.output_dir is not None else self.paths.default_output_root
        print(f"issue-discovery command: {mode}")
        print(f"repo_root: {self.repo_root}")
        print(f"output: {output}")
        print("dry_run: yes")
        print(f"phase_file: {phase_path}")
        if phase_scope_start is not None:
            print(f"phase_scope_start: {phase_scope_start}")
            print("assumed_passed_phases:")
            for phase_id in assumed_phase_ids:
                print(f"  - {phase_id}")
        if workarounds:
            print("workarounds:")
            for workaround in workarounds:
                print(f"  - {workaround.id}")
        if profile_env:
            print("profile_env:")
            for key in sorted(profile_env):
                print(f"  {key}={profile_env[key]}")
        print("phases:")
        for phase in phases:
            suffix = " (skipped by workaround)" if phase.id in skip_phases else ""
            print(f"  - {phase.id}{suffix}")

    def _print_pending(self, command: str) -> None:
        output = self.output_dir if self.output_dir is not None else self.paths.default_output_root
        dry_run = "yes" if self.dry_run else "no"
        print(f"issue-discovery command: {command}")
        print(f"repo_root: {self.repo_root}")
        print(f"output: {output}")
        print(f"dry_run: {dry_run}")


def _select_phases(phase_file: PhaseFile, selected_phase_ids: tuple[str, ...] | None) -> tuple[PhaseSpec, ...]:
    if selected_phase_ids is None:
        return phase_file.phases
    by_id = {phase.id: phase for phase in phase_file.phases}
    missing = [phase_id for phase_id in selected_phase_ids if phase_id not in by_id]
    if missing:
        raise ValueError(f"unknown phase ids in {phase_file.name}: {', '.join(missing)}")
    included: set[str] = set()
    visiting: set[str] = set()

    def include_with_dependencies(phase_id: str) -> None:
        if phase_id in included:
            return
        if phase_id in visiting:
            raise ValueError(f"cyclic phase dependency in {phase_file.name}: {phase_id}")
        phase = by_id.get(phase_id)
        if phase is None:
            raise ValueError(f"unknown required phase id in {phase_file.name}: {phase_id}")
        visiting.add(phase_id)
        for required in phase.requires:
            include_with_dependencies(required)
        visiting.remove(phase_id)
        included.add(phase_id)

    for phase_id in selected_phase_ids:
        include_with_dependencies(phase_id)

    return tuple(phase for phase in phase_file.phases if phase.id in included)


def _select_phases_from_start(
    phase_file: PhaseFile,
    start_phase: str,
) -> tuple[tuple[PhaseSpec, ...], tuple[str, ...]]:
    phase_ids = [phase.id for phase in phase_file.phases]
    try:
        start_index = phase_ids.index(start_phase)
    except ValueError as exc:
        raise ValueError(f"unknown continuation start phase in {phase_file.name}: {start_phase}") from exc
    selected = tuple(phase_file.phases[start_index:])
    assumed = _dependency_closure_outside_selection(phase_file, selected)
    return selected, assumed


def _earliest_start_phase(
    phase_file: PhaseFile,
    workarounds: tuple[WorkaroundSpec, ...],
) -> str | None:
    phase_indexes = {phase.id: index for index, phase in enumerate(phase_file.phases)}
    starts = []
    for workaround in workarounds:
        if workaround.start_phase is None:
            continue
        if workaround.start_phase not in phase_indexes:
            raise ValueError(
                f"unknown continuation start phase for {workaround.id}: {workaround.start_phase}"
            )
        starts.append(workaround.start_phase)
    if not starts:
        return None
    return min(starts, key=lambda phase_id: phase_indexes[phase_id])


def _dependency_satisfied(status: str | None) -> bool:
    return status in {"passed", "assumed_passed"}


def _dependency_closure_outside_selection(
    phase_file: PhaseFile,
    selected: tuple[PhaseSpec, ...],
) -> tuple[str, ...]:
    by_id = {phase.id: phase for phase in phase_file.phases}
    selected_ids = {phase.id for phase in selected}
    required: set[str] = set()
    visiting: set[str] = set()

    def visit(phase_id: str) -> None:
        if phase_id in visiting:
            raise ValueError(f"cyclic phase dependency in {phase_file.name}: {phase_id}")
        phase = by_id.get(phase_id)
        if phase is None:
            raise ValueError(f"unknown required phase id in {phase_file.name}: {phase_id}")
        visiting.add(phase_id)
        for required_id in phase.requires:
            if required_id not in selected_ids:
                required.add(required_id)
                visit(required_id)
        visiting.remove(phase_id)

    for phase in selected:
        visit(phase.id)

    return tuple(phase.id for phase in phase_file.phases if phase.id in required)


def _workaround_json(workaround: WorkaroundSpec | None) -> dict[str, Any] | None:
    if workaround is None:
        return None
    return {
        "id": workaround.id,
        "status": workaround.status,
        "issue": workaround.issue,
        "start_phase": workaround.start_phase,
        "reason": workaround.reason,
        "removal_condition": workaround.removal_condition,
        "skip_phases": workaround.skip_phases,
        "env": workaround.env or {},
    }


def _normalize_workarounds(
    workaround: WorkaroundSpec | tuple[WorkaroundSpec, ...] | None,
) -> tuple[WorkaroundSpec, ...]:
    if workaround is None:
        return ()
    if isinstance(workaround, tuple):
        return workaround
    return (workaround,)


def _git_identity(repo_root: Path) -> dict[str, str]:
    def git(*args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=False,
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            return "unknown"
        return completed.stdout.strip() or "unknown"

    return {
        "branch": git("branch", "--show-current"),
        "ref": git("rev-parse", "HEAD"),
    }


def _merged_workaround_env(workarounds: tuple[WorkaroundSpec, ...]) -> dict[str, str]:
    env: dict[str, str] = {}
    for workaround in workarounds:
        env.update(workaround.env or {})
    return env
