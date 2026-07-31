from __future__ import annotations

import json
from pathlib import Path

import pytest

from issue_discovery.capacity import (
    CapacityValidationError,
    scenario_sha256,
    validate_scenario,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def valid_scenario() -> dict[str, object]:
    path = (
        repo_root()
        / "tools"
        / "issue-discovery"
        / "config"
        / "capacity"
        / "scenarios"
        / "b2-s1-g1.json"
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_capacity_scenario_is_vm_only_and_balances_terminal_outcomes() -> None:
    scenario = valid_scenario()
    validate_scenario(scenario, repo_root())

    scenario["deal_type"] = "container"
    with pytest.raises(CapacityValidationError, match="deal_type.*vm"):
        validate_scenario(scenario, repo_root())


def test_capacity_scenario_rejects_private_runtime_listing_identity() -> None:
    scenario = valid_scenario()
    scenario["listing_topology"]["runtime_listing_id"] = "live-listing-123"

    with pytest.raises(
        CapacityValidationError,
        match="listing_topology.*runtime_listing_id.*unexpected",
    ):
        validate_scenario(scenario, repo_root())


def test_capacity_scenario_sha256_is_canonical() -> None:
    scenario = valid_scenario()
    reordered = json.loads(json.dumps(scenario, sort_keys=True, indent=4))

    digest = scenario_sha256(scenario)
    assert digest == (
        "46e0ff44baed6a1113471bd2e0c3dbf5fb7a50a6b24b43d2b948fff83ab7832c"
    )
    assert digest == scenario_sha256(reordered)
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_all_tracked_capacity_scenarios_are_valid_and_cover_seller_scaling() -> None:
    scenario_dir = (
        repo_root()
        / "tools"
        / "issue-discovery"
        / "config"
        / "capacity"
        / "scenarios"
    )
    scenarios = []
    for path in sorted(scenario_dir.glob("*.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        validate_scenario(scenario, repo_root())
        scenarios.append(scenario)

    assert {item["scenario_id"] for item in scenarios} == {
        "b1-s1-g1",
        "b2-s1-g1",
        "b3-s1-g1",
        "b4-s1-g1",
        "b5-s1-g1",
        "b6-s1-g1",
        "b7-s1-g1",
        "b8-s1-g1",
        "serialized-reuse-a",
        "serialized-reuse-b",
        "b2-s2-g1",
        "b4-s2-g1",
        "b4-s3-g1",
        "b4-s4-g1",
    }
    for scenario in scenarios:
        topology = scenario["listing_topology"]
        sellers = topology["sellers"]
        assert len(sellers) == scenario["actor_counts"]["sellers"]
        assert all(len(seller["listing_slots"]) == 1 for seller in sellers)
        assert scenario["load_counts"]["selected_listings"] == len(sellers)
        assert scenario["physical_capacity"] == {
            "independently_assignable_gpus": 1,
            "gpus_per_successful_vm": 1,
        }
        assert scenario["expected_outcomes"] == {
            "vm-succeeded": 1,
            "capacity-refused": scenario["load_counts"]["requests"] - 1,
            "fault": 0,
        }
        expected_mode = (
            "single-seller"
            if scenario["actor_counts"]["sellers"] == 1
            else "shared-globally-fenced"
        )
        assert topology["capacity_authority_mode"] == expected_mode
