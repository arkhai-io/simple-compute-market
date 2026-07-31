from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest

from issue_discovery.capacity import CapacityValidationError, canonical_json_bytes
from issue_discovery.issues import (
    IssueCandidate,
    IssuePacketGenerator,
    IssueRepository,
)


POLICY_ROOT = Path(__file__).resolve().parents[3]


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def write_private_json(path: Path, value: dict[str, object]) -> None:
    path.write_bytes(canonical_json_bytes(value))
    path.chmod(0o600)


def write_private_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_bytes(b"".join(canonical_json_bytes(row) for row in rows))
    path.chmod(0o600)


def write_run(
    run_dir: Path,
    *,
    stderr_text: str,
    classifiers: list[str],
    phase_id: str = "compose_start_strict",
    command_id: str = "compose_up",
    manifest_extra: dict[str, object] | None = None,
) -> None:
    (run_dir / "commands" / phase_id).mkdir(parents=True)
    (run_dir / "commands" / phase_id / f"{command_id}.stdout.txt").write_text(
        "", encoding="utf-8"
    )
    (run_dir / "commands" / phase_id / f"{command_id}.stderr.txt").write_text(
        stderr_text,
        encoding="utf-8",
    )
    (run_dir / "commands" / phase_id / f"{command_id}.meta.json").write_text(
        json.dumps({"exit_code": 1, "timed_out": False}),
        encoding="utf-8",
    )
    manifest = {
        "run_id": "test-run",
        "mode": "strict",
        "status": "failed",
        "phase_file": "test.yaml",
        "output_dir": str(run_dir),
    }
    if manifest_extra:
        manifest.update(manifest_extra)
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    write_jsonl(
        run_dir / "phases.jsonl",
        [
            {
                "id": phase_id,
                "name": "Strict compose startup",
                "category": "runtime",
                "status": "failed",
                "failed_command": command_id,
                "failed_commands": [command_id],
                "classifiers": classifiers,
                "commands": [
                    {
                        "id": command_id,
                        "exit_code": 1,
                        "timed_out": False,
                        "stdout": f"commands/{phase_id}/{command_id}.stdout.txt",
                        "stderr": f"commands/{phase_id}/{command_id}.stderr.txt",
                        "meta": f"commands/{phase_id}/{command_id}.meta.json",
                    }
                ],
            }
        ],
    )
    write_jsonl(run_dir / "collectors.jsonl", [])


def write_candidate(run_dir: Path) -> None:
    issue_dir = run_dir / "issue-candidates"
    issue_dir.mkdir(parents=True)
    (issue_dir / "candidate.md").write_text("# Candidate\n", encoding="utf-8")
    write_jsonl(
        issue_dir / "candidates.jsonl",
        [
            {
                "fingerprint": "fingerprint",
                "title": "Candidate",
                "labels": ["bug"],
                "classification": "test",
                "phase": "phase",
                "body_file": "issue-candidates/candidate.md",
                "evidence": [],
                "state": "ready_to_file",
            }
        ],
    )


def write_capacity_v2_candidate(run_dir: Path) -> None:
    issue_dir = run_dir / "issue-candidates"
    issue_dir.mkdir(parents=True)
    (issue_dir / "finding-001.md").write_text(
        "# Marker-free occurrence\n",
        encoding="utf-8",
    )
    write_jsonl(
        issue_dir / "candidates.jsonl",
        [
            {
                "candidate_kind": "capacity-finding-v2",
                "candidate_id": "finding-001",
                "finding_id": "finding-001",
                "finding_sha256": "a" * 64,
                "fingerprint": "capacity-" + "b" * 64,
                "title": "Validated capacity occurrence",
                "labels": ["bug"],
                "classification": "public-harness",
                "phase": "settlement",
                "body_file": "issue-candidates/finding-001.md",
                "evidence": [],
                "state": "ready_to_file",
                "publication_capability": "guard-issue-fix-publication",
                "lifecycle_state": "detected",
            }
        ],
    )


