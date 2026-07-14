from __future__ import annotations

import json
from pathlib import Path
import subprocess

from issue_discovery.capacity import (
    CapacityValidationError,
    ingest_finding,
    validate_scenario,
)
from issue_discovery.issues import IssueRepository


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def valid_scenario() -> dict[str, object]:
    return {
        "schema_version": 1,
        "scenario_id": "b2-g1-contention",
        "deal_type": "vm",
        "provisioning": "real-kvm-ansible",
        "gpu_assignment": "whole-device-passthrough",
        "listing": {
            "fingerprint": "one-vm-listing",
            "count": 1,
            "gpus_per_vm": 1,
            "seller_distribution": [1],
        },
        "wave": {
            "buyers": 2,
            "sellers": 1,
            "requests": 2,
            "expected_successes": 1,
            "expected_scarcity": 1,
            "retry_count": 0,
        },
    }


def valid_finding() -> dict[str, object]:
    return {
        "schema_version": 1,
        "finding_id": "finding-001",
        "fingerprint": "double-allocation",
        "scenario_id": "b2-g1-contention",
        "scenario_fingerprint": "scenario-sha256-example",
        "frontier": "correctness",
        "classification": "public-product",
        "destination_repo": "simple-compute-market",
        "summary": "One-GPU contention allocated two buyers",
        "expected": "Exactly one request succeeds and one reaches scarcity.",
        "actual": "Both requests reached a successful allocation.",
        "evidence": ["sanitized/wave-result.json", "sanitized/allocation-trace.jsonl"],
        "observed": {
            "run_id": "qualification-001",
            "stage": "b2-g1-contention",
            "working_branch": "feat/issue-discovery-harness",
            "observed_ref": "a" * 40,
        },
        "filing_readiness": {
            "state": "ready_to_file",
            "confidence": "high",
            "reason": "The synchronized wave has complete allocation evidence.",
        },
    }


