from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from issue_discovery.capacity import finding_fingerprint
from issue_discovery.issues import (
    CapacityIssuePlanError,
    IssuePacketGenerator,
    IssueRepository,
    plan_capacity_fix_candidate,
    plan_capacity_issues,
)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


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


def capacity_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def capacity_finding(
    *,
    classification: str = "possible-product-defect",
    run_id: str = "example-run-001",
    observed_at: str = "2026-08-02T00:00:00Z",
    public_sha: str = "a" * 40,
    cleanup_proven: bool = True,
) -> dict[str, object]:
    path = (
        capacity_repo_root()
        / "tools"
        / "issue-discovery"
        / "config"
        / "capacity"
        / "findings"
        / "example.json"
    )
    finding = json.loads(path.read_text(encoding="utf-8"))
    finding["classification"] = classification
    finding["occurrence"]["run_id"] = run_id
    finding["occurrence"]["observed_at"] = observed_at
    finding["public_context"]["sha"] = public_sha
    if classification == "harness-defect":
        finding["summary"] = (
            "The substantive buyer session did not own its released action."
        )
        finding["failure"] = {
            "code": "buyer-session-not-retained",
            "location": "role_receipts",
            "stable_evidence_summary": (
                "the substantive buyer session did not own its released action."
            ),
        }
    elif classification == "cleanup-failure":
        finding["summary"] = "Cleanup did not prove the zero-residue baseline."
        finding["failure"] = {
            "code": "cleanup-not-proven",
            "location": "cleanup",
            "stable_evidence_summary": (
                "cleanup did not prove the zero-residue baseline."
            ),
        }
    if cleanup_proven:
        finding["cleanup"] = {
            "attempted": True,
            "status": "succeeded",
            "zero_residue": True,
        }
        finding["publication"] = {"eligible": True, "reason": "cleanup-proven"}
    else:
        finding["cleanup"] = {
            "attempted": True,
            "status": "failed",
            "zero_residue": False,
        }
        finding["publication"] = {"eligible": False, "reason": "cleanup-failed"}
    finding["fingerprint"] = finding_fingerprint(
        scenario_sha256_value=finding["scenario"]["sha256"],
        classification=finding["classification"],
        code=finding["failure"]["code"],
        location=finding["failure"]["location"],
        stable_evidence_summary=finding["failure"]["stable_evidence_summary"],
    )
    return finding


def capacity_evaluation(
    findings: list[dict[str, object]],
    *,
    classification: str | None = None,
) -> dict[str, object]:
    finding = findings[0] if findings else capacity_finding()
    return {
        "schema_version": 1,
        "scenario_id": finding["scenario"]["id"],
        "scenario_sha256": finding["scenario"]["sha256"],
        "termination": finding["occurrence"]["termination"],
        "run": {
            "repository": finding["public_context"]["repository"],
            "branch": finding["public_context"]["branch"],
            "sha": finding["public_context"]["sha"],
            "run_id": finding["occurrence"]["run_id"],
            "observed_at": finding["occurrence"]["observed_at"],
            "timeout_seconds": finding["occurrence"]["timeout_seconds"],
        },
        "classification": classification or finding["classification"],
        "findings": findings,
    }


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


def test_issue_create_runs_gh_from_repo_root(tmp_path: Path, monkeypatch) -> None:
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
        calls.append({"command": command, "check": check, "text": text, "cwd": cwd})
        if command[:3] == ["gh", "issue", "list"]:
            return subprocess.CompletedProcess(command, 0, stdout="[]")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", fake_run)

    code = IssueRepository(run_dir, repo_root=repo_root).create(
        "fingerprint", dry_run=False
    )

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

    code = IssueRepository(run_dir, repo_root=repo_root).create(
        "fingerprint", dry_run=False
    )

    assert code == 0
    assert len(calls) == 1
    assert "--state" not in calls[0]
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


