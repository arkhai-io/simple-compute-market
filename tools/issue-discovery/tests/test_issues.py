from __future__ import annotations

import json
import subprocess
from pathlib import Path

from issue_discovery.issues import IssuePacketGenerator, IssueRepository


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
    (run_dir / "commands" / phase_id / f"{command_id}.stdout.txt").write_text("", encoding="utf-8")
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

    assert [candidate.fingerprint for candidate in candidates] == ["compose-start-strict-compose-up"]
    assert candidates[0].state == "needs_targeted_repro"
    assert candidates[0].confidence == "low"


def test_issue_generator_uses_matching_classifier_for_known_root_cause(tmp_path: Path) -> None:
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

    assert [candidate.fingerprint for candidate in candidates] == ["storefront-volume-ownership"]
    assert candidates[0].state == "needs_targeted_repro"
    assert candidates[0].confidence == "medium"


def test_issue_generator_matches_docker_redis_port_conflict_text(tmp_path: Path) -> None:
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

    assert [candidate.fingerprint for candidate in candidates] == ["redis-host-port-conflict"]
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

    assert [candidate.fingerprint for candidate in candidates] == ["registry-agent-indexing-race"]
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

    assert [candidate.fingerprint for candidate in candidates] == ["zerotier-build-path"]
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

    assert [candidate.fingerprint for candidate in candidates] == ["zerotier-build-path"]
    assert candidates[0].state == "ready_to_file"
    assert candidates[0].confidence == "high"
    assert "targeted ZeroTier build-path profile" in candidates[0].state_reason


def test_issue_generator_renders_all_continue_workarounds_in_reproduction(tmp_path: Path) -> None:
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
    body = (run_dir / candidates[0].body_file.relative_to(run_dir)).read_text(encoding="utf-8")

    assert "Run `./scripts/issue-discovery continue --with first --with second`." in body


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

    assert [candidate.fingerprint for candidate in candidates] == ["stale-seller-layer-route"]
    assert candidates[0].state == "ready_to_file"
    assert candidates[0].confidence == "high"
    assert "commands/full_integration_sweep/integration_full.stdout.txt" in candidates[0].evidence
    body = (run_dir / candidates[0].body_file.relative_to(run_dir)).read_text(encoding="utf-8")
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

    assert [candidate.fingerprint for candidate in candidates] == ["storefront-volume-ownership"]
    assert "docker/compose-logs.txt" in candidates[0].evidence


def test_issue_generator_marks_root_service_test_failure_ready_to_file(tmp_path: Path) -> None:
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
        (run_dir / "issue-candidates" / "candidates.jsonl").read_text(encoding="utf-8").strip()
    )

    assert [candidate.fingerprint for candidate in candidates] == ["root-service-tests-make-test"]
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

    code = IssueRepository(run_dir, repo_root=repo_root).create("fingerprint", dry_run=False)

    assert code == 0
    assert calls[0]["command"][:3] == ["gh", "issue", "list"]
    assert calls[0]["command"][calls[0]["command"].index("--state") + 1] == "open"
    assert calls[0]["command"][calls[0]["command"].index("--search") + 1] == "fingerprint in:title"
    assert calls[1]["command"][:3] == ["gh", "issue", "create"]
    assert calls[1]["cwd"] == repo_root


def test_issue_create_blocks_non_ready_candidate_without_force(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    repo_root = tmp_path / "repo"
    run_dir.mkdir()
    repo_root.mkdir()
    write_candidate(run_dir)
    candidate_path = run_dir / "issue-candidates" / "candidates.jsonl"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["state"] = "needs_targeted_repro"
    candidate_path.write_text(json.dumps(candidate) + "\n", encoding="utf-8")

    def fake_run(*args, **kwargs) -> subprocess.CompletedProcess[str]:  # pragma: no cover
        raise AssertionError("non-ready issue should not call gh")

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", fake_run)

    code = IssueRepository(run_dir, repo_root=repo_root).create("fingerprint", dry_run=True)

    assert code == 2


def test_issue_create_force_allows_non_ready_candidate_dry_run(tmp_path: Path, capsys) -> None:
    run_dir = tmp_path / "run"
    repo_root = tmp_path / "repo"
    run_dir.mkdir()
    repo_root.mkdir()
    write_candidate(run_dir)
    candidate_path = run_dir / "issue-candidates" / "candidates.jsonl"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["state"] = "needs_targeted_repro"
    candidate_path.write_text(json.dumps(candidate) + "\n", encoding="utf-8")

    code = IssueRepository(run_dir, repo_root=repo_root).create("fingerprint", dry_run=True, force=True)

    assert code == 0
    assert "--body-file" in capsys.readouterr().out


def test_issue_create_skips_duplicate_issue(tmp_path: Path, monkeypatch, capsys) -> None:
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

    code = IssueRepository(run_dir, repo_root=repo_root).create("fingerprint", dry_run=False)

    assert code == 0
    assert len(calls) == 1
    assert "duplicate issue exists" in capsys.readouterr().out


def test_issue_create_blocks_unredacted_body_before_gh(tmp_path: Path, monkeypatch, capsys) -> None:
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

    def fake_run(*args, **kwargs) -> subprocess.CompletedProcess[str]:  # pragma: no cover
        raise AssertionError("unredacted issue should not call gh")

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", fake_run)

    code = IssueRepository(run_dir, repo_root=repo_root).create("fingerprint", dry_run=False)

    assert code == 2
    assert "unredacted data" in capsys.readouterr().out
