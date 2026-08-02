from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from issue_discovery.capacity import (
    CapacityValidationError,
    FINITE_STAGE_ORDER,
    scenario_sha256,
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
    loaded = [
        validate_scenario_file(path, repo_root())
        for path in paths
    ]
    by_id = {item["stage"]: item for item in loaded}
    assert len(loaded) == len(by_id) == len(FINITE_STAGE_ORDER) == 10
    assert set(by_id) == set(FINITE_STAGE_ORDER)
    return [by_id[stage] for stage in FINITE_STAGE_ORDER]


def by_stage(stage: str) -> dict[str, object]:
    return next(item for item in scenarios() if item["stage"] == stage)


def test_capacity_schema_is_valid_draft_2020_12() -> None:
    schema_path = repo_root() / "tools" / "issue-discovery" / "schemas" / "capacity-scenario.schema.json"
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
        assert scenario["role_contract"]["buyer_quickstart"] == "docs/buyer-quickstart.md"
        assert scenario["role_contract"]["seller_quickstart"] == "docs/seller-quickstart.md"


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
    assert "controller.reference-request-invoked" in reference["role_contract"]["required_receipts"]
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
        assert scenario["role_contract"]["same_session_prepare_wait_invoke"] is substantive
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
