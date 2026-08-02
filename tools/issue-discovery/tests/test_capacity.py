from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from issue_discovery.capacity import (
    CapacityValidationError,
    FINITE_STAGE_ORDER,
    evaluate_capacity_result,
    finding_fingerprint,
    scenario_sha256,
    validate_cancellation_receipt,
    validate_capacity_result,
    validate_cleanup_receipt,
    validate_finding,
    validate_finding_file,
    validate_scenario,
    validate_scenario_file,
)


EXPECTED_CAPACITY_FILENAMES = {
    "b1-g1-qualification.json",
    "b2-g1-contention.json",
    "b2-s2-g1-contention.json",
    "q0-g1-host-capability.json",
    "q1-b1-s1-g1-agent-driven.json",
    "q3-b4-s1-g1-contention.json",
    "q4-b8-s1-g1-contention.json",
    "q5-b1-s1-g1-serialized-reuse.json",
    "q7-b4-s2-g1-contention.json",
    "q8-b4-s4-g1-contention.json",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def scenario_dir() -> Path:
    return repo_root() / "tools" / "issue-discovery" / "config" / "capacity"


def scenarios() -> list[dict[str, object]]:
    paths = sorted(scenario_dir().glob("*.json"))
    assert {path.name for path in paths} == EXPECTED_CAPACITY_FILENAMES
    loaded = [validate_scenario_file(path, repo_root()) for path in paths]
    by_id = {item["stage"]: item for item in loaded}
    assert len(loaded) == len(by_id) == len(FINITE_STAGE_ORDER) == 10
    assert set(by_id) == set(FINITE_STAGE_ORDER)
    return [by_id[stage] for stage in FINITE_STAGE_ORDER]


def by_stage(stage: str) -> dict[str, object]:
    return next(item for item in scenarios() if item["stage"] == stage)


def success_observation(
    ordinal: int,
    *,
    reservation_id: str | None = None,
    fulfillment_id: str | None = None,
) -> dict[str, object]:
    reservation = reservation_id or f"reservation-{ordinal}"
    fulfillment = fulfillment_id or f"fulfillment-{ordinal}"
    identity = {
        "fulfillment_id": fulfillment,
        "capacity_reservation_id": reservation,
    }
    wire_identity = {"contract_version": "1.0", **identity}
    return {
        "request_ordinal": ordinal,
        "outcome": "success",
        "capacity_reservation_id": reservation,
        "fulfillment": {
            "acceptance": {**wire_identity, "state": "dispatching"},
            "status": {**wire_identity, "state": "active"},
            "result": {
                "kind": "fulfillment.result.v1",
                "schema_version": 1,
                **identity,
                "state": "active",
                "domain_result": {
                    "kind": "vm.fulfillment.result.v1",
                    "schema_version": 1,
                    "present": True,
                },
            },
            "executor_correlation": {
                "reference_correlated": True,
                "target_correlated": True,
                "failure_origin": None,
            },
            "teardown_acceptance": {
                **wire_identity,
                "state": "teardown_dispatch_pending",
            },
            "teardown_status": {**wire_identity, "state": "torn_down"},
        },
    }


def scarcity_observation(
    ordinal: int,
    *,
    error: str = "offer_unfulfillable",
    reason: str = "no_matching_inventory",
) -> dict[str, object]:
    return {
        "request_ordinal": ordinal,
        "outcome": "http-error",
        "http_status": 409,
        "detail": {"error": error, "reason": reason},
    }


def capacity_result(
    scenario: dict[str, object],
    observations: list[dict[str, object]],
    *,
    run_id: str = "run-001",
    observed_at: str = "2026-08-02T00:00:00Z",
    termination: str = "completed",
    timeout_seconds: int = 900,
    branch: str = "feat/issue-discovery-harness-post-pools",
    sha: str = "a" * 40,
    role_receipts: dict[str, object] | None = None,
    serialized_reuse: dict[str, object] | None = None,
    host_status: str | None = None,
    run_failure: dict[str, object] | None = None,
    cancellation: dict[str, object] | None = None,
    cleanup: dict[str, object] | None = None,
) -> dict[str, object]:
    if host_status is None:
        host_status = (
            "succeeded"
            if scenario["stage"] == "q0-host-capability"
            else "not-applicable"
        )
    return {
        "schema_version": 1,
        "scenario_id": scenario["scenario_id"],
        "scenario_sha256": scenario_sha256(scenario),
        "termination": termination,
        "run": {
            "run_id": run_id,
            "observed_at": observed_at,
            "timeout_seconds": timeout_seconds,
            "repository": "arkhai-io/simple-compute-market",
            "branch": branch,
            "sha": sha,
        },
        "role_receipts": role_receipts or {"status": "satisfied", "failure": None},
        "serialized_reuse": serialized_reuse
        or {
            "status": (
                "satisfied"
                if scenario["stage"] == "q5-serialized-reuse"
                else "not-applicable"
            ),
            "failure": None,
        },
        "host_preflight": {"status": host_status, "failure": None},
        "observations": observations,
        "run_failure": run_failure,
        "cancellation": cancellation
        or {"attempted": False, "status": "not-required", "failure": None},
        "cleanup": cleanup
        or {
            "attempted": True,
            "status": "succeeded",
            "zero_residue": True,
            "failure": None,
        },
    }


def test_capacity_schema_is_valid_draft_2020_12() -> None:
    schema_path = (
        repo_root()
        / "tools"
        / "issue-discovery"
        / "schemas"
        / "capacity-scenario.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)


def test_exact_finite_vm_g1_matrix_is_tracked() -> None:
    expected = {
        "q0-host-capability": (1, 0, 0, 1, 0, 0, 1, 0, 0),
        "reference-b1": (1, 1, 1, 1, 1, 1, 1, 1, 0),
        "q1-b1-s1-g1": (1, 1, 1, 1, 1, 1, 1, 1, 0),
        "q2-b2-s1-g1": (1, 2, 1, 1, 1, 2, 1, 1, 1),
        "q3-b4-s1-g1": (1, 4, 1, 1, 1, 4, 1, 1, 3),
        "q4-b8-s1-g1": (1, 8, 1, 1, 1, 8, 1, 1, 7),
        "q5-serialized-reuse": (1, 1, 1, 1, 1, 2, 1, 2, 0),
        "q6-b2-s2-g1": (1, 2, 2, 1, 2, 2, 1, 1, 1),
        "q7-b4-s2-g1": (1, 4, 2, 1, 2, 4, 1, 1, 3),
        "q8-b4-s4-g1": (1, 4, 4, 1, 4, 4, 1, 1, 3),
    }
    tracked = scenarios()
    assert tuple(item["stage"] for item in tracked) == FINITE_STAGE_ORDER
    assert set(expected) == set(FINITE_STAGE_ORDER)
    for scenario in tracked:
        counts = scenario["counts"]
        outcomes = scenario["expectations"]
        assert (
            counts["orchestrators"],
            counts["buyers"],
            counts["sellers"],
            counts["hosts"],
            counts["listings"],
            counts["requests"],
            counts["physical_gpus"],
            outcomes["successes"],
            outcomes["scarcity"],
        ) == expected[scenario["stage"]]


def test_every_scenario_is_vm_only_g1_and_uses_current_quickstarts() -> None:
    for scenario in scenarios():
        assert scenario["deal_type"] == "vm"
        assert scenario["provisioning"] == "real-kvm-ansible"
        assert scenario["gpu_assignment"] == "whole-device-passthrough"
        assert scenario["counts"]["physical_gpus"] == 1
        assert scenario["listings"]["gpus_per_vm"] == 1
        assert scenario["listings"]["global_physical_gpu_fence"] is True
        assert (
            scenario["role_contract"]["buyer_quickstart"] == "docs/buyer-quickstart.md"
        )
        assert (
            scenario["role_contract"]["seller_quickstart"]
            == "docs/seller-quickstart.md"
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("deal_type", "container", "vm"),
        ("gpu_assignment", "shared-device", "whole-device-passthrough"),
    ],
)
def test_scenario_rejects_non_vm_or_non_whole_gpu(
    field: str, value: str, message: str
) -> None:
    scenario = copy.deepcopy(by_stage("q2-b2-s1-g1"))
    scenario[field] = value
    with pytest.raises(CapacityValidationError, match=message):
        validate_scenario(scenario, repo_root())


def test_scenario_rejects_g2_and_unbounded_stage() -> None:
    g2 = copy.deepcopy(by_stage("q2-b2-s1-g1"))
    g2["counts"]["physical_gpus"] = 2
    with pytest.raises(CapacityValidationError, match="physical_gpus"):
        validate_scenario(g2, repo_root())

    adaptive = copy.deepcopy(by_stage("q2-b2-s1-g1"))
    adaptive["stage"] = "adaptive-frontier"
    adaptive["scenario_id"] = "adaptive-frontier"
    with pytest.raises(CapacityValidationError, match="stage"):
        validate_scenario(adaptive, repo_root())

    assert not list(scenario_dir().glob("*g2*.json"))


def test_reference_and_agent_rows_have_distinct_ownership() -> None:
    reference = by_stage("reference-b1")
    q1 = by_stage("q1-b1-s1-g1")
    assert reference["role_contract"]["ownership"] == "controller-reference"
    assert (
        "controller.reference-request-invoked"
        in reference["role_contract"]["required_receipts"]
    )
    assert "buyer.demand-invoked" not in reference["role_contract"]["required_receipts"]

    assert q1["role_contract"]["ownership"] == "substantive-agents"
    assert "buyer.demand-invoked" in q1["role_contract"]["required_receipts"]
    assert "buyer.same-session-invocation" in q1["role_contract"]["required_receipts"]
    assert "seller.listing-published" in q1["role_contract"]["required_receipts"]
    assert q1["role_contract"]["same_session_prepare_wait_invoke"] is True
    assert q1["arrival"] == {
        "mode": "release-barrier",
        "barrier_participants": 1,
        "teardown_between_requests": False,
    }


def test_q5_serialized_reuse_allows_two_requests_for_one_persistent_buyer() -> None:
    q5 = by_stage("q5-serialized-reuse")
    assert q5["counts"]["buyers"] == 1
    assert q5["counts"]["requests"] == 2
    assert q5["expectations"]["successes"] == 2
    assert q5["role_contract"]["same_session_prepare_wait_invoke"] is True
    assert q5["role_contract"]["persistent_across_requests"] is True
    assert q5["bindings"]["request_assignment"] == "single-persistent-buyer"
    assert q5["arrival"] == {
        "mode": "serialized-reuse",
        "barrier_participants": 0,
        "teardown_between_requests": True,
    }


def test_seller_rows_require_one_listing_per_distinct_seller() -> None:
    for stage in ("q6-b2-s2-g1", "q7-b4-s2-g1", "q8-b4-s4-g1"):
        scenario = by_stage(stage)
        distribution = scenario["listings"]["seller_distribution"]
        assert distribution == [1] * scenario["counts"]["sellers"]
        assert sum(distribution) == scenario["counts"]["listings"]

    broken = copy.deepcopy(by_stage("q6-b2-s2-g1"))
    broken["listings"]["seller_distribution"] = [1]
    with pytest.raises(CapacityValidationError, match="one entry per seller"):
        validate_scenario(broken, repo_root())


def test_bindings_are_frozen_and_assign_only_finite_role_slots() -> None:
    expected_assignments = {
        "q0-host-capability": ("none", "none"),
        "reference-b1": ("seller-ordinal", "controller-reference"),
        "q1-b1-s1-g1": ("seller-ordinal", "buyer-ordinal"),
        "q2-b2-s1-g1": ("seller-ordinal", "buyer-ordinal"),
        "q3-b4-s1-g1": ("seller-ordinal", "buyer-ordinal"),
        "q4-b8-s1-g1": ("seller-ordinal", "buyer-ordinal"),
        "q5-serialized-reuse": ("seller-ordinal", "single-persistent-buyer"),
        "q6-b2-s2-g1": ("seller-ordinal", "buyer-ordinal"),
        "q7-b4-s2-g1": ("seller-ordinal", "buyer-ordinal"),
        "q8-b4-s4-g1": ("seller-ordinal", "buyer-ordinal"),
    }
    for scenario in scenarios():
        bindings = scenario["bindings"]
        assert bindings["role_id_scheme"] == "ordinal-v1"
        assert (
            bindings["listing_assignment"],
            bindings["request_assignment"],
        ) == expected_assignments[scenario["stage"]]
        has_market_input = scenario["stage"] != "q0-host-capability"
        assert (bindings["listing_set_sha256"] is not None) is has_market_input
        assert (bindings["demand_set_sha256"] is not None) is has_market_input


def test_q0_has_only_host_preflight_and_zero_residue_requirements() -> None:
    q0 = by_stage("q0-host-capability")
    assert q0["lifecycle"] == {
        "applicability": "not-applicable",
        "reservation_identity": "not-applicable",
        "fulfillment_identity": "not-applicable",
        "reservation_fulfillment_correlation_required": False,
        "terminal_status_required": False,
        "versioned_result_required": False,
        "executor_ref_target_correlation": "not-applicable",
        "fulfillment_teardown_required": False,
    }
    assert q0["cleanup"] == {
        "required": True,
        "zero_residue": True,
        "vm_teardown": "not-applicable",
        "lease": "not-applicable",
    }


def test_only_substantive_rows_require_same_session_and_only_q5_reuses_it() -> None:
    for scenario in scenarios():
        substantive = (
            scenario["stage"].startswith("q")
            and scenario["stage"] != "q0-host-capability"
        )
        assert (
            scenario["role_contract"]["same_session_prepare_wait_invoke"] is substantive
        )
        assert scenario["role_contract"]["persistent_across_requests"] is (
            scenario["stage"] == "q5-serialized-reuse"
        )


def test_scenario_hash_is_canonical_and_semantic() -> None:
    scenario = by_stage("q2-b2-s1-g1")
    reordered = json.loads(json.dumps(scenario, sort_keys=True, indent=4))
    digest = scenario_sha256(scenario)
    assert digest == scenario_sha256(reordered)
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")

    changed = copy.deepcopy(scenario)
    changed["description"] = "A different normative scenario description."
    assert scenario_sha256(changed) != digest

    reordered_receipts = copy.deepcopy(scenario)
    reordered_receipts["role_contract"]["required_receipts"].reverse()
    assert scenario_sha256(reordered_receipts) == digest

    changed_input = copy.deepcopy(scenario)
    changed_input["bindings"]["demand_set_sha256"] = "f" * 64
    assert scenario_sha256(changed_input) != digest


def test_stage_contract_rejects_count_or_ownership_drift() -> None:
    scenario = copy.deepcopy(by_stage("q3-b4-s1-g1"))
    scenario["counts"]["buyers"] = 3
    with pytest.raises(CapacityValidationError, match="O/B/S/H/L/R/G"):
        validate_scenario(scenario, repo_root())

    scenario = copy.deepcopy(by_stage("q3-b4-s1-g1"))
    scenario["role_contract"]["ownership"] = "controller-reference"
    with pytest.raises(CapacityValidationError, match="ownership"):
        validate_scenario(scenario, repo_root())


def test_stage_contract_rejects_retry_adaptation_or_binding_drift() -> None:
    retry = copy.deepcopy(by_stage("q2-b2-s1-g1"))
    retry["expectations"]["retry_count"] = 1
    with pytest.raises(CapacityValidationError, match="retry_count"):
        validate_scenario(retry, repo_root())

    adaptive = copy.deepcopy(by_stage("q2-b2-s1-g1"))
    adaptive["adaptive"] = True
    with pytest.raises(CapacityValidationError, match="adaptive"):
        validate_scenario(adaptive, repo_root())

    wrong_assignment = copy.deepcopy(by_stage("q5-serialized-reuse"))
    wrong_assignment["bindings"]["request_assignment"] = "buyer-ordinal"
    with pytest.raises(CapacityValidationError, match="request_assignment"):
        validate_scenario(wrong_assignment, repo_root())

    missing_hash = copy.deepcopy(by_stage("q6-b2-s2-g1"))
    missing_hash["bindings"]["listing_set_sha256"] = None
    with pytest.raises(CapacityValidationError, match="listing_set_sha256"):
        validate_scenario(missing_hash, repo_root())

    private_runtime = copy.deepcopy(by_stage("q2-b2-s1-g1"))
    private_runtime["project"] = "must-not-be-public"
    with pytest.raises(CapacityValidationError, match="project"):
        validate_scenario(private_runtime, repo_root())


def test_substantive_contract_rejects_session_or_global_fence_drift() -> None:
    wrong_session = copy.deepcopy(by_stage("q1-b1-s1-g1"))
    wrong_session["role_contract"]["same_session_prepare_wait_invoke"] = False
    with pytest.raises(CapacityValidationError, match="same_session"):
        validate_scenario(wrong_session, repo_root())

    missing_teardown = copy.deepcopy(by_stage("q5-serialized-reuse"))
    missing_teardown["arrival"]["teardown_between_requests"] = False
    with pytest.raises(CapacityValidationError, match="teardown_between_requests"):
        validate_scenario(missing_teardown, repo_root())

    missing_fence = copy.deepcopy(by_stage("q6-b2-s2-g1"))
    missing_fence["listings"]["global_physical_gpu_fence"] = False
    with pytest.raises(CapacityValidationError, match="global_physical_gpu_fence"):
        validate_scenario(missing_fence, repo_root())


def test_capacity_finding_schema_is_valid_draft_2020_12() -> None:
    schema_path = (
        repo_root()
        / "tools"
        / "issue-discovery"
        / "schemas"
        / "capacity-finding.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize(
    ("receipt", "termination"),
    [
        (
            {"attempted": False, "status": "not-required", "failure": None},
            "completed",
        ),
        (
            {"attempted": True, "status": "succeeded", "failure": None},
            "timeout",
        ),
        (
            {
                "attempted": True,
                "status": "failed",
                "failure": {
                    "code": "cancellation-failed",
                    "location": "cancellation",
                    "evidence_summary": "The bounded cancellation attempt failed.",
                },
            },
            "controller-failure",
        ),
    ],
)
def test_cancellation_receipt_validator_accepts_complete_consistent_states(
    receipt: dict[str, object],
    termination: str,
) -> None:
    validate_cancellation_receipt(
        receipt,
        termination=termination,
        repo_root=repo_root(),
    )


@pytest.mark.parametrize(
    ("receipt", "termination", "message"),
    [
        (
            {"attempted": False, "status": "not-required"},
            "completed",
            "missing failure",
        ),
        (
            {"attempted": True, "status": "not-required", "failure": None},
            "completed",
            "status must agree",
        ),
        (
            {"attempted": False, "status": "not-required", "failure": None},
            "timeout",
            "cancellation must be attempted",
        ),
        (
            {"attempted": True, "status": "failed", "failure": None},
            "completed",
            "failure must be an object",
        ),
        (
            {
                "attempted": True,
                "status": "succeeded",
                "failure": {
                    "code": "unexpected-failure",
                    "location": "cancellation",
                    "evidence_summary": "Success cannot retain failure evidence.",
                },
            },
            "completed",
            "failure must be null unless cancellation failed",
        ),
    ],
)
def test_cancellation_receipt_validator_rejects_inconsistent_states(
    receipt: dict[str, object],
    termination: str,
    message: str,
) -> None:
    with pytest.raises(CapacityValidationError, match=message):
        validate_cancellation_receipt(
            receipt,
            termination=termination,
            repo_root=repo_root(),
        )


@pytest.mark.parametrize(
    "receipt",
    [
        {
            "attempted": True,
            "status": "succeeded",
            "zero_residue": True,
            "failure": None,
        },
        {
            "attempted": True,
            "status": "failed",
            "zero_residue": False,
            "failure": {
                "code": "cleanup-failed",
                "location": "cleanup",
                "evidence_summary": "The bounded cleanup attempt failed.",
            },
        },
        {
            "attempted": False,
            "status": "not-attempted",
            "zero_residue": False,
            "failure": {
                "code": "cleanup-not-attempted",
                "location": "cleanup",
                "evidence_summary": "Cleanup could not be attempted.",
            },
        },
    ],
)
def test_cleanup_receipt_validator_accepts_complete_consistent_states(
    receipt: dict[str, object],
) -> None:
    validate_cleanup_receipt(receipt, repo_root=repo_root())


@pytest.mark.parametrize(
    ("receipt", "message"),
    [
        (
            {"attempted": True, "status": "succeeded", "zero_residue": True},
            "missing failure",
        ),
        (
            {
                "attempted": False,
                "status": "succeeded",
                "zero_residue": True,
                "failure": None,
            },
            "status must agree",
        ),
        (
            {
                "attempted": True,
                "status": "succeeded",
                "zero_residue": False,
                "failure": None,
            },
            "zero_residue must be true",
        ),
        (
            {
                "attempted": True,
                "status": "failed",
                "zero_residue": True,
                "failure": None,
            },
            "zero_residue must be false",
        ),
        (
            {
                "attempted": True,
                "status": "failed",
                "zero_residue": False,
                "failure": None,
            },
            "failure must be an object",
        ),
        (
            {
                "attempted": False,
                "status": "not-attempted",
                "zero_residue": False,
                "failure": None,
            },
            "failure must be an object",
        ),
        (
            {
                "attempted": True,
                "status": "succeeded",
                "zero_residue": True,
                "failure": {
                    "code": "unexpected-failure",
                    "location": "cleanup",
                    "evidence_summary": "Successful cleanup cannot retain failure evidence.",
                },
            },
            "failure must be null when cleanup succeeded",
        ),
    ],
)
def test_cleanup_receipt_validator_rejects_inconsistent_states(
    receipt: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(CapacityValidationError, match=message):
        validate_cleanup_receipt(receipt, repo_root=repo_root())


def test_q0_evaluates_host_preflight_without_market_lifecycle() -> None:
    scenario = by_stage("q0-host-capability")
    result = capacity_result(scenario, [])

    evaluation = evaluate_capacity_result(scenario, result, repo_root())

    assert evaluation["classification"] == "success"
    assert evaluation["counts"] == {
        "success": 0,
        "expected_scarcity": 0,
        "findings": 0,
    }
    assert evaluation["findings"] == []


def test_durable_success_correlates_current_receipts_without_exporting_raw_ids() -> (
    None
):
    scenario = by_stage("q1-b1-s1-g1")
    result = capacity_result(scenario, [success_observation(1)])

    evaluation = evaluate_capacity_result(scenario, result, repo_root())

    assert evaluation["classification"] == "success"
    assert evaluation["counts"] == {
        "success": 1,
        "expected_scarcity": 0,
        "findings": 0,
    }
    assert evaluation["observations"] == [
        {
            "request_ordinal": 1,
            "classification": "success",
            "correlations": {
                "reservation_fulfillment": "satisfied",
                "terminal_status": "satisfied",
                "executor_ref_target": "satisfied",
                "versioned_result": "satisfied",
                "fulfillment_teardown": "satisfied",
            },
        }
    ]
    serialized = json.dumps(evaluation, sort_keys=True)
    assert "reservation-1" not in serialized
    assert "fulfillment-1" not in serialized


def test_exact_typed_scarcity_is_counted_and_suppressed_as_a_finding() -> None:
    scenario = by_stage("q2-b2-s1-g1")
    result = capacity_result(
        scenario,
        [success_observation(1), scarcity_observation(2)],
    )

    evaluation = evaluate_capacity_result(scenario, result, repo_root())

    assert evaluation["classification"] == "success"
    assert evaluation["counts"] == {
        "success": 1,
        "expected_scarcity": 1,
        "findings": 0,
    }
    assert [item["classification"] for item in evaluation["observations"]] == [
        "success",
        "expected-scarcity",
    ]
    assert evaluation["findings"] == []


def test_other_409_is_a_possible_product_finding() -> None:
    scenario = by_stage("q2-b2-s1-g1")
    result = capacity_result(
        scenario,
        [success_observation(1), scarcity_observation(2, reason="listing_not_open")],
        cancellation={"attempted": True, "status": "succeeded", "failure": None},
    )

    evaluation = evaluate_capacity_result(scenario, result, repo_root())

    assert evaluation["classification"] == "possible-product-defect"
    assert [item["failure"]["code"] for item in evaluation["findings"]] == [
        "unexpected-scarcity-reason"
    ]


def test_mismatched_lifecycle_identity_is_a_sanitized_product_finding() -> None:
    scenario = by_stage("q1-b1-s1-g1")
    observation = success_observation(1)
    observation["fulfillment"]["status"]["capacity_reservation_id"] = (
        "reservation-other"
    )
    result = capacity_result(
        scenario,
        [observation],
        cancellation={"attempted": True, "status": "succeeded", "failure": None},
    )

    evaluation = evaluate_capacity_result(scenario, result, repo_root())
    finding = evaluation["findings"][0]

    assert evaluation["classification"] == "possible-product-defect"
    assert finding["failure"]["code"] == "reservation-fulfillment-mismatch"
    assert finding["correlations"]["reservation_fulfillment"] == "failed"
    serialized = json.dumps(finding, sort_keys=True)
    assert "reservation-other" not in serialized
    assert "reservation-1" not in serialized


def test_executor_assertion_mismatch_is_an_environment_provider_finding() -> None:
    scenario = by_stage("q1-b1-s1-g1")
    observation = success_observation(1)
    observation["fulfillment"]["executor_correlation"]["target_correlated"] = False
    observation["fulfillment"]["executor_correlation"]["failure_origin"] = (
        "environment-provider"
    )
    result = capacity_result(
        scenario,
        [observation],
        cancellation={"attempted": True, "status": "succeeded", "failure": None},
    )

    evaluation = evaluate_capacity_result(scenario, result, repo_root())

    assert evaluation["classification"] == "environment-provider-issue"
    assert evaluation["findings"][0]["failure"]["code"] == (
        "executor-ref-target-mismatch"
    )


def test_above_capacity_success_is_retained_as_a_product_finding() -> None:
    scenario = by_stage("q2-b2-s1-g1")
    result = capacity_result(
        scenario,
        [success_observation(1), success_observation(2)],
        cancellation={"attempted": True, "status": "succeeded", "failure": None},
    )

    evaluation = evaluate_capacity_result(scenario, result, repo_root())

    assert evaluation["counts"]["success"] == 2
    assert evaluation["classification"] == "possible-product-defect"
    assert any(
        item["failure"]["code"] == "unexpected-success-count"
        for item in evaluation["findings"]
    )


def test_cleanup_failure_remains_a_finding_after_market_success() -> None:
    scenario = by_stage("q1-b1-s1-g1")
    result = capacity_result(
        scenario,
        [success_observation(1)],
        cleanup={
            "attempted": True,
            "status": "failed",
            "zero_residue": False,
            "failure": {
                "code": "residue-remains",
                "location": "cleanup",
                "evidence_summary": "Sanitized cleanup probes still report managed residue.",
            },
        },
    )

    evaluation = evaluate_capacity_result(scenario, result, repo_root())
    finding = evaluation["findings"][0]

    assert evaluation["classification"] == "cleanup-failure"
    assert finding["classification"] == "cleanup-failure"
    assert finding["publication"] == {
        "eligible": False,
        "reason": "cleanup-failed",
    }
    assert finding["cleanup"]["zero_residue"] is False


def test_explicit_harness_failure_requires_and_records_cancellation() -> None:
    scenario = by_stage("q1-b1-s1-g1")
    failure = {
        "code": "receipt-collection-failed",
        "location": "observation",
        "evidence_summary": "The mock receipt collector ended before lifecycle evidence arrived.",
    }
    result = capacity_result(
        scenario,
        [{"request_ordinal": 1, "outcome": "harness-failure", "failure": failure}],
        cancellation={"attempted": True, "status": "succeeded", "failure": None},
    )

    evaluation = evaluate_capacity_result(scenario, result, repo_root())

    assert evaluation["classification"] == "harness-defect"
    assert evaluation["cancellation"] == {"attempted": True, "status": "succeeded"}
    assert evaluation["findings"][0]["classification"] == "harness-defect"


def test_fingerprint_excludes_run_branch_and_public_sha_occurrence_metadata() -> None:
    scenario = by_stage("q2-b2-s1-g1")
    first = capacity_result(
        scenario,
        [success_observation(1), scarcity_observation(2, error="another_conflict")],
        run_id="run-first",
        cancellation={"attempted": True, "status": "succeeded", "failure": None},
    )
    second = capacity_result(
        scenario,
        [success_observation(1), scarcity_observation(2, error="another_conflict")],
        run_id="run-second",
        observed_at="2026-08-02T00:01:00Z",
        branch="feat/another-public-test",
        sha="b" * 40,
        cancellation={"attempted": True, "status": "succeeded", "failure": None},
    )

    first_finding = evaluate_capacity_result(scenario, first, repo_root())["findings"][
        0
    ]
    second_finding = evaluate_capacity_result(scenario, second, repo_root())[
        "findings"
    ][0]

    assert first_finding["fingerprint"] == second_finding["fingerprint"]
    assert first_finding["occurrence"] != second_finding["occurrence"]
    assert first_finding["public_context"] != second_finding["public_context"]


def test_capacity_result_rejects_raw_payloads_or_wrong_scenario_binding() -> None:
    scenario = by_stage("q1-b1-s1-g1")
    raw = capacity_result(scenario, [success_observation(1)])
    raw["observations"][0]["fulfillment"]["result"]["payload"] = {
        "password": "must-not-enter-public-results"
    }
    with pytest.raises(CapacityValidationError, match="unexpected payload"):
        validate_capacity_result(raw, scenario, repo_root())

    wrong_hash = capacity_result(scenario, [success_observation(1)])
    wrong_hash["scenario_sha256"] = "0" * 64
    with pytest.raises(CapacityValidationError, match="scenario_sha256"):
        validate_capacity_result(wrong_hash, scenario, repo_root())


def test_finding_validation_rejects_credentials_paths_and_raw_identity_fields() -> None:
    scenario = by_stage("q2-b2-s1-g1")
    result = capacity_result(
        scenario,
        [success_observation(1), scarcity_observation(2, error="another_conflict")],
        cancellation={"attempted": True, "status": "succeeded", "failure": None},
    )
    finding = evaluate_capacity_result(scenario, result, repo_root())["findings"][0]

    credential = copy.deepcopy(finding)
    credential["failure"]["stable_evidence_summary"] = "password=not-public"
    credential["fingerprint"] = finding_fingerprint(
        scenario_sha256_value=credential["scenario"]["sha256"],
        classification=credential["classification"],
        code=credential["failure"]["code"],
        location=credential["failure"]["location"],
        stable_evidence_summary=credential["failure"]["stable_evidence_summary"],
    )
    with pytest.raises(CapacityValidationError, match="credential-shaped"):
        validate_finding(credential, repo_root())

    workstation_path = copy.deepcopy(finding)
    workstation_path["evidence"][0]["summary"] = "Evidence retained at /home/user/run."
    with pytest.raises(
        CapacityValidationError, match="redaction rules|workstation path"
    ):
        validate_finding(workstation_path, repo_root())

    raw_identity = copy.deepcopy(finding)
    raw_identity["capacity_reservation_id"] = "reservation-1"
    with pytest.raises(CapacityValidationError, match="capacity_reservation_id"):
        validate_finding(raw_identity, repo_root())


def test_tracked_sanitized_finding_example_is_valid() -> None:
    example = (
        repo_root()
        / "tools"
        / "issue-discovery"
        / "config"
        / "capacity"
        / "findings"
        / "example.json"
    )
    finding = validate_finding_file(example, repo_root())
    assert finding["classification"] == "possible-product-defect"
    assert finding["publication"]["eligible"] is True
    assert finding["fingerprint"] == finding_fingerprint(
        scenario_sha256_value=finding["scenario"]["sha256"],
        classification=finding["classification"],
        code=finding["failure"]["code"],
        location=finding["failure"]["location"],
        stable_evidence_summary=finding["failure"]["stable_evidence_summary"],
    )
    scenario = by_stage("q2-b2-s1-g1")
    evaluation = evaluate_capacity_result(
        scenario,
        capacity_result(scenario, [success_observation(1), success_observation(2)]),
        repo_root(),
    )
    generated = next(
        item
        for item in evaluation["findings"]
        if item["failure"]["code"] == "unexpected-success-count"
    )
    assert finding["correlations"] == generated["correlations"]


def test_finding_date_time_is_format_checked() -> None:
    scenario = by_stage("q2-b2-s1-g1")
    result = capacity_result(
        scenario,
        [success_observation(1), scarcity_observation(2, error="other_conflict")],
    )
    finding = evaluate_capacity_result(scenario, result, repo_root())["findings"][0]
    finding["occurrence"]["observed_at"] = "2026-13-40T25:61:61Z"

    with pytest.raises(CapacityValidationError, match="date-time"):
        validate_finding(finding, repo_root())


def test_q0_failure_uses_not_applicable_lifecycle_correlations() -> None:
    scenario = by_stage("q0-host-capability")
    result = capacity_result(scenario, [])
    result["host_preflight"] = {
        "status": "failed",
        "failure": {
            "code": "host-preflight-failed",
            "location": "host_preflight",
            "evidence_summary": "The sanitized mock host preflight failed.",
        },
    }

    evaluation = evaluate_capacity_result(scenario, result, repo_root())

    assert evaluation["classification"] == "environment-provider-issue"
    assert evaluation["findings"][0]["correlations"] == {
        "reservation_fulfillment": "not-applicable",
        "terminal_status": "not-applicable",
        "executor_ref_target": "not-applicable",
        "versioned_result": "not-applicable",
        "fulfillment_teardown": "not-applicable",
    }


@pytest.mark.parametrize(
    ("path", "value", "classification", "code"),
    [
        (
            ("acceptance", "contract_version"),
            "2.0",
            "possible-product-defect",
            "fulfillment-wire-contract-mismatch",
        ),
        (
            ("status", "state"),
            "failed",
            "possible-product-defect",
            "active-status-not-observed",
        ),
        (
            ("result", "kind"),
            "fulfillment.result.v2",
            "possible-product-defect",
            "versioned-result-mismatch",
        ),
        (
            ("result", "schema_version"),
            2,
            "possible-product-defect",
            "versioned-result-mismatch",
        ),
        (
            ("result", "domain_result", "kind"),
            "bare-metal.fulfillment.result.v1",
            "possible-product-defect",
            "versioned-result-mismatch",
        ),
        (
            ("result", "domain_result", "present"),
            False,
            "possible-product-defect",
            "versioned-result-mismatch",
        ),
        (
            ("executor_correlation", "reference_correlated"),
            False,
            "environment-provider-issue",
            "executor-ref-target-mismatch",
        ),
        (
            ("teardown_status", "state"),
            "teardown_failed",
            "cleanup-failure",
            "fulfillment-teardown-not-terminal",
        ),
    ],
)
def test_each_current_lifecycle_boundary_is_classified_without_identifier_leakage(
    path: tuple[str, ...],
    value: object,
    classification: str,
    code: str,
) -> None:
    scenario = by_stage("q1-b1-s1-g1")
    observation = success_observation(1)
    target = observation["fulfillment"]
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    if path[0] == "executor_correlation":
        observation["fulfillment"]["executor_correlation"]["failure_origin"] = (
            "environment-provider"
        )
    result = capacity_result(scenario, [observation])

    evaluation = evaluate_capacity_result(scenario, result, repo_root())
    finding = next(
        item for item in evaluation["findings"] if item["failure"]["code"] == code
    )

    assert finding["classification"] == classification
    serialized = json.dumps(evaluation, sort_keys=True)
    assert "reservation-1" not in serialized
    assert "fulfillment-1" not in serialized


def test_teardown_acceptance_identity_mismatch_is_not_hidden_by_terminal_status() -> (
    None
):
    scenario = by_stage("q1-b1-s1-g1")
    observation = success_observation(1)
    observation["fulfillment"]["teardown_acceptance"]["capacity_reservation_id"] = (
        "reservation-other"
    )

    evaluation = evaluate_capacity_result(
        scenario,
        capacity_result(scenario, [observation]),
        repo_root(),
    )

    assert evaluation["findings"][0]["failure"]["code"] == (
        "reservation-fulfillment-mismatch"
    )


@pytest.mark.parametrize(
    ("status", "error", "reason", "code"),
    [
        (409, "other_conflict", "no_matching_inventory", "unexpected-scarcity-error"),
        (409, "offer_unfulfillable", "other_reason", "unexpected-scarcity-reason"),
        (503, "offer_unfulfillable", "no_matching_inventory", "unexpected-http-status"),
    ],
)
def test_only_the_exact_typed_409_consumes_scarcity_budget(
    status: int,
    error: str,
    reason: str,
    code: str,
) -> None:
    scenario = by_stage("q2-b2-s1-g1")
    response = scarcity_observation(2, error=error, reason=reason)
    response["http_status"] = status

    evaluation = evaluate_capacity_result(
        scenario,
        capacity_result(scenario, [success_observation(1), response]),
        repo_root(),
    )

    assert evaluation["counts"]["expected_scarcity"] == 0
    assert any(item["failure"]["code"] == code for item in evaluation["findings"])


def test_exact_scarcity_is_a_defect_when_the_scenario_has_no_scarcity_budget() -> None:
    scenario = by_stage("q1-b1-s1-g1")

    evaluation = evaluate_capacity_result(
        scenario,
        capacity_result(scenario, [scarcity_observation(1)]),
        repo_root(),
    )

    assert evaluation["counts"]["expected_scarcity"] == 0
    assert evaluation["findings"][0]["failure"]["code"] == ("unexpected-scarcity-count")


def test_exact_scarcity_beyond_the_expected_budget_is_a_defect() -> None:
    scenario = by_stage("q2-b2-s1-g1")

    evaluation = evaluate_capacity_result(
        scenario,
        capacity_result(
            scenario,
            [scarcity_observation(2), scarcity_observation(1)],
        ),
        repo_root(),
    )

    assert evaluation["counts"]["expected_scarcity"] == 1
    assert any(
        item["failure"]["code"] == "unexpected-scarcity-count"
        for item in evaluation["findings"]
    )


def test_missing_role_receipts_are_a_harness_defect() -> None:
    scenario = by_stage("q1-b1-s1-g1")
    result = capacity_result(
        scenario,
        [success_observation(1)],
        role_receipts={
            "status": "not-observed",
            "failure": {
                "code": "role-receipts-not-observed",
                "location": "role_receipts",
                "evidence_summary": "One or more required sanitized role receipts were absent.",
            },
        },
    )

    evaluation = evaluate_capacity_result(scenario, result, repo_root())

    assert evaluation["classification"] == "harness-defect"
    assert any(
        item["failure"]["code"] == "role-receipts-not-observed"
        for item in evaluation["findings"]
    )


def test_q5_requires_sanitized_same_session_and_inter_request_teardown_assertion() -> (
    None
):
    scenario = by_stage("q5-serialized-reuse")
    successful = capacity_result(
        scenario,
        [success_observation(2), success_observation(1)],
    )
    assert evaluate_capacity_result(scenario, successful, repo_root())[
        "classification"
    ] == ("success")

    missing = capacity_result(
        scenario,
        [success_observation(1), success_observation(2)],
        serialized_reuse={
            "status": "not-observed",
            "failure": {
                "code": "serialized-reuse-not-proven",
                "location": "serialized_reuse",
                "evidence_summary": "The same buyer session and inter-request teardown were not proven.",
            },
        },
    )
    evaluation = evaluate_capacity_result(scenario, missing, repo_root())

    assert evaluation["classification"] == "harness-defect"
    assert any(
        item["failure"]["code"] == "serialized-reuse-not-proven"
        for item in evaluation["findings"]
    )


@pytest.mark.parametrize(
    ("outcome", "classification"),
    [
        ("harness-failure", "harness-defect"),
        ("product-failure", "possible-product-defect"),
        ("environment-provider-failure", "environment-provider-issue"),
    ],
)
def test_explicit_request_fault_origin_is_preserved(
    outcome: str,
    classification: str,
) -> None:
    scenario = by_stage("q1-b1-s1-g1")
    result = capacity_result(
        scenario,
        [
            {
                "request_ordinal": 1,
                "outcome": outcome,
                "failure": {
                    "code": "normalized-request-failure",
                    "location": "request",
                    "evidence_summary": "The sanitized request fault was classified at its observed boundary.",
                },
            }
        ],
    )

    evaluation = evaluate_capacity_result(scenario, result, repo_root())

    assert evaluation["classification"] == classification
    assert evaluation["findings"][0]["classification"] == classification


@pytest.mark.parametrize(
    "termination",
    ["timeout", "cancelled", "partial-launch", "role-failure", "controller-failure"],
)
def test_non_completed_run_termination_records_cancellation_and_cleanup(
    termination: str,
) -> None:
    scenario = by_stage("q1-b1-s1-g1")
    result = capacity_result(
        scenario,
        [],
        termination=termination,
        run_failure={
            "origin": "harness",
            "code": f"{termination}-observed",
            "location": "runner",
            "evidence_summary": "The hermetic runner recorded a bounded non-completed termination.",
        },
        cancellation={"attempted": True, "status": "succeeded", "failure": None},
    )

    evaluation = evaluate_capacity_result(scenario, result, repo_root())

    assert evaluation["termination"] == termination
    assert evaluation["cancellation"] == {"attempted": True, "status": "succeeded"}
    assert evaluation["cleanup"] == {
        "attempted": True,
        "status": "succeeded",
        "zero_residue": True,
    }
    assert all(
        item["occurrence"]["termination"] == termination
        for item in evaluation["findings"]
    )


def test_non_completed_run_without_cancellation_is_rejected() -> None:
    scenario = by_stage("q1-b1-s1-g1")
    result = capacity_result(
        scenario,
        [],
        termination="timeout",
        run_failure={
            "origin": "harness",
            "code": "timeout-observed",
            "location": "runner",
            "evidence_summary": "The hermetic runner timed out.",
        },
    )

    with pytest.raises(CapacityValidationError, match="cancellation must be attempted"):
        validate_capacity_result(result, scenario, repo_root())


def test_failed_cancellation_and_unattempted_cleanup_remain_findings() -> None:
    scenario = by_stage("q1-b1-s1-g1")
    result = capacity_result(
        scenario,
        [success_observation(1)],
        cancellation={
            "attempted": True,
            "status": "failed",
            "failure": {
                "code": "cancellation-failed",
                "location": "cancellation",
                "evidence_summary": "The bounded mock cancellation attempt failed.",
            },
        },
        cleanup={
            "attempted": False,
            "status": "not-attempted",
            "zero_residue": False,
            "failure": {
                "code": "cleanup-not-attempted",
                "location": "cleanup",
                "evidence_summary": "The required cleanup operation was not attempted.",
            },
        },
    )

    evaluation = evaluate_capacity_result(scenario, result, repo_root())

    assert evaluation["classification"] == "cleanup-failure"
    assert {item["classification"] for item in evaluation["findings"]} == {
        "harness-defect",
        "cleanup-failure",
    }
    assert all(
        item["publication"]["eligible"] is False for item in evaluation["findings"]
    )


def test_teardown_and_global_cleanup_failures_retain_distinct_fingerprints() -> None:
    scenario = by_stage("q1-b1-s1-g1")
    observation = success_observation(1)
    observation["fulfillment"]["teardown_status"]["state"] = "teardown_failed"
    result = capacity_result(
        scenario,
        [observation],
        cleanup={
            "attempted": True,
            "status": "failed",
            "zero_residue": False,
            "failure": {
                "code": "residue-remains",
                "location": "cleanup",
                "evidence_summary": "The sanitized cleanup assertion still reports residue.",
            },
        },
    )

    evaluation = evaluate_capacity_result(scenario, result, repo_root())
    cleanup_findings = [
        item
        for item in evaluation["findings"]
        if item["classification"] == "cleanup-failure"
    ]

    assert {item["failure"]["code"] for item in cleanup_findings} == {
        "fulfillment-teardown-not-terminal",
        "residue-remains",
    }
    assert len({item["fingerprint"] for item in cleanup_findings}) == 2


def test_request_order_is_irrelevant_but_duplicate_or_out_of_range_ordinals_are_not() -> (
    None
):
    scenario = by_stage("q2-b2-s1-g1")
    ordered = evaluate_capacity_result(
        scenario,
        capacity_result(scenario, [success_observation(1), scarcity_observation(2)]),
        repo_root(),
    )
    reversed_result = evaluate_capacity_result(
        scenario,
        capacity_result(scenario, [scarcity_observation(2), success_observation(1)]),
        repo_root(),
    )
    assert ordered["observations"] == reversed_result["observations"]

    duplicate = evaluate_capacity_result(
        scenario,
        capacity_result(scenario, [success_observation(1), scarcity_observation(1)]),
        repo_root(),
    )
    assert duplicate["classification"] == "harness-defect"
    assert any(
        item["failure"]["code"] == "request-observation-set-mismatch"
        for item in duplicate["findings"]
    )

    out_of_range = capacity_result(
        scenario,
        [success_observation(1), scarcity_observation(9)],
    )
    with pytest.raises(CapacityValidationError, match="1 through 8"):
        validate_capacity_result(out_of_range, scenario, repo_root())


def test_fingerprint_changes_only_with_semantic_identity_fields() -> None:
    base = {
        "scenario_sha256_value": "a" * 64,
        "classification": "harness-defect",
        "code": "receipt-missing",
        "location": "role_receipts",
        "stable_evidence_summary": "A required sanitized receipt was missing.",
    }
    digest = finding_fingerprint(**base)
    for key, value in (
        ("scenario_sha256_value", "b" * 64),
        ("classification", "possible-product-defect"),
        ("code", "receipt-mismatched"),
        ("location", "runner"),
        ("stable_evidence_summary", "A different stable assertion was observed."),
    ):
        changed = dict(base)
        changed[key] = value
        assert finding_fingerprint(**changed) != digest

    normalized = dict(base)
    normalized["stable_evidence_summary"] = (
        "  A REQUIRED sanitized receipt was missing.  "
    )
    assert finding_fingerprint(**normalized) == digest


@pytest.mark.parametrize(
    "sensitive_value",
    [
        "password=not-public",
        "Bearer not-a-real-token",
        "ghp_notarealtokenvalue",
        "github_pat_notarealtokenvalue",
        "sk-proj-notarealtokenvalue",
        "sk_live_notarealtokenvalue",
        "rk_live_notarealtokenvalue",
        "npm_notarealtokenvalue",
        "pypi-notarealtokenvalue",
        "eyJhbGciOiJub25lIn0.eyJzdWIiOiJzeW50aGV0aWMifQ.notarealsignature",
        "Authorization: Basic dXNlcjpwYXNz",
        "Proxy-Authorization: Basic dXNlcjpwYXNz",
        "Basic dXNlcjpwYXNz",
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIsyntheticnotrealkeymaterial",
        "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABsyntheticnotrealkeymaterial",
        "gpu-host ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIsyntheticnotrealkeymaterial",
        "SHA256:syntheticnotrealsshfingerprintvalue",
        "0x1111111111111111111111111111111111111111",
        "0x2222222222222222222222222222222222222222222222222222222222222222",
        "wallet_address=0x3333333333333333333333333333333333333333",
        "4/0AXsynthetic-device-code-not-real",
        "/home/private-user/capacity/run.json",
        "/tmp/capacity-run-123/result.json",
        "path=C:\\Users\\alice\\secret",
        "path=../secret",
        "path=(/var/private/run.json)",
        "https://internal.invalid/run",
        "fe80::1",
        "2001:db8::1234",
        "::1",
        "::dead:beef",
        "00:11:22:33:44:55",
        "00-11-22-33-44-55",
        "0011.2233.4455",
        "internal-host.example.invalid",
        "server.localdomain",
        "localhost:2222",
        "server:22",
        "operator@example.invalid",
        "capacity_reservation_id=reservation-opaque",
        "project_id=private-project",
        "private repository ref must-not-appear",
        "raw log line one\nraw log line two",
    ],
)
def test_finding_privacy_scan_rejects_sensitive_public_evidence(
    sensitive_value: str,
) -> None:
    scenario = by_stage("q2-b2-s1-g1")
    result = capacity_result(
        scenario,
        [success_observation(1), scarcity_observation(2, error="other_conflict")],
    )
    finding = evaluate_capacity_result(scenario, result, repo_root())["findings"][0]
    finding["failure"]["stable_evidence_summary"] = sensitive_value
    finding["summary"] = sensitive_value[:240]
    finding["fingerprint"] = finding_fingerprint(
        scenario_sha256_value=finding["scenario"]["sha256"],
        classification=finding["classification"],
        code=finding["failure"]["code"],
        location=finding["failure"]["location"],
        stable_evidence_summary=" ".join(sensitive_value.split()),
    )

    with pytest.raises(CapacityValidationError):
        validate_finding(finding, repo_root())


def test_finding_privacy_scan_does_not_treat_word_suffix_as_token() -> None:
    scenario = by_stage("q2-b2-s1-g1")
    result = capacity_result(
        scenario,
        [success_observation(1), scarcity_observation(2, error="other_conflict")],
    )
    finding = evaluate_capacity_result(scenario, result, repo_root())["findings"][0]
    summary = "A task-oriented assertion identified a bounded harness mismatch."
    finding["failure"]["stable_evidence_summary"] = summary.lower()
    finding["summary"] = summary
    finding["fingerprint"] = finding_fingerprint(
        scenario_sha256_value=finding["scenario"]["sha256"],
        classification=finding["classification"],
        code=finding["failure"]["code"],
        location=finding["failure"]["location"],
        stable_evidence_summary=summary.lower(),
    )

    validate_finding(finding, repo_root())


def test_finding_privacy_scan_allows_public_version_and_timestamp_text() -> None:
    scenario = by_stage("q2-b2-s1-g1")
    result = capacity_result(
        scenario,
        [success_observation(1), scarcity_observation(2, error="other_conflict")],
    )
    finding = evaluate_capacity_result(scenario, result, repo_root())["findings"][0]
    summary = (
        "Basic validation for version 1.2.3 with schema_version:1 and request:2 "
        "produced status:409 "
        "at 2026-08-02T12:34:56Z after duration 00:45 and ratio 12:34."
    )
    finding["occurrence"]["observed_at"] = "2026-08-02T12:34:56Z"
    finding["failure"]["stable_evidence_summary"] = summary.lower()
    finding["summary"] = summary
    finding["fingerprint"] = finding_fingerprint(
        scenario_sha256_value=finding["scenario"]["sha256"],
        classification=finding["classification"],
        code=finding["failure"]["code"],
        location=finding["failure"]["location"],
        stable_evidence_summary=summary.lower(),
    )

    validate_finding(finding, repo_root())


def test_untrusted_http_detail_is_never_echoed_into_the_finding() -> None:
    scenario = by_stage("q2-b2-s1-g1")
    response = scarcity_observation(
        2,
        error="password=must-not-echo",
        reason="capacity_reservation_id=must-not-echo",
    )

    evaluation = evaluate_capacity_result(
        scenario,
        capacity_result(scenario, [success_observation(1), response]),
        repo_root(),
    )

    serialized = json.dumps(evaluation, sort_keys=True)
    assert "must-not-echo" not in serialized
    assert evaluation["findings"][0]["failure"]["code"] == ("unexpected-scarcity-error")


def test_sanitized_code_shaped_409_is_classified_without_accepting_raw_message() -> (
    None
):
    scenario = by_stage("q2-b2-s1-g1")
    conflict = {
        "request_ordinal": 2,
        "outcome": "http-error",
        "http_status": 409,
        "detail": {"code": "fulfillment_conflict"},
    }

    evaluation = evaluate_capacity_result(
        scenario,
        capacity_result(scenario, [success_observation(1), conflict]),
        repo_root(),
    )

    assert evaluation["findings"][0]["failure"]["code"] == ("unexpected-http-conflict")

    raw = capacity_result(scenario, [success_observation(1), conflict])
    raw["observations"][1]["detail"]["message"] = "provider internals"
    with pytest.raises(CapacityValidationError, match="sanitized code"):
        validate_capacity_result(raw, scenario, repo_root())
