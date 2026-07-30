from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
from typing import Any, Iterator

import pytest

from issue_discovery.capacity import (
    CapacityValidationError,
    canonical_json_bytes,
    canonical_sha256,
    resolve_pinned_profile_stage,
)
from issue_discovery.capacity_roles import (
    ACTOR_INVOCATION_BINDING_DOMAIN,
    ACTION_RESULT_SCHEMA,
    BASELINE_EQUIVALENCE_BINDING_DOMAIN,
    BUYER_GUEST_STEPS,
    BUYER_INSTRUCTION_PATH,
    BUYER_PRE_RELEASE_STEPS,
    BUYER_REQUEST_WRAPPER_PATH,
    CUDA_RESULT_CHECKSUM,
    CUDA_SOURCE_PATH,
    CUDA_SUCCESS_MARKER,
    CUDA_WRAPPER_PATH,
    CONCRETE_PAYLOAD_BINDING_DOMAIN,
    HOST_OPERATOR_INSTRUCTION_PATH,
    HOST_OPERATOR_STEPS,
    MOCK_CAPTURE_SCHEMA,
    NATIVE_EVIDENCE_BINDING_DOMAIN,
    OBSERVER_INSTRUCTION_PATH,
    OBSERVER_STEPS,
    REVERSIBLE_BASELINE_BINDING_DOMAIN,
    RUNTIME_BINDING_DOMAIN,
    SELLER_INSTRUCTION_PATH,
    SELLER_PUBLICATION_WRAPPER_PATH,
    SELLER_SERVICE_WRAPPER_PATH,
    SELLER_STEPS,
    TOPOLOGY_BINDING_DOMAIN,
    SubstantiveRoleEvidence,
    ValidatedActionResult,
    ValidatedConcurrencyPolicy,
    ValidatedFrozenAction,
    ValidatedOracleAuthority,
    ValidatedRolePlan,
    action_capture,
    prepared_action_sha256,
    prepared_authority_sha256,
    validate_action_result,
    validate_concurrency_policy,
    validate_frozen_action,
    validate_invocation_offsets,
    validate_mock_capture,
    validate_oracle_authority,
    validate_privacy_preserving_binding,
    validate_role_plan,
    validate_role_receipt,
    validate_substantive_actor_set,
    validate_substantive_role_evidence,
    validate_unauthorized_retry_rejection,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]
CAPACITY_RESULT_SCHEMA = (
    "tools/issue-discovery/schemas/capacity-result.schema.json"
)
PROFILE_REGISTRY_PATH = (
    "tools/issue-discovery/config/capacity/profiles/g1-v2.json"
)
MOCK_STAGE_PATH = (
    "tools/issue-discovery/config/capacity/profile-stages/"
    "b1-s1-g1-mock.json"
)


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def binding(domain: str, identity: str) -> dict[str, str]:
    test_only_key = b"scm-capacity-contract-tests-only-v1"
    material = f"{domain}\0{identity}".encode("utf-8")
    return {
        "method": "hmac-sha256-v1",
        "domain": domain,
        "value": hmac.digest(test_only_key, material, "sha256").hex(),
    }


def tracked(repo: Path, path: str) -> dict[str, str]:
    return {
        "path": path,
        "sha256": hashlib.sha256((repo / path).read_bytes()).hexdigest(),
    }


@pytest.fixture
def authority_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "scm"
    repo.mkdir(mode=0o700)
    git(repo, "init")
    git(repo, "config", "user.name", "Capacity Contract Test")
    git(repo, "config", "user.email", "capacity@example.invalid")

    for relative in (
        "tools/issue-discovery/config/capacity",
        "tools/issue-discovery/schemas",
        "tools/issue-discovery/instructions/capacity",
        "tools/issue-discovery/workloads/cuda",
        "tools/issue-discovery/wrappers",
    ):
        source = REPO_ROOT / relative
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
    for relative in (BUYER_INSTRUCTION_PATH, SELLER_INSTRUCTION_PATH):
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, destination)

    git(repo, "add", ".")
    git(repo, "commit", "-m", "test: freeze capacity role authority")
    return repo, git(repo, "rev-parse", "HEAD")


def _seller_by_slot(scenario: dict[str, Any], actor_slot: str) -> dict[str, Any]:
    return next(
        seller
        for seller in scenario["listing_topology"]["sellers"]
        if seller["seller_slot"] == actor_slot
    )


def _request_by_buyer(scenario: dict[str, Any], actor_slot: str) -> dict[str, Any]:
    return next(
        request
        for request in scenario["requests"]
        if request["buyer_slot"] == actor_slot
    )


def _common_plan(
    repo: Path,
    scm_ref: str,
    stage_id: str,
    stage_sha256: str,
    scenario: dict[str, Any],
    scenario_sha256: str,
    *,
    role: str,
    actor_slot: str,
    instruction_path: str,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "plan_id": f"{actor_slot}-plan",
        "role": role,
        "actor_slot": actor_slot,
        "profile_stage_id": stage_id,
        "profile_stage_sha256": stage_sha256,
        "scenario_id": scenario["scenario_id"],
        "scenario_sha256": scenario_sha256,
        "scm_ref": scm_ref,
        "instruction": tracked(repo, instruction_path),
        "isolated_identity_fingerprint": digest(f"identity:{actor_slot}"),
        "actor_invocation_capability_binding": binding(
            ACTOR_INVOCATION_BINDING_DOMAIN,
            f"invocation:{actor_slot}",
        ),
    }


def _portable_intent(action_kind: str) -> dict[str, Any]:
    if action_kind == "buyer-request":
        return {
            "deal_type": "vm",
            "gpu_count": 1,
            "provisioner": "kvm-ansible",
            "settlement_flow": "negotiate-then-settle",
            "guest_check": "cuda-vector-add",
        }
    if action_kind == "seller-service-start":
        return {
            "deal_type": "vm",
            "service_isolation": "per-seller",
            "provisioner": "kvm-ansible",
        }
    return {
        "deal_type": "vm",
        "gpu_count": 1,
        "inventory_cardinality": 1,
        "provisioner": "kvm-ansible",
    }


def _oracle_value(
    repo: Path,
    scm_ref: str,
    stage_id: str,
    observer_plan_value: dict[str, Any] | None,
) -> dict[str, Any]:
    stage = resolve_pinned_profile_stage(repo, scm_ref, stage_id)
    boundary = stage.stage["execution_boundary"]
    is_mock = boundary == "mock"
    return {
        "schema_version": 2,
        "oracle_authority_id": f"{stage_id}-oracle",
        "scm_ref": scm_ref,
        "profile_stage_id": stage_id,
        "profile_stage_sha256": stage.canonical_sha256,
        "execution_boundary": boundary,
        "actor_trigger": stage.stage["actor_trigger"],
        "oracle_kind": (
            "capture-only" if is_mock else "independent-vm-capacity"
        ),
        "result_schema": tracked(
            repo,
            MOCK_CAPTURE_SCHEMA.as_posix()
            if is_mock
            else CAPACITY_RESULT_SCHEMA,
        ),
        "observer_plan_sha256": (
            None
            if is_mock
            else canonical_sha256(observer_plan_value)
        ),
        "real_oracle_allowed": not is_mock,
    }


def _prepared_action_fields(
    repo: Path,
    base_plan: dict[str, Any],
    oracle_value: dict[str, Any],
    *,
    action_id: str,
    action_kind: str,
    selection: dict[str, Any],
    wrapper_path: str,
    runtime_binding: dict[str, str],
) -> tuple[dict[str, Any], bytes]:
    payload = canonical_json_bytes(
        {
            "schema_version": 2,
            "action_id": action_id,
            "action_kind": action_kind,
            "actor_slot": base_plan["actor_slot"],
            "logical_selection": selection,
            "portable_intent": _portable_intent(action_kind),
            "operation": {
                "buyer-request": "market-negotiate-settle",
                "seller-service-start": "seller-service-start",
                "seller-listing-publication": "seller-inventory-publish",
            }[action_kind],
        }
    )
    return (
        {
            "schema_version": 2,
            "action_id": action_id,
            "action_kind": action_kind,
            "scm_ref": base_plan["scm_ref"],
            "scenario_id": base_plan["scenario_id"],
            "scenario_sha256": base_plan["scenario_sha256"],
            "profile_stage_id": base_plan["profile_stage_id"],
            "profile_stage_sha256": base_plan["profile_stage_sha256"],
            "actor_slot": base_plan["actor_slot"],
            "role_plan_id": base_plan["plan_id"],
            "isolated_identity_fingerprint": base_plan[
                "isolated_identity_fingerprint"
            ],
            "actor_invocation_capability_binding": base_plan[
                "actor_invocation_capability_binding"
            ],
            "logical_selection": selection,
            "runtime_binding": runtime_binding,
            "concrete_payload_binding": binding(
                CONCRETE_PAYLOAD_BINDING_DOMAIN,
                f"concrete:{action_id}",
            ),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "wrapper": tracked(repo, wrapper_path),
            "expected_result": {
                "schema_version": 2,
                "action_result_schema": tracked(
                    repo,
                    ACTION_RESULT_SCHEMA.as_posix(),
                ),
                "oracle_authority_id": oracle_value[
                    "oracle_authority_id"
                ],
                "independent_oracle_authority_sha256": canonical_sha256(
                    oracle_value
                ),
            },
        },
        payload,
    )