def ingest(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    finding = valid_finding()
    finding_path = tmp_path / "finding.json"
    finding_path.write_text(json.dumps(finding), encoding="utf-8")
    run_dir = tmp_path / "run"
    ingest_finding(run_dir, finding_path, repo_root())
    candidate = IssueRepository(run_dir, repo_root=repo_root()).list()[0]
    return run_dir, candidate


def test_capacity_scenario_is_vm_only_and_balances_terminal_outcomes() -> None:
    scenario = valid_scenario()
    validate_scenario(scenario, repo_root())

    scenario["deal_type"] = "container"
    try:
        validate_scenario(scenario, repo_root())
    except CapacityValidationError as exc:
        assert "deal_type" in str(exc)
        assert "vm" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a non-VM capacity scenario passed")


def test_all_tracked_capacity_scenarios_are_valid_and_cover_seller_scaling() -> None:
    scenario_dir = repo_root() / "tools" / "issue-discovery" / "config" / "capacity"
    scenarios = []
    for path in sorted(scenario_dir.glob("*.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        validate_scenario(scenario, repo_root())
        scenarios.append(scenario)
    ids = {item["scenario_id"] for item in scenarios}
    assert {"b2-s2-g1-contention", "b2-s2-g2-fulfillment"}.issubset(ids)
    for scenario in scenarios:
        assert len(scenario["listing"]["seller_distribution"]) == scenario["wave"]["sellers"]
        assert sum(scenario["listing"]["seller_distribution"]) == scenario["listing"]["count"]


def test_capacity_finding_ingest_preserves_defect_identity_and_branch_authority(
    tmp_path: Path,
) -> None:
    run_dir, candidate = ingest(tmp_path)

    assert candidate["fingerprint"] == "double-allocation"
    assert candidate["working_branch"] == "feat/issue-discovery-harness"
    assert candidate["labels"] == ["bug"]
    assert candidate["observed_ref"] == "a" * 40
    assert candidate["scenario_fingerprint"] == "scenario-sha256-example"
    body = (run_dir / candidate["body_file"]).read_text(encoding="utf-8")
    assert (
        "<!-- scm-issue-discovery fingerprint=double-allocation "
        "branch=feat/issue-discovery-harness "
        "scenario=scenario-sha256-example -->"
    ) in body
    assert "Working branch: `feat/issue-discovery-harness`" in body
    assert "Observed ref: `" + "a" * 40 + "`" in body
    assert "does not authorize promotion to `dev` or `main`" in body
    lifecycle = [
        json.loads(line)
        for line in (run_dir / "issue-lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["state"] for event in lifecycle] == ["detected"]


def test_capacity_defect_fingerprint_is_independent_of_occurrence_context(
    tmp_path: Path,
) -> None:
    public_root = tmp_path / "public"
    public_root.mkdir()
    public_run, public_candidate = ingest(public_root)

    private = valid_finding()
    private.update(
        {
            "finding_id": "finding-private-identity",
            "classification": "private-infra",
            "destination_repo": "compute-market-internal-infra",
            "scenario_fingerprint": "different-scenario-fingerprint",
        }
    )
    private["observed"].update(
        {
            "run_id": "qualification-private",
            "working_branch": "tools/agent-orchestration-scratch",
            "observed_ref": "b" * 40,
        }
    )
    private_path = tmp_path / "private-finding.json"
    private_path.write_text(json.dumps(private), encoding="utf-8")
    private_run = tmp_path / "private-run"
    ingest_finding(private_run, private_path, repo_root())
    private_candidate = IssueRepository(private_run, repo_root=repo_root()).list()[0]

    assert public_run != private_run
    assert public_candidate["fingerprint"] == private_candidate["fingerprint"]
    assert private_candidate["fingerprint"] == "double-allocation"


def test_capacity_duplicate_updates_exact_open_issue(tmp_path: Path, monkeypatch) -> None:
    run_dir, candidate = ingest(tmp_path)
    body = (run_dir / candidate["body_file"]).read_text(encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        text: bool,
        cwd: Path,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[:4] == ["git", "remote", "get-url", "origin"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="https://github.com/arkhai-io/simple-compute-market.git\n"
            )
        if command[:3] == ["git", "branch", "--show-current"]:
            return subprocess.CompletedProcess(command, 0, stdout="feat/issue-discovery-harness\n")
        if command[:3] == ["gh", "issue", "list"]:
            payload = [{"number": 41, "title": candidate["title"], "state": "OPEN", "url": "https://example.test/41", "body": body}]
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload))
        if command[:3] == ["gh", "issue", "comment"]:
            return subprocess.CompletedProcess(command, 0, stdout="https://example.test/41#comment")
        raise AssertionError(command)

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", fake_run)

    assert IssueRepository(run_dir, repo_root=repo_root()).create(candidate["fingerprint"], dry_run=False) == 0
    assert not any(command[:3] == ["gh", "issue", "create"] for command in calls)
    lifecycle = [
        json.loads(line)
        for line in (run_dir / "issue-lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["state"] for event in lifecycle] == ["detected", "updated"]


def test_capacity_duplicate_requires_exact_branch_and_scenario_marker(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir, candidate = ingest(tmp_path)
    body = (run_dir / candidate["body_file"]).read_text(encoding="utf-8")
    other_branch_body = body.replace(
        "branch=feat/issue-discovery-harness",
        "branch=tools/agent-orchestration-scratch",
    )
    other_scenario_body = body.replace(
        "scenario=scenario-sha256-example",
        "scenario=other-scenario",
    )
    calls: list[tuple[list[str], Path]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        text: bool,
        cwd: Path,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, cwd))
        if command[:4] == ["git", "remote", "get-url", "origin"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="https://github.com/arkhai-io/simple-compute-market.git\n"
            )
        if command[:3] == ["git", "branch", "--show-current"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="feat/issue-discovery-harness\n"
            )
        if command[:3] == ["gh", "issue", "list"]:
            payload = [
                {
                    "number": 51,
                    "title": candidate["title"],
                    "state": "OPEN",
                    "url": "https://example.test/51",
                    "body": other_branch_body,
                },
                {
                    "number": 52,
                    "title": candidate["title"],
                    "state": "OPEN",
                    "url": "https://example.test/52",
                    "body": other_scenario_body,
                },
            ]
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload))
        if command[:3] == ["gh", "issue", "create"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="https://example.test/53\n"
            )
        raise AssertionError(command)

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", fake_run)

    assert (
        IssueRepository(run_dir, repo_root=repo_root()).create(
            candidate["fingerprint"], dry_run=False
        )
        == 0
    )
    issue_list_call = next(
        (command, cwd)
        for command, cwd in calls
        if command[:3] == ["gh", "issue", "list"]
    )
    assert issue_list_call[1] == repo_root()
    assert issue_list_call[0][issue_list_call[0].index("--search") + 1] == (
        "double-allocation in:title"
    )
    assert any(command[:3] == ["gh", "issue", "create"] for command, _ in calls)
    assert not any(command[:3] == ["gh", "issue", "comment"] for command, _ in calls)


def test_capacity_issue_creation_records_filed_lifecycle(tmp_path: Path, monkeypatch) -> None:
    run_dir, candidate = ingest(tmp_path)
    calls: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        text: bool,
        cwd: Path,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[:4] == ["git", "remote", "get-url", "origin"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="https://github.com/arkhai-io/simple-compute-market.git\n"
            )
        if command[:3] == ["git", "branch", "--show-current"]:
            return subprocess.CompletedProcess(command, 0, stdout="feat/issue-discovery-harness\n")
        if command[:3] == ["gh", "issue", "list"]:
            return subprocess.CompletedProcess(command, 0, stdout="[]")
        if command[:3] == ["gh", "issue", "create"]:
            return subprocess.CompletedProcess(command, 0, stdout="https://example.test/43\n")
        raise AssertionError(command)

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", fake_run)

    assert IssueRepository(run_dir, repo_root=repo_root()).create(candidate["fingerprint"], dry_run=False) == 0
    create = next(command for command in calls if command[:3] == ["gh", "issue", "create"])
    assert create[create.index("--label") + 1] == "bug"
    lifecycle = [
        json.loads(line)
        for line in (run_dir / "issue-lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["state"] for event in lifecycle] == ["detected", "filed"]
    assert lifecycle[-1]["issue_url"] == "https://example.test/43"


def test_capacity_duplicate_reopens_exact_closed_issue(tmp_path: Path, monkeypatch) -> None:
    run_dir, candidate = ingest(tmp_path)
    body = (run_dir / candidate["body_file"]).read_text(encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        text: bool,
        cwd: Path,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[:4] == ["git", "remote", "get-url", "origin"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="https://github.com/arkhai-io/simple-compute-market.git\n"
            )
        if command[:3] == ["git", "branch", "--show-current"]:
            return subprocess.CompletedProcess(command, 0, stdout="feat/issue-discovery-harness\n")
        if command[:3] == ["gh", "issue", "list"]:
            payload = [{"number": 42, "title": candidate["title"], "state": "CLOSED", "url": "https://example.test/42", "body": body}]
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload))
        if command[:3] in (["gh", "issue", "reopen"], ["gh", "issue", "comment"]):
            return subprocess.CompletedProcess(command, 0, stdout="ok")
        raise AssertionError(command)

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", fake_run)

    assert IssueRepository(run_dir, repo_root=repo_root()).create(candidate["fingerprint"], dry_run=False) == 0
    assert any(command[:3] == ["gh", "issue", "reopen"] for command in calls)
    lifecycle = [
        json.loads(line)
        for line in (run_dir / "issue-lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["state"] for event in lifecycle] == ["detected", "reopened"]


def test_fix_pr_proposal_targets_working_branch_only(tmp_path: Path) -> None:
    run_dir, candidate = ingest(tmp_path)
    repository = IssueRepository(run_dir, repo_root=repo_root())
    head = f"fix/{candidate['fingerprint']}"

    proposal_path = repository.propose_fix(candidate["fingerprint"], head)
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal["status"] == "proposal-only"
    assert proposal["head_branch"] == head
    assert proposal["base_branch"] == "feat/issue-discovery-harness"
    assert proposal["auto_merge"] is False

    try:
        repository.propose_fix(candidate["fingerprint"], "main")
    except ValueError as exc:
        assert "must begin" in str(exc) or "authority" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a main-targeted fix proposal passed")


def test_capacity_lifecycle_requires_verification_before_close(tmp_path: Path) -> None:
    run_dir, candidate = ingest(tmp_path)
    repository = IssueRepository(run_dir, repo_root=repo_root())

    repository.transition(candidate["fingerprint"], "triaged", "Confirmed product invariant.")
    repository.transition(candidate["fingerprint"], "fix_in_progress", "Prepared branch-scoped fix.")
    repository.transition(candidate["fingerprint"], "fixed_unverified", "Fix merged to working branch.")
    try:
        repository.transition(candidate["fingerprint"], "closed", "Too early.")
    except ValueError as exc:
        assert "fixed_unverified -> closed" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unverified finding closed")
    repository.transition(candidate["fingerprint"], "verified", "Passed in a new qualification series.")
    repository.transition(candidate["fingerprint"], "closed", "Verified lifecycle is complete.")

    lifecycle = [
        json.loads(line)
        for line in (run_dir / "issue-lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["state"] for event in lifecycle] == [
        "detected",
        "triaged",
        "fix_in_progress",
        "fixed_unverified",
        "verified",
        "closed",
    ]


def test_private_infra_finding_uses_public_policy_and_private_git_authority(
    tmp_path: Path, capsys
) -> None:
    finding = valid_finding()
    finding.update(
        {
            "finding_id": "finding-private-001",
            "classification": "private-infra",
            "destination_repo": "compute-market-internal-infra",
            "actual": "X-Admin-Key: should-not-survive",
        }
    )
    finding["observed"].update(
        {
            "working_branch": "tools/agent-orchestration-scratch",
            "observed_ref": "b" * 40,
        }
    )
    finding_path = tmp_path / "private-finding.json"
    finding_path.write_text(json.dumps(finding), encoding="utf-8")
    run_dir = tmp_path / "run-private"
    ingest_finding(run_dir, finding_path, repo_root())
    candidate = IssueRepository(run_dir, repo_root=repo_root()).list()[0]
    body = (run_dir / candidate["body_file"]).read_text(encoding="utf-8")
    assert "should-not-survive" not in body

    infra = tmp_path / "compute-market-internal-infra"
    infra.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "tools/agent-orchestration-scratch"],
        cwd=infra,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "origin",
            "https://github.com/arkhai-io/compute-market-internal-infra.git",
        ],
        cwd=infra,
        check=True,
    )
    repository = IssueRepository(run_dir, repo_root=infra, policy_root=repo_root())
    assert repository.create(candidate["fingerprint"], dry_run=True) == 0
    output = capsys.readouterr().out
    assert f"cd {infra}" in output
    assert "gh issue create" in output

    subprocess.run(
        ["git", "remote", "set-url", "origin", "https://github.com/arkhai-io/wrong-repo.git"],
        cwd=infra,
        check=True,
    )
    assert repository.create(candidate["fingerprint"], dry_run=True) == 2
    assert "issue repository mismatch" in capsys.readouterr().out
