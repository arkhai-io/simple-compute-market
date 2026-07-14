from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from issue_discovery.capacity import (
    CapacityValidationError,
    ingest_finding,
    scenario_sha256,
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


def marker_payload(body: str, kind: str) -> dict[str, str]:
    prefix = f"<!-- scm-issue-discovery-{kind} "
    line = next(item for item in body.splitlines() if item.startswith(prefix))
    return json.loads(line.removeprefix(prefix).removesuffix(" -->"))


def authorized_git_result(
    command: list[str],
    *,
    repository: str = "simple-compute-market",
    branch: str = "feat/issue-discovery-harness",
    observed_ref: str = "a" * 40,
) -> subprocess.CompletedProcess[str] | None:
    if command[:4] == ["git", "remote", "get-url", "origin"]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"git@github.com:arkhai-io/{repository}.git\n",
        )
    if command[:3] == ["git", "branch", "--show-current"]:
        return subprocess.CompletedProcess(command, 0, stdout=f"{branch}\n")
    if command[:3] == ["git", "rev-parse", "HEAD"]:
        return subprocess.CompletedProcess(command, 0, stdout=f"{observed_ref}\n")
    if command[:2] == ["git", "status"]:
        return subprocess.CompletedProcess(command, 0, stdout="")
    return None


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


def test_capacity_scenario_rejects_private_runtime_listing_identity() -> None:
    scenario = valid_scenario()
    scenario["listing"]["fingerprint"] = "runtime-listing-fingerprint"

    try:
        validate_scenario(scenario, repo_root())
    except CapacityValidationError as exc:
        assert "listing" in str(exc)
        assert "fingerprint" in str(exc)
        assert "was unexpected" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a runtime listing fingerprint passed the public schema")