def _plan_values(
    repo: Path,
    scm_ref: str,
    stage_id: str,
    *,
    roles: set[str] | None = None,
) -> list[dict[str, Any]]:
    stage = resolve_pinned_profile_stage(repo, scm_ref, stage_id)
    assert stage.scenario is not None
    scenario = stage.scenario.scenario
    scenario_sha256 = stage.scenario.scenario_sha256
    selected_roles = roles or {
        "buyer",
        "seller",
        "host-operator",
        "observer",
    }
    values_by_role: dict[str, list[dict[str, Any]]] = {
        role: [] for role in selected_roles
    }

    observer_value: dict[str, Any] | None = None
    if stage.stage["execution_boundary"] != "mock":
        actor_slot = scenario["actor_slots"]["observers"][0]
        observer_value = _common_plan(
            repo,
            scm_ref,
            stage_id,
            stage.canonical_sha256,
            scenario,
            scenario_sha256,
            role="observer",
            actor_slot=actor_slot,
            instruction_path=OBSERVER_INSTRUCTION_PATH,
        )
        observer_value["role_plan"] = {
            "kind": "observer",
            "independent_source_plan_sha256": digest(
                f"{stage_id}:independent-source"
            ),
            "native_evidence_bindings": [
                binding(
                    NATIVE_EVIDENCE_BINDING_DOMAIN,
                    f"{stage_id}:native-observation",
                )
            ],
        }
        observer_value["prepared_authority_sha256"] = (
            prepared_authority_sha256(observer_value["role_plan"])
        )

    oracle_value = _oracle_value(
        repo,
        scm_ref,
        stage_id,
        observer_value,
    )

    if "buyer" in selected_roles:
        for actor_slot in scenario["actor_slots"]["buyers"]:
            request = _request_by_buyer(scenario, actor_slot)
            value = _common_plan(
                repo,
                scm_ref,
                stage_id,
                stage.canonical_sha256,
                scenario,
                scenario_sha256,
                role="buyer",
                actor_slot=actor_slot,
                instruction_path=BUYER_INSTRUCTION_PATH,
            )
            number = actor_slot.rsplit("-", 1)[1]
            action_id = f"buyer-request-{number}"
            prepared_fields, _ = _prepared_action_fields(
                repo,
                value,
                oracle_value,
                action_id=action_id,
                action_kind="buyer-request",
                selection={
                    "kind": "buyer-request",
                    "request_id": request["request_id"],
                    "seller_slot": request["seller_slot"],
                    "listing_slot": request["listing_slot"],
                },
                wrapper_path=BUYER_REQUEST_WRAPPER_PATH,
                runtime_binding=binding(
                    RUNTIME_BINDING_DOMAIN,
                    f"listing:{request['seller_slot']}:{request['listing_slot']}",
                ),
            )
            value["role_plan"] = {
                "kind": "buyer",
                "request_id": request["request_id"],
                "action_id": action_id,
                "prepared_action_sha256": prepared_action_sha256(
                    prepared_fields
                ),
                "preparation_steps": list(BUYER_PRE_RELEASE_STEPS),
                "success_steps": list(BUYER_GUEST_STEPS),
                "guest_exercise": {
                    "wrapper": tracked(repo, CUDA_WRAPPER_PATH),
                    "source": tracked(repo, CUDA_SOURCE_PATH),
                },
            }
            value["prepared_authority_sha256"] = prepared_authority_sha256(
                value["role_plan"]
            )
            values_by_role["buyer"].append(value)

    if "seller" in selected_roles:
        for actor_slot in scenario["actor_slots"]["sellers"]:
            seller = _seller_by_slot(scenario, actor_slot)
            number = actor_slot.rsplit("-", 1)[1]
            value = _common_plan(
                repo,
                scm_ref,
                stage_id,
                stage.canonical_sha256,
                scenario,
                scenario_sha256,
                role="seller",
                actor_slot=actor_slot,
                instruction_path=SELLER_INSTRUCTION_PATH,
            )
            service_id = f"seller-service-start-{number}"
            service_fields, _ = _prepared_action_fields(
                repo,
                value,
                oracle_value,
                action_id=service_id,
                action_kind="seller-service-start",
                selection={
                    "kind": "seller-service-start",
                    "seller_slot": actor_slot,
                    "service_slot": seller["service_slot"],
                },
                wrapper_path=SELLER_SERVICE_WRAPPER_PATH,
                runtime_binding=binding(
                    RUNTIME_BINDING_DOMAIN,
                    f"service:{actor_slot}:{seller['service_slot']}",
                ),
            )
            publication_ids: list[str] = []
            publication_digests: list[str] = []
            for listing in seller["listing_slots"]:
                action_id = (
                    f"seller-{number}-publication-"
                    f"{listing.rsplit('-', 1)[1]}"
                )
                fields, _ = _prepared_action_fields(
                    repo,
                    value,
                    oracle_value,
                    action_id=action_id,
                    action_kind="seller-listing-publication",
                    selection={
                        "kind": "seller-listing-publication",
                        "seller_slot": actor_slot,
                        "service_slot": seller["service_slot"],
                        "listing_slot": listing,
                    },
                    wrapper_path=SELLER_PUBLICATION_WRAPPER_PATH,
                    runtime_binding=binding(
                        RUNTIME_BINDING_DOMAIN,
                        f"listing:{actor_slot}:{listing}",
                    ),
                )
                publication_ids.append(action_id)
                publication_digests.append(prepared_action_sha256(fields))
            value["role_plan"] = {
                "kind": "seller",
                "service_slot": seller["service_slot"],
                "listing_slots": list(seller["listing_slots"]),
                "service_start_action_id": service_id,
                "service_start_prepared_action_sha256": (
                    prepared_action_sha256(service_fields)
                ),
                "publication_action_ids": publication_ids,
                "publication_prepared_action_sha256s": publication_digests,
                "required_steps": list(SELLER_STEPS),
            }
            value["prepared_authority_sha256"] = prepared_authority_sha256(
                value["role_plan"]
            )
            values_by_role["seller"].append(value)

    if "host-operator" in selected_roles:
        actor_slot = scenario["actor_slots"]["host_operators"][0]
        value = _common_plan(
            repo,
            scm_ref,
            stage_id,
            stage.canonical_sha256,
            scenario,
            scenario_sha256,
            role="host-operator",
            actor_slot=actor_slot,
            instruction_path=HOST_OPERATOR_INSTRUCTION_PATH,
        )
        value["role_plan"] = {
            "kind": "host-operator",
            "topology_authority_binding": binding(
                TOPOLOGY_BINDING_DOMAIN,
                f"{stage_id}:topology",
            ),
            "reversible_baseline_binding": binding(
                REVERSIBLE_BASELINE_BINDING_DOMAIN,
                f"{stage_id}:before",
            ),
            "baseline_equivalence_binding": binding(
                BASELINE_EQUIVALENCE_BINDING_DOMAIN,
                f"{stage_id}:after",
            ),
            "admitted_gpus": 1,
            "kvm_ansible_readiness": True,
            "observation_plan_sha256": digest(f"{stage_id}:observation-plan"),
            "teardown_plan_sha256": digest(f"{stage_id}:teardown-plan"),
        }
        value["prepared_authority_sha256"] = prepared_authority_sha256(
            value["role_plan"]
        )
        values_by_role["host-operator"].append(value)
    if "observer" in selected_roles and observer_value is not None:
        values_by_role["observer"].append(observer_value)
    return [
        value
        for role in ("buyer", "seller", "host-operator", "observer")
        for value in values_by_role.get(role, ())
    ]


def _validated_plans(
    repo: Path,
    scm_ref: str,
    stage_id: str,
    *,
    roles: set[str] | None = None,
) -> list[ValidatedRolePlan]:
    return [
        validate_role_plan(value, repo, expected_scm_ref=scm_ref)
        for value in _plan_values(
            repo,
            scm_ref,
            stage_id,
            roles=roles,
        )
    ]


def _oracle(
    repo: Path,
    scm_ref: str,
    stage_id: str,
    plans: list[ValidatedRolePlan],
) -> ValidatedOracleAuthority:
    observer = next(
        (plan for plan in plans if plan.role == "observer"),
        None,
    )
    value = _oracle_value(
        repo,
        scm_ref,
        stage_id,
        observer.plan if observer is not None else None,
    )
    is_mock = value["execution_boundary"] == "mock"
    return validate_oracle_authority(
        value,
        repo,
        observer_plan=None if is_mock else observer,
    )


def _concurrency_policy(
    repo: Path,
    scm_ref: str,
    stage_id: str,
    plans: list[ValidatedRolePlan],
) -> ValidatedConcurrencyPolicy:
    stage = resolve_pinned_profile_stage(repo, scm_ref, stage_id)
    assert stage.scenario is not None
    action_ids: list[str] = []
    prepared_action_authorities: list[dict[str, str]] = []
    for plan in plans:
        role_plan = plan.plan["role_plan"]
        if plan.role == "buyer":
            action_ids.append(role_plan["action_id"])
            prepared_action_authorities.append(
                {
                    "action_id": role_plan["action_id"],
                    "prepared_action_sha256": role_plan[
                        "prepared_action_sha256"
                    ],
                }
            )
        elif plan.role == "seller":
            action_ids.append(role_plan["service_start_action_id"])
            action_ids.extend(role_plan["publication_action_ids"])
            prepared_action_authorities.append(
                {
                    "action_id": role_plan["service_start_action_id"],
                    "prepared_action_sha256": role_plan[
                        "service_start_prepared_action_sha256"
                    ],
                }
            )
            prepared_action_authorities.extend(
                {
                    "action_id": action_id,
                    "prepared_action_sha256": prepared_sha256,
                }
                for action_id, prepared_sha256 in zip(
                    role_plan["publication_action_ids"],
                    role_plan["publication_prepared_action_sha256s"],
                    strict=True,
                )
            )
    value = {
        "schema_version": 2,
        "policy_id": f"{stage_id}-policy",
        "scm_ref": scm_ref,
        "scenario_id": stage.scenario.scenario_id,
        "scenario_sha256": stage.scenario.scenario_sha256,
        "profile_stage_id": stage_id,
        "profile_stage_sha256": stage.canonical_sha256,
        "release_id": f"{stage_id}-release",
        "frozen_at": "2026-07-30T10:00:00.000000Z",
        "actor_slots": sorted(plan.actor_slot for plan in plans),
        "action_ids": sorted(action_ids),
        "role_plan_authorities": sorted(
            (
                {
                    "plan_id": plan.plan_id,
                    "plan_sha256": plan.canonical_sha256,
                }
                for plan in plans
            ),
            key=lambda item: item["plan_id"],
        ),
        "prepared_action_authorities": sorted(
            prepared_action_authorities,
            key=lambda item: item["action_id"],
        ),
        "clock_evidence_binding": binding(
            NATIVE_EVIDENCE_BINDING_DOMAIN,
            f"{stage_id}:clock",
        ),
        "invocation_windows": [
            {
                "action_kind": "seller-service-start",
                "opened_offset_ns": 0,
                "closed_offset_ns": 100,
                "max_emission_skew_ns": 50,
            },
            {
                "action_kind": "seller-listing-publication",
                "opened_offset_ns": 200,
                "closed_offset_ns": 300,
                "max_emission_skew_ns": 50,
            },
            {
                "action_kind": "buyer-request",
                "opened_offset_ns": 400,
                "closed_offset_ns": 500,
                "max_emission_skew_ns": 50,
            },
        ],
        "deny_local_queue": True,
        "deny_controller_throttle": True,
    }
    return validate_concurrency_policy(value, repo, plans)