def write_capacity_v2_packet_run(
    run_dir: Path,
    *,
    finding_ids: tuple[str, ...] = ("finding-001", "finding-002"),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, bytes]]:
    run_dir.mkdir(mode=0o700)
    ingest_lock = run_dir / ".capacity-finding-ingest.lock"
    ingest_lock.write_bytes(b"")
    ingest_lock.chmod(0o600)
    fingerprint = "capacity-" + "b" * 64
    sources = [
        {
            "schema_version": 2,
            "finding_id": finding_id,
            "summary": f"Occurrence {finding_id}",
        }
        for finding_id in finding_ids
    ]
    indexes: list[dict[str, Any]] = []
    body_bytes: dict[str, bytes] = {}
    source_root = run_dir / "capacity-findings"
    index_root = run_dir / "capacity-finding-index"
    body_root = run_dir / "capacity-finding-bodies"
    source_root.mkdir(mode=0o700)
    index_root.mkdir(mode=0o700)
    body_root.mkdir(mode=0o700)
    evidence_root = run_dir / "evidence"
    evidence_root.mkdir(mode=0o700)
    evidence_path = evidence_root / "result.json"
    evidence_path.write_bytes(b"{}\n")
    evidence_path.chmod(0o600)
    for source in sources:
        finding_id = str(source["finding_id"])
        body = f"# {finding_id}\n\nMarker-free detected occurrence.\n"
        body_path = body_root / f"{finding_id}.md"
        body_path.write_text(body, encoding="utf-8")
        body_path.chmod(0o600)
        body_bytes[finding_id] = body_path.read_bytes()
        index = {
            "schema_version": 1,
            "candidate_kind": "capacity-finding-v2",
            "publication_capability": "guard-issue-fix-publication",
            "finding_id": finding_id,
            "finding_sha256": "a" * 64,
            "fingerprint": fingerprint,
            "destination_repo": "simple-compute-market",
            "classification": "public-harness",
            "frontier": "correctness",
            "scenario_id": "b2-s1-g1",
            "scenario_sha256": "c" * 64,
            "profile_stage_id": "b2-s1-g1-measured",
            "profile_stage_sha256": "d" * 64,
            "result_id": "result-001",
            "result_sha256": "e" * 64,
            "scm_contract_ref": "f" * 40,
            "defect_semantics": {
                "expected_outcome_kind": "vm-succeeded",
                "actual_fault_category": "double-allocation",
                "failure_code": "double-allocation",
                "stable_signature": "overlapping whole gpu assignments",
                "lifecycle_phase": "provisioning",
            },
            "observed_outcome": {
                "request_ids": ["request-1", "request-2"],
                "outcome_kind": "vm-succeeded",
                "diagnostic_code": None,
            },
            "durable_correlations": [],
            "observed_authority": {
                "run_id": "capacity-run-001",
                "stage_id": "b2-s1-g1-measured",
                "working_branch": "feat/issue-discovery-harness",
                "working_ref": "1" * 40,
                "upstream_branch": "dev",
                "upstream_ref": "2" * 40,
                "inbound_merge_ref": "3" * 40,
                "reconciliation_epoch_id": "epoch-001",
                "observed_at": "2026-07-30T12:00:00Z",
            },
            "evidence": [
                {
                    "path": "evidence/result.json",
                    "sha256": "4" * 64,
                }
            ],
            "filing_readiness": {
                "terminal_correlations_complete": True,
                "teardown_complete": True,
                "zero_active_residue": True,
                "baseline_equivalent": True,
                "ready_to_file": True,
            },
            "lifecycle": {
                "state": "detected",
                "detected_at": "2026-07-30T12:00:00Z",
            },
            "occurrence_body_path": f"capacity-finding-bodies/{finding_id}.md",
            "occurrence_body": body,
            "occurrence_body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        }
        indexes.append(index)
        source_path = source_root / f"{finding_id}.json"
        index_path = index_root / f"{finding_id}.json"
        source_path.write_bytes(canonical_json_bytes(source))
        index_path.write_bytes(canonical_json_bytes(index))
        source_path.chmod(0o600)
        index_path.chmod(0o600)
    write_private_jsonl(run_dir / "capacity-findings.jsonl", sources)
    write_private_jsonl(run_dir / "capacity-finding-index.jsonl", indexes)
    authority = indexes[0]["observed_authority"]
    assert isinstance(authority, dict)
    write_private_json(
        run_dir / "manifest.json",
        {
            "schema_version": 2,
            "run_id": authority["run_id"],
            "capacity_finding_authority": {
                "run_id": authority["run_id"],
                "working_branch": authority["working_branch"],
                "working_ref": authority["working_ref"],
                "upstream_branch": authority["upstream_branch"],
                "upstream_ref": authority["upstream_ref"],
                "inbound_merge_ref": authority["inbound_merge_ref"],
                "reconciliation_epoch_id": authority["reconciliation_epoch_id"],
            },
            "capacity_findings": [
                {
                    "finding_id": index["finding_id"],
                    "finding_sha256": index["finding_sha256"],
                    "fingerprint": index["fingerprint"],
                    "destination_repo": index["destination_repo"],
                    "classification": index["classification"],
                    "scenario_id": index["scenario_id"],
                    "scenario_sha256": index["scenario_sha256"],
                    "profile_stage_id": index["profile_stage_id"],
                    "profile_stage_sha256": index["profile_stage_sha256"],
                    "result_id": index["result_id"],
                    "result_sha256": index["result_sha256"],
                    "stage_id": index["observed_authority"]["stage_id"],
                    "observed_at": index["observed_authority"]["observed_at"],
                }
                for index in indexes
            ],
        },
    )
    write_private_jsonl(
        run_dir / "issue-lifecycle.jsonl",
        [
            {
                "schema_version": 2,
                "candidate_kind": "capacity-finding-v2",
                "finding_id": index["finding_id"],
                "finding_sha256": index["finding_sha256"],
                "fingerprint": index["fingerprint"],
                "state": "detected",
                "recorded_at": index["observed_authority"]["observed_at"],
                "destination_repo": index["destination_repo"],
                "classification": index["classification"],
                "frontier": index["frontier"],
                "scenario_id": index["scenario_id"],
                "scenario_sha256": index["scenario_sha256"],
                "profile_stage_id": index["profile_stage_id"],
                "profile_stage_sha256": index["profile_stage_sha256"],
                "result_id": index["result_id"],
                "result_sha256": index["result_sha256"],
                "scm_contract_ref": index["scm_contract_ref"],
                "observed_authority": index["observed_authority"],
                "filing_readiness": index["filing_readiness"],
            }
            for index in indexes
        ],
    )
    return sources, indexes, body_bytes


def patch_capacity_v2_packet_validation(
    monkeypatch: pytest.MonkeyPatch,
    indexes: list[dict[str, Any]],
) -> None:
    monkeypatch.setattr(
        "issue_discovery.capacity_findings.validate_capacity_finding_index_record",
        lambda record, source, **kwargs: dict(record),
    )
    indexes_by_id = {str(index["finding_id"]): index for index in indexes}
    monkeypatch.setattr(
        "issue_discovery.capacity_findings.load_capacity_finding_index_artifacts",
        lambda source_path, *args, **kwargs: dict(indexes_by_id[source_path.stem]),
    )


def add_failed_phase_to_capacity_v2_run(run_dir: Path) -> str:
    phase_id = "root_service_tests"
    command_id = "make_test"
    command_dir = run_dir / "commands" / phase_id
    command_dir.mkdir(parents=True)
    (command_dir / f"{command_id}.stdout.txt").write_text("", encoding="utf-8")
    (command_dir / f"{command_id}.stderr.txt").write_text(
        "root service tests failed\n",
        encoding="utf-8",
    )
    (command_dir / f"{command_id}.meta.json").write_text(
        json.dumps({"exit_code": 1, "timed_out": False}),
        encoding="utf-8",
    )
    write_jsonl(
        run_dir / "phases.jsonl",
        [
            {
                "id": phase_id,
                "name": "Root service tests",
                "category": "stack_test",
                "status": "failed",
                "failed_command": command_id,
                "failed_commands": [command_id],
                "classifiers": [],
                "commands": [
                    {
                        "id": command_id,
                        "exit_code": 1,
                        "timed_out": False,
                        "stdout": (
                            f"commands/{phase_id}/{command_id}.stdout.txt"
                        ),
                        "stderr": (
                            f"commands/{phase_id}/{command_id}.stderr.txt"
                        ),
                        "meta": f"commands/{phase_id}/{command_id}.meta.json",
                    }
                ],
            }
        ],
    )
    write_jsonl(run_dir / "collectors.jsonl", [])
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "mode": "continue",
            "status": "failed",
            "phase_file": "test.yaml",
            "output_dir": str(run_dir),
        }
    )
    write_private_json(manifest_path, manifest)
    return "root-service-tests-make-test"