def test_capacity_issue_planner_suppresses_expected_scarcity_before_snapshot_access() -> (
    None
):
    result = plan_capacity_issues(
        capacity_evaluation([], classification="expected-scarcity"),
        [{"malformed": True}],
        capacity_repo_root(),
    )

    assert result == {
        "schema_version": 1,
        "kind": "capacity-issue-decisions",
        "decision": "suppressed",
        "reason": "expected-scarcity",
        "plans": [],
    }


def test_capacity_issue_planner_creates_stable_sanitized_packet() -> None:
    finding = capacity_finding()
    evaluation = capacity_evaluation([finding])

    first = plan_capacity_issues(evaluation, [], capacity_repo_root())
    second = plan_capacity_issues(evaluation, [], capacity_repo_root())

    assert first == second
    plan = first["plans"][0]
    assert plan["action"] == "create"
    assert plan["dry_run"] is True
    assert plan["issue_number"] is None
    assert plan["scope_marker"] in plan["operations"][0]["body"]
    assert plan["occurrence_markers"][0] in plan["operations"][0]["body"]
    assert plan["operations"][0]["labels"] == ["bug", "capacity", "issue-discovery"]
    serialized = json.dumps(first, sort_keys=True)
    assert "internal-infra" not in serialized
    assert "/home/" not in serialized
    assert "executor_ref" not in serialized


def test_capacity_issue_planner_noops_for_recorded_occurrence() -> None:
    finding = capacity_finding()
    evaluation = capacity_evaluation([finding])
    created = plan_capacity_issues(evaluation, [], capacity_repo_root())["plans"][0]
    snapshot = [
        {
            "number": 17,
            "state": "OPEN",
            "body": created["operations"][0]["body"],
            "comments": [],
        }
    ]

    plan = plan_capacity_issues(evaluation, snapshot, capacity_repo_root())["plans"][0]

    assert plan["action"] == "no-op"
    assert plan["issue_number"] == 17
    assert plan["operations"] == []


@pytest.mark.parametrize(
    ("state", "expected_action", "operation_names"),
    [
        ("OPEN", "update", ["comment"]),
        ("CLOSED", "reopen", ["reopen", "comment"]),
    ],
)
def test_capacity_issue_planner_updates_or_reopens_for_new_occurrence(
    state: str,
    expected_action: str,
    operation_names: list[str],
) -> None:
    original = capacity_finding()
    created = plan_capacity_issues(
        capacity_evaluation([original]), [], capacity_repo_root()
    )["plans"][0]
    recurring = capacity_finding(
        run_id="example-run-002",
        observed_at="2026-08-03T00:00:00Z",
        public_sha="b" * 40,
    )
    snapshot = [
        {
            "number": 18,
            "state": state,
            "body": created["operations"][0]["body"],
            "comments": [],
        }
    ]

    plan = plan_capacity_issues(
        capacity_evaluation([recurring]), snapshot, capacity_repo_root()
    )["plans"][0]

    assert plan["action"] == expected_action
    assert plan["scope_marker"] == created["scope_marker"]
    assert plan["occurrence_markers"] != created["occurrence_markers"]
    assert [
        operation["operation"] for operation in plan["operations"]
    ] == operation_names
    assert created["operations"][0]["body"] not in json.dumps(plan["operations"])


def test_capacity_issue_planner_deduplicates_same_occurrence_in_one_evaluation() -> (
    None
):
    finding = capacity_finding()
    plan = plan_capacity_issues(
        capacity_evaluation([finding, dict(finding)]),
        [],
        capacity_repo_root(),
    )["plans"][0]

    assert plan["action"] == "create"
    assert len(plan["occurrence_markers"]) == 1


def test_capacity_issue_planner_merges_same_occurrence_evidence_deterministically() -> (
    None
):
    first = capacity_finding()
    second = json.loads(json.dumps(first))
    second["evidence"].append(
        {
            "kind": "portable-receipt",
            "summary": "A second sanitized assertion confirms the same occurrence.",
        }
    )

    forward = plan_capacity_issues(
        capacity_evaluation([first, second]), [], capacity_repo_root()
    )
    reverse = plan_capacity_issues(
        capacity_evaluation([second, first]), [], capacity_repo_root()
    )

    assert forward == reverse
    assert (
        "A second sanitized assertion" in forward["plans"][0]["operations"][0]["body"]
    )