@dataclass
class ActionChain:
    authority: ValidatedFrozenAction
    payload: bytes
    runtime_binding: dict[str, str]
    result: ValidatedActionResult | None = None


def _action_chains(
    plans: list[ValidatedRolePlan],
    oracle: ValidatedOracleAuthority,
    policy: ValidatedConcurrencyPolicy | None,
) -> list[ActionChain]:
    chains: list[ActionChain] = []
    release_id = policy.release_id if policy is not None else "mock-release"
    for plan in plans:
        if plan.role not in {"buyer", "seller"}:
            continue
        scenario = plan.profile_stage.scenario
        assert scenario is not None
        scenario_value = scenario.scenario
        role_plan = plan.plan["role_plan"]
        definitions: list[
            tuple[str, str, dict[str, Any], str, dict[str, str]]
        ] = []
        if plan.role == "buyer":
            request = next(
                item
                for item in scenario_value["requests"]
                if item["request_id"] == role_plan["request_id"]
            )
            selection = {
                "kind": "buyer-request",
                "request_id": request["request_id"],
                "seller_slot": request["seller_slot"],
                "listing_slot": request["listing_slot"],
            }
            definitions.append(
                (
                    role_plan["action_id"],
                    "buyer-request",
                    selection,
                    BUYER_REQUEST_WRAPPER_PATH,
                    binding(
                        RUNTIME_BINDING_DOMAIN,
                        f"listing:{request['seller_slot']}:{request['listing_slot']}",
                    ),
                )
            )
        else:
            number = plan.actor_slot.rsplit("-", 1)[1]
            definitions.append(
                (
                    role_plan["service_start_action_id"],
                    "seller-service-start",
                    {
                        "kind": "seller-service-start",
                        "seller_slot": plan.actor_slot,
                        "service_slot": role_plan["service_slot"],
                    },
                    SELLER_SERVICE_WRAPPER_PATH,
                    binding(
                        RUNTIME_BINDING_DOMAIN,
                        f"service:{plan.actor_slot}:{role_plan['service_slot']}",
                    ),
                )
            )
            for action_id, listing_slot in zip(
                role_plan["publication_action_ids"],
                role_plan["listing_slots"],
                strict=True,
            ):
                definitions.append(
                    (
                        action_id,
                        "seller-listing-publication",
                        {
                            "kind": "seller-listing-publication",
                            "seller_slot": plan.actor_slot,
                            "service_slot": role_plan["service_slot"],
                            "listing_slot": listing_slot,
                        },
                        SELLER_PUBLICATION_WRAPPER_PATH,
                        binding(
                            RUNTIME_BINDING_DOMAIN,
                            f"listing:{plan.actor_slot}:{listing_slot}",
                        ),
                    )
                )
        for action_id, kind, selection, wrapper, runtime in definitions:
            prepared_fields, payload = _prepared_action_fields(
                plan.repo_root,
                plan.plan,
                oracle.authority,
                action_id=action_id,
                action_kind=kind,
                selection=selection,
                wrapper_path=wrapper,
                runtime_binding=runtime,
            )
            value = {
                **prepared_fields,
                "role_plan_sha256": plan.canonical_sha256,
                "prepared_action_sha256": prepared_action_sha256(
                    prepared_fields
                ),
                "release_id": release_id,
                "concurrency_policy_id": (
                    policy.policy_id if policy is not None else None
                ),
                "concurrency_policy_sha256": (
                    policy.canonical_sha256 if policy is not None else None
                ),
                "attempt": 1,
            }
            chains.append(
                ActionChain(
                    authority=validate_frozen_action(
                        value,
                        plan,
                        payload_bytes=payload,
                        oracle_authority=oracle,
                        concurrency_policy=policy,
                    ),
                    payload=payload,
                    runtime_binding=runtime,
                )
            )
    return chains


def _result(
    chain: ActionChain,
    *,
    invoked_at: str,
    terminal_at: str,
) -> ValidatedActionResult:
    action = chain.authority
    value = {
        "schema_version": 2,
        "action_result_id": f"{action.action_id}-result",
        "action_id": action.action_id,
        "action_sha256": action.canonical_sha256,
        "actor_slot": action.actor_slot,
        "release_id": action.release_id,
        "attempt": 1,
        "invoked_at": invoked_at,
        "terminal_at": terminal_at,
        "actor_alive_at_invocation": True,
        "release_claim_count": 1,
        "pre_emission_checks": {
            "authority_unchanged": True,
            "payload_unchanged": True,
            "selection_unchanged": True,
            "runtime_binding_unchanged": True,
            "wrapper_unchanged": True,
        },
        "result_kind": "emitted",
        "emission_count": 1,
        "terminal_payload_sha256": action.action["payload_sha256"],
        "failure_code": None,
    }
    return validate_action_result(value, action)


def _populate_results(chains: list[ActionChain]) -> None:
    counters = {
        "seller-service-start": 0,
        "seller-listing-publication": 0,
        "buyer-request": 0,
    }
    bases = {
        "seller-service-start": 2,
        "seller-listing-publication": 4,
        "buyer-request": 6,
    }
    for chain in chains:
        kind = chain.authority.action_kind
        counters[kind] += 1
        suffix = counters[kind]
        base = bases[kind]
        chain.result = _result(
            chain,
            invoked_at=f"2026-07-30T10:00:0{base}.{suffix:06d}Z",
            terminal_at=f"2026-07-30T10:00:0{base + 1}.{suffix:06d}Z",
        )


def _step_outcomes(steps: tuple[str, ...]) -> list[dict[str, str]]:
    return [
        {
            "step_id": step,
            "status": "passed",
            "evidence_sha256": digest(f"step:{step}"),
        }
        for step in steps
    ]


def _receipt_value(
    plan: ValidatedRolePlan,
    chains: list[ActionChain],
    *,
    successful_guest: bool = False,
) -> dict[str, Any]:
    action_chains = [
        chain for chain in chains if chain.authority.actor_slot == plan.actor_slot
    ]
    plan_value = plan.plan
    common = {
        "schema_version": 2,
        "receipt_id": f"{plan.actor_slot}-receipt",
        "plan_id": plan.plan_id,
        "plan_sha256": plan.canonical_sha256,
        "role": plan.role,
        "actor_slot": plan.actor_slot,
        "profile_stage_id": plan.profile_stage_id,
        "profile_stage_sha256": plan.profile_stage_sha256,
        "scenario_id": plan.scenario_id,
        "scenario_sha256": plan.scenario_sha256,
        "scm_ref": plan.scm_ref,
        "instruction": plan_value["instruction"],
        "isolated_identity_fingerprint": plan_value[
            "isolated_identity_fingerprint"
        ],
        "prepared_authority_sha256": plan_value["prepared_authority_sha256"],
        "run_authority": {
            "release_id": chains[0].authority.release_id,
            "concurrency_policy_id": chains[0].authority.action[
                "concurrency_policy_id"
            ],
            "concurrency_policy_sha256": chains[0].authority.action[
                "concurrency_policy_sha256"
            ],
        },
        "provenance": {
            "producer": "actor-process",
            "controller_authored": False,
            "actor_invocation_capability_binding": plan_value[
                "actor_invocation_capability_binding"
            ],
            "actor_liveness_binding": binding(
                NATIVE_EVIDENCE_BINDING_DOMAIN,
                f"{plan.actor_slot}:liveness",
            ),
        },
        "lifecycle": {
            "started_at": "2026-07-30T10:00:00.100000Z",
            "prepared_at": "2026-07-30T10:00:01.000000Z",
            "barrier_observed_at": "2026-07-30T10:00:08.000000Z",
            "completed_at": "2026-07-30T10:00:09.000000Z",
        },
    }
    if plan.role == "buyer":
        assert len(action_chains) == 1 and action_chains[0].result is not None
        guest = None
        steps = BUYER_PRE_RELEASE_STEPS
        if successful_guest:
            steps += BUYER_GUEST_STEPS
            guest = {
                "fulfillment_id": f"{plan.actor_slot}-fulfillment",
                "ssh_resumed": True,
                "visible_gpus": 1,
                "workload_sha256": canonical_sha256(
                    plan_value["role_plan"]["guest_exercise"]
                ),
                "success_marker": CUDA_SUCCESS_MARKER,
                "result_checksum": CUDA_RESULT_CHECKSUM,
            }
        common["barrier"] = {
            "barrier_kind": "release",
            "barrier_id": action_chains[0].authority.release_id,
            "actor_alive_at_barrier": True,
        }
        common["lifecycle"]["barrier_observed_at"] = (
            "2026-07-30T10:00:05.000000Z"
        )
        common["step_outcomes"] = _step_outcomes(steps)
        common["role_evidence"] = {
            "kind": "buyer",
            "action_result_sha256": action_chains[0].result.canonical_sha256,
            "guest_verification": guest,
        }
    elif plan.role == "seller":
        assert all(chain.result is not None for chain in action_chains)
        service = next(
            chain
            for chain in action_chains
            if chain.authority.action_kind == "seller-service-start"
        )
        publications = [
            chain
            for chain in action_chains
            if chain.authority.action_kind == "seller-listing-publication"
        ]
        common["barrier"] = {
            "barrier_kind": "observation",
            "barrier_id": f"{plan.profile_stage_id}-observation",
            "actor_alive_at_barrier": True,
        }
        common["step_outcomes"] = _step_outcomes(SELLER_STEPS)
        common["role_evidence"] = {
            "kind": "seller",
            "service_start_result_sha256": service.result.canonical_sha256,
            "publication_result_sha256s": [
                chain.result.canonical_sha256 for chain in publications
            ],
            "alive_through_observation": True,
        }
    elif plan.role == "host-operator":
        role_plan = plan_value["role_plan"]
        common["barrier"] = {
            "barrier_kind": "cleanup",
            "barrier_id": f"{plan.profile_stage_id}-cleanup",
            "actor_alive_at_barrier": True,
        }
        common["step_outcomes"] = _step_outcomes(HOST_OPERATOR_STEPS)
        common["role_evidence"] = {
            "kind": "host-operator",
            "topology_authority_binding": role_plan[
                "topology_authority_binding"
            ],
            "reversible_baseline_binding": role_plan[
                "reversible_baseline_binding"
            ],
            "baseline_equivalence_binding": role_plan[
                "baseline_equivalence_binding"
            ],
            "kvm_ansible_ready": True,
            "cleanup_complete": True,
        }
    else:
        common["barrier"] = {
            "barrier_kind": "observation",
            "barrier_id": f"{plan.profile_stage_id}-observation",
            "actor_alive_at_barrier": True,
        }
        common["step_outcomes"] = _step_outcomes(OBSERVER_STEPS)
        common["role_evidence"] = {
            "kind": "observer",
            "independent_source": True,
            "controller_source": False,
            "release_observed": True,
            "terminal_observed": True,
            "native_evidence_bindings": plan_value["role_plan"][
                "native_evidence_bindings"
            ],
        }
    return common