def test_issue_generator_uses_generic_fingerprint_when_classifier_evidence_does_not_match(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_run(
        run_dir,
        stderr_text="compose failed for an unexpected reason",
        classifiers=[
            "compose_start_failure",
            "redis_host_port_conflict",
            "storefront_volume_ownership",
        ],
    )

    candidates = IssuePacketGenerator(run_dir).generate()

    assert [candidate.fingerprint for candidate in candidates] == [
        "compose-start-strict-compose-up"
    ]
    assert candidates[0].state == "needs_targeted_repro"
    assert candidates[0].confidence == "low"


def test_preexisting_stack_classifier_does_not_match_service_name_only(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_run(
        run_dir,
        stderr_text="registry failed readiness while provisioning was starting",
        classifiers=["preexisting_compose_stack"],
    )

    candidates = IssuePacketGenerator(run_dir).generate()

    assert [candidate.fingerprint for candidate in candidates] == [
        "compose-start-strict-compose-up"
    ]


def test_preexisting_stack_classifier_matches_container_name_collision(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_run(
        run_dir,
        stderr_text=(
            'Error response from daemon: Conflict. The container name "/registry" '
            "is already in use by container abc123."
        ),
        classifiers=["preexisting_compose_stack"],
    )

    candidates = IssuePacketGenerator(run_dir).generate()

    assert [candidate.fingerprint for candidate in candidates] == [
        "preexisting-compose-stack"
    ]


def test_issue_generator_uses_matching_classifier_for_known_root_cause(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_run(
        run_dir,
        stderr_text="sqlite3.OperationalError: unable to open database file",
        classifiers=[
            "redis_host_port_conflict",
            "storefront_volume_ownership",
        ],
    )

    candidates = IssuePacketGenerator(run_dir).generate()

    assert [candidate.fingerprint for candidate in candidates] == [
        "storefront-volume-ownership"
    ]
    assert candidates[0].state == "needs_targeted_repro"
    assert candidates[0].confidence == "medium"


def test_issue_generator_matches_docker_redis_port_conflict_text(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_run(
        run_dir,
        stderr_text=(
            "Error response from daemon: driver failed programming external connectivity "
            "on endpoint simple-compute-market-redis-1: Error starting userland proxy: "
            "listen tcp4 0.0.0.0:6379: bind: address already in use"
        ),
        classifiers=[
            "redis_host_port_conflict",
            "storefront_volume_ownership",
        ],
    )

    candidates = IssuePacketGenerator(run_dir).generate()

    assert [candidate.fingerprint for candidate in candidates] == [
        "redis-host-port-conflict"
    ]
    assert candidates[0].state == "needs_targeted_repro"
    assert candidates[0].confidence == "medium"


def test_issue_generator_matches_registry_agent_indexing_race(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_run(
        run_dir,
        phase_id="smoke_marker_tests",
        command_id="registry",
        stderr_text="No agents found in the registry. Response: total=None agents_in_page=0",
        classifiers=["registry_agent_indexing_race"],
    )

    candidates = IssuePacketGenerator(run_dir).generate()

    assert [candidate.fingerprint for candidate in candidates] == [
        "registry-agent-indexing-race"
    ]
    assert candidates[0].state == "ready_to_file"
    assert candidates[0].confidence == "high"


def test_issue_generator_matches_zerotier_build_path(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_run(
        run_dir,
        phase_id="zerotier_build_path",
        command_id="make_build",
        stderr_text="curl -s https://install.zerotier.com | bash failed installing zerotier-one",
        classifiers=["zerotier_build_path"],
    )

    candidates = IssuePacketGenerator(run_dir).generate()

    assert [candidate.fingerprint for candidate in candidates] == [
        "zerotier-build-path"
    ]
    assert candidates[0].state == "needs_targeted_repro"
    assert candidates[0].confidence == "medium"


def test_targeted_profile_promotes_matching_candidate_to_ready(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_run(
        run_dir,
        phase_id="zerotier_build_path",
        command_id="make_build",
        stderr_text="sudo: a terminal is required while installing zerotier-one",
        classifiers=["zerotier_build_path"],
        manifest_extra={"mode": "profile:zerotier-build-path"},
    )

    candidates = IssuePacketGenerator(run_dir).generate()

    assert [candidate.fingerprint for candidate in candidates] == [
        "zerotier-build-path"
    ]
    assert candidates[0].state == "ready_to_file"
    assert candidates[0].confidence == "high"
    assert "targeted ZeroTier build-path profile" in candidates[0].state_reason


def test_issue_generator_renders_all_continue_workarounds_in_reproduction(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_run(
        run_dir,
        stderr_text="phase failed",
        classifiers=[],
        manifest_extra={
            "mode": "continue",
            "workarounds": [
                {"id": "first", "reason": "first reason"},
                {"id": "second", "reason": "second reason"},
            ],
        },
    )

    candidates = IssuePacketGenerator(run_dir).generate()
    body = (run_dir / candidates[0].body_file.relative_to(run_dir)).read_text(
        encoding="utf-8"
    )

    assert (
        "Run `./scripts/issue-discovery continue --with first --with second`." in body
    )


def test_issue_generator_deduplicates_repeated_fingerprints(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for phase_id, command_id in (
        ("role_layer_marker_tests", "roles_layer_seller"),
        ("full_integration_sweep", "integration_full"),
    ):
        command_dir = run_dir / "commands" / phase_id
        command_dir.mkdir(parents=True)
        (command_dir / f"{command_id}.stdout.txt").write_text(
            'Storefront at http://localhost:8001 not reachable: status=404 body={"detail":"Not Found"}',
            encoding="utf-8",
        )
        (command_dir / f"{command_id}.stderr.txt").write_text("", encoding="utf-8")
        (command_dir / f"{command_id}.meta.json").write_text(
            json.dumps({"exit_code": 2, "timed_out": False}),
            encoding="utf-8",
        )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "test-run",
                "mode": "strict",
                "status": "failed",
                "phase_file": "test.yaml",
                "output_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    write_jsonl(
        run_dir / "phases.jsonl",
        [
            {
                "id": "role_layer_marker_tests",
                "name": "Role layer marker tests",
                "category": "stack_test",
                "status": "failed",
                "failed_command": "roles_layer_seller",
                "failed_commands": ["roles_layer_seller"],
                "classifiers": ["stale_seller_layer_route"],
                "commands": [
                    {
                        "id": "roles_layer_seller",
                        "exit_code": 2,
                        "timed_out": False,
                        "stdout": "commands/role_layer_marker_tests/roles_layer_seller.stdout.txt",
                        "stderr": "commands/role_layer_marker_tests/roles_layer_seller.stderr.txt",
                        "meta": "commands/role_layer_marker_tests/roles_layer_seller.meta.json",
                    }
                ],
            },
            {
                "id": "full_integration_sweep",
                "name": "Full unfiltered integration test sweep",
                "category": "stack_test",
                "status": "failed",
                "failed_command": "integration_full",
                "failed_commands": ["integration_full"],
                "classifiers": ["stale_seller_layer_route"],
                "commands": [
                    {
                        "id": "integration_full",
                        "exit_code": 2,
                        "timed_out": False,
                        "stdout": "commands/full_integration_sweep/integration_full.stdout.txt",
                        "stderr": "commands/full_integration_sweep/integration_full.stderr.txt",
                        "meta": "commands/full_integration_sweep/integration_full.meta.json",
                    }
                ],
            },
        ],
    )
    write_jsonl(run_dir / "collectors.jsonl", [])

    candidates = IssuePacketGenerator(run_dir).generate()

    assert [candidate.fingerprint for candidate in candidates] == [
        "stale-seller-layer-route"
    ]
    assert candidates[0].state == "ready_to_file"
    assert candidates[0].confidence == "high"
    assert (
        "commands/full_integration_sweep/integration_full.stdout.txt"
        in candidates[0].evidence
    )
    body = (run_dir / candidates[0].body_file.relative_to(run_dir)).read_text(
        encoding="utf-8"
    )
    assert "commands/full_integration_sweep/integration_full.stdout.txt" in body
    assert "State: `ready_to_file`" in body
    assert "Confidence: `high`" in body


def test_issue_generator_uses_compose_logs_for_storefront_volume_crash(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    command_dir = run_dir / "commands" / "role_layer_marker_tests"
    command_dir.mkdir(parents=True)
    (command_dir / "roles_layer_seller.stdout.txt").write_text(
        "tests/e2e/roles/layers/test_seller.py::TestSellerNode::test_storefront_reachable\n"
        "AssertionError: Storefront at http://localhost:8001 not reachable: "
        "status=0 body=<urlopen error [Errno 111] Connection refused>\n",
        encoding="utf-8",
    )
    (command_dir / "roles_layer_seller.stderr.txt").write_text("", encoding="utf-8")
    (command_dir / "roles_layer_seller.meta.json").write_text(
        json.dumps({"exit_code": 1, "timed_out": False}),
        encoding="utf-8",
    )
    docker_dir = run_dir / "docker"
    docker_dir.mkdir()
    (docker_dir / "compose-logs.txt").write_text(
        "simple-compute-market-bob-storefront-1 | sqlite3.OperationalError: "
        "unable to open database file\n",
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "test-run",
                "mode": "continue",
                "status": "failed",
                "phase_file": "test.yaml",
                "output_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    write_jsonl(
        run_dir / "phases.jsonl",
        [
            {
                "id": "role_layer_marker_tests",
                "name": "Role layer marker tests",
                "category": "stack_test",
                "status": "failed",
                "failed_command": "roles_layer_seller",
                "failed_commands": ["roles_layer_seller"],
                "classifiers": [
                    "stale_seller_layer_route",
                    "storefront_volume_ownership",
                ],
                "commands": [
                    {
                        "id": "roles_layer_seller",
                        "exit_code": 1,
                        "timed_out": False,
                        "stdout": "commands/role_layer_marker_tests/roles_layer_seller.stdout.txt",
                        "stderr": "commands/role_layer_marker_tests/roles_layer_seller.stderr.txt",
                        "meta": "commands/role_layer_marker_tests/roles_layer_seller.meta.json",
                    }
                ],
            }
        ],
    )
    write_jsonl(
        run_dir / "collectors.jsonl",
        [
            {
                "id": "compose_logs",
                "reason": "phase_failed:role_layer_marker_tests",
                "output": "docker/compose-logs.txt",
            }
        ],
    )

    candidates = IssuePacketGenerator(run_dir).generate()

    assert [candidate.fingerprint for candidate in candidates] == [
        "storefront-volume-ownership"
    ]
    assert "docker/compose-logs.txt" in candidates[0].evidence


def test_issue_generator_marks_root_service_test_failure_ready_to_file(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_run(
        run_dir,
        phase_id="root_service_tests",
        command_id="make_test",
        stderr_text="make test failed",
        classifiers=[],
    )

    candidates = IssuePacketGenerator(run_dir).generate()
    candidate_json = json.loads(
        (run_dir / "issue-candidates" / "candidates.jsonl")
        .read_text(encoding="utf-8")
        .strip()
    )

    assert [candidate.fingerprint for candidate in candidates] == [
        "root-service-tests-make-test"
    ]
    assert candidates[0].state == "ready_to_file"
    assert candidates[0].confidence == "high"
    assert candidate_json["state"] == "ready_to_file"
    assert candidate_json["confidence"] == "high"
    assert candidate_json["state_reason"]


def test_legacy_issue_candidate_json_keeps_historical_seventeen_key_contract(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    body_file = run_dir / "issue-candidates" / "legacy.md"
    body_file.parent.mkdir(parents=True)
    body_file.write_text("# Legacy\n", encoding="utf-8")
    candidate = IssueCandidate(
        fingerprint="legacy-fingerprint",
        title="Legacy candidate",
        labels=("bug",),
        classification="runtime",
        phase="legacy-phase",
        body_file=body_file,
        evidence=("manifest.json",),
        state="ready_to_file",
        confidence="high",
        state_reason="Historical legacy readiness.",
    )

    assert set(candidate.to_json(run_dir)) == {
        "fingerprint",
        "title",
        "labels",
        "classification",
        "phase",
        "body_file",
        "evidence",
        "state",
        "confidence",
        "state_reason",
        "working_branch",
        "observed_ref",
        "scenario_id",
        "scenario_fingerprint",
        "run_id",
        "destination_repo",
        "lifecycle_state",
    }


def test_issue_create_runs_gh_from_repo_root(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    repo_root = tmp_path / "repo"
    run_dir.mkdir(mode=0o700)
    repo_root.mkdir()
    write_candidate(run_dir)
    calls = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        text: bool,
        cwd: Path,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, "check": check, "text": text, "cwd": cwd})
        if command[:3] == ["gh", "issue", "list"]:
            return subprocess.CompletedProcess(command, 0, stdout="[]")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", fake_run)

    code = IssueRepository(
        run_dir, repo_root=repo_root, policy_root=POLICY_ROOT
    ).create("fingerprint", dry_run=False)

    assert code == 0
    assert calls[0]["command"][:3] == ["gh", "issue", "list"]
    assert calls[0]["command"][calls[0]["command"].index("--state") + 1] == "open"
    assert (
        calls[0]["command"][calls[0]["command"].index("--search") + 1]
        == "fingerprint in:title"
    )
    assert calls[1]["command"][:3] == ["gh", "issue", "create"]
    assert calls[1]["cwd"] == repo_root


def test_issue_create_blocks_non_ready_candidate_without_force(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    repo_root = tmp_path / "repo"
    run_dir.mkdir()
    repo_root.mkdir()
    write_candidate(run_dir)
    candidate_path = run_dir / "issue-candidates" / "candidates.jsonl"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["state"] = "needs_targeted_repro"
    candidate_path.write_text(json.dumps(candidate) + "\n", encoding="utf-8")

    def fake_run(
        *args, **kwargs
    ) -> subprocess.CompletedProcess[str]:  # pragma: no cover
        raise AssertionError("non-ready issue should not call gh")

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", fake_run)

    code = IssueRepository(run_dir, repo_root=repo_root).create(
        "fingerprint", dry_run=True
    )

    assert code == 2


def test_issue_create_force_allows_non_ready_candidate_dry_run(
    tmp_path: Path, capsys
) -> None:
    run_dir = tmp_path / "run"
    repo_root = tmp_path / "repo"
    run_dir.mkdir()
    repo_root.mkdir()
    write_candidate(run_dir)
    candidate_path = run_dir / "issue-candidates" / "candidates.jsonl"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["state"] = "needs_targeted_repro"
    candidate_path.write_text(json.dumps(candidate) + "\n", encoding="utf-8")

    code = IssueRepository(run_dir, repo_root=repo_root).create(
        "fingerprint", dry_run=True, force=True
    )

    assert code == 0
    assert "--body-file" in capsys.readouterr().out


def test_issue_create_skips_duplicate_issue(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    run_dir = tmp_path / "run"
    repo_root = tmp_path / "repo"
    run_dir.mkdir()
    repo_root.mkdir()
    write_candidate(run_dir)
    calls = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        text: bool,
        cwd: Path,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[:3] == ["gh", "issue", "list"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout='[{"number":1,"title":"Candidate","state":"OPEN","url":"https://example.test/1"}]',
            )
        raise AssertionError("duplicate should skip gh issue create")

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", fake_run)

    code = IssueRepository(
        run_dir, repo_root=repo_root, policy_root=POLICY_ROOT
    ).create("fingerprint", dry_run=False)

    assert code == 0
    assert len(calls) == 1
    assert calls[0][calls[0].index("--state") + 1] == "open"
    assert "duplicate issue exists" in capsys.readouterr().out


def test_issue_create_blocks_unredacted_body_before_gh(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    run_dir = tmp_path / "run"
    repo_root = tmp_path / "repo"
    run_dir.mkdir()
    repo_root.mkdir()
    config_dir = repo_root / "tools" / "issue-discovery" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "redactions.yaml").write_text(
        "\n".join(
            [
                "schema_version: 1",
                "patterns:",
                "  - id: admin_key",
                '    regex: "(?i)((?:x-admin-key|admin[_-]?key)\\\\s*[:=]\\\\s*)[^\\\\s]+"',
                "    replacement: '\\\\1<redacted-admin-key>'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    write_candidate(run_dir)
    (run_dir / "issue-candidates" / "candidate.md").write_text(
        "# Candidate\n\nadmin_key=secret-value\n",
        encoding="utf-8",
    )

    def fake_run(
        *args, **kwargs
    ) -> subprocess.CompletedProcess[str]:  # pragma: no cover
        raise AssertionError("unredacted issue should not call gh")

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", fake_run)

    code = IssueRepository(run_dir, repo_root=repo_root).create(
        "fingerprint", dry_run=False
    )

    assert code == 2
    assert "unredacted data" in capsys.readouterr().out


def test_legacy_issue_create_rejects_capacity_v2_before_force_dry_run_or_subprocess(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run"
    repo_root = tmp_path / "repo"
    run_dir.mkdir()
    repo_root.mkdir()
    write_capacity_v2_candidate(run_dir)

    def forbidden_run(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        raise AssertionError("capacity v2 must not reach subprocess")

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", forbidden_run)
    repository = IssueRepository(run_dir, repo_root=repo_root)

    assert repository.create("finding-001", dry_run=False) == 2
    assert repository.create("finding-001", dry_run=True) == 2
    assert repository.create("finding-001", dry_run=True, force=True) == 2


def test_legacy_fix_and_transition_reject_capacity_v2_without_writes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run"
    repo_root = tmp_path / "repo"
    run_dir.mkdir()
    repo_root.mkdir()
    write_capacity_v2_candidate(run_dir)
    before = {
        path.relative_to(run_dir): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }

    def forbidden_run(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        raise AssertionError("capacity v2 must not reach subprocess")

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", forbidden_run)
    repository = IssueRepository(run_dir, repo_root=repo_root)

    with pytest.raises(ValueError, match="guarded publication"):
        repository.propose_fix(
            "finding-001",
            "fix/capacity-" + "b" * 64,
        )
    with pytest.raises(ValueError, match="guarded publication"):
        repository.transition("finding-001", "triaged", "must not append")

    after = {
        path.relative_to(run_dir): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_issue_repository_regeneration_preserves_explicit_repo_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    repo_root = tmp_path / "repo"
    run_dir.mkdir()
    repo_root.mkdir()
    observed_roots: list[Path | None] = []

    def fake_generate(
        generator: IssuePacketGenerator,
        *,
        secure_capacity: bool,
        authority: object | None = None,
    ) -> list[IssueCandidate]:
        assert secure_capacity is False
        assert authority is None
        observed_roots.append(generator.repo_root)
        body_file = run_dir / "issue-candidates" / "candidate.md"
        body_file.parent.mkdir(parents=True)
        body_file.write_text("# Candidate\n", encoding="utf-8")
        return [
            IssueCandidate(
                fingerprint="fingerprint",
                title="Candidate",
                labels=("bug",),
                classification="test",
                phase="phase",
                body_file=body_file,
                evidence=(),
                state="ready_to_file",
                confidence="high",
                state_reason="Regenerated for repository read.",
            )
        ]

    monkeypatch.setattr(IssuePacketGenerator, "_generate", fake_generate)

    candidates = IssueRepository(run_dir, repo_root=repo_root).list()

    assert candidates[0]["fingerprint"] == "fingerprint"
    assert observed_roots == [repo_root.resolve()]


def test_lock_only_private_run_remains_legacy_for_list_and_body_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    lock_path = run_dir / ".capacity-finding-ingest.lock"
    lock_path.write_bytes(b"")
    lock_path.chmod(0o600)
    write_candidate(run_dir)

    monkeypatch.setattr(
        IssuePacketGenerator,
        "_generate",
        lambda *args, **kwargs: pytest.fail(
            "an existing lock-only legacy packet must not regenerate"
        ),
    )
    repository = IssueRepository(run_dir, repo_root=tmp_path)

    assert [candidate["fingerprint"] for candidate in repository.list()] == [
        "fingerprint"
    ]
    selected = repository.get("fingerprint")
    assert selected["fingerprint"] == "fingerprint"
    assert "candidate_kind" not in selected
    assert repository.body_path("fingerprint") == (
        run_dir / "issue-candidates" / "candidate.md"
    )
    assert repository.read_body("fingerprint") == "# Candidate\n"
    assert lock_path.stat().st_mode & 0o777 == 0o600


def test_v2_marker_creation_race_never_leaves_permissive_candidate_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from issue_discovery.capacity_findings import capacity_finding_ingest_lock

    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    write_run(
        run_dir,
        stderr_text="root service tests failed",
        classifiers=[],
        phase_id="root_service_tests",
        command_id="make_test",
    )
    original_generate = IssuePacketGenerator._generate
    legacy_selected = threading.Event()
    release_legacy = threading.Event()
    writer_attempted = threading.Event()
    writer_acquired = threading.Event()
    listed: list[dict[str, Any]] = []
    errors: list[BaseException] = []

    def pause_after_legacy_selection(
        generator: IssuePacketGenerator,
        *,
        secure_capacity: bool,
        authority: object | None = None,
    ) -> list[IssueCandidate]:
        if not secure_capacity:
            legacy_selected.set()
            if not release_legacy.wait(timeout=5):
                raise AssertionError("legacy selection was not released")
        return original_generate(
            generator,
            secure_capacity=secure_capacity,
            authority=authority,
        )

    monkeypatch.setattr(
        IssuePacketGenerator,
        "_generate",
        pause_after_legacy_selection,
    )

    def list_legacy_run() -> None:
        try:
            listed.extend(IssueRepository(run_dir, repo_root=tmp_path).list())
        except BaseException as error:  # pragma: no cover - asserted below
            errors.append(error)

    marker_path = run_dir / "capacity-finding-index.jsonl"

    def begin_v2_ingest() -> None:
        writer_attempted.set()
        try:
            with capacity_finding_ingest_lock(run_dir):
                writer_acquired.set()
                marker_path.write_bytes(b"")
                marker_path.chmod(0o600)
        except BaseException as error:  # pragma: no cover - asserted below
            errors.append(error)

    previous_umask = os.umask(0o022)
    reader = threading.Thread(target=list_legacy_run)
    writer = threading.Thread(target=begin_v2_ingest)
    try:
        reader.start()
        assert legacy_selected.wait(timeout=2)
        writer.start()
        assert writer_attempted.wait(timeout=2)
        assert not writer_acquired.wait(timeout=0.2)
        release_legacy.set()
        reader.join(timeout=5)
        writer.join(timeout=5)
    finally:
        release_legacy.set()
        reader.join(timeout=5)
        if writer.ident is not None:
            writer.join(timeout=5)
        os.umask(previous_umask)

    assert not reader.is_alive()
    assert not writer.is_alive()
    assert errors == []
    assert [candidate["fingerprint"] for candidate in listed] == [
        "root-service-tests-make-test"
    ]
    assert writer_acquired.is_set()
    assert marker_path.exists()
    issue_dir = run_dir / "issue-candidates"
    assert issue_dir.stat().st_mode & 0o777 == 0o700
    for path in issue_dir.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600


def test_legacy_capacity_v1_transition_still_appends_lifecycle(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    repo_root = tmp_path / "repo"
    run_dir.mkdir()
    repo_root.mkdir()
    issue_dir = run_dir / "issue-candidates"
    issue_dir.mkdir()
    write_jsonl(
        issue_dir / "candidates.jsonl",
        [
            {
                "fingerprint": "capacity-legacy",
                "title": "Legacy capacity occurrence",
                "labels": ["bug"],
                "classification": "public-harness",
                "phase": "provisioning",
                "body_file": "issue-candidates/capacity-legacy.md",
                "evidence": [],
                "state": "ready_to_file",
                "lifecycle_state": "detected",
                "scenario_id": "b1-s1-g1",
                "scenario_fingerprint": "scenario-legacy",
                "run_id": "run-legacy",
            }
        ],
    )
    finding = {
        "finding_id": "finding-legacy",
        "fingerprint": "capacity-legacy",
        "destination_repo": "simple-compute-market",
        "scenario_id": "b1-s1-g1",
        "scenario_fingerprint": "scenario-legacy",
        "observed": {
            "run_id": "run-legacy",
            "stage": "b1-s1-g1",
            "working_branch": "feat/issue-discovery-harness",
            "observed_ref": "a" * 40,
        },
    }
    write_jsonl(run_dir / "capacity-findings.jsonl", [finding])

    IssueRepository(run_dir, repo_root=repo_root).transition(
        "capacity-legacy",
        "triaged",
        "legacy compatibility",
    )

    event = json.loads((run_dir / "issue-lifecycle.jsonl").read_text(encoding="utf-8"))
    assert event["schema_version"] == 1
    assert event["finding_id"] == "finding-legacy"
    assert event["state"] == "triaged"
    assert event["detail"] == "legacy compatibility"


def test_legacy_mutation_rejects_capacity_v2_index_before_packet_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    repo_root = tmp_path / "repo"
    run_dir.mkdir(mode=0o700)
    repo_root.mkdir()
    fingerprint = "capacity-" + "b" * 64
    write_private_jsonl(
        run_dir / "capacity-finding-index.jsonl",
        [
            {
                "candidate_kind": "capacity-finding-v2",
                "finding_id": "finding-001",
                "fingerprint": fingerprint,
            }
        ],
    )
    (run_dir / ".capacity-finding-ingest.lock").touch(mode=0o600)
    before = {
        path.relative_to(run_dir): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }

    monkeypatch.setattr(
        "issue_discovery.issues.IssuePacketGenerator.generate",
        lambda self: pytest.fail("legacy mutation generated v2 packets"),
    )
    monkeypatch.setattr(
        "issue_discovery.issues.subprocess.run",
        lambda *args, **kwargs: pytest.fail("legacy mutation reached subprocess"),
    )
    repository = IssueRepository(run_dir, repo_root=repo_root)

    assert repository.create("finding-001", dry_run=True, force=True) == 2
    with pytest.raises(ValueError, match="guarded publication"):
        repository.propose_fix("finding-001", f"fix/{fingerprint}")
    with pytest.raises(ValueError, match="guarded publication"):
        repository.transition("finding-001", "triaged", "must not append")

    assert not (run_dir / "issue-candidates").exists()
    after = {
        path.relative_to(run_dir): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_capacity_v2_packets_preserve_same_defect_occurrences_and_create_once_bodies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    finding_ids = ("finding-001", "finding-002")
    fingerprint = "capacity-" + "b" * 64
    _, indexes, body_bytes = write_capacity_v2_packet_run(
        run_dir,
        finding_ids=finding_ids,
    )
    body_root = run_dir / "capacity-finding-bodies"
    patch_capacity_v2_packet_validation(monkeypatch, indexes)

    candidates = IssuePacketGenerator(
        run_dir,
        repo_root=POLICY_ROOT,
    ).generate()

    assert [candidate.candidate_id for candidate in candidates] == list(finding_ids)
    assert {candidate.fingerprint for candidate in candidates} == {fingerprint}
    assert {
        candidate.body_file.relative_to(run_dir).as_posix() for candidate in candidates
    } == {f"capacity-finding-bodies/{finding_id}.md" for finding_id in finding_ids}
    for finding_id in finding_ids:
        body_path = body_root / f"{finding_id}.md"
        assert body_path.read_bytes() == body_bytes[finding_id]
        assert body_path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="ambiguous"):
        IssueRepository(run_dir, repo_root=POLICY_ROOT).get(fingerprint)
    assert (
        IssueRepository(run_dir, repo_root=POLICY_ROOT).get("finding-002")["finding_id"]
        == "finding-002"
    )


def test_mixed_v2_run_authenticates_legacy_body_but_keeps_v2_mutations_guarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    _, indexes, _ = write_capacity_v2_packet_run(
        run_dir,
        finding_ids=("finding-001",),
    )
    patch_capacity_v2_packet_validation(monkeypatch, indexes)
    command_dir = run_dir / "commands" / "root_service_tests"
    command_dir.mkdir(parents=True)
    (command_dir / "make_test.stdout.txt").write_text("", encoding="utf-8")
    (command_dir / "make_test.stderr.txt").write_text(
        "root service tests failed\n",
        encoding="utf-8",
    )
    (command_dir / "make_test.meta.json").write_text(
        json.dumps({"exit_code": 1, "timed_out": False}),
        encoding="utf-8",
    )
    write_jsonl(
        run_dir / "phases.jsonl",
        [
            {
                "id": "root_service_tests",
                "name": "Root service tests",
                "category": "stack_test",
                "status": "failed",
                "failed_command": "make_test",
                "failed_commands": ["make_test"],
                "classifiers": [],
                "commands": [
                    {
                        "id": "make_test",
                        "exit_code": 1,
                        "timed_out": False,
                        "stdout": "commands/root_service_tests/make_test.stdout.txt",
                        "stderr": "commands/root_service_tests/make_test.stderr.txt",
                        "meta": "commands/root_service_tests/make_test.meta.json",
                    }
                ],
            }
        ],
    )
    write_jsonl(run_dir / "collectors.jsonl", [])
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "mode": "continue",
            "status": "failed",
            "phase_file": "test.yaml",
            "output_dir": str(run_dir),
        }
    )
    write_private_json(manifest_path, manifest)
    legacy_fingerprint = "root-service-tests-make-test"
    repository = IssueRepository(run_dir, repo_root=POLICY_ROOT)

    generated = IssuePacketGenerator(run_dir, repo_root=POLICY_ROOT).generate()
    legacy = next(
        candidate
        for candidate in generated
        if candidate.fingerprint == legacy_fingerprint
    )
    expected_body = legacy.body_file.read_text(encoding="utf-8")
    assert repository.get(legacy_fingerprint)["fingerprint"] == legacy_fingerprint

    from issue_discovery.capacity_findings import (
        read_capacity_finding_private_file,
    )

    authenticated_reads: list[tuple[Path, Path, object | None]] = []

    def observed_private_read(
        path: Path,
        *,
        root: Path,
        authority: object | None = None,
    ) -> bytes:
        authenticated_reads.append((path, root, authority))
        return read_capacity_finding_private_file(
            path,
            root=root,
            authority=authority,
        )

    monkeypatch.setattr(
        "issue_discovery.capacity_findings.read_capacity_finding_private_file",
        observed_private_read,
    )
    assert repository.read_body(legacy_fingerprint) == expected_body
    assert any(
        path == legacy.body_file and root == run_dir and authority is not None
        for path, root, authority in authenticated_reads
    )
    with pytest.raises(ValueError, match="authenticated snapshot reads"):
        repository.body_path("finding-001")
    assert repository.create("finding-001", dry_run=True, force=True) == 2
    with pytest.raises(ValueError, match="guarded publication"):
        repository.propose_fix(
            "finding-001",
            "fix/capacity-" + "b" * 64,
        )
    with pytest.raises(ValueError, match="guarded publication"):
        repository.transition("finding-001", "triaged", "must not append")

    subprocess_calls: list[dict[str, object]] = []
    body_swapped = False

    def fake_run(
        command: list[str],
        *,
        check: bool,
        text: bool,
        cwd: Path,
        capture_output: bool = False,
        input: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal body_swapped
        subprocess_calls.append(
            {
                "command": command,
                "cwd": cwd,
                "input": input,
            }
        )
        if command[:3] == ["gh", "issue", "list"]:
            if not body_swapped:
                body_swapped = True
                legacy.body_file.rename(
                    legacy.body_file.with_name("legacy-body-held.md")
                )
                legacy.body_file.write_text(
                    "# Untrusted pathname replacement\n",
                    encoding="utf-8",
                )
                legacy.body_file.chmod(0o600)
            return subprocess.CompletedProcess(command, 0, stdout="[]")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="https://example.invalid/issues/1\n",
        )

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", fake_run)

    assert repository.create(legacy_fingerprint, dry_run=False, force=True) == 0
    create_call = next(
        call
        for call in subprocess_calls
        if call["command"][:3] == ["gh", "issue", "create"]
    )
    create_command = create_call["command"]
    assert isinstance(create_command, list)
    assert create_command[create_command.index("--body-file") + 1] == "-"
    assert create_call["input"] == expected_body
    assert str(legacy.body_file) not in create_command


def test_capacity_v2_packet_replay_is_atomic_deterministic_and_regenerated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    _, indexes, _ = write_capacity_v2_packet_run(
        run_dir,
        finding_ids=("finding-001",),
    )
    patch_capacity_v2_packet_validation(monkeypatch, indexes)
    generator = IssuePacketGenerator(run_dir, repo_root=POLICY_ROOT)

    first = generator.generate()
    candidates_path = run_dir / "issue-candidates" / "candidates.jsonl"
    first_bytes = candidates_path.read_bytes()
    second = generator.generate()

    assert [candidate.finding_id for candidate in first] == ["finding-001"]
    assert [candidate.finding_id for candidate in second] == ["finding-001"]
    assert candidates_path.read_bytes() == first_bytes
    assert (run_dir / "issue-candidates").stat().st_mode & 0o777 == 0o700
    assert candidates_path.stat().st_mode & 0o777 == 0o600
    assert candidates_path.stat().st_nlink == 1

    write_private_jsonl(
        candidates_path,
        [{"candidate_kind": "stale-but-owner-only"}],
    )
    replayed = IssueRepository(run_dir, repo_root=POLICY_ROOT).list()

    assert [candidate["finding_id"] for candidate in replayed] == ["finding-001"]
    assert candidates_path.read_bytes() == first_bytes


@pytest.mark.parametrize("output_kind", ("candidate-body", "candidate-ledger"))
def test_capacity_v2_packet_replay_recovers_post_link_output_temporary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output_kind: str,
) -> None:
    run_dir = tmp_path / "run"
    _, indexes, _ = write_capacity_v2_packet_run(
        run_dir,
        finding_ids=("finding-001",),
    )
    legacy_fingerprint = add_failed_phase_to_capacity_v2_run(run_dir)
    patch_capacity_v2_packet_validation(monkeypatch, indexes)
    generator = IssuePacketGenerator(run_dir, repo_root=POLICY_ROOT)
    generator.generate()
    if output_kind == "candidate-body":
        target = run_dir / "issue-candidates" / f"{legacy_fingerprint}.md"
    else:
        target = run_dir / "issue-candidates" / "candidates.jsonl"
    expected = target.read_bytes()
    temporary = target.with_name(
        f".{target.name}.123.{'7' * 24}.tmp"
    )
    os.link(target, temporary)
    assert target.stat().st_nlink == 2

    generator.generate()

    assert not temporary.exists()
    assert target.stat().st_nlink == 1
    assert target.read_bytes() == expected


def test_capacity_v2_packet_replay_rejects_ledger_change_before_baseline_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    sources, indexes, _ = write_capacity_v2_packet_run(
        run_dir,
        finding_ids=("finding-001",),
    )
    patch_capacity_v2_packet_validation(monkeypatch, indexes)
    from issue_discovery import capacity_findings

    original_snapshot = (
        capacity_findings.snapshot_capacity_finding_replay_authority
    )
    mutated_sources = [dict(source) for source in sources]
    mutated_sources[0]["summary"] = "Changed immediately before replay snapshot"
    mutated = False

    def mutate_then_snapshot(*args: object, **kwargs: object) -> object:
        nonlocal mutated
        if not mutated:
            mutated = True
            write_private_jsonl(
                run_dir / "capacity-findings.jsonl",
                mutated_sources,
            )
        return original_snapshot(*args, **kwargs)

    monkeypatch.setattr(
        capacity_findings,
        "snapshot_capacity_finding_replay_authority",
        mutate_then_snapshot,
    )

    with pytest.raises(
        ValueError,
        match="replay authority changed before output",
    ):
        IssuePacketGenerator(run_dir, repo_root=POLICY_ROOT).generate()

    assert not (run_dir / "issue-candidates").exists()
    assert (
        run_dir / "capacity-findings.jsonl"
    ).read_bytes() == b"".join(
        canonical_json_bytes(source) for source in mutated_sources
    )


@pytest.mark.parametrize("mutation_target", ("source-artifact", "evidence"))
def test_capacity_v2_packet_replay_rejects_input_change_after_final_derivation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation_target: str,
) -> None:
    run_dir = tmp_path / "run"
    _, indexes, _ = write_capacity_v2_packet_run(
        run_dir,
        finding_ids=("finding-001",),
    )
    patch_capacity_v2_packet_validation(monkeypatch, indexes)
    generator = IssuePacketGenerator(run_dir, repo_root=POLICY_ROOT)
    original_derivation = generator._from_capacity_findings
    derivations = 0

    def derive_then_mutate(
        findings: list[dict[str, Any]],
        derived_indexes: list[dict[str, Any]],
    ) -> list[IssueCandidate]:
        nonlocal derivations
        candidates = original_derivation(findings, derived_indexes)
        derivations += 1
        if derivations == 2:
            if mutation_target == "source-artifact":
                source_path = (
                    run_dir / "capacity-findings" / "finding-001.json"
                )
                source = json.loads(source_path.read_text(encoding="utf-8"))
                source["summary"] = "Changed after final candidate derivation"
                write_private_json(source_path, source)
            else:
                evidence_path = run_dir / "evidence" / "result.json"
                evidence_path.write_bytes(b'{"changed":true}\n')
                evidence_path.chmod(0o600)
        return candidates

    monkeypatch.setattr(generator, "_from_capacity_findings", derive_then_mutate)

    with pytest.raises(
        CapacityValidationError,
        match="replay authority changed before output",
    ):
        generator.generate()

    assert not (run_dir / "issue-candidates").exists()


def test_capacity_v2_packet_replay_requires_existing_ingest_lock_without_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    _, indexes, _ = write_capacity_v2_packet_run(
        run_dir,
        finding_ids=("finding-001",),
    )
    patch_capacity_v2_packet_validation(monkeypatch, indexes)
    lock_path = run_dir / ".capacity-finding-ingest.lock"
    lock_path.unlink()
    before = {
        path.relative_to(run_dir): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }

    with pytest.raises(RuntimeError, match="cannot open existing finding ingest lock"):
        IssuePacketGenerator(run_dir, repo_root=POLICY_ROOT).generate()

    assert not lock_path.exists()
    assert not (run_dir / "issue-candidates").exists()
    assert {
        path.relative_to(run_dir): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    } == before


@pytest.mark.parametrize(
    ("damage", "message"),
    (
        ("replacement", "body snapshot does not match"),
        ("symlink", "cannot open private finding file"),
    ),
)
def test_capacity_issue_body_read_rejects_post_selection_pathname_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
    message: str,
) -> None:
    run_dir = tmp_path / "run"
    _, indexes, body_bytes = write_capacity_v2_packet_run(
        run_dir,
        finding_ids=("finding-001",),
    )
    patch_capacity_v2_packet_validation(monkeypatch, indexes)
    repository = IssueRepository(run_dir, repo_root=POLICY_ROOT)
    body_path = run_dir / "capacity-finding-bodies" / "finding-001.md"
    untrusted = b"# Untrusted replacement\n"
    original_get = repository._get_under_selection
    swapped = False

    def get_then_swap(selector: str, selection: object) -> dict[str, Any]:
        nonlocal swapped
        candidate = original_get(selector, selection)
        if not swapped:
            swapped = True
            if damage == "replacement":
                body_path.rename(body_path.with_name("finding-001-held.md"))
                body_path.write_bytes(untrusted)
                body_path.chmod(0o600)
            else:
                body_path.unlink()
                outside = tmp_path / "untrusted-body.md"
                outside.write_bytes(untrusted)
                outside.chmod(0o600)
                body_path.symlink_to(outside)
        return candidate

    monkeypatch.setattr(repository, "_get_under_selection", get_then_swap)

    with pytest.raises((RuntimeError, ValueError), match=message):
        repository.read_body("finding-001")

    assert body_bytes["finding-001"] != untrusted


@pytest.mark.parametrize(
    ("ledger_name", "damage"),
    [
        ("capacity-findings.jsonl", "wrong-mode"),
        ("capacity-finding-index.jsonl", "wrong-mode"),
        ("capacity-findings.jsonl", "hardlink"),
        ("capacity-finding-index.jsonl", "hardlink"),
    ],
)
def test_capacity_v2_packet_replay_rejects_unsafe_ledgers_without_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ledger_name: str,
    damage: str,
) -> None:
    run_dir = tmp_path / "run"
    _, indexes, _ = write_capacity_v2_packet_run(
        run_dir,
        finding_ids=("finding-001",),
    )
    patch_capacity_v2_packet_validation(monkeypatch, indexes)
    ledger = run_dir / ledger_name
    before = ledger.read_bytes()
    if damage == "wrong-mode":
        ledger.chmod(0o640)
    else:
        os.link(ledger, tmp_path / f"{ledger_name}.second-link")

    with pytest.raises(RuntimeError, match="mode 0600|exactly one hard link"):
        IssuePacketGenerator(run_dir, repo_root=POLICY_ROOT).generate()

    assert ledger.read_bytes() == before
    assert not (run_dir / "issue-candidates").exists()


@pytest.mark.parametrize("damage", ["wrong-mode", "symlink"])
def test_capacity_v2_packet_replay_rejects_unsafe_candidate_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    run_dir = tmp_path / "run"
    _, indexes, _ = write_capacity_v2_packet_run(
        run_dir,
        finding_ids=("finding-001",),
    )
    patch_capacity_v2_packet_validation(monkeypatch, indexes)
    issue_dir = run_dir / "issue-candidates"
    if damage == "wrong-mode":
        issue_dir.mkdir(mode=0o755)
    else:
        outside = tmp_path / "outside-candidates"
        outside.mkdir()
        issue_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="mode 0700|non-symlink directory"):
        IssuePacketGenerator(run_dir, repo_root=POLICY_ROOT).generate()


@pytest.mark.parametrize(
    "directory_name",
    [
        "capacity-findings",
        "capacity-finding-index",
        "capacity-finding-bodies",
    ],
)
def test_capacity_v2_packet_replay_requires_owner_only_artifact_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    directory_name: str,
) -> None:
    run_dir = tmp_path / "run"
    _, indexes, _ = write_capacity_v2_packet_run(
        run_dir,
        finding_ids=("finding-001",),
    )
    patch_capacity_v2_packet_validation(monkeypatch, indexes)
    (run_dir / directory_name).chmod(0o750)

    with pytest.raises(RuntimeError, match="mode 0700"):
        IssuePacketGenerator(run_dir, repo_root=POLICY_ROOT).generate()

    assert not (run_dir / "issue-candidates").exists()


@pytest.mark.parametrize(
    ("directory_name", "suffix"),
    (
        ("capacity-findings", ".json"),
        ("capacity-finding-index", ".json"),
        ("capacity-finding-bodies", ".md"),
    ),
)
@pytest.mark.parametrize(
    "damage",
    ("orphan-regular", "orphan-symlink", "missing-ledger-id"),
)
def test_capacity_v2_packet_replay_requires_exact_closed_artifact_inventories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    directory_name: str,
    suffix: str,
    damage: str,
) -> None:
    run_dir = tmp_path / "run"
    _, indexes, _ = write_capacity_v2_packet_run(
        run_dir,
        finding_ids=("finding-001",),
    )
    patch_capacity_v2_packet_validation(monkeypatch, indexes)
    directory = run_dir / directory_name
    if damage == "missing-ledger-id":
        (directory / f"finding-001{suffix}").unlink()
    else:
        orphan = directory / f"orphan-001{suffix}"
        if damage == "orphan-regular":
            orphan.write_bytes(b"owner-only orphan")
            orphan.chmod(0o600)
        else:
            outside = tmp_path / f"{directory_name}-outside{suffix}"
            outside.write_bytes(b"outside artifact")
            outside.chmod(0o600)
            orphan.symlink_to(outside)

    with pytest.raises(
        RuntimeError,
        match="artifact inventory|cannot open private finding file",
    ):
        IssuePacketGenerator(run_dir, repo_root=POLICY_ROOT).generate()

    assert not (run_dir / "issue-candidates").exists()


@pytest.mark.parametrize("damage", ["wrong-mode", "hardlink", "symlink"])
def test_capacity_v2_packet_replay_rejects_unsafe_candidate_file_without_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    run_dir = tmp_path / "run"
    _, indexes, _ = write_capacity_v2_packet_run(
        run_dir,
        finding_ids=("finding-001",),
    )
    patch_capacity_v2_packet_validation(monkeypatch, indexes)
    generator = IssuePacketGenerator(run_dir, repo_root=POLICY_ROOT)
    generator.generate()
    candidates_path = run_dir / "issue-candidates" / "candidates.jsonl"
    original = candidates_path.read_bytes()
    if damage == "wrong-mode":
        candidates_path.chmod(0o640)
    elif damage == "hardlink":
        os.link(candidates_path, tmp_path / "candidate-second-link")
    else:
        candidates_path.unlink()
        target = tmp_path / "candidate-target"
        target.write_bytes(original)
        candidates_path.symlink_to(target)

    with pytest.raises(RuntimeError, match="mode 0600|hard link|cannot open"):
        generator.generate()

    assert candidates_path.read_bytes() == original


def test_capacity_v2_packet_replay_requires_canonical_owner_only_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    _, indexes, _ = write_capacity_v2_packet_run(
        run_dir,
        finding_ids=("finding-001",),
    )
    patch_capacity_v2_packet_validation(monkeypatch, indexes)
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps({"run_id": "capacity-run-001"}, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="canonical JSON"):
        IssuePacketGenerator(run_dir, repo_root=POLICY_ROOT).generate()

    assert not (run_dir / "issue-candidates").exists()


@pytest.mark.parametrize(
    "damage",
    ["missing", "wrong-mode", "duplicate-detected", "changed-detected"],
)
def test_capacity_v2_packet_replay_requires_exact_detected_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    run_dir = tmp_path / "run"
    _, indexes, _ = write_capacity_v2_packet_run(
        run_dir,
        finding_ids=("finding-001",),
    )
    patch_capacity_v2_packet_validation(monkeypatch, indexes)
    lifecycle_path = run_dir / "issue-lifecycle.jsonl"
    if damage == "missing":
        lifecycle_path.unlink()
    elif damage == "wrong-mode":
        lifecycle_path.chmod(0o640)
    else:
        events = [
            json.loads(line)
            for line in lifecycle_path.read_text(encoding="utf-8").splitlines()
        ]
        if damage == "duplicate-detected":
            events.append(dict(events[0]))
        else:
            events[0]["recorded_at"] = "2026-07-30T12:00:01Z"
        write_private_jsonl(lifecycle_path, events)

    with pytest.raises(
        (RuntimeError, ValueError),
        match=(
            "required capacity ledger is missing|mode 0600|detected lifecycle collision"
        ),
    ):
        IssuePacketGenerator(run_dir, repo_root=POLICY_ROOT).generate()

    assert not (run_dir / "issue-candidates").exists()


def test_capacity_v2_packet_replay_rejects_manifest_index_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    _, indexes, _ = write_capacity_v2_packet_run(
        run_dir,
        finding_ids=("finding-001",),
    )
    patch_capacity_v2_packet_validation(monkeypatch, indexes)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["capacity_findings"] = []
    write_private_json(manifest_path, manifest)

    with pytest.raises(RuntimeError, match="does not exactly project"):
        IssuePacketGenerator(run_dir, repo_root=POLICY_ROOT).generate()

    assert not (run_dir / "issue-candidates" / "candidates.jsonl").exists()


def test_capacity_v2_packet_replay_serializes_on_the_ingest_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from issue_discovery.capacity_findings import capacity_finding_ingest_lock

    run_dir = tmp_path / "run"
    _, indexes, _ = write_capacity_v2_packet_run(
        run_dir,
        finding_ids=("finding-001",),
    )
    patch_capacity_v2_packet_validation(monkeypatch, indexes)
    index = dict(indexes[0])
    entered_loader = threading.Event()
    worker_started = threading.Event()
    errors: list[BaseException] = []

    def observed_loader(*args, **kwargs) -> dict[str, Any]:
        entered_loader.set()
        return dict(index)

    monkeypatch.setattr(
        "issue_discovery.capacity_findings.load_capacity_finding_index_artifacts",
        observed_loader,
    )

    def replay() -> None:
        worker_started.set()
        try:
            IssuePacketGenerator(run_dir, repo_root=POLICY_ROOT).generate()
        except BaseException as error:  # pragma: no cover - asserted below
            errors.append(error)

    with capacity_finding_ingest_lock(run_dir):
        worker = threading.Thread(target=replay)
        worker.start()
        assert worker_started.wait(timeout=2)
        assert not entered_loader.wait(timeout=0.2)

    worker.join(timeout=5)
    assert not worker.is_alive()
    assert entered_loader.is_set()
    assert errors == []
