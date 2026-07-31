from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_ROOT = PACKAGE_ROOT / "schemas"
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "capacity" / "v2"
FINDING_V2_CONTRACT_REF = "94dd6b636fcaf8fe9ae1bb350b708a33d28d2258"
DELETE = object()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validator(schema_name: str) -> Draft202012Validator:
    schema = load_json(SCHEMA_ROOT / schema_name)
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.mark.parametrize(
    ("schema_name", "fixture_name", "collection"),
    [
        ("capacity-profile-stage.schema.json", "profile-stage.json", False),
        ("capacity-profile-stage.schema.json", "mock-profile-stage.json", False),
        ("capacity-role-plan.schema.json", "role-plans.json", True),
        ("capacity-role-plan.schema.json", "mock-role-plans.json", True),
        ("capacity-role-receipt.schema.json", "role-receipts.json", True),
        ("capacity-role-receipt.schema.json", "mock-role-receipts.json", True),
        ("capacity-action-payload.schema.json", "action-payloads.json", True),
        (
            "capacity-action-payload.schema.json",
            "mock-action-payloads.json",
            True,
        ),
        ("capacity-frozen-action.schema.json", "frozen-actions.json", True),
        (
            "capacity-frozen-action.schema.json",
            "mock-frozen-actions.json",
            True,
        ),
        ("capacity-action-result.schema.json", "action-results.json", True),
        (
            "capacity-action-result.schema.json",
            "mock-action-results.json",
            True,
        ),
        ("capacity-oracle-authority.schema.json", "oracle-authorities.json", True),
        (
            "capacity-concurrency-policy.schema.json",
            "concurrency-policy.json",
            False,
        ),
        ("capacity-actor-set.schema.json", "actor-set.json", False),
        ("capacity-mock-capture.schema.json", "mock-capture.json", False),
        ("capacity-result.schema.json", "capacity-result.json", False),
        (
            "capacity-finding.schema.json",
            "findings/classification-findings.json",
            True,
        ),
    ],
)
def test_capacity_v2_positive_contract_fixtures(
    schema_name: str,
    fixture_name: str,
    collection: bool,
) -> None:
    value = load_json(FIXTURE_ROOT / fixture_name)
    values = value if collection else [value]
    contract = validator(schema_name)

    assert values
    for item in values:
        contract.validate(item)