def _role_evidence(
    plans: list[ValidatedRolePlan],
    chains: list[ActionChain],
) -> list[SubstantiveRoleEvidence]:
    evidence: list[SubstantiveRoleEvidence] = []
    for plan in plans:
        owned = [
            chain for chain in chains if chain.authority.actor_slot == plan.actor_slot
        ]
        results = [chain.result for chain in owned]
        assert all(result is not None for result in results)
        receipt = validate_role_receipt(
            _receipt_value(plan, chains),
            plan,
        )
        evidence.append(
            validate_substantive_role_evidence(
                plan,
                receipt,
                [chain.authority for chain in owned],
                [result for result in results if result is not None],
            )
        )
    return evidence


@dataclass
class RealChain:
    repo: Path
    scm_ref: str
    plans: list[ValidatedRolePlan]
    oracle: ValidatedOracleAuthority
    policy: ValidatedConcurrencyPolicy
    chains: list[ActionChain]
    evidence: list[SubstantiveRoleEvidence]
    actor_set: dict[str, Any]


def _real_chain(repo: Path, scm_ref: str, stage_id: str) -> RealChain:
    plans = _validated_plans(repo, scm_ref, stage_id)
    oracle = _oracle(repo, scm_ref, stage_id, plans)
    policy = _concurrency_policy(repo, scm_ref, stage_id, plans)
    chains = _action_chains(plans, oracle, policy)
    _populate_results(chains)
    evidence = _role_evidence(plans, chains)
    scenario = plans[0].profile_stage.scenario
    assert scenario is not None

    services: list[dict[str, Any]] = []
    listings: list[dict[str, Any]] = []
    for seller in scenario.scenario["listing_topology"]["sellers"]:
        services.append(
            {
                "seller_slot": seller["seller_slot"],
                "service_slot": seller["service_slot"],
                "runtime_binding": binding(
                    RUNTIME_BINDING_DOMAIN,
                    f"service:{seller['seller_slot']}:{seller['service_slot']}",
                ),
            }
        )
        for listing_slot in seller["listing_slots"]:
            listings.append(
                {
                    "seller_slot": seller["seller_slot"],
                    "listing_slot": listing_slot,
                    "runtime_binding": binding(
                        RUNTIME_BINDING_DOMAIN,
                        f"listing:{seller['seller_slot']}:{listing_slot}",
                    ),
                }
            )

    offsets = {
        "seller-service-start": iter(range(10, 60, 5)),
        "seller-listing-publication": iter(range(210, 260, 5)),
        "buyer-request": iter(range(410, 460, 5)),
    }
    actions = []
    for chain in chains:
        assert chain.result is not None
        invoked = next(offsets[chain.authority.action_kind])
        actions.append(
            {
                "action_id": chain.authority.action_id,
                "action_kind": chain.authority.action_kind,
                "actor_slot": chain.authority.actor_slot,
                "action_sha256": chain.authority.canonical_sha256,
                "action_result_sha256": chain.result.canonical_sha256,
                "invoked_offset_ns": invoked,
                "terminal_offset_ns": invoked + 1,
            }
        )
    actor_set = {
        "schema_version": 2,
        "actor_set_id": f"{stage_id}-actor-set",
        "scm_ref": scm_ref,
        "scenario_id": scenario.scenario_id,
        "scenario_sha256": scenario.scenario_sha256,
        "profile_stage_id": stage_id,
        "profile_stage_sha256": plans[0].profile_stage_sha256,
        "execution_boundary": plans[0].profile_stage.stage[
            "execution_boundary"
        ],
        "actor_trigger": "agent-triggered",
        "release_id": policy.release_id,
        "concurrency_policy_id": policy.policy_id,
        "concurrency_policy_sha256": policy.canonical_sha256,
        "clock_evidence_binding": policy.policy["clock_evidence_binding"],
        "release_observed_at": "2026-07-30T10:00:01.000000Z",
        "actors": [
            {
                "role": item.plan.role,
                "actor_slot": item.plan.actor_slot,
                "plan_sha256": item.plan.canonical_sha256,
                "receipt_sha256": item.receipt.canonical_sha256,
                "started_offset_ns": -1,
                "completed_offset_ns": 501,
            }
            for item in evidence
        ],
        "actions": actions,
        "runtime_service_bindings": services,
        "runtime_listing_bindings": listings,
        "invocation_windows": policy.policy["invocation_windows"],
        "controller_observation": {
            "role_receipts_authored": False,
            "local_queue_detected": False,
            "throttle_detected": False,
        },
    }
    return RealChain(
        repo=repo,
        scm_ref=scm_ref,
        plans=plans,
        oracle=oracle,
        policy=policy,
        chains=chains,
        evidence=evidence,
        actor_set=actor_set,
    )


def test_real_b2_s2_chain_proves_exact_roles_and_per_listing_bindings(
    authority_repo: tuple[Path, str],
) -> None:
    repo, scm_ref = authority_repo
    chain = _real_chain(repo, scm_ref, "b2-s2-g1-qualification")

    validated = validate_substantive_actor_set(
        chain.actor_set,
        chain.policy,
        chain.evidence,
    )

    assert validated.actor_slots == (
        "buyer-1",
        "buyer-2",
        "host-operator-1",
        "observer-1",
        "seller-1",
        "seller-2",
    )
    assert len(validated.runtime_service_bindings) == 2
    assert len(validated.runtime_listing_bindings) == 2
    assert validated.buyer_invocation_skew_ns == 5
    assert validated.publication_invocation_skew_ns == 5


def test_actor_set_rejects_actions_validated_under_another_same_stage_policy(
    authority_repo: tuple[Path, str],
) -> None:
    repo, scm_ref = authority_repo
    chain = _real_chain(repo, scm_ref, "b2-s2-g1-qualification")
    other_policy_value = deepcopy(chain.policy.policy)
    other_policy_value["policy_id"] = "b2-s2-g1-qualification-other-policy"
    other_policy = validate_concurrency_policy(
        other_policy_value,
        repo,
        chain.plans,
    )
    substituted_actor_set = deepcopy(chain.actor_set)
    substituted_actor_set["concurrency_policy_id"] = other_policy.policy_id
    substituted_actor_set[
        "concurrency_policy_sha256"
    ] = other_policy.canonical_sha256

    with pytest.raises(
        CapacityValidationError,
        match="every action must bind the exact concurrency policy",
    ):
        validate_substantive_actor_set(
            substituted_actor_set,
            other_policy,
            chain.evidence,
        )


def test_role_evidence_rejects_result_from_another_same_id_action(
    authority_repo: tuple[Path, str],
) -> None:
    repo, scm_ref = authority_repo
    chain = _real_chain(repo, scm_ref, "b2-s2-g1-qualification")
    other_policy_value = deepcopy(chain.policy.policy)
    other_policy_value["policy_id"] = "b2-s2-g1-qualification-other-policy"
    other_policy = validate_concurrency_policy(
        other_policy_value,
        repo,
        chain.plans,
    )
    other_chains = _action_chains(
        chain.plans,
        chain.oracle,
        other_policy,
    )
    _populate_results(other_chains)

    buyer = next(item for item in chain.evidence if item.plan.role == "buyer")
    buyer_action = next(
        item.authority
        for item in chain.chains
        if item.authority.actor_slot == buyer.plan.actor_slot
    )
    substituted_result = next(
        item.result
        for item in other_chains
        if item.authority.action_id == buyer_action.action_id
    )
    assert substituted_result is not None
    changed_receipt = buyer.receipt.receipt
    changed_receipt["role_evidence"][
        "action_result_sha256"
    ] = substituted_result.canonical_sha256
    receipt = validate_role_receipt(changed_receipt, buyer.plan)

    with pytest.raises(
        CapacityValidationError,
        match="does not bind the exact supplied frozen action",
    ):
        validate_substantive_role_evidence(
            buyer.plan,
            receipt,
            [buyer_action],
            [substituted_result],
        )