def test_capacity_scenario_sha256_is_canonical() -> None:
    scenario = valid_scenario()
    reordered = json.loads(json.dumps(scenario, sort_keys=True, indent=4))

    digest = scenario_sha256(scenario)
    assert digest == (
        "dff78da34b800f24423bd3e04c4439eb3f86ab2890a0be7bdb81e5f1e57c17e2"
    )
    assert digest == scenario_sha256(reordered)
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_all_tracked_capacity_scenarios_are_valid_and_cover_seller_scaling() -> None:
    scenario_dir = repo_root() / "tools" / "issue-discovery" / "config" / "capacity"
    scenarios = []
    for path in sorted(scenario_dir.glob("*.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        validate_scenario(scenario, repo_root())
        scenarios.append(scenario)
    ordered_ids = [item["scenario_id"] for item in scenarios]
    ids = set(ordered_ids)
    assert {"b2-s2-g1-contention", "b2-s2-g2-fulfillment"}.issubset(ids)
    assert ordered_ids[0] == "b1-g1-qualification"
    assert ordered_ids.index("b2-g1-contention") < ordered_ids.index(
        "b2-s2-g1-contention"
    )
    assert ordered_ids.index("b2-g2-fulfillment") < ordered_ids.index(
        "b2-s2-g2-fulfillment"
    )
    for scenario in scenarios:
        assert set(scenario["listing"]) == {
            "count",
            "gpus_per_vm",
            "seller_distribution",
        }
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
    assert candidate["destination_repo"] == "simple-compute-market"
    assert candidate["scenario_id"] == "b2-g1-contention"
    assert candidate["scenario_fingerprint"] == "scenario-sha256-example"
    assert candidate["run_id"] == "qualification-001"
    body = (run_dir / candidate["body_file"]).read_text(encoding="utf-8")
    assert marker_payload(body, "scope") == {
        "fingerprint": "double-allocation",
        "repository": "github.com/arkhai-io/simple-compute-market",
        "scenario_fingerprint": "scenario-sha256-example",
        "scenario_id": "b2-g1-contention",
        "working_branch": "feat/issue-discovery-harness",
    }
    assert marker_payload(body, "occurrence") == {
        "observed_ref": "a" * 40,
        "repository": "github.com/arkhai-io/simple-compute-market",
        "run_id": "qualification-001",
        "scenario_fingerprint": "scenario-sha256-example",
        "scenario_id": "b2-g1-contention",
        "stage": "b2-g1-contention",
        "working_branch": "feat/issue-discovery-harness",
    }
    assert "Working branch: `feat/issue-discovery-harness`" in body
    assert "Observed ref: `" + "a" * 40 + "`" in body
    assert "does not authorize promotion to `dev` or `main`" in body
    lifecycle = [
        json.loads(line)
        for line in (run_dir / "issue-lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["state"] for event in lifecycle] == ["detected"]
    assert {
        key: lifecycle[0][key]
        for key in (
            "destination_repo",
            "working_branch",
            "observed_ref",
            "scenario_id",
            "scenario_fingerprint",
            "run_id",
            "stage",
        )
    } == {
        "destination_repo": "simple-compute-market",
        "working_branch": "feat/issue-discovery-harness",
        "observed_ref": "a" * 40,
        "scenario_id": "b2-g1-contention",
        "scenario_fingerprint": "scenario-sha256-example",
        "run_id": "qualification-001",
        "stage": "b2-g1-contention",
    }


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
        authority = authorized_git_result(command)
        if authority is not None:
            return authority
        if command[:3] == ["gh", "issue", "list"]:
            payload = [{"number": 41, "title": candidate["title"], "state": "OPEN", "url": "https://example.test/41", "body": body}]
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload))
        if command[:3] == ["gh", "issue", "comment"]:
            return subprocess.CompletedProcess(command, 0, stdout="https://example.test/41#comment")
        raise AssertionError(command)

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", fake_run)

    assert IssueRepository(run_dir, repo_root=repo_root()).create(candidate["fingerprint"], dry_run=False) == 0
    assert not any(command[:3] == ["gh", "issue", "create"] for command in calls)
    assert all(
        command[command.index("--repo") + 1]
        == "github.com/arkhai-io/simple-compute-market"
        for command in calls
        if command[:3] in (["gh", "issue", "list"], ["gh", "issue", "comment"])
    )
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
        '"working_branch":"feat/issue-discovery-harness"',
        '"working_branch":"tools/agent-orchestration-scratch"',
    )
    other_scenario_body = body.replace(
        '"scenario_fingerprint":"scenario-sha256-example"',
        '"scenario_fingerprint":"other-scenario"',
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
        authority = authorized_git_result(command)
        if authority is not None:
            return authority
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
    assert issue_list_call[0][issue_list_call[0].index("--repo") + 1] == (
        "github.com/arkhai-io/simple-compute-market"
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
        authority = authorized_git_result(command)
        if authority is not None:
            return authority
        if command[:3] == ["gh", "issue", "list"]:
            return subprocess.CompletedProcess(command, 0, stdout="[]")
        if command[:3] == ["gh", "issue", "create"]:
            return subprocess.CompletedProcess(command, 0, stdout="https://example.test/43\n")
        raise AssertionError(command)

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", fake_run)

    assert IssueRepository(run_dir, repo_root=repo_root()).create(candidate["fingerprint"], dry_run=False) == 0
    create = next(command for command in calls if command[:3] == ["gh", "issue", "create"])
    assert create[create.index("--label") + 1] == "bug"
    assert create[create.index("--repo") + 1] == (
        "github.com/arkhai-io/simple-compute-market"
    )
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
        authority = authorized_git_result(command)
        if authority is not None:
            return authority
        if command[:3] == ["gh", "issue", "list"]:
            payload = [{"number": 42, "title": candidate["title"], "state": "CLOSED", "url": "https://example.test/42", "body": body}]
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload))
        if command[:3] in (["gh", "issue", "reopen"], ["gh", "issue", "comment"]):
            return subprocess.CompletedProcess(command, 0, stdout="ok")
        raise AssertionError(command)

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", fake_run)

    assert IssueRepository(run_dir, repo_root=repo_root()).create(candidate["fingerprint"], dry_run=False) == 0
    assert any(command[:3] == ["gh", "issue", "reopen"] for command in calls)
    assert all(
        command[command.index("--repo") + 1]
        == "github.com/arkhai-io/simple-compute-market"
        for command in calls
        if command[:3]
        in (["gh", "issue", "list"], ["gh", "issue", "reopen"], ["gh", "issue", "comment"])
    )
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
    assert proposal["destination_repository"] == (
        "github.com/arkhai-io/simple-compute-market"
    )
    assert proposal["head_branch"] == head
    assert proposal["base_branch"] == "feat/issue-discovery-harness"
    assert proposal["observed_ref"] == "a" * 40
    assert proposal["scenario_id"] == "b2-g1-contention"
    assert proposal["scenario_fingerprint"] == "scenario-sha256-example"
    assert proposal["run_id"] == "qualification-001"
    assert proposal["auto_merge"] is False

    try:
        repository.propose_fix(candidate["fingerprint"], "main")
    except ValueError as exc:
        assert "dev or main" in str(exc)
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
    (infra / "authority.txt").write_text("exact issue authority\n", encoding="utf-8")
    subprocess.run(["git", "add", "authority.txt"], cwd=infra, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Issue Test",
            "-c",
            "user.email=issue-test@example.invalid",
            "commit",
            "-q",
            "-m",
            "record exact authority",
        ],
        cwd=infra,
        check=True,
    )
    observed_ref = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=infra,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
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
            "observed_ref": observed_ref,
        }
    )
    finding_path = tmp_path / "private-finding.json"
    finding_path.write_text(json.dumps(finding), encoding="utf-8")
    run_dir = tmp_path / "run-private"
    ingest_finding(run_dir, finding_path, repo_root())
    candidate = IssueRepository(run_dir, repo_root=repo_root()).list()[0]
    body = (run_dir / candidate["body_file"]).read_text(encoding="utf-8")
    assert "should-not-survive" not in body

    repository = IssueRepository(run_dir, repo_root=infra, policy_root=repo_root())
    assert repository.create(candidate["fingerprint"], dry_run=True) == 0
    output = capsys.readouterr().out
    assert f"cd {infra}" in output
    assert "gh issue create" in output
    assert "--repo github.com/arkhai-io/compute-market-internal-infra" in output

    subprocess.run(
        ["git", "remote", "set-url", "origin", "https://github.com/arkhai-io/wrong-repo.git"],
        cwd=infra,
        check=True,
    )
    assert repository.create(candidate["fingerprint"], dry_run=True) == 2
    assert "issue repository mismatch" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("remote", "branch", "observed_ref", "status", "message"),
    [
        (
            "https://github.com/a-fork/simple-compute-market.git\n",
            "feat/issue-discovery-harness",
            "a" * 40,
            "",
            "issue repository mismatch",
        ),
        (
            "https://github.com/arkhai-io/simple-compute-market.git\n",
            "dev",
            "a" * 40,
            "",
            "default branch is forbidden",
        ),
        (
            "https://github.com/arkhai-io/simple-compute-market.git\n",
            "feat/issue-discovery-harness",
            "b" * 40,
            "",
            "issue ref mismatch",
        ),
        (
            "https://github.com/arkhai-io/simple-compute-market.git\n",
            "feat/issue-discovery-harness",
            "a" * 40,
            " M tracked-file\n",
            "exact clean observed worktree",
        ),
    ],
)
def test_capacity_publish_fails_closed_outside_exact_repository_branch_and_ref(
    tmp_path: Path,
    monkeypatch,
    capsys,
    remote: str,
    branch: str,
    observed_ref: str,
    status: str,
    message: str,
) -> None:
    run_dir, candidate = ingest(tmp_path)

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        if command[:4] == ["git", "remote", "get-url", "origin"]:
            return subprocess.CompletedProcess(command, 0, stdout=remote)
        if command[:3] == ["git", "branch", "--show-current"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"{branch}\n")
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"{observed_ref}\n")
        if command[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(command, 0, stdout=status)
        raise AssertionError(f"publication must fail before GitHub mutation: {command}")

    monkeypatch.setattr("issue_discovery.issues.subprocess.run", fake_run)

    assert (
        IssueRepository(run_dir, repo_root=repo_root()).create(
            candidate["fingerprint"], dry_run=False
        )
        == 2
    )
    assert message in capsys.readouterr().out


def test_fix_proposal_rejects_tampered_default_base(tmp_path: Path) -> None:
    run_dir, candidate = ingest(tmp_path)
    candidates_path = run_dir / "issue-candidates" / "candidates.jsonl"
    candidate["working_branch"] = "main"
    candidates_path.write_text(json.dumps(candidate) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="working branch is forbidden"):
        IssueRepository(run_dir, repo_root=repo_root()).propose_fix(
            candidate["fingerprint"], f"fix/{candidate['fingerprint']}"
        )