def test_public_finding_example_is_pinned_to_committed_v2_authority() -> None:
    schema_path = Path("tools/issue-discovery/schemas/capacity-finding.schema.json")
    example_path = PACKAGE_ROOT / "config" / "capacity" / "findings" / "example.json"
    pinned_schema = subprocess.run(
        [
            "git",
            "show",
            f"{FINDING_V2_CONTRACT_REF}:{schema_path.as_posix()}",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    current_schema = (REPO_ROOT / schema_path).read_bytes()
    schema = json.loads(pinned_schema.decode("utf-8"))
    example = load_json(example_path)

    assert current_schema == pinned_schema
    assert schema["properties"]["schema_version"]["const"] == 2
    assert example["schema_version"] == 2
    assert example["scm_contract_ref"] == FINDING_V2_CONTRACT_REF
    assert example["observed_authority"]["working_ref"] == FINDING_V2_CONTRACT_REF
    evidence = FIXTURE_ROOT / example["evidence"][0]["path"]
    assert (
        hashlib.sha256(evidence.read_bytes()).hexdigest()
        == (example["evidence"][0]["sha256"])
    )
    Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    ).validate(example)


def test_all_json_schemas_are_valid_draft_2020_12_contracts() -> None:
    schemas = sorted(SCHEMA_ROOT.glob("*.schema.json"))

    assert schemas
    for path in schemas:
        Draft202012Validator.check_schema(load_json(path))


def assert_real_receipt_run_authorities(
    receipts: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    policy: dict[str, Any],
) -> None:
    qualification_actions = [
        action
        for action in actions
        if action["profile_stage_id"] == policy["profile_stage_id"]
    ]
    policy_digests = {
        action["concurrency_policy_sha256"] for action in qualification_actions
    }
    assert qualification_actions
    assert len(policy_digests) == 1
    policy_digest = next(iter(policy_digests))
    assert policy_digest is not None

    expected_campaign_authority = {
        "release_id": policy["release_id"],
        "concurrency_policy_id": policy["policy_id"],
        "concurrency_policy_sha256": policy_digest,
    }
    for receipt in receipts:
        if receipt["profile_stage_id"] == policy["profile_stage_id"]:
            assert receipt["run_authority"] == expected_campaign_authority
        else:
            assert receipt["scenario_id"] is None
            assert receipt["scenario_sha256"] is None
            assert receipt["run_authority"] == {
                "release_id": receipt["profile_stage_id"],
                "concurrency_policy_id": None,
                "concurrency_policy_sha256": None,
            }


def test_capacity_v2_fixture_authority_chain_is_coherent() -> None:
    plans = load_json(FIXTURE_ROOT / "role-plans.json")
    receipts = load_json(FIXTURE_ROOT / "role-receipts.json")
    payloads = load_json(FIXTURE_ROOT / "action-payloads.json")
    actions = load_json(FIXTURE_ROOT / "frozen-actions.json")
    policy = load_json(FIXTURE_ROOT / "concurrency-policy.json")
    actor_set = load_json(FIXTURE_ROOT / "actor-set.json")
    plans_by_id = {plan["plan_id"]: plan for plan in plans}
    plans_by_stage_actor = {
        (plan["profile_stage_id"], plan["actor_slot"]): plan for plan in plans
    }
    host_topology_authority = next(
        plan["role_plan"]["topology_authority_binding"]
        for plan in plans
        if plan["role"] == "host-operator"
    )
    payloads_by_id = {payload["action_id"]: payload for payload in payloads}
    assert_real_receipt_run_authorities(receipts, actions, policy)

    for receipt in receipts:
        plan = plans_by_stage_actor[
            (receipt["profile_stage_id"], receipt["actor_slot"])
        ]
        assert receipt["plan_id"] == plan["plan_id"]
        assert (
            receipt["provenance"]["actor_invocation_capability_binding"]
            == plan["actor_invocation_capability_binding"]
        )
        if plan["role"] == "seller":
            assert (
                plan["role_plan"]["topology_authority_binding"]
                == host_topology_authority
            )
            assert (
                receipt["role_evidence"]["topology_authority_binding"]
                == host_topology_authority
            )

    prepared_actions: dict[str, str] = {}
    for plan in plans:
        role_plan = plan["role_plan"]
        if role_plan["kind"] == "buyer":
            prepared_actions[role_plan["action_id"]] = role_plan[
                "prepared_action_sha256"
            ]
        elif role_plan["kind"] == "seller":
            prepared_actions[role_plan["service_start_action_id"]] = role_plan[
                "service_start_prepared_action_sha256"
            ]
            prepared_actions.update(
                zip(
                    role_plan["publication_action_ids"],
                    role_plan["publication_prepared_action_sha256s"],
                    strict=True,
                )
            )

    for action in actions:
        plan = plans_by_id[action["role_plan_id"]]
        payload = payloads_by_id[action["action_id"]]
        assert action["actor_slot"] == plan["actor_slot"] == payload["actor_slot"]
        assert (
            action["isolated_identity_fingerprint"]
            == plan["isolated_identity_fingerprint"]
        )
        assert (
            action["actor_invocation_capability_binding"]
            == plan["actor_invocation_capability_binding"]
        )
        assert action["prepared_action_sha256"] == prepared_actions[action["action_id"]]
        assert action["action_kind"] == payload["action_kind"]
        assert action["logical_selection"] == payload["logical_selection"]
        assert action["release_id"] == policy["release_id"]
        assert action["concurrency_policy_id"] == policy["policy_id"]

    qualification_receipts = {
        receipt["plan_id"]: receipt["plan_sha256"]
        for receipt in receipts
        if receipt["profile_stage_id"] == policy["profile_stage_id"]
    }
    assert {
        item["plan_id"]: item["plan_sha256"] for item in policy["role_plan_authorities"]
    } == qualification_receipts
    assert {
        item["action_id"]: item["prepared_action_sha256"]
        for item in policy["prepared_action_authorities"]
    } == prepared_actions

    assert policy["release_id"] == actor_set["release_id"]


@pytest.mark.parametrize(
    ("field", "stale_value"),
    [
        ("release_id", "stale-release"),
        ("concurrency_policy_id", "stale-concurrency-policy"),
        ("concurrency_policy_sha256", "f" * 64),
    ],
)
def test_receipt_run_authority_coherence_rejects_stale_campaign_binding(
    field: str,
    stale_value: str,
) -> None:
    receipts = load_json(FIXTURE_ROOT / "role-receipts.json")
    actions = load_json(FIXTURE_ROOT / "frozen-actions.json")
    policy = load_json(FIXTURE_ROOT / "concurrency-policy.json")
    receipts[0]["run_authority"][field] = stale_value

    # The stale value remains structurally valid; campaign coherence must reject it.
    validator("capacity-role-receipt.schema.json").validate(receipts[0])
    with pytest.raises(AssertionError):
        assert_real_receipt_run_authorities(receipts, actions, policy)


def canonical_sha256(value: Any) -> str:
    encoded = (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


PREPARED_ACTION_FIELDS = (
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


def test_mock_fixture_chain_is_distinct_exact_and_self_consistent() -> None:
    stage = load_json(FIXTURE_ROOT / "mock-profile-stage.json")
    plans = load_json(FIXTURE_ROOT / "mock-role-plans.json")
    receipts = load_json(FIXTURE_ROOT / "mock-role-receipts.json")
    payloads = load_json(FIXTURE_ROOT / "mock-action-payloads.json")
    actions = load_json(FIXTURE_ROOT / "mock-frozen-actions.json")
    results = load_json(FIXTURE_ROOT / "mock-action-results.json")
    oracle = next(
        item
        for item in load_json(FIXTURE_ROOT / "oracle-authorities.json")
        if item["execution_boundary"] == "mock"
    )
    capture = load_json(FIXTURE_ROOT / "mock-capture.json")

    assert stage["stage_id"] == "b1-s1-g1-mock"
    assert stage["execution_boundary"] == "mock"
    assert stage["expected_outcomes"] is None
    assert capture["profile_stage_sha256"] == canonical_sha256(stage)
    assert {plan["profile_stage_id"] for plan in plans} == {stage["stage_id"]}
    assert {plan["role"] for plan in plans} == {"buyer", "seller"}
    assert {receipt["profile_stage_id"] for receipt in receipts} == {stage["stage_id"]}
    assert {action["profile_stage_id"] for action in actions} == {stage["stage_id"]}
    assert all(action["concurrency_policy_id"] is None for action in actions)
    assert all(action["concurrency_policy_sha256"] is None for action in actions)
    expected_mock_run_authority = {
        "release_id": capture["release_id"],
        "concurrency_policy_id": None,
        "concurrency_policy_sha256": None,
    }
    assert all(
        receipt["run_authority"] == expected_mock_run_authority for receipt in receipts
    )
    assert all(
        action["release_id"] == expected_mock_run_authority["release_id"]
        for action in actions
    )
    assert (
        oracle["profile_stage_id"] == capture["profile_stage_id"] == stage["stage_id"]
    )
    assert capture["oracle_authority_id"] == oracle["oracle_authority_id"]
    assert capture["oracle_authority_sha256"] == canonical_sha256(oracle)

    plans_by_id = {plan["plan_id"]: plan for plan in plans}
    receipts_by_plan = {receipt["plan_id"]: receipt for receipt in receipts}
    payloads_by_id = {payload["action_id"]: payload for payload in payloads}
    actions_by_id = {action["action_id"]: action for action in actions}
    results_by_action = {result["action_id"]: result for result in results}
    assert len(plans_by_id) == len(plans)
    assert len(receipts_by_plan) == len(receipts)
    assert len(payloads_by_id) == len(payloads) == 3
    assert set(payloads_by_id) == set(actions_by_id) == set(results_by_action)

    prepared_by_id: dict[str, str] = {}
    for plan in plans:
        role_plan = plan["role_plan"]
        assert plan["prepared_authority_sha256"] == canonical_sha256(role_plan)
        if plan["role"] == "buyer":
            prepared_by_id[role_plan["action_id"]] = role_plan["prepared_action_sha256"]
        else:
            prepared_by_id[role_plan["service_start_action_id"]] = role_plan[
                "service_start_prepared_action_sha256"
            ]
            prepared_by_id.update(
                zip(
                    role_plan["publication_action_ids"],
                    role_plan["publication_prepared_action_sha256s"],
                    strict=True,
                )
            )
        receipt = receipts_by_plan[plan["plan_id"]]
        assert receipt["plan_sha256"] == canonical_sha256(plan)
        assert (
            receipt["provenance"]["actor_invocation_capability_binding"]
            == plan["actor_invocation_capability_binding"]
        )
        if plan["role"] == "seller":
            assert (
                receipt["role_evidence"]["topology_authority_binding"]
                == role_plan["topology_authority_binding"]
            )

    for action_id, action in actions_by_id.items():
        plan = plans_by_id[action["role_plan_id"]]
        payload = payloads_by_id[action_id]
        result = results_by_action[action_id]
        prepared_projection = {field: action[field] for field in PREPARED_ACTION_FIELDS}
        assert action["role_plan_sha256"] == canonical_sha256(plan)
        assert action["prepared_action_sha256"] == canonical_sha256(prepared_projection)
        assert action["prepared_action_sha256"] == prepared_by_id[action_id]
        assert action["payload_sha256"] == canonical_sha256(payload)
        assert action["expected_result"][
            "independent_oracle_authority_sha256"
        ] == canonical_sha256(oracle)
        assert result["action_sha256"] == canonical_sha256(action)
        assert result["terminal_payload_sha256"] == action["payload_sha256"]

    assert set(capture["buyer_receipt_sha256s"]) == {
        canonical_sha256(receipt) for receipt in receipts if receipt["role"] == "buyer"
    }
    assert set(capture["seller_receipt_sha256s"]) == {
        canonical_sha256(receipt) for receipt in receipts if receipt["role"] == "seller"
    }
    assert set(capture["action_sha256s"]) == {
        canonical_sha256(action) for action in actions
    }
    assert set(capture["prepared_action_sha256s"]) == set(prepared_by_id.values())
    assert set(capture["action_result_sha256s"]) == {
        canonical_sha256(result) for result in results
    }
    expected_capabilities = {
        plan["actor_slot"]: plan["actor_invocation_capability_binding"]
        for plan in plans
    }
    assert {
        item["actor_slot"]: item["binding"]
        for item in capture["actor_invocation_capabilities"]
    } == expected_capabilities
    assert capture["agent_ownership_proof_scope"] == "portable-binding-only"
    assert capture["private_actor_ownership_verified"] is False
    assert capture["live_resource_ledger"] == []
    assert capture["capacity_claimed"] is False

    captured_by_id = {item["action_id"]: item for item in capture["captured_payloads"]}
    for action_id, action in actions_by_id.items():
        captured = captured_by_id[action_id]
        assert captured["action_sha256"] == canonical_sha256(action)
        assert captured["prepared_action_sha256"] == action["prepared_action_sha256"]
        assert captured["payload_sha256"] == action["payload_sha256"]
        assert captured["runtime_binding"] == action["runtime_binding"]
        assert (
            captured["concrete_payload_binding"] == action["concrete_payload_binding"]
        )

    service_runtime = {
        (item["seller_slot"], item["service_slot"]): item["runtime_binding"]
        for item in capture["runtime_service_bindings"]
    }
    listing_runtime = {
        (item["seller_slot"], item["listing_slot"]): item["runtime_binding"]
        for item in capture["runtime_listing_bindings"]
    }
    for action in actions:
        selection = action["logical_selection"]
        if action["action_kind"] == "seller-service-start":
            expected_runtime = service_runtime[
                (selection["seller_slot"], selection["service_slot"])
            ]
        else:
            expected_runtime = listing_runtime[
                (selection["seller_slot"], selection["listing_slot"])
            ]
        assert action["runtime_binding"] == expected_runtime

    buyer_receipt = next(receipt for receipt in receipts if receipt["role"] == "buyer")
    buyer_action_id = plans_by_id[buyer_receipt["plan_id"]]["role_plan"]["action_id"]
    assert buyer_receipt["role_evidence"]["action_result_sha256"] == (
        canonical_sha256(results_by_action[buyer_action_id])
    )
    seller_receipt = next(
        receipt for receipt in receipts if receipt["role"] == "seller"
    )
    seller_role_plan = plans_by_id[seller_receipt["plan_id"]]["role_plan"]
    assert seller_receipt["role_evidence"][
        "service_start_result_sha256"
    ] == canonical_sha256(
        results_by_action[seller_role_plan["service_start_action_id"]]
    )
    assert seller_receipt["role_evidence"]["publication_result_sha256s"] == [
        canonical_sha256(results_by_action[action_id])
        for action_id in seller_role_plan["publication_action_ids"]
    ]


@dataclass(frozen=True)
class NegativeCase:
    name: str
    schema_name: str
    fixture_name: str
    item_index: int | None
    path: tuple[str | int, ...]
    replacement: object


NEGATIVE_CASES = [
    NegativeCase(
        "unknown profile-stage key",
        "capacity-profile-stage.schema.json",
        "profile-stage.json",
        None,
        ("private_host_id",),
        "host-17",
    ),
    NegativeCase(
        "missing exact SCM authority",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        0,
        ("scm_ref",),
        DELETE,
    ),
    NegativeCase(
        "unresolved scenario path placeholder",
        "capacity-profile-stage.schema.json",
        "profile-stage.json",
        None,
        ("scenario_binding", "scenario_path"),
        "${SCENARIO_PATH}",
    ),
    NegativeCase(
        "private wallet identity field",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        0,
        ("wallet_address",),
        "0x1234567890abcdef",
    ),
    NegativeCase(
        "executor-local instruction path",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        0,
        ("instruction", "path"),
        "/home/operator/private-buyer.md",
    ),
    NegativeCase(
        "malformed content digest",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        0,
        ("instruction", "sha256"),
        "not-a-sha256",
    ),
    NegativeCase(
        "calendar-invalid lifecycle timestamp",
        "capacity-role-receipt.schema.json",
        "role-receipts.json",
        0,
        ("lifecycle", "started_at"),
        "not-a-timestamp",
    ),
    NegativeCase(
        "receipt omits run authority",
        "capacity-role-receipt.schema.json",
        "role-receipts.json",
        0,
        ("run_authority",),
        DELETE,
    ),
    NegativeCase(
        "receipt run authority is not closed",
        "capacity-role-receipt.schema.json",
        "role-receipts.json",
        0,
        ("run_authority", "private_release_token"),
        "forbidden",
    ),
    NegativeCase(
        "receipt policy authority is half null",
        "capacity-role-receipt.schema.json",
        "role-receipts.json",
        0,
        ("run_authority", "concurrency_policy_sha256"),
        None,
    ),
    NegativeCase(
        "duplicate logical listing identities",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        1,
        ("role_plan", "listing_slots"),
        ["listing-1", "listing-1"],
    ),
    NegativeCase(
        "duplicate native evidence identities",
        "capacity-role-receipt.schema.json",
        "role-receipts.json",
        3,
        ("role_evidence", "native_evidence_bindings"),
        [
            {
                "method": "hmac-sha256-v1",
                "domain": "scm.capacity.native-evidence.v1",
                "value": "f" * 64,
            },
            {
                "method": "hmac-sha256-v1",
                "domain": "scm.capacity.native-evidence.v1",
                "value": "f" * 64,
            },
        ],
    ),
    NegativeCase(
        "frozen action retry",
        "capacity-frozen-action.schema.json",
        "frozen-actions.json",
        0,
        ("attempt",),
        2,
    ),
    NegativeCase(
        "one-shot result retry",
        "capacity-action-result.schema.json",
        "action-results.json",
        0,
        ("attempt",),
        2,
    ),
    NegativeCase(
        "buyer role with seller variant",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        0,
        ("role_plan",),
        {
            "kind": "seller",
            "service_slot": "seller-service-1",
            "listing_slots": ["listing-1"],
            "service_start_action_id": "seller-service-start-1",
            "service_start_prepared_action_sha256": "6" * 64,
            "publication_action_ids": ["seller-publication-1"],
            "publication_prepared_action_sha256s": ["7" * 64],
            "required_steps": [
                "install-build",
                "configuration",
                "wallet-preparation",
                "publication-preparation",
                "service-start",
                "listing-publication",
                "observation-liveness",
            ],
        },
    ),
    NegativeCase(
        "buyer action with service-start variant",
        "capacity-frozen-action.schema.json",
        "frozen-actions.json",
        0,
        ("logical_selection",),
        {
            "kind": "seller-service-start",
            "seller_slot": "seller-1",
            "service_slot": "seller-service-1",
        },
    ),
    NegativeCase(
        "wrong topology binding domain",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        2,
        ("role_plan", "topology_authority_binding", "domain"),
        "scm.capacity.reversible-baseline.v1",
    ),
    NegativeCase(
        "wrong seller-plan topology binding domain",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        1,
        ("role_plan", "topology_authority_binding", "domain"),
        "scm.capacity.reversible-baseline.v1",
    ),
    NegativeCase(
        "wrong seller-receipt topology binding domain",
        "capacity-role-receipt.schema.json",
        "role-receipts.json",
        1,
        ("role_evidence", "topology_authority_binding", "domain"),
        "scm.capacity.reversible-baseline.v1",
    ),
    NegativeCase(
        "wrong native-evidence binding domain",
        "capacity-role-receipt.schema.json",
        "role-receipts.json",
        3,
        ("role_evidence", "native_evidence_bindings", 0, "domain"),
        "scm.capacity.topology-authority.v1",
    ),
    NegativeCase(
        "wrong runtime binding domain",
        "capacity-frozen-action.schema.json",
        "frozen-actions.json",
        0,
        ("runtime_binding", "domain"),
        "scm.capacity.topology-authority.v1",
    ),
    NegativeCase(
        "wrong baseline binding domain",
        "capacity-result.schema.json",
        "capacity-result.json",
        None,
        ("cleanup", "reversible_baseline_binding", "domain"),
        "scm.capacity.baseline-equivalence.v1",
    ),
    NegativeCase(
        "missing scenario digest authority",
        "capacity-frozen-action.schema.json",
        "frozen-actions.json",
        0,
        ("scenario_sha256",),
        DELETE,
    ),
    NegativeCase(
        "malformed independent result digest",
        "capacity-result.schema.json",
        "capacity-result.json",
        None,
        (
            "aggregate_observation",
            "native_evidence_bindings",
            0,
            "value",
        ),
        "a" * 63,
    ),
    NegativeCase(
        "malformed action terminal timestamp",
        "capacity-action-result.schema.json",
        "action-results.json",
        0,
        ("terminal_at",),
        "2026-07-30 10:00:03",
    ),
    NegativeCase(
        "cross-role actor identity",
        "capacity-role-receipt.schema.json",
        "role-receipts.json",
        0,
        ("actor_slot",),
        "seller-1",
    ),
    NegativeCase(
        "emitted result carries failure",
        "capacity-action-result.schema.json",
        "action-results.json",
        0,
        ("failure_code",),
        "emission-failed",
    ),
    NegativeCase(
        "private capacity-result identity field",
        "capacity-result.schema.json",
        "capacity-result.json",
        None,
        ("cloud_project_id",),
        "private-project",
    ),
    NegativeCase(
        "mock stage claims capacity outcomes",
        "capacity-profile-stage.schema.json",
        "mock-profile-stage.json",
        None,
        ("expected_outcomes",),
        {
            "vm-succeeded": 1,
            "capacity-refused": 0,
            "fault": 0,
        },
    ),
    NegativeCase(
        "mock stage omits empty-ledger admission",
        "capacity-profile-stage.schema.json",
        "mock-profile-stage.json",
        None,
        ("admission",),
        {
            "all_of": ["capture-only-boundary"],
            "any_of": [],
        },
    ),
    NegativeCase(
        "buyer payload uses seller operation",
        "capacity-action-payload.schema.json",
        "action-payloads.json",
        0,
        ("operation",),
        "seller-service-start",
    ),
    NegativeCase(
        "buyer payload uses seller selection",
        "capacity-action-payload.schema.json",
        "action-payloads.json",
        0,
        ("logical_selection",),
        {
            "kind": "seller-service-start",
            "seller_slot": "seller-1",
            "service_slot": "seller-service-1",
        },
    ),
    NegativeCase(
        "private action payload field",
        "capacity-action-payload.schema.json",
        "action-payloads.json",
        0,
        ("wallet_private_key",),
        "redacted-but-forbidden",
    ),
    NegativeCase(
        "controller-authored role receipt",
        "capacity-role-receipt.schema.json",
        "role-receipts.json",
        0,
        ("provenance", "controller_authored"),
        True,
    ),
    NegativeCase(
        "controller-sourced observer evidence",
        "capacity-role-receipt.schema.json",
        "role-receipts.json",
        3,
        ("role_evidence", "controller_source"),
        True,
    ),
    NegativeCase(
        "observer probe plan carries scenario",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        4,
        ("scenario_id",),
        "b1-s1-g1",
    ),
    NegativeCase(
        "qualification plan omits scenario",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        0,
        ("scenario_id",),
        None,
    ),
    NegativeCase(
        "frozen action omits role plan digest",
        "capacity-frozen-action.schema.json",
        "frozen-actions.json",
        0,
        ("role_plan_sha256",),
        DELETE,
    ),
    NegativeCase(
        "absolute action-result schema path",
        "capacity-frozen-action.schema.json",
        "frozen-actions.json",
        0,
        ("expected_result", "action_result_schema", "path"),
        "/tmp/capacity-action-result.schema.json",
    ),
    NegativeCase(
        "emitted result actor already exited",
        "capacity-action-result.schema.json",
        "action-results.json",
        0,
        ("actor_alive_at_invocation",),
        False,
    ),
    NegativeCase(
        "emitted result failed authority check",
        "capacity-action-result.schema.json",
        "action-results.json",
        0,
        ("pre_emission_checks", "authority_unchanged"),
        False,
    ),
    NegativeCase(
        "unauthorized retry reports first attempt",
        "capacity-action-result.schema.json",
        "action-results.json",
        2,
        ("attempt",),
        1,
    ),
    NegativeCase(
        "duplicate release reports one claim",
        "capacity-action-result.schema.json",
        "action-results.json",
        3,
        ("release_claim_count",),
        1,
    ),
    NegativeCase(
        "actor-exited result reports live actor",
        "capacity-action-result.schema.json",
        "action-results.json",
        4,
        ("actor_alive_at_invocation",),
        True,
    ),
    NegativeCase(
        "mock oracle permits real capacity claim",
        "capacity-oracle-authority.schema.json",
        "oracle-authorities.json",
        0,
        ("real_oracle_allowed",),
        True,
    ),
    NegativeCase(
        "real oracle omits observer authority",
        "capacity-oracle-authority.schema.json",
        "oracle-authorities.json",
        1,
        ("observer_plan_sha256",),
        None,
    ),
    NegativeCase(
        "duplicate concurrency actor slots",
        "capacity-concurrency-policy.schema.json",
        "concurrency-policy.json",
        None,
        ("actor_slots",),
        [
            "observer-1",
            "buyer-1",
            "seller-1",
            "seller-1",
        ],
    ),
    NegativeCase(
        "wrong concurrency clock domain",
        "capacity-concurrency-policy.schema.json",
        "concurrency-policy.json",
        None,
        ("clock_evidence_binding", "domain"),
        "scm.capacity.runtime-binding.v1",
    ),
    NegativeCase(
        "unbounded concurrency emission skew",
        "capacity-concurrency-policy.schema.json",
        "concurrency-policy.json",
        None,
        ("invocation_windows", 0, "max_emission_skew_ns"),
        60_000_000_001,
    ),
    NegativeCase(
        "concurrency policy permits local queue",
        "capacity-concurrency-policy.schema.json",
        "concurrency-policy.json",
        None,
        ("deny_local_queue",),
        False,
    ),
    NegativeCase(
        "mock boundary claims substantive actor set",
        "capacity-actor-set.schema.json",
        "actor-set.json",
        None,
        ("execution_boundary",),
        "mock",
    ),
    NegativeCase(
        "wrong actor-set clock domain",
        "capacity-actor-set.schema.json",
        "actor-set.json",
        None,
        ("clock_evidence_binding", "domain"),
        "scm.capacity.runtime-binding.v1",
    ),
    NegativeCase(
        "actor start offset is not an integer",
        "capacity-actor-set.schema.json",
        "actor-set.json",
        None,
        ("actors", 0, "started_offset_ns"),
        1.5,
    ),
    NegativeCase(
        "actor completion offset is not an integer",
        "capacity-actor-set.schema.json",
        "actor-set.json",
        None,
        ("actors", 0, "completed_offset_ns"),
        "early",
    ),
    NegativeCase(
        "actor-set controller authors receipts",
        "capacity-actor-set.schema.json",
        "actor-set.json",
        None,
        ("controller_observation", "role_receipts_authored"),
        True,
    ),
    NegativeCase(
        "mock capture contains live resource",
        "capacity-mock-capture.schema.json",
        "mock-capture.json",
        None,
        ("live_resource_ledger",),
        ["vm-1"],
    ),
    NegativeCase(
        "mock capture claims complete actor set",
        "capacity-mock-capture.schema.json",
        "mock-capture.json",
        None,
        ("complete_stage_actor_set_claimed",),
        True,
    ),
    NegativeCase(
        "mock capture claims registry admission",
        "capacity-mock-capture.schema.json",
        "mock-capture.json",
        None,
        ("registry_admission_claimed",),
        True,
    ),
    NegativeCase(
        "mock capture claims real oracle",
        "capacity-mock-capture.schema.json",
        "mock-capture.json",
        None,
        ("real_oracle_claimed",),
        True,
    ),
    NegativeCase(
        "mock capture claims capacity result",
        "capacity-mock-capture.schema.json",
        "mock-capture.json",
        None,
        ("capacity_claimed",),
        True,
    ),
    NegativeCase(
        "role plan omits invocation capability",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        0,
        ("actor_invocation_capability_binding",),
        DELETE,
    ),
    NegativeCase(
        "wrong role-plan invocation capability domain",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        0,
        ("actor_invocation_capability_binding", "domain"),
        "scm.capacity.runtime-binding.v1",
    ),
    NegativeCase(
        "buyer plan omits prepared action authority",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        0,
        ("role_plan", "prepared_action_sha256"),
        DELETE,
    ),
    NegativeCase(
        "seller plan has malformed publication action authority",
        "capacity-role-plan.schema.json",
        "role-plans.json",
        1,
        ("role_plan", "publication_prepared_action_sha256s", 0),
        "a" * 63,
    ),
    NegativeCase(
        "receipt omits invocation capability",
        "capacity-role-receipt.schema.json",
        "role-receipts.json",
        0,
        ("provenance", "actor_invocation_capability_binding"),
        DELETE,
    ),
    NegativeCase(
        "wrong receipt invocation capability domain",
        "capacity-role-receipt.schema.json",
        "role-receipts.json",
        0,
        ("provenance", "actor_invocation_capability_binding", "domain"),
        "scm.capacity.runtime-binding.v1",
    ),
    NegativeCase(
        "buyer portable intent uses non-VM deal",
        "capacity-action-payload.schema.json",
        "action-payloads.json",
        0,
        ("portable_intent", "deal_type"),
        "container",
    ),
    NegativeCase(
        "buyer payload uses seller portable intent",
        "capacity-action-payload.schema.json",
        "action-payloads.json",
        0,
        ("portable_intent",),
        {
            "deal_type": "vm",
            "service_isolation": "per-seller",
            "provisioner": "kvm-ansible",
        },
    ),
    NegativeCase(
        "portable intent leaks provider identity",
        "capacity-action-payload.schema.json",
        "action-payloads.json",
        0,
        ("portable_intent", "cloud_project_id"),
        "private-project",
    ),
    NegativeCase(
        "frozen action omits prepared action authority",
        "capacity-frozen-action.schema.json",
        "frozen-actions.json",
        0,
        ("prepared_action_sha256",),
        DELETE,
    ),
    NegativeCase(
        "wrong frozen-action invocation capability domain",
        "capacity-frozen-action.schema.json",
        "frozen-actions.json",
        0,
        ("actor_invocation_capability_binding", "domain"),
        "scm.capacity.runtime-binding.v1",
    ),
    NegativeCase(
        "wrong concrete payload binding domain",
        "capacity-frozen-action.schema.json",
        "frozen-actions.json",
        0,
        ("concrete_payload_binding", "domain"),
        "scm.capacity.runtime-binding.v1",
    ),
    NegativeCase(
        "concurrency policy omits role-plan authorities",
        "capacity-concurrency-policy.schema.json",
        "concurrency-policy.json",
        None,
        ("role_plan_authorities",),
        DELETE,
    ),
    NegativeCase(
        "malformed concurrency role-plan authority",
        "capacity-concurrency-policy.schema.json",
        "concurrency-policy.json",
        None,
        ("role_plan_authorities", 0, "plan_sha256"),
        "a" * 63,
    ),
    NegativeCase(
        "concurrency policy omits prepared-action authorities",
        "capacity-concurrency-policy.schema.json",
        "concurrency-policy.json",
        None,
        ("prepared_action_authorities",),
        DELETE,
    ),
    NegativeCase(
        "malformed concurrency prepared-action authority",
        "capacity-concurrency-policy.schema.json",
        "concurrency-policy.json",
        None,
        ("prepared_action_authorities", 0, "prepared_action_sha256"),
        "a" * 63,
    ),
    NegativeCase(
        "mock capture omits release authority",
        "capacity-mock-capture.schema.json",
        "mock-capture.json",
        None,
        ("release_id",),
        DELETE,
    ),
    NegativeCase(
        "mock capture omits oracle authority digest",
        "capacity-mock-capture.schema.json",
        "mock-capture.json",
        None,
        ("oracle_authority_sha256",),
        DELETE,
    ),
    NegativeCase(
        "mock capture omits frozen action digests",
        "capacity-mock-capture.schema.json",
        "mock-capture.json",
        None,
        ("action_sha256s",),
        DELETE,
    ),
    NegativeCase(
        "mock capture omits prepared action digests",
        "capacity-mock-capture.schema.json",
        "mock-capture.json",
        None,
        ("prepared_action_sha256s",),
        DELETE,
    ),
    NegativeCase(
        "mock capture uses wrong concrete payload domain",
        "capacity-mock-capture.schema.json",
        "mock-capture.json",
        None,
        ("captured_payloads", 0, "concrete_payload_binding", "domain"),
        "scm.capacity.runtime-binding.v1",
    ),
    NegativeCase(
        "mock capture omits service runtime map",
        "capacity-mock-capture.schema.json",
        "mock-capture.json",
        None,
        ("runtime_service_bindings",),
        [],
    ),
    NegativeCase(
        "mock capture omits listing runtime map",
        "capacity-mock-capture.schema.json",
        "mock-capture.json",
        None,
        ("runtime_listing_bindings",),
        [],
    ),
    NegativeCase(
        "mock capture uses wrong invocation capability domain",
        "capacity-mock-capture.schema.json",
        "mock-capture.json",
        None,
        ("actor_invocation_capabilities", 0, "binding", "domain"),
        "scm.capacity.native-evidence.v1",
    ),
    NegativeCase(
        "mock capture claims private ownership proof scope",
        "capacity-mock-capture.schema.json",
        "mock-capture.json",
        None,
        ("agent_ownership_proof_scope",),
        "private-verified",
    ),
    NegativeCase(
        "mock capture claims private actor ownership",
        "capacity-mock-capture.schema.json",
        "mock-capture.json",
        None,
        ("private_actor_ownership_verified",),
        True,
    ),
]

FINDING_REQUIRED_FIELD_PATHS = [
    ("schema version", ("schema_version",)),
    ("occurrence identity", ("finding_id",)),
    ("destination repository", ("destination_repo",)),
    ("classification", ("classification",)),
    ("frontier", ("frontier",)),
    ("scenario identity", ("scenario_id",)),
    ("scenario digest", ("scenario_sha256",)),
    ("profile-stage identity", ("profile_stage_id",)),
    ("profile-stage digest", ("profile_stage_sha256",)),
    ("result identity", ("result_id",)),
    ("result digest", ("result_sha256",)),
    ("SCM contract ref", ("scm_contract_ref",)),
    ("defect semantics", ("defect_semantics",)),
    ("summary", ("summary",)),
    ("expected prose", ("expected",)),
    ("actual prose", ("actual",)),
    ("observed outcome", ("observed_outcome",)),
    ("durable correlations", ("durable_correlations",)),
    ("observed authority", ("observed_authority",)),
    ("evidence", ("evidence",)),
    ("filing readiness", ("filing_readiness",)),
    (
        "expected outcome kind",
        ("defect_semantics", "expected_outcome_kind"),
    ),
    (
        "actual fault category",
        ("defect_semantics", "actual_fault_category"),
    ),
    ("failure code", ("defect_semantics", "failure_code")),
    ("stable signature", ("defect_semantics", "stable_signature")),
    ("lifecycle phase", ("defect_semantics", "lifecycle_phase")),
    ("selected request identities", ("observed_outcome", "request_ids")),
    ("observed outcome kind", ("observed_outcome", "outcome_kind")),
    ("diagnostic code", ("observed_outcome", "diagnostic_code")),
    (
        "correlation request identity",
        ("durable_correlations", 0, "request_id"),
    ),
    (
        "correlation outcome kind",
        ("durable_correlations", 0, "outcome_kind"),
    ),
    (
        "deal-reference digest",
        ("durable_correlations", 0, "deal_reference_sha256"),
    ),
    (
        "capacity-reservation identity",
        ("durable_correlations", 0, "capacity_reservation_id"),
    ),
    (
        "fulfillment identity",
        ("durable_correlations", 0, "fulfillment_id"),
    ),
    (
        "settlement-record digest",
        ("durable_correlations", 0, "settlement_record_sha256"),
    ),
    (
        "provisioned-resource identity",
        ("durable_correlations", 0, "provisioned_resource_id"),
    ),
    (
        "allocation identity",
        ("durable_correlations", 0, "allocation_id"),
    ),
    (
        "provisioning-job identity",
        ("durable_correlations", 0, "provisioning_job_id"),
    ),
    (
        "commercial-resolution digest",
        ("durable_correlations", 0, "commercial_resolution_sha256"),
    ),
    (
        "request-cleanup digest",
        ("durable_correlations", 0, "request_cleanup_sha256"),
    ),
    ("run identity", ("observed_authority", "run_id")),
    ("stage identity", ("observed_authority", "stage_id")),
    ("working branch", ("observed_authority", "working_branch")),
    ("working ref", ("observed_authority", "working_ref")),
    ("upstream branch", ("observed_authority", "upstream_branch")),
    ("upstream ref", ("observed_authority", "upstream_ref")),
    ("inbound merge ref", ("observed_authority", "inbound_merge_ref")),
    (
        "reconciliation epoch identity",
        ("observed_authority", "reconciliation_epoch_id"),
    ),
    ("observation timestamp", ("observed_authority", "observed_at")),
    ("evidence path", ("evidence", 0, "path")),
    ("evidence digest", ("evidence", 0, "sha256")),
    (
        "terminal-correlation readiness",
        ("filing_readiness", "terminal_correlations_complete"),
    ),
    (
        "teardown readiness",
        ("filing_readiness", "teardown_complete"),
    ),
    (
        "zero-residue readiness",
        ("filing_readiness", "zero_active_residue"),
    ),
    (
        "baseline-equivalence readiness",
        ("filing_readiness", "baseline_equivalent"),
    ),
    ("filing decision", ("filing_readiness", "ready_to_file")),
]

FINDING_SCHEMA_NEGATIVE_CASES = [
    *[
        NegativeCase(
            f"finding omits required {label}",
            "capacity-finding.schema.json",
            "findings/classification-findings.json",
            0,
            path,
            DELETE,
        )
        for label, path in FINDING_REQUIRED_FIELD_PATHS
    ],
    NegativeCase(
        "finding contains producer fingerprint",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("fingerprint",),
        f"capacity-{'a' * 64}",
    ),
    NegativeCase(
        "finding defect semantics contain unknown key",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("defect_semantics", "private_fault_detail"),
        "forbidden",
    ),
    NegativeCase(
        "finding observed outcome contains unknown key",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("observed_outcome", "selected_by"),
        "controller",
    ),
    NegativeCase(
        "finding durable correlation contains unknown key",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("durable_correlations", 0, "provider_project"),
        "forbidden-project",
    ),
    NegativeCase(
        "finding observed authority contains unknown key",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("observed_authority", "runner_host"),
        "private-host",
    ),
    NegativeCase(
        "finding evidence contains unknown key",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("evidence", 0, "media_type"),
        "application/json",
    ),
    NegativeCase(
        "finding readiness contains unknown key",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("filing_readiness", "operator_approved"),
        True,
    ),
    NegativeCase(
        "finding uses stale schema version",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("schema_version",),
        1,
    ),
    NegativeCase(
        "finding has malformed occurrence identity",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("finding_id",),
        "invalid occurrence id",
    ),
    NegativeCase(
        "finding has unsupported destination repository",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("destination_repo",),
        "some-other-repository",
    ),
    NegativeCase(
        "public finding uses private destination variant",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("destination_repo",),
        "compute-market-internal-infra",
    ),
    NegativeCase(
        "private finding uses public destination variant",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        2,
        ("destination_repo",),
        "simple-compute-market",
    ),
    NegativeCase(
        "finding has unsupported classification",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("classification",),
        "provider-product",
    ),
    NegativeCase(
        "finding has unsupported frontier",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("frontier",),
        "wallet-funding",
    ),
    NegativeCase(
        "finding has malformed scenario identity",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("scenario_id",),
        "B1-S1-G1",
    ),
    NegativeCase(
        "finding has uppercase scenario digest",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("scenario_sha256",),
        "A" * 64,
    ),
    NegativeCase(
        "finding has short profile-stage digest",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("profile_stage_sha256",),
        "a" * 63,
    ),
    NegativeCase(
        "finding has nonhex result digest",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("result_sha256",),
        "g" * 64,
    ),
    NegativeCase(
        "finding has malformed SCM contract ref",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("scm_contract_ref",),
        "a" * 64,
    ),
    NegativeCase(
        "finding expects unsupported outcome variant",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("defect_semantics", "expected_outcome_kind"),
        "fault",
    ),
    NegativeCase(
        "finding uses unsupported fault variant",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("defect_semantics", "actual_fault_category"),
        "provider-busy",
    ),
    NegativeCase(
        "finding has nonnormalized failure code",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("defect_semantics", "failure_code"),
        "Provisioning Error",
    ),
    NegativeCase(
        "finding has multiline stable signature",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("defect_semantics", "stable_signature"),
        "provisioning failed\nat provider",
    ),
    NegativeCase(
        "finding uses unsupported lifecycle phase",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("defect_semantics", "lifecycle_phase"),
        "issue-filing",
    ),
    NegativeCase(
        "finding has multiline summary",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("summary",),
        "Provisioning failed\nat provider",
    ),
    NegativeCase(
        "finding has empty expected prose",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("expected",),
        "",
    ),
    NegativeCase(
        "finding has empty actual prose",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("actual",),
        "",
    ),
    NegativeCase(
        "finding repeats selected request identity",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("observed_outcome", "request_ids"),
        ["request-1", "request-1"],
    ),
    NegativeCase(
        "finding has malformed selected request identity",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("observed_outcome", "request_ids", 0),
        "request 1",
    ),
    NegativeCase(
        "finding uses unsupported observed outcome variant",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("observed_outcome", "outcome_kind"),
        "provisioning-error",
    ),
    NegativeCase(
        "finding has malformed diagnostic identity",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("observed_outcome", "diagnostic_code"),
        "Provisioning Error",
    ),
    NegativeCase(
        "finding repeats exact durable correlation",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("durable_correlations",),
        [
            {
                "request_id": "request-1",
                "outcome_kind": "fault",
                "deal_reference_sha256": "4" * 64,
                "capacity_reservation_id": None,
                "fulfillment_id": None,
                "settlement_record_sha256": None,
                "provisioned_resource_id": None,
                "allocation_id": None,
                "provisioning_job_id": None,
                "commercial_resolution_sha256": "5" * 64,
                "request_cleanup_sha256": "6" * 64,
            },
            {
                "request_id": "request-1",
                "outcome_kind": "fault",
                "deal_reference_sha256": "4" * 64,
                "capacity_reservation_id": None,
                "fulfillment_id": None,
                "settlement_record_sha256": None,
                "provisioned_resource_id": None,
                "allocation_id": None,
                "provisioning_job_id": None,
                "commercial_resolution_sha256": "5" * 64,
                "request_cleanup_sha256": "6" * 64,
            },
        ],
    ),
    NegativeCase(
        "finding has malformed deal-reference digest",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("durable_correlations", 0, "deal_reference_sha256"),
        "not-a-digest",
    ),
    NegativeCase(
        "finding has malformed nullable settlement digest",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("durable_correlations", 0, "settlement_record_sha256"),
        "a" * 63,
    ),
    NegativeCase(
        "finding has invalid nullable resource identity",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("durable_correlations", 0, "provisioned_resource_id"),
        42,
    ),
    NegativeCase(
        "finding has malformed commercial-resolution digest",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("durable_correlations", 0, "commercial_resolution_sha256"),
        "a" * 65,
    ),
    NegativeCase(
        "finding has malformed request-cleanup digest",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("durable_correlations", 0, "request_cleanup_sha256"),
        "A" * 64,
    ),
    NegativeCase(
        "finding has unsupported working branch",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("observed_authority", "working_branch"),
        "feature/capacity-test",
    ),
    NegativeCase(
        "finding has malformed working ref",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("observed_authority", "working_ref"),
        "a" * 39,
    ),
    NegativeCase(
        "finding has unsupported upstream branch",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("observed_authority", "upstream_branch"),
        "master",
    ),
    NegativeCase(
        "finding has malformed upstream ref",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("observed_authority", "upstream_ref"),
        "z" * 40,
    ),
    NegativeCase(
        "finding has malformed inbound merge ref",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("observed_authority", "inbound_merge_ref"),
        "a" * 41,
    ),
    NegativeCase(
        "finding timestamp omits UTC designator",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("observed_authority", "observed_at"),
        "2026-07-30T10:00:13+00:00",
    ),
    NegativeCase(
        "finding timestamp has out-of-range structural fields",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("observed_authority", "observed_at"),
        "2026-13-40T25:61:61Z",
    ),
    NegativeCase(
        "finding timestamp is arbitrary text ending in UTC designator",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("observed_authority", "observed_at"),
        "not-a-timestampZ",
    ),
    NegativeCase(
        "finding has bare evidence namespace",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("evidence", 0, "path"),
        "evidence",
    ),
    NegativeCase(
        "finding has absolute evidence path",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("evidence", 0, "path"),
        "/tmp/evidence.json",
    ),
    NegativeCase(
        "finding has escaping evidence path",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("evidence", 0, "path"),
        "evidence/../private.json",
    ),
    NegativeCase(
        "finding has non-POSIX evidence path",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("evidence", 0, "path"),
        "evidence\\private.json",
    ),
    NegativeCase(
        "finding has malformed evidence digest",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("evidence", 0, "sha256"),
        "a" * 63,
    ),
    NegativeCase(
        "finding repeats exact evidence identity",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("evidence",),
        [
            {
                "path": "evidence/provisioning-error.json",
                "sha256": (
                    "313ff7f421dd5558088cdef33d2a177aa26f5806739232896e0afcc67710517a"
                ),
            },
            {
                "path": "evidence/provisioning-error.json",
                "sha256": (
                    "313ff7f421dd5558088cdef33d2a177aa26f5806739232896e0afcc67710517a"
                ),
            },
        ],
    ),
    NegativeCase(
        "finding readiness uses nonboolean value",
        "capacity-finding.schema.json",
        "findings/classification-findings.json",
        0,
        ("filing_readiness", "ready_to_file"),
        1,
    ),
]


def mutate(value: object, path: tuple[str | int, ...], replacement: object) -> None:
    assert path
    cursor = value
    for key in path[:-1]:
        cursor = cursor[key]  # type: ignore[index]
    key = path[-1]
    if replacement is DELETE:
        del cursor[key]  # type: ignore[index]
    else:
        cursor[key] = deepcopy(replacement)  # type: ignore[index]


@pytest.mark.parametrize("case", NEGATIVE_CASES, ids=lambda case: case.name)
def test_capacity_v2_contracts_reject_invalid_authority(case: NegativeCase) -> None:
    fixture = load_json(FIXTURE_ROOT / case.fixture_name)
    value = fixture if case.item_index is None else fixture[case.item_index]
    invalid = deepcopy(value)
    mutate(invalid, case.path, case.replacement)

    errors = list(validator(case.schema_name).iter_errors(invalid))

    assert errors, f"{case.name} unexpectedly passed {case.schema_name}"


@pytest.mark.parametrize(
    "case",
    FINDING_SCHEMA_NEGATIVE_CASES,
    ids=lambda case: case.name,
)
def test_capacity_finding_v2_schema_rejects_invalid_occurrence(
    case: NegativeCase,
) -> None:
    fixtures = load_json(FIXTURE_ROOT / case.fixture_name)
    assert case.item_index is not None
    invalid = deepcopy(fixtures[case.item_index])
    mutate(invalid, case.path, case.replacement)

    errors = list(validator(case.schema_name).iter_errors(invalid))

    assert errors, f"{case.name} unexpectedly passed {case.schema_name}"