def test_privacy_binding_is_closed_typed_and_domain_separated() -> None:
    value = binding(RUNTIME_BINDING_DOMAIN, "runtime")
    assert value["value"] != digest("runtime")
    assert validate_privacy_preserving_binding(
        value,
        expected_domain=RUNTIME_BINDING_DOMAIN,
        field_name="runtime_binding",
    ) == value
    with pytest.raises(CapacityValidationError, match="exactly method"):
        validate_privacy_preserving_binding(
            digest("raw-private-value"),
            expected_domain=RUNTIME_BINDING_DOMAIN,
            field_name="runtime_binding",
        )
    with pytest.raises(CapacityValidationError, match="domain"):
        validate_privacy_preserving_binding(
            {**value, "domain": TOPOLOGY_BINDING_DOMAIN},
            expected_domain=RUNTIME_BINDING_DOMAIN,
            field_name="runtime_binding",
        )
    with pytest.raises(CapacityValidationError, match="method"):
        validate_privacy_preserving_binding(
            {**value, "method": "sha256"},
            expected_domain=RUNTIME_BINDING_DOMAIN,
            field_name="runtime_binding",
        )


def test_role_plan_rechecks_git_pins_and_rejects_controller_fields(
    authority_repo: tuple[Path, str],
) -> None:
    repo, scm_ref = authority_repo
    value = _plan_values(repo, scm_ref, "b2-s1-g1-qualification")[0]
    validate_role_plan(value, repo)

    leaked = deepcopy(value)
    leaked["host_alias"] = "forbidden-private-host"
    with pytest.raises(CapacityValidationError, match="Additional properties"):
        validate_role_plan(leaked, repo)

    (repo / BUYER_INSTRUCTION_PATH).write_text(
        "unreviewed instruction drift\n",
        encoding="utf-8",
    )
    with pytest.raises(CapacityValidationError, match="worktree bytes differ"):
        validate_role_plan(value, repo)


def test_observer_probe_is_the_only_null_scenario_role_authority(
    authority_repo: tuple[Path, str],
) -> None:
    repo, scm_ref = authority_repo
    stage = resolve_pinned_profile_stage(repo, scm_ref, "observer-probe")
    observer = {
        "schema_version": 2,
        "plan_id": "observer-1-plan",
        "role": "observer",
        "actor_slot": "observer-1",
        "profile_stage_id": "observer-probe",
        "profile_stage_sha256": stage.canonical_sha256,
        "scenario_id": None,
        "scenario_sha256": None,
        "scm_ref": scm_ref,
        "instruction": tracked(repo, OBSERVER_INSTRUCTION_PATH),
        "isolated_identity_fingerprint": digest("probe-observer"),
        "actor_invocation_capability_binding": binding(
            ACTOR_INVOCATION_BINDING_DOMAIN,
            "probe-observer-capability",
        ),
        "role_plan": {
            "kind": "observer",
            "independent_source_plan_sha256": digest("probe-source"),
            "native_evidence_bindings": [
                binding(NATIVE_EVIDENCE_BINDING_DOMAIN, "probe-evidence")
            ],
        },
    }
    observer["prepared_authority_sha256"] = prepared_authority_sha256(
        observer["role_plan"]
    )
    assert validate_role_plan(observer, repo).scenario_id is None

    invalid_buyer = deepcopy(observer)
    invalid_buyer.update(
        {
            "plan_id": "buyer-1-plan",
            "role": "buyer",
            "actor_slot": "buyer-1",
            "instruction": tracked(repo, BUYER_INSTRUCTION_PATH),
        }
    )
    with pytest.raises(CapacityValidationError, match="buyer|observer-probe"):
        validate_role_plan(invalid_buyer, repo)


def test_concurrency_policy_freezes_plan_and_prepared_action_content(
    authority_repo: tuple[Path, str],
) -> None:
    repo, scm_ref = authority_repo
    plans = _validated_plans(repo, scm_ref, "b2-s1-g1-qualification")
    policy = _concurrency_policy(
        repo,
        scm_ref,
        "b2-s1-g1-qualification",
        plans,
    )

    changed = policy.policy
    changed["prepared_action_authorities"][0][
        "prepared_action_sha256"
    ] = "0" * 64
    with pytest.raises(CapacityValidationError, match="prepared action"):
        validate_concurrency_policy(changed, repo, plans)


def test_concurrency_policy_rejects_duplicate_actor_identities(
    authority_repo: tuple[Path, str],
) -> None:
    repo, scm_ref = authority_repo
    values = _plan_values(repo, scm_ref, "b2-s1-g1-qualification")
    buyers = [value for value in values if value["role"] == "buyer"]
    buyers[1]["isolated_identity_fingerprint"] = buyers[0][
        "isolated_identity_fingerprint"
    ]
    plans = [validate_role_plan(value, repo) for value in values]

    with pytest.raises(CapacityValidationError, match="duplicate identities"):
        _concurrency_policy(
            repo,
            scm_ref,
            "b2-s1-g1-qualification",
            plans,
        )


def test_concurrency_policy_rejects_duplicate_invocation_capabilities(
    authority_repo: tuple[Path, str],
) -> None:
    repo, scm_ref = authority_repo
    values = _plan_values(repo, scm_ref, "b2-s1-g1-qualification")
    buyers = [value for value in values if value["role"] == "buyer"]
    buyers[1]["actor_invocation_capability_binding"] = deepcopy(
        buyers[0]["actor_invocation_capability_binding"]
    )
    plans = [validate_role_plan(value, repo) for value in values]

    with pytest.raises(
        CapacityValidationError,
        match="duplicate invocation capabilities",
    ):
        _concurrency_policy(
            repo,
            scm_ref,
            "b2-s1-g1-qualification",
            plans,
        )


def test_concurrency_policy_rejects_duplicate_role_plan_ids(
    authority_repo: tuple[Path, str],
) -> None:
    repo, scm_ref = authority_repo
    values = _plan_values(repo, scm_ref, "b2-s1-g1-qualification")
    host = next(value for value in values if value["role"] == "host-operator")
    observer = next(value for value in values if value["role"] == "observer")
    host["plan_id"] = observer["plan_id"]
    plans = [validate_role_plan(value, repo) for value in values]

    with pytest.raises(
        CapacityValidationError,
        match="role-plan IDs must be globally unique",
    ):
        _concurrency_policy(
            repo,
            scm_ref,
            "b2-s1-g1-qualification",
            plans,
        )


def test_real_action_oracle_must_use_the_policy_frozen_observer(
    authority_repo: tuple[Path, str],
) -> None:
    repo, scm_ref = authority_repo
    stage_id = "b2-s1-g1-qualification"
    plans = _validated_plans(repo, scm_ref, stage_id)
    policy = _concurrency_policy(repo, scm_ref, stage_id, plans)

    values = _plan_values(repo, scm_ref, stage_id)
    alternate_value = deepcopy(
        next(value for value in values if value["role"] == "observer")
    )
    alternate_value["plan_id"] = "observer-alternate-plan"
    alternate_value["isolated_identity_fingerprint"] = digest(
        "observer-alternate-identity"
    )
    alternate_value["actor_invocation_capability_binding"] = binding(
        ACTOR_INVOCATION_BINDING_DOMAIN,
        "observer-alternate-capability",
    )
    alternate_value["role_plan"]["independent_source_plan_sha256"] = digest(
        "observer-alternate-source"
    )
    alternate_value["role_plan"]["native_evidence_bindings"] = [
        binding(
            NATIVE_EVIDENCE_BINDING_DOMAIN,
            "observer-alternate-evidence",
        )
    ]
    alternate_value[
        "prepared_authority_sha256"
    ] = prepared_authority_sha256(alternate_value["role_plan"])
    alternate_observer = validate_role_plan(alternate_value, repo)
    alternate_oracle = validate_oracle_authority(
        _oracle_value(
            repo,
            scm_ref,
            stage_id,
            alternate_observer.plan,
        ),
        repo,
        observer_plan=alternate_observer,
    )

    with pytest.raises(
        CapacityValidationError,
        match="oracle observer was not frozen exactly once",
    ):
        _action_chains(plans, alternate_oracle, policy)


def test_receipts_reject_readiness_only_controller_authorship_and_early_exit(
    authority_repo: tuple[Path, str],
) -> None:
    repo, scm_ref = authority_repo
    chain = _real_chain(repo, scm_ref, "b2-s1-g1-qualification")
    buyer = next(item for item in chain.evidence if item.plan.role == "buyer")
    owned = [
        item for item in chain.chains if item.authority.actor_slot == buyer.plan.actor_slot
    ]

    readiness = buyer.receipt.receipt
    readiness["step_outcomes"] = readiness["step_outcomes"][:1]
    with pytest.raises(CapacityValidationError, match="exact ordered"):
        validate_role_receipt(readiness, buyer.plan)

    controller = buyer.receipt.receipt
    controller["provenance"]["controller_authored"] = True
    with pytest.raises(CapacityValidationError, match="controller"):
        validate_role_receipt(controller, buyer.plan)

    early = buyer.receipt.receipt
    early["lifecycle"]["completed_at"] = "2026-07-30T10:00:06.500000Z"
    early_receipt = validate_role_receipt(early, buyer.plan)
    with pytest.raises(CapacityValidationError, match="remain alive"):
        validate_substantive_role_evidence(
            buyer.plan,
            early_receipt,
            [owned[0].authority],
            [owned[0].result],
        )


