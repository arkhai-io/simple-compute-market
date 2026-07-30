from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

from issue_discovery.capacity import (
    CapacityValidationError,
    canonical_json_bytes,
    canonical_sha256,
    resolve_pinned_scenario,
)


SCENARIO_PATH = Path(
    "tools/issue-discovery/config/capacity/scenarios/b1-s1-g1.json"
)
SCENARIO_SCHEMA_PATH = Path(
    "tools/issue-discovery/schemas/capacity-scenario.schema.json"
)


def source_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def valid_scenario() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "scenario_id": "b1-s1-g1",
        "deal_type": "vm",
        "provisioning": "real-kvm-ansible",
        "gpu_assignment": "whole-device-passthrough",
        "physical_capacity": {
            "independently_assignable_gpus": 1,
            "gpus_per_successful_vm": 1,
        },
        "actor_slots": {
            "observers": ["observer-1"],
            "buyers": ["buyer-1"],
            "sellers": ["seller-1"],
            "host_operators": ["host-operator-1"],
        },
        "actor_counts": {
            "observers": 1,
            "buyers": 1,
            "sellers": 1,
            "host_operators": 1,
        },
        "listing_topology": {
            "capacity_authority_mode": "single-seller",
            "sellers": [
                {
                    "seller_slot": "seller-1",
                    "service_slot": "seller-service-1",
                    "listing_slots": ["listing-1"],
                }
            ],
        },
        "load_counts": {
            "selected_listings": 1,
            "requests": 1,
        },
        "requests": [
            {
                "request_id": "request-1",
                "buyer_slot": "buyer-1",
                "seller_slot": "seller-1",
                "listing_slot": "listing-1",
            }
        ],
        "expected_outcomes": {
            "vm-succeeded": 1,
            "capacity-refused": 0,
            "fault": 0,
        },
        "retry_budget": 0,
    }


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(
        repo,
        "-c",
        "user.name=Capacity Test",
        "-c",
        "user.email=capacity-test@example.invalid",
        "commit",
        "-q",
        "-m",
        message,
    )
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def pinned_repo(tmp_path: Path) -> tuple[Path, str, dict[str, Any]]:
    repo = tmp_path / "simple-compute-market"
    schema_dir = repo / "tools" / "issue-discovery" / "schemas"
    scenario_path = repo / SCENARIO_PATH
    schema_dir.mkdir(parents=True)
    scenario_path.parent.mkdir(parents=True)
    shutil.copyfile(
        source_repo_root()
        / "tools"
        / "issue-discovery"
        / "schemas"
        / "capacity-scenario.schema.json",
        schema_dir / "capacity-scenario.schema.json",
    )
    scenario = valid_scenario()
    scenario_path.write_text(
        json.dumps(scenario, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    git(repo, "init", "-q", "-b", "fixture")
    ref = commit_all(repo, "add pinned capacity scenario")
    return repo, ref, scenario


def test_canonical_json_is_utf8_sorted_compact_and_newline_terminated() -> None:
    first = {"z": ["π", {"b": 2, "a": 1}], "a": "雪"}
    second = {"a": "雪", "z": ["π", {"a": 1, "b": 2}]}

    expected = '{"a":"雪","z":["π",{"a":1,"b":2}]}\n'.encode()
    assert canonical_json_bytes(first) == expected
    assert canonical_json_bytes(second) == expected
    assert canonical_sha256(first) == canonical_sha256(second)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_json_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(CapacityValidationError, match="cannot be canonicalized"):
        canonical_json_bytes({"value": value})


def test_resolver_returns_exact_pinned_identity(
    pinned_repo: tuple[Path, str, dict[str, Any]],
) -> None:
    repo, ref, scenario = pinned_repo
    expected_digest = canonical_sha256(scenario)

    resolved = resolve_pinned_scenario(
        repo,
        ref,
        SCENARIO_PATH.as_posix(),
        expected_sha256=expected_digest,
    )

    assert resolved.scenario_id == "b1-s1-g1"
    assert resolved.scm_ref == ref
    assert resolved.relative_path == SCENARIO_PATH.as_posix()
    assert resolved.scenario_sha256 == expected_digest
    assert resolved.scenario == scenario


def test_resolved_scenario_returns_an_immutable_snapshot(
    pinned_repo: tuple[Path, str, dict[str, Any]],
) -> None:
    repo, ref, scenario = pinned_repo
    resolved = resolve_pinned_scenario(repo, ref, SCENARIO_PATH.as_posix())

    caller_copy = resolved.scenario
    caller_copy["scenario_id"] = "changed-by-caller"

    assert resolved.scenario == scenario
    assert canonical_sha256(resolved.scenario) == resolved.scenario_sha256


@pytest.mark.parametrize(
    "selected_path",
    [
        "/tmp/b1-s1-g1.json",
        "../b1-s1-g1.json",
        "tools/issue-discovery/config/capacity/scenarios/../b1-s1-g1.json",
        "tools/issue-discovery/config/capacity/b1-s1-g1.json",
        "tools/issue-discovery/config/capacity/scenarios/nested/b1-s1-g1.json",
        "tools\\issue-discovery\\config\\capacity\\scenarios\\b1-s1-g1.json",
    ],
)
def test_resolver_rejects_paths_outside_the_known_scenario_root(
    pinned_repo: tuple[Path, str, dict[str, Any]],
    selected_path: str,
) -> None:
    repo, ref, _scenario = pinned_repo

    with pytest.raises(CapacityValidationError, match="scenario path"):
        resolve_pinned_scenario(repo, ref, selected_path)


def test_resolver_rejects_untracked_and_non_regular_worktree_entries(
    pinned_repo: tuple[Path, str, dict[str, Any]],
) -> None:
    repo, ref, scenario = pinned_repo
    untracked = SCENARIO_PATH.with_name("untracked.json")
    (repo / untracked).write_text(json.dumps(scenario), encoding="utf-8")

    with pytest.raises(CapacityValidationError, match="tracked"):
        resolve_pinned_scenario(repo, ref, untracked.as_posix())

    directory = SCENARIO_PATH.with_name("directory.json")
    (repo / directory).mkdir()
    with pytest.raises(CapacityValidationError, match="regular file"):
        resolve_pinned_scenario(repo, ref, directory.as_posix())


def test_resolver_rejects_symlink_path_and_symlink_tree_mode(
    pinned_repo: tuple[Path, str, dict[str, Any]],
) -> None:
    repo, _ref, scenario = pinned_repo
    scenario_path = repo / SCENARIO_PATH
    target = scenario_path.with_name("target.json")
    target.write_text(json.dumps(scenario), encoding="utf-8")
    scenario_path.unlink()
    scenario_path.symlink_to(target.name)
    symlink_ref = commit_all(repo, "track scenario as a symlink")

    with pytest.raises(CapacityValidationError, match="symlink"):
        resolve_pinned_scenario(repo, symlink_ref, SCENARIO_PATH.as_posix())

    scenario_path.unlink()
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
    with pytest.raises(CapacityValidationError, match="regular Git file"):
        resolve_pinned_scenario(repo, symlink_ref, SCENARIO_PATH.as_posix())


def test_resolver_accepts_executable_regular_git_mode(
    pinned_repo: tuple[Path, str, dict[str, Any]],
) -> None:
    repo, _ref, scenario = pinned_repo
    scenario_path = repo / SCENARIO_PATH
    scenario_path.chmod(0o755)
    git(repo, "update-index", "--chmod=+x", SCENARIO_PATH.as_posix())
    executable_ref = commit_all(repo, "record executable regular scenario")
    assert git(repo, "ls-tree", executable_ref, SCENARIO_PATH.as_posix()).startswith(
        "100755 blob "
    )

    assert (
        resolve_pinned_scenario(
            repo,
            executable_ref,
            SCENARIO_PATH.as_posix(),
        ).scenario
        == scenario
    )


def test_resolver_rejects_gitlink_tree_mode(
    pinned_repo: tuple[Path, str, dict[str, Any]],
) -> None:
    repo, ref, _scenario = pinned_repo
    git(repo, "update-index", "--force-remove", SCENARIO_PATH.as_posix())
    git(
        repo,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{ref},{SCENARIO_PATH.as_posix()}",
    )
    git(
        repo,
        "-c",
        "user.name=Capacity Test",
        "-c",
        "user.email=capacity-test@example.invalid",
        "commit",
        "-q",
        "-m",
        "record scenario path as a gitlink",
    )
    gitlink_ref = git(repo, "rev-parse", "HEAD")
    assert git(repo, "ls-tree", gitlink_ref, SCENARIO_PATH.as_posix()).startswith(
        "160000 commit "
    )

    with pytest.raises(CapacityValidationError, match="regular Git file"):
        resolve_pinned_scenario(repo, gitlink_ref, SCENARIO_PATH.as_posix())


@pytest.mark.parametrize(
    "index_flag",
    ["--assume-unchanged", "--skip-worktree"],
)
def test_resolver_detects_worktree_drift_hidden_by_index_flags(
    pinned_repo: tuple[Path, str, dict[str, Any]],
    index_flag: str,
) -> None:
    repo, ref, scenario = pinned_repo
    git(repo, "update-index", index_flag, SCENARIO_PATH.as_posix())
    scenario["scenario_id"] = "changed-behind-index"
    (repo / SCENARIO_PATH).write_text(json.dumps(scenario), encoding="utf-8")
    assert git(repo, "status", "--porcelain", "--", SCENARIO_PATH.as_posix()) == ""

    with pytest.raises(CapacityValidationError, match="worktree bytes differ"):
        resolve_pinned_scenario(repo, ref, SCENARIO_PATH.as_posix())


def test_resolver_detects_pinned_schema_drift_hidden_by_assume_unchanged(
    pinned_repo: tuple[Path, str, dict[str, Any]],
) -> None:
    repo, ref, _scenario = pinned_repo
    git(repo, "update-index", "--assume-unchanged", SCENARIO_SCHEMA_PATH.as_posix())
    schema_path = repo / SCENARIO_SCHEMA_PATH
    schema_path.write_text(
        schema_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    assert git(repo, "status", "--porcelain", "--", SCENARIO_SCHEMA_PATH.as_posix()) == ""

    with pytest.raises(CapacityValidationError, match="worktree bytes differ"):
        resolve_pinned_scenario(repo, ref, SCENARIO_PATH.as_posix())


def test_resolver_requires_filename_and_scenario_identity_to_match(
    pinned_repo: tuple[Path, str, dict[str, Any]],
) -> None:
    repo, _ref, scenario = pinned_repo
    scenario["scenario_id"] = "b2-s1-g1"
    (repo / SCENARIO_PATH).write_text(
        json.dumps(scenario, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    ref = commit_all(repo, "record mismatched scenario identity")

    with pytest.raises(CapacityValidationError, match="filename stem"):
        resolve_pinned_scenario(repo, ref, SCENARIO_PATH.as_posix())


@pytest.mark.parametrize(
    ("selected_ref", "message"),
    [
        ("fixture", "exact lowercase 40-character commit"),
        ("A" * 40, "exact lowercase 40-character commit"),
        ("f" * 40, "Git cat-file -t"),
    ],
)
def test_resolver_rejects_non_exact_or_missing_refs(
    pinned_repo: tuple[Path, str, dict[str, Any]],
    selected_ref: str,
    message: str,
) -> None:
    repo, _ref, _scenario = pinned_repo

    with pytest.raises(CapacityValidationError, match=message):
        resolve_pinned_scenario(repo, selected_ref, SCENARIO_PATH.as_posix())


def test_resolver_rejects_full_blob_object_id_as_a_commit(
    pinned_repo: tuple[Path, str, dict[str, Any]],
) -> None:
    repo, _ref, _scenario = pinned_repo
    blob_id = git(repo, "hash-object", SCENARIO_PATH.as_posix())
    assert len(blob_id) == 40

    with pytest.raises(CapacityValidationError, match="identify a Git commit"):
        resolve_pinned_scenario(repo, blob_id, SCENARIO_PATH.as_posix())


@pytest.mark.parametrize("expected_digest", ["A" * 64, "0" * 63, "f" * 64])
def test_resolver_rejects_malformed_or_mismatched_declared_digest(
    pinned_repo: tuple[Path, str, dict[str, Any]],
    expected_digest: str,
) -> None:
    repo, ref, _scenario = pinned_repo

    with pytest.raises(CapacityValidationError, match="scenario SHA-256"):
        resolve_pinned_scenario(
            repo,
            ref,
            SCENARIO_PATH.as_posix(),
            expected_sha256=expected_digest,
        )


@pytest.mark.parametrize(
    ("raw_json", "message"),
    [
        ('{"schema_version":2,"scenario_id":"one","scenario_id":"two"}\n', "duplicate"),
        ('{"schema_version":2,"value":NaN}\n', "non-finite"),
    ],
)
def test_resolver_rejects_non_strict_json_before_schema_authority(
    pinned_repo: tuple[Path, str, dict[str, Any]],
    raw_json: str,
    message: str,
) -> None:
    repo, _ref, _scenario = pinned_repo
    (repo / SCENARIO_PATH).write_text(raw_json, encoding="utf-8")
    ref = commit_all(repo, "record invalid JSON scenario")

    with pytest.raises(CapacityValidationError, match=message):
        resolve_pinned_scenario(repo, ref, SCENARIO_PATH.as_posix())