def test_capacity_issue_planner_rejects_conflicting_same_occurrence() -> None:
    first = capacity_finding()
    second = json.loads(json.dumps(first))
    second["summary"] = "A conflicting presentation of the same occurrence."

    with pytest.raises(CapacityIssuePlanError, match="conflicting findings"):
        plan_capacity_issues(
            capacity_evaluation([first, second]), [], capacity_repo_root()
        )


def test_capacity_issue_scope_remains_stable_across_public_branch_changes() -> None:
    original = capacity_finding()
    created = plan_capacity_issues(
        capacity_evaluation([original]), [], capacity_repo_root()
    )["plans"][0]
    recurring = capacity_finding(
        run_id="example-run-branch-change",
        observed_at="2026-08-04T00:00:00Z",
        public_sha="c" * 40,
    )
    recurring["public_context"]["branch"] = "feat/next-harness-branch"
    snapshot = [
        {
            "number": 23,
            "state": "OPEN",
            "body": created["operations"][0]["body"],
        }
    ]

    plan = plan_capacity_issues(
        capacity_evaluation([recurring]), snapshot, capacity_repo_root()
    )["plans"][0]

    assert plan["action"] == "update"
    assert plan["scope_marker"] == created["scope_marker"]
    assert "feat/next-harness-branch" in plan["operations"][0]["body"]


def test_capacity_issue_planner_ignores_title_only_fingerprint_match() -> None:
    finding = capacity_finding()
    snapshot = [
        {
            "number": 19,
            "state": "OPEN",
            "title": f"unscoped {finding['fingerprint']}",
            "body": "No machine-readable marker.",
        }
    ]

    plan = plan_capacity_issues(
        capacity_evaluation([finding]), snapshot, capacity_repo_root()
    )["plans"][0]

    assert plan["action"] == "create"


def test_capacity_issue_planner_rejects_duplicate_scope_issues() -> None:
    finding = capacity_finding()
    created = plan_capacity_issues(
        capacity_evaluation([finding]), [], capacity_repo_root()
    )["plans"][0]
    scope = created["scope_marker"]
    snapshot = [
        {"number": 20, "state": "OPEN", "body": scope},
        {"number": 21, "state": "CLOSED", "body": scope},
    ]

    with pytest.raises(CapacityIssuePlanError, match="multiple issues"):
        plan_capacity_issues(
            capacity_evaluation([finding]), snapshot, capacity_repo_root()
        )


def test_capacity_issue_planner_rejects_orphan_occurrence_marker() -> None:
    finding = capacity_finding()
    created = plan_capacity_issues(
        capacity_evaluation([finding]), [], capacity_repo_root()
    )["plans"][0]
    recurring = capacity_finding(
        run_id="example-run-002",
        observed_at="2026-08-03T00:00:00Z",
        public_sha="b" * 40,
    )
    snapshot = [
        {
            "number": 22,
            "state": "OPEN",
            "body": created["occurrence_markers"][0],
        }
    ]

    with pytest.raises(CapacityIssuePlanError, match="without its stable scope"):
        plan_capacity_issues(
            capacity_evaluation([recurring]), snapshot, capacity_repo_root()
        )


def test_capacity_issue_planner_withholds_cleanup_failure() -> None:
    finding = capacity_finding(classification="cleanup-failure", cleanup_proven=False)

    result = plan_capacity_issues(
        capacity_evaluation([finding]), [{"malformed": True}], capacity_repo_root()
    )

    assert result["decision"] == "withheld"
    assert result["reason"] == "cleanup-not-proven"
    assert result["plans"][0]["action"] == "withhold"
    assert result["plans"][0]["operations"] == []
    assert result["plans"][0]["withheld_occurrence_markers"]