def test_successful_buyer_receipt_proves_guest_ssh_one_gpu_and_pinned_cuda(
    authority_repo: tuple[Path, str],
) -> None:
    repo, scm_ref = authority_repo
    chain = _real_chain(repo, scm_ref, "b2-s1-g1-qualification")
    buyer_plan = next(plan for plan in chain.plans if plan.role == "buyer")
    buyer_chain = next(
        item
        for item in chain.chains
        if item.authority.actor_slot == buyer_plan.actor_slot
    )
    assert buyer_chain.result is not None

    receipt_value = _receipt_value(
        buyer_plan,
        chain.chains,
        successful_guest=True,
    )
    receipt = validate_role_receipt(receipt_value, buyer_plan)
    evidence = validate_substantive_role_evidence(
        buyer_plan,
        receipt,
        [buyer_chain.authority],
        [buyer_chain.result],
    )
    guest = evidence.receipt.receipt["role_evidence"]["guest_verification"]
    assert guest["ssh_resumed"] is True
    assert guest["visible_gpus"] == 1
    assert guest["success_marker"] == CUDA_SUCCESS_MARKER
    assert guest["result_checksum"] == CUDA_RESULT_CHECKSUM

    mutations = {
        "ssh_resumed": False,
        "visible_gpus": 2,
        "workload_sha256": "0" * 64,
        "success_marker": "UNPINNED_MARKER",
        "result_checksum": "0" * 64,
        "fulfillment_id": "",
    }
    for field_name, changed_value in mutations.items():
        changed = deepcopy(receipt_value)
        changed["role_evidence"]["guest_verification"][
            field_name
        ] = changed_value
        with pytest.raises(CapacityValidationError):
            validate_role_receipt(changed, buyer_plan)


def test_action_rejects_changed_payload_wrapper_mapping_and_retry(
    authority_repo: tuple[Path, str],
) -> None:
    repo, scm_ref = authority_repo
    chain = _real_chain(repo, scm_ref, "b2-s1-g1-qualification")
    buyer = next(
        item for item in chain.chains if item.authority.action_kind == "buyer-request"
    )
    plan = next(
        plan for plan in chain.plans if plan.actor_slot == buyer.authority.actor_slot
    )
    raw = buyer.authority.action

    with pytest.raises(CapacityValidationError, match="payload_sha256"):
        validate_frozen_action(
            raw,
            plan,
            payload_bytes=buyer.payload + b"drift",
            oracle_authority=chain.oracle,
            concurrency_policy=chain.policy,
        )
    changed = deepcopy(raw)
    changed["runtime_binding"] = binding(
        RUNTIME_BINDING_DOMAIN,
        "changed-listing",
    )
    with pytest.raises(CapacityValidationError, match="prepared"):
        validate_frozen_action(
            changed,
            plan,
            payload_bytes=buyer.payload,
            oracle_authority=chain.oracle,
            concurrency_policy=chain.policy,
        )
    changed = deepcopy(raw)
    changed["wrapper"]["sha256"] = "0" * 64
    with pytest.raises(CapacityValidationError, match="wrapper"):
        validate_frozen_action(
            changed,
            plan,
            payload_bytes=buyer.payload,
            oracle_authority=chain.oracle,
            concurrency_policy=chain.policy,
        )
    changed = deepcopy(raw)
    changed["attempt"] = 2
    with pytest.raises(CapacityValidationError, match="attempt"):
        validate_frozen_action(
            changed,
            plan,
            payload_bytes=buyer.payload,
            oracle_authority=chain.oracle,
            concurrency_policy=chain.policy,
        )


def test_typed_retry_and_duplicate_results_preserve_attempt_counts(
    authority_repo: tuple[Path, str],
) -> None:
    repo, scm_ref = authority_repo
    chain = _real_chain(repo, scm_ref, "b2-s1-g1-qualification")
    action = next(
        item.authority
        for item in chain.chains
        if item.authority.action_kind == "buyer-request"
    )
    checks = {
        "authority_unchanged": True,
        "payload_unchanged": True,
        "selection_unchanged": True,
        "runtime_binding_unchanged": True,
        "wrapper_unchanged": True,
    }
    retry = {
        "schema_version": 2,
        "action_result_id": "typed-retry-result",
        "action_id": action.action_id,
        "action_sha256": action.canonical_sha256,
        "actor_slot": action.actor_slot,
        "release_id": action.release_id,
        "attempt": 2,
        "invoked_at": "2026-07-30T10:00:10.000000Z",
        "terminal_at": "2026-07-30T10:00:11.000000Z",
        "actor_alive_at_invocation": True,
        "release_claim_count": 1,
        "pre_emission_checks": checks,
        "result_kind": "rejected-before-emission",
        "emission_count": 0,
        "terminal_payload_sha256": None,
        "failure_code": "unauthorized-retry",
    }
    assert validate_unauthorized_retry_rejection(retry, action).result[
        "attempt"
    ] == 2
    duplicate = {**retry}
    duplicate.update(
        {
            "action_result_id": "typed-duplicate-result",
            "attempt": 1,
            "release_claim_count": 2,
            "failure_code": "duplicate-release",
        }
    )
    assert validate_action_result(duplicate, action).result[
        "release_claim_count"
    ] == 2


def test_actor_set_rejects_duplicate_identity_wrong_maps_and_controller_queue(
    authority_repo: tuple[Path, str],
) -> None:
    repo, scm_ref = authority_repo
    chain = _real_chain(repo, scm_ref, "b2-s2-g1-qualification")

    queued = deepcopy(chain.actor_set)
    queued["controller_observation"]["local_queue_detected"] = True
    with pytest.raises(CapacityValidationError, match="controller observation"):
        validate_substantive_actor_set(queued, chain.policy, chain.evidence)

    changed_map = deepcopy(chain.actor_set)
    changed_map["runtime_listing_bindings"][0]["runtime_binding"] = (
        changed_map["runtime_service_bindings"][0]["runtime_binding"]
    )
    with pytest.raises(CapacityValidationError, match="one-to-one|does not match"):
        validate_substantive_actor_set(
            changed_map,
            chain.policy,
            chain.evidence,
        )

    duplicate_identity_plans = deepcopy(chain.actor_set)
    duplicate_identity_plans["actors"][1]["plan_sha256"] = (
        duplicate_identity_plans["actors"][0]["plan_sha256"]
    )
    with pytest.raises(CapacityValidationError, match="plan_sha256"):
        validate_substantive_actor_set(
            duplicate_identity_plans,
            chain.policy,
            chain.evidence,
        )

    terminal_after_exit = deepcopy(chain.actor_set)
    buyer_action = next(
        item
        for item in terminal_after_exit["actions"]
        if item["action_kind"] == "buyer-request"
    )
    buyer_actor = next(
        item
        for item in terminal_after_exit["actors"]
        if item["actor_slot"] == buyer_action["actor_slot"]
    )
    buyer_actor["completed_offset_ns"] = 501
    buyer_action["terminal_offset_ns"] = 600
    with pytest.raises(CapacityValidationError, match="owning actor lifetime"):
        validate_substantive_actor_set(
            terminal_after_exit,
            chain.policy,
            chain.evidence,
        )

    stale_host = next(
        item for item in chain.evidence if item.plan.role == "host-operator"
    )
    stale_receipt_value = stale_host.receipt.receipt
    stale_receipt_value["run_authority"] = {
        "release_id": "stale-unrelated-release",
        "concurrency_policy_id": "stale-unrelated-policy",
        "concurrency_policy_sha256": "0" * 64,
    }
    stale_receipt = validate_role_receipt(
        stale_receipt_value,
        stale_host.plan,
    )
    stale_evidence = [
        (
            SubstantiveRoleEvidence(
                plan=item.plan,
                receipt=stale_receipt,
                actions=item.actions,
                results=item.results,
            )
            if item.plan.actor_slot == stale_host.plan.actor_slot
            else item
        )
        for item in chain.evidence
    ]
    stale_actor_set = deepcopy(chain.actor_set)
    next(
        item
        for item in stale_actor_set["actors"]
        if item["actor_slot"] == stale_host.plan.actor_slot
    )["receipt_sha256"] = stale_receipt.canonical_sha256
    with pytest.raises(CapacityValidationError, match="exact run authority"):
        validate_substantive_actor_set(
            stale_actor_set,
            chain.policy,
            stale_evidence,
        )


@pytest.mark.parametrize("buyer_count", [2, 4, 8])
def test_serial_buyer_execution_cannot_satisfy_concurrent_stage(
    buyer_count: int,
) -> None:
    serial_offsets = [index * 80 for index in range(buyer_count)]
    with pytest.raises(CapacityValidationError, match="skew exceeds"):
        validate_invocation_offsets(
            serial_offsets,
            max_emission_skew_ns=50,
            label=f"b{buyer_count}-buyer-request",
        )


class SequenceClock:
    def __init__(self, start: datetime) -> None:
        self.value = start

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(microseconds=1)
        return current


def _mock_evidence(
    plans: list[ValidatedRolePlan],
    chains: list[ActionChain],
) -> list[SubstantiveRoleEvidence]:
    return _role_evidence(plans, chains)


