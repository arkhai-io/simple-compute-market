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


def test_issue_create_runs_gh_from_repo_root(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    repo_root = tmp_path / "repo"
    run_dir.mkdir()
    repo_root.mkdir()
    write_candidate(run_dir)
    calls = []

    def fake_run(command: list[str], *, check: bool, text: bool, cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, "check": check, "text": text, "cwd": cwd})
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", fake_run)

    code = IssueRepository(run_dir, repo_root=repo_root).create("fingerprint", dry_run=False)

    assert code == 0
    assert calls[0]["cwd"] == repo_root