def test_capacity_fix_candidate_is_exact_draft_and_never_executes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finding = capacity_finding(classification="harness-defect")
    proposal = {
        "schema_version": 1,
        "ownership": "public-harness",
        "summary": "Retain the substantive buyer session through release",
        "paths": [
            "tools/issue-discovery/tests/test_runner.py",
            "tools/issue-discovery/src/issue_discovery/runner.py",
        ],
    }

    def fail_subprocess(*args, **kwargs):
        raise AssertionError("capacity planning must not invoke a subprocess")

    def fail_write(*args, **kwargs):
        raise AssertionError("capacity planning must not write files")

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", fail_subprocess)
    monkeypatch.setattr(Path, "write_text", fail_write)
    candidate = plan_capacity_fix_candidate(
        finding, proposal, capacity_repo_root(), mutation_authorized=False
    )
    ready = plan_capacity_fix_candidate(
        finding, proposal, capacity_repo_root(), mutation_authorized=True
    )

    expected_head = f"fix/{finding['fingerprint']}"
    assert candidate["status"] == "candidate"
    assert candidate["reason"] == "mutation-authority-absent"
    assert ready["status"] == "ready-for-authorized-mutation"
    assert candidate["head"] == ready["head"] == expected_head
    assert candidate["base"] == "feat/issue-discovery-harness-post-pools"
    assert candidate["draft"] is True
    assert candidate["auto_merge"] is False
    assert candidate["executed"] is False
    assert candidate["paths"] == sorted(proposal["paths"])
    command_text = json.dumps(candidate["commands"])
    assert "--draft" in command_text
    assert "auto-merge" not in command_text
    assert "merge" not in [command["purpose"] for command in candidate["commands"]]


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/tools/issue-discovery/tests/test_runner.py",
        "tools/issue-discovery/../secrets.txt",
        r"tools\issue-discovery\tests\test_runner.py",
        "tools/issue-discovery/tests//test_runner.py",
        "tools/issue-discovery/tests/",
        "tools/issue-discovery/tests-evil/test_runner.py",
        "domains/vms/provisioning/product.py",
        "tools/issue-discovery/schemas/unrelated.json",
    ],
)
def test_capacity_fix_candidate_rejects_non_harness_paths(path: str) -> None:
    finding = capacity_finding(classification="harness-defect")
    proposal = {
        "schema_version": 1,
        "ownership": "public-harness",
        "summary": "Retain the substantive buyer session through release",
        "paths": ["tools/issue-discovery/tests/test_runner.py", path],
    }

    with pytest.raises(CapacityIssuePlanError, match="paths|path"):
        plan_capacity_fix_candidate(finding, proposal, capacity_repo_root())


def test_capacity_fix_candidate_rejects_non_harness_finding_and_control_overrides() -> (
    None
):
    product_finding = capacity_finding()
    proposal = {
        "schema_version": 1,
        "ownership": "public-harness",
        "summary": "Do not alter product behavior from the harness",
        "paths": ["tools/issue-discovery/tests/test_runner.py"],
    }
    with pytest.raises(CapacityIssuePlanError, match="harness-defect"):
        plan_capacity_fix_candidate(product_finding, proposal, capacity_repo_root())

    harness_finding = capacity_finding(classification="harness-defect")
    proposal["head"] = "fix/shortened"
    with pytest.raises(CapacityIssuePlanError, match="fields must be exactly"):
        plan_capacity_fix_candidate(harness_finding, proposal, capacity_repo_root())


def test_capacity_fix_candidate_rejects_unproven_cleanup_and_derives_base() -> None:
    proposal = {
        "schema_version": 1,
        "ownership": "public-harness",
        "summary": "Retain the substantive buyer session through release",
        "paths": ["tools/issue-discovery/tests/test_runner.py"],
    }
    cleanup_failed = capacity_finding(
        classification="harness-defect", cleanup_proven=False
    )
    with pytest.raises(CapacityIssuePlanError, match="cleanup-proven"):
        plan_capacity_fix_candidate(cleanup_failed, proposal, capacity_repo_root())

    alternate_base = capacity_finding(classification="harness-defect")
    alternate_base["public_context"]["branch"] = "feat/another-harness-branch"
    plan = plan_capacity_fix_candidate(alternate_base, proposal, capacity_repo_root())
    assert plan["base"] == "feat/another-harness-branch"