def test_capture_only_composition_is_portably_bound_one_shot_and_zero_resource(
    authority_repo: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repo, scm_ref = authority_repo
    plans = _validated_plans(
        repo,
        scm_ref,
        "b1-s1-g1-mock",
        roles={"buyer", "seller"},
    )
    oracle = _oracle(repo, scm_ref, "b1-s1-g1-mock", plans)
    chains = _action_chains(plans, oracle, None)
    order = {
        "seller-service-start": 0,
        "seller-listing-publication": 1,
        "buyer-request": 2,
    }
    chains.sort(key=lambda item: order[item.authority.action_kind])
    ledger = tmp_path / "claims"
    outputs = tmp_path / "results"
    ledger.mkdir(mode=0o700)
    outputs.mkdir(mode=0o700)
    clock = SequenceClock(
        datetime(2026, 7, 30, 10, 0, 6, tzinfo=UTC)
    )
    for index, chain in enumerate(chains):
        captured = action_capture(
            chain.authority,
            next(
                plan
                for plan in plans
                if plan.actor_slot == chain.authority.actor_slot
            ),
            payload_bytes=chain.payload,
            oracle_authority=oracle,
            concurrency_policy=None,
            expected_action_kind=chain.authority.action_kind,
            current_runtime_binding=chain.runtime_binding,
            current_concrete_payload_binding=chain.authority.action[
                "concrete_payload_binding"
            ],
            current_actor_invocation_capability=chain.authority.action[
                "actor_invocation_capability_binding"
            ],
            actor_alive_at_invocation=True,
            claim_ledger=ledger,
            result_output=outputs / f"result-{index}.json",
            clock=clock,
        )
        chain.result = captured.result
        assert captured.record_path is not None
        assert stat.S_IMODE(captured.record_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(captured.result_path.stat().st_mode) == 0o600
        assert captured.recovered is False

    evidence = _mock_evidence(plans, chains)
    stage = resolve_pinned_profile_stage(repo, scm_ref, "b1-s1-g1-mock")
    assert stage.scenario is not None
    capture = {
        "schema_version": 2,
        "capture_id": "b1-s1-g1-mock-capture",
        "scm_ref": scm_ref,
        "scenario_id": stage.scenario.scenario_id,
        "scenario_sha256": stage.scenario.scenario_sha256,
        "profile_stage_id": stage.stage_id,
        "profile_stage_sha256": stage.canonical_sha256,
        "execution_boundary": "mock",
        "actor_trigger": "agent-triggered",
        "release_id": "mock-release",
        "oracle_authority_id": oracle.oracle_authority_id,
        "oracle_authority_sha256": oracle.canonical_sha256,
        "buyer_receipt_sha256s": [
            item.receipt.canonical_sha256
            for item in evidence
            if item.plan.role == "buyer"
        ],
        "seller_receipt_sha256s": [
            item.receipt.canonical_sha256
            for item in evidence
            if item.plan.role == "seller"
        ],
        "action_result_sha256s": [
            chain.result.canonical_sha256 for chain in chains
        ],
        "action_sha256s": [
            chain.authority.canonical_sha256 for chain in chains
        ],
        "prepared_action_sha256s": [
            chain.authority.action["prepared_action_sha256"]
            for chain in chains
        ],
        "captured_payloads": [
            {
                "action_id": chain.authority.action_id,
                "action_kind": chain.authority.action_kind,
                "actor_slot": chain.authority.actor_slot,
                "release_id": chain.authority.release_id,
                "action_sha256": chain.authority.canonical_sha256,
                "prepared_action_sha256": chain.authority.action[
                    "prepared_action_sha256"
                ],
                "payload_sha256": chain.authority.action["payload_sha256"],
                "runtime_binding": chain.authority.action[
                    "runtime_binding"
                ],
                "concrete_payload_binding": chain.authority.action[
                    "concrete_payload_binding"
                ],
            }
            for chain in chains
        ],
        "runtime_service_bindings": [
            {
                "seller_slot": "seller-1",
                "service_slot": "seller-service-1",
                "runtime_binding": binding(
                    RUNTIME_BINDING_DOMAIN,
                    "service:seller-1:seller-service-1",
                ),
            }
        ],
        "runtime_listing_bindings": [
            {
                "seller_slot": "seller-1",
                "listing_slot": "listing-1",
                "runtime_binding": binding(
                    RUNTIME_BINDING_DOMAIN,
                    "listing:seller-1:listing-1",
                ),
            }
        ],
        "actor_invocation_capabilities": [
            {
                "actor_slot": plan.actor_slot,
                "binding": plan.plan[
                    "actor_invocation_capability_binding"
                ],
            }
            for plan in plans
        ],
        "agent_ownership_proof_scope": "portable-binding-only",
        "private_actor_ownership_verified": False,
        "live_resource_ledger": [],
        "complete_stage_actor_set_claimed": False,
        "registry_admission_claimed": False,
        "real_oracle_claimed": False,
        "capacity_claimed": False,
        "result_kind": "mock-preparation-only",
        "completed_at": "2026-07-30T10:00:09.000000Z",
    }
    assert validate_mock_capture(capture, evidence).capture_id == (
        "b1-s1-g1-mock-capture"
    )
    assert "b1-s1-g1-mock" not in {
        item["stage_id"]
        for item in json.loads((repo / PROFILE_REGISTRY_PATH).read_text())[
            "stages"
        ]
    }

    duplicate = action_capture(
        chains[0].authority,
        next(
            plan
            for plan in plans
            if plan.actor_slot == chains[0].authority.actor_slot
        ),
        payload_bytes=chains[0].payload,
        oracle_authority=oracle,
        concurrency_policy=None,
        expected_action_kind=chains[0].authority.action_kind,
        current_runtime_binding=chains[0].runtime_binding,
        current_concrete_payload_binding=chains[0].authority.action[
            "concrete_payload_binding"
        ],
        current_actor_invocation_capability=chains[0].authority.action[
            "actor_invocation_capability_binding"
        ],
        actor_alive_at_invocation=True,
        claim_ledger=ledger,
        result_output=outputs / "duplicate.json",
        clock=clock,
    )
    assert duplicate.result.result["failure_code"] == "duplicate-release"
    assert duplicate.result.result["emission_count"] == 0
    assert duplicate.record_path is not None


def test_capture_rejects_changed_runtime_binding_before_claim(
    authority_repo: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repo, scm_ref = authority_repo
    plans = _validated_plans(
        repo,
        scm_ref,
        "b1-s1-g1-mock",
        roles={"buyer", "seller"},
    )
    oracle = _oracle(repo, scm_ref, "b1-s1-g1-mock", plans)
    chains = _action_chains(plans, oracle, None)
    chain = next(
        item
        for item in chains
        if item.authority.action_kind == "buyer-request"
    )
    ledger = tmp_path / "claims"
    results = tmp_path / "results"
    ledger.mkdir(mode=0o700)
    results.mkdir(mode=0o700)
    captured = action_capture(
        chain.authority,
        next(
            plan
            for plan in plans
            if plan.actor_slot == chain.authority.actor_slot
        ),
        payload_bytes=chain.payload,
        oracle_authority=oracle,
        concurrency_policy=None,
        expected_action_kind="buyer-request",
        current_runtime_binding=binding(
            RUNTIME_BINDING_DOMAIN,
            "changed-native-listing",
        ),
        current_concrete_payload_binding=chain.authority.action[
            "concrete_payload_binding"
        ],
        current_actor_invocation_capability=chain.authority.action[
            "actor_invocation_capability_binding"
        ],
        actor_alive_at_invocation=True,
        claim_ledger=ledger,
        result_output=results / "changed-binding.json",
    )

    assert captured.result.result["failure_code"] == "runtime-binding-changed"
    assert captured.result.result["emission_count"] == 0
    assert captured.record_path is not None

    corrected = action_capture(
        chain.authority,
        next(
            plan
            for plan in plans
            if plan.actor_slot == chain.authority.actor_slot
        ),
        payload_bytes=chain.payload,
        oracle_authority=oracle,
        concurrency_policy=None,
        expected_action_kind="buyer-request",
        current_runtime_binding=chain.runtime_binding,
        current_concrete_payload_binding=chain.authority.action[
            "concrete_payload_binding"
        ],
        current_actor_invocation_capability=chain.authority.action[
            "actor_invocation_capability_binding"
        ],
        actor_alive_at_invocation=True,
        claim_ledger=ledger,
        result_output=results / "corrected-after-rejection.json",
    )
    assert corrected.result.result["failure_code"] == "duplicate-release"
    assert corrected.result.result["emission_count"] == 0


def test_capture_emits_typed_rejections_for_every_just_in_time_guard(
    authority_repo: tuple[Path, str],
    tmp_path: Path,
) -> None:
    repo, scm_ref = authority_repo
    plans = _validated_plans(
        repo,
        scm_ref,
        "b1-s1-g1-mock",
        roles={"buyer", "seller"},
    )
    oracle = _oracle(repo, scm_ref, "b1-s1-g1-mock", plans)
    chain = next(
        item
        for item in _action_chains(plans, oracle, None)
        if item.authority.action_kind == "buyer-request"
    )
    plan = next(
        item for item in plans if item.actor_slot == chain.authority.actor_slot
    )
    ledger = tmp_path / "claims"
    results = tmp_path / "results"
    ledger.mkdir(mode=0o700)
    results.mkdir(mode=0o700)

    def capture(label: str, **overrides: Any) -> str | None:
        claim_ledger = ledger / label
        arguments: dict[str, Any] = {
            "payload_bytes": chain.payload,
            "oracle_authority": oracle,
            "concurrency_policy": None,
            "expected_action_kind": "buyer-request",
            "current_runtime_binding": chain.runtime_binding,
            "current_concrete_payload_binding": chain.authority.action[
                "concrete_payload_binding"
            ],
            "current_actor_invocation_capability": chain.authority.action[
                "actor_invocation_capability_binding"
            ],
            "actor_alive_at_invocation": True,
            "claim_ledger": claim_ledger,
            "result_output": results / f"{label}.json",
        }
        arguments.update(overrides)
        captured = action_capture(chain.authority, plan, **arguments)
        assert captured.result.result_kind == "rejected-before-emission"
        assert captured.result.result["emission_count"] == 0
        assert captured.record_path is not None
        return captured.result.result["failure_code"]

    changed_action = deepcopy(chain.authority.action)
    changed_action["release_id"] = "changed-release"
    assert capture(
        "authority-action",
        current_action=changed_action,
    ) == "authority-changed"

    changed_plan = deepcopy(plan.plan)
    changed_plan["actor_slot"] = "buyer-99"
    assert capture(
        "authority-plan",
        current_plan=changed_plan,
    ) == "authority-changed"

    changed_oracle = deepcopy(oracle.authority)
    changed_oracle["oracle_authority_id"] = "changed-oracle"
    assert capture(
        "authority-oracle",
        current_oracle_authority=changed_oracle,
    ) == "authority-changed"

    changed_payload = json.loads(chain.payload)
    changed_payload["operation"] = "changed-operation"
    assert capture(
        "payload",
        current_payload_bytes=canonical_json_bytes(changed_payload),
    ) == "payload-changed"

    assert capture(
        "selection",
        expected_action_kind="seller-service-start",
    ) == "selection-changed"

    assert capture(
        "concrete-payload",
        current_concrete_payload_binding=binding(
            CONCRETE_PAYLOAD_BINDING_DOMAIN,
            "changed-concrete-payload",
        ),
    ) == "payload-changed"

    assert capture(
        "capability",
        current_actor_invocation_capability=binding(
            ACTOR_INVOCATION_BINDING_DOMAIN,
            "changed-capability",
        ),
    ) == "authority-changed"

    assert capture(
        "actor-exited",
        actor_alive_at_invocation=False,
    ) == "actor-exited"
    assert capture("retry", attempt=2) == "unauthorized-retry"
    assert capture(
        "retry-after-exit",
        attempt=2,
        actor_alive_at_invocation=False,
    ) == "unauthorized-retry"

    wrapper = repo / chain.authority.action["wrapper"]["path"]
    wrapper.write_text(
        wrapper.read_text(encoding="utf-8") + "# hidden drift\n",
        encoding="utf-8",
    )
    assert capture("wrapper") == "wrapper-changed"


def test_atomic_capture_record_recovers_terminal_result_after_output_failure(
    authority_repo: tuple[Path, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, scm_ref = authority_repo
    plans = _validated_plans(
        repo,
        scm_ref,
        "b1-s1-g1-mock",
        roles={"buyer", "seller"},
    )
    oracle = _oracle(repo, scm_ref, "b1-s1-g1-mock", plans)
    chains = _action_chains(plans, oracle, None)
    chain = next(
        item
        for item in chains
        if item.authority.action_kind == "buyer-request"
    )
    plan = next(
        item for item in plans if item.actor_slot == chain.authority.actor_slot
    )
    ledger = tmp_path / "ledger"
    results = tmp_path / "results"
    ledger.mkdir(mode=0o700)
    results.mkdir(mode=0o700)
    result_output = results / "recover.json"

    from issue_discovery import capacity_roles as role_module

    original_install = role_module._atomic_install_owner_only
    failed = False

    def fail_first_result(path: Path, content: bytes, *, label: str) -> None:
        nonlocal failed
        if label == "action result" and not failed:
            failed = True
            raise CapacityValidationError("simulated result materialization failure")
        original_install(path, content, label=label)

    monkeypatch.setattr(
        role_module,
        "_atomic_install_owner_only",
        fail_first_result,
    )
    with pytest.raises(CapacityValidationError, match="simulated"):
        action_capture(
            chain.authority,
            plan,
            payload_bytes=chain.payload,
            oracle_authority=oracle,
            concurrency_policy=None,
            expected_action_kind="buyer-request",
            current_runtime_binding=chain.runtime_binding,
            current_concrete_payload_binding=chain.authority.action[
                "concrete_payload_binding"
            ],
            current_actor_invocation_capability=chain.authority.action[
                "actor_invocation_capability_binding"
            ],
            actor_alive_at_invocation=True,
            claim_ledger=ledger,
            result_output=result_output,
        )
    record = next(ledger.glob("*.capture-record.json"))
    original_record_bytes = record.read_bytes()
    original_record = json.loads(original_record_bytes)
    first_result = original_record["first_result"]
    monkeypatch.setattr(
        role_module,
        "_atomic_install_owner_only",
        original_install,
    )

    corrupted_record = deepcopy(original_record)
    corrupted_record["action_sha256"] = "0" * 64
    record.write_bytes(canonical_json_bytes(corrupted_record))
    with pytest.raises(
        CapacityValidationError,
        match="capture record action_sha256",
    ):
        action_capture(
            chain.authority,
            plan,
            payload_bytes=chain.payload,
            oracle_authority=oracle,
            concurrency_policy=None,
            expected_action_kind="buyer-request",
            current_runtime_binding=chain.runtime_binding,
            current_concrete_payload_binding=chain.authority.action[
                "concrete_payload_binding"
            ],
            current_actor_invocation_capability=chain.authority.action[
                "actor_invocation_capability_binding"
            ],
            actor_alive_at_invocation=True,
            claim_ledger=ledger,
            result_output=result_output,
        )
    record.write_bytes(original_record_bytes)

    result_output.write_bytes(b"{}\n")
    result_output.chmod(0o600)
    with pytest.raises(
        CapacityValidationError,
        match="does not match the durable first result",
    ):
        action_capture(
            chain.authority,
            plan,
            payload_bytes=chain.payload,
            oracle_authority=oracle,
            concurrency_policy=None,
            expected_action_kind="buyer-request",
            current_runtime_binding=chain.runtime_binding,
            current_concrete_payload_binding=chain.authority.action[
                "concrete_payload_binding"
            ],
            current_actor_invocation_capability=chain.authority.action[
                "actor_invocation_capability_binding"
            ],
            actor_alive_at_invocation=True,
            claim_ledger=ledger,
            result_output=result_output,
        )
    result_output.unlink()

    recovered = action_capture(
        chain.authority,
        plan,
        payload_bytes=chain.payload,
        oracle_authority=oracle,
        concurrency_policy=None,
        expected_action_kind="buyer-request",
        current_runtime_binding=chain.runtime_binding,
        current_concrete_payload_binding=chain.authority.action[
            "concrete_payload_binding"
        ],
        current_actor_invocation_capability=chain.authority.action[
            "actor_invocation_capability_binding"
        ],
        actor_alive_at_invocation=True,
        claim_ledger=ledger,
        result_output=result_output,
    )
    assert recovered.recovered is True
    assert recovered.result.result == first_result
    assert json.loads(result_output.read_text()) == first_result

    post_link_chain = next(
        item
        for item in chains
        if item.authority.action_kind == "seller-service-start"
    )
    post_link_plan = next(
        item
        for item in plans
        if item.actor_slot == post_link_chain.authority.actor_slot
    )
    post_link_failed = False

    def install_then_report_failure(
        path: Path,
        content: bytes,
        *,
        label: str,
    ) -> None:
        nonlocal post_link_failed
        original_install(path, content, label=label)
        if label == "atomic action capture record" and not post_link_failed:
            post_link_failed = True
            raise OSError("simulated directory fsync failure after link")

    monkeypatch.setattr(
        role_module,
        "_atomic_install_owner_only",
        install_then_report_failure,
    )
    post_link_output = results / "post-link-recovery.json"
    post_link = action_capture(
        post_link_chain.authority,
        post_link_plan,
        payload_bytes=post_link_chain.payload,
        oracle_authority=oracle,
        concurrency_policy=None,
        expected_action_kind="seller-service-start",
        current_runtime_binding=post_link_chain.runtime_binding,
        current_concrete_payload_binding=post_link_chain.authority.action[
            "concrete_payload_binding"
        ],
        current_actor_invocation_capability=post_link_chain.authority.action[
            "actor_invocation_capability_binding"
        ],
        actor_alive_at_invocation=True,
        claim_ledger=ledger,
        result_output=post_link_output,
    )
    assert post_link.recovered is True
    assert post_link.result.result_kind == "emitted"
    assert json.loads(post_link_output.read_text()) == post_link.result.result

    result_link_chain = next(
        item
        for item in chains
        if item.authority.action_kind == "seller-listing-publication"
    )
    result_link_plan = next(
        item
        for item in plans
        if item.actor_slot == result_link_chain.authority.actor_slot
    )
    result_link_failed = False

    def result_install_then_report_failure(
        path: Path,
        content: bytes,
        *,
        label: str,
    ) -> None:
        nonlocal result_link_failed
        original_install(path, content, label=label)
        if label == "action result" and not result_link_failed:
            result_link_failed = True
            raise OSError("simulated result fsync failure after link")

    monkeypatch.setattr(
        role_module,
        "_atomic_install_owner_only",
        result_install_then_report_failure,
    )
    result_link_output = results / "post-result-link.json"
    result_link = action_capture(
        result_link_chain.authority,
        result_link_plan,
        payload_bytes=result_link_chain.payload,
        oracle_authority=oracle,
        concurrency_policy=None,
        expected_action_kind="seller-listing-publication",
        current_runtime_binding=result_link_chain.runtime_binding,
        current_concrete_payload_binding=result_link_chain.authority.action[
            "concrete_payload_binding"
        ],
        current_actor_invocation_capability=result_link_chain.authority.action[
            "actor_invocation_capability_binding"
        ],
        actor_alive_at_invocation=True,
        claim_ledger=ledger,
        result_output=result_link_output,
    )
    assert result_link.result.result_kind == "emitted"
    assert json.loads(result_link_output.read_text()) == result_link.result.result


def test_cuda_workload_is_pinned_real_kernel_and_exact_checksum() -> None:
    source = (REPO_ROOT / CUDA_SOURCE_PATH).read_text(encoding="utf-8")
    wrapper = (REPO_ROOT / CUDA_WRAPPER_PATH).read_text(encoding="utf-8")

    assert "__global__ void vector_add" in source
    assert "cudaGetDeviceCount" in source
    assert "visible_devices != 1" in source
    assert "cudaDeviceSynchronize" in source
    assert "checksum=1571328" in wrapper
    expected_output = "SCM_CUDA_VECTOR_ADD_OK elements=1024 checksum=1571328\n"
    assert hashlib.sha256(expected_output.encode()).hexdigest() == (
        CUDA_RESULT_CHECKSUM
    )
    assert os.access(REPO_ROOT / CUDA_WRAPPER_PATH, os.X_OK)
