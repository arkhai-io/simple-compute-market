from __future__ import annotations

import json
from pathlib import Path

import pytest

from issue_discovery.artifacts import ArtifactStore
from issue_discovery.capacity import (
    MAX_JSON_NESTING_DEPTH,
    evaluate_capacity_result,
    scenario_sha256,
)
from issue_discovery.collectors import CollectorRunner, CollectorSpec
from issue_discovery.commands import run_shell_command
from issue_discovery.config import load_yaml
from issue_discovery.phases import CommandSpec
from issue_discovery.redaction import Redactor
from issue_discovery.runner import DiscoveryRunner
from issue_discovery.workarounds import WorkaroundSpec


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def capacity_scenario_path() -> Path:
    return (
        repo_root()
        / "tools"
        / "issue-discovery"
        / "config"
        / "capacity"
        / "b2-g1-contention.json"
    )


def capacity_scenario() -> dict[str, object]:
    return json.loads(capacity_scenario_path().read_text(encoding="utf-8"))


def capacity_success(ordinal: int) -> dict[str, object]:
    identity = {
        "fulfillment_id": f"fulfillment-{ordinal}",
        "capacity_reservation_id": f"reservation-{ordinal}",
    }
    wire_identity = {"contract_version": "1.0", **identity}
    return {
        "request_ordinal": ordinal,
        "outcome": "success",
        "capacity_reservation_id": identity["capacity_reservation_id"],
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


def capacity_failure(
    ordinal: int,
    *,
    code: str = "synthetic-role-failure",
) -> dict[str, object]:
    return {
        "request_ordinal": ordinal,
        "outcome": "harness-failure",
        "failure": {
            "code": code,
            "location": "buyer",
            "evidence_summary": "A bounded synthetic buyer receipt reported failure.",
        },
    }


def capacity_result(observations: list[dict[str, object]]) -> dict[str, object]:
    scenario = capacity_scenario()
    return {
        "schema_version": 1,
        "scenario_id": scenario["scenario_id"],
        "scenario_sha256": scenario_sha256(scenario),
        "termination": "completed",
        "run": {
            "run_id": "run-001",
            "observed_at": "2026-08-02T00:00:00Z",
            "timeout_seconds": 900,
            "repository": "arkhai-io/simple-compute-market",
            "branch": "feat/issue-discovery-harness-post-pools",
            "sha": "a" * 40,
        },
        "role_receipts": {"status": "satisfied", "failure": None},
        "serialized_reuse": {"status": "not-applicable", "failure": None},
        "host_preflight": {"status": "not-applicable", "failure": None},
        "observations": observations,
        "run_failure": None,
        "cancellation": {
            "attempted": False,
            "status": "not-required",
            "failure": None,
        },
        "cleanup": {
            "attempted": True,
            "status": "succeeded",
            "zero_residue": True,
            "failure": None,
        },
    }


def capacity_context() -> dict[str, object]:
    return {
        "repository": "arkhai-io/simple-compute-market",
        "branch": "feat/issue-discovery-harness-post-pools",
        "sha": "a" * 40,
        "run_id": "run-001",
        "timeout_seconds": 900,
        "adapters": ("market=mock",),
    }


def capacity_bound_receipt(
    *,
    operation: str,
    termination: str,
    idempotency_key: str,
    receipt: dict[str, object],
) -> dict[str, object]:
    context = capacity_context()
    scenario = capacity_scenario()
    return {
        "schema_version": 1,
        "operation": operation,
        "idempotency_key": idempotency_key,
        "public_context": {
            "repository": context["repository"],
            "branch": context["branch"],
            "sha": context["sha"],
        },
        "scenario": {
            "id": scenario["scenario_id"],
            "sha256": scenario_sha256(scenario),
        },
        "run": {
            "run_id": context["run_id"],
            "timeout_seconds": context["timeout_seconds"],
        },
        "adapters": {"market": "mock"},
        "termination": termination,
        "receipt": receipt,
    }


def test_shell_command_writes_logs_and_metadata(tmp_path: Path) -> None:
    result = run_shell_command(
        command_id="hello",
        command="echo hello",
        cwd=tmp_path,
        output_dir=tmp_path / "commands",
        redactor=Redactor(),
    )

    assert result.ok
    assert result.stdout_path.read_text(encoding="utf-8") == "hello\n"
    assert json.loads(result.meta_path.read_text(encoding="utf-8"))["exit_code"] == 0


def test_collector_context_includes_stderr(tmp_path: Path) -> None:
    store = ArtifactStore.create(tmp_path / "runs", run_id="run-1")
    runner = CollectorRunner(
        repo_root=tmp_path,
        store=store,
        collectors={
            "stderr_only": CollectorSpec(
                id="stderr_only",
                command="python -c 'import sys; print(\"diagnostic\", file=sys.stderr)'",
                output=Path("context/stderr.txt"),
            )
        },
        redactor=Redactor(),
    )

    record = runner.collect("stderr_only", "test")

    assert record["status"] == "passed"
    context = (store.run_dir / "context" / "stderr.txt").read_text(encoding="utf-8")
    assert "## stderr" in context
    assert "diagnostic" in context


def test_exact_artifact_dir_refuses_existing_contents(tmp_path: Path) -> None:
    run_dir = tmp_path / "existing-run"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError):
        ArtifactStore.use_exact_dir(run_dir)


def test_runner_continues_after_nonblocking_failure(tmp_path: Path) -> None:
    phase_file = tmp_path / "phases.yaml"
    phase_file.write_text(
        """
schema_version: 1
name: test
phases:
  - id: setup
    name: Setup
    category: test
    blocking: true
    commands:
      - id: ok
        run: echo setup
  - id: diagnostic_failure
    name: Diagnostic failure
    category: test
    blocking: false
    commands:
      - id: fail_one
        run: exit 3
      - id: fail_two
        run: exit 4
      - id: after_failures
        run: echo continued within phase
  - id: still_runs
    name: Still runs
    category: test
    blocking: false
    commands:
      - id: ok
        run: echo continued
  - id: teardown
    name: Teardown
    category: teardown
    blocking: false
    always_run: true
    commands:
      - id: ok
        run: echo down
""".lstrip(),
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"

    code = DiscoveryRunner(repo_root=repo_root(), output_dir=run_dir)._run_phase_file(
        mode="test",
        phase_path=phase_file,
        selected_phase_ids=None,
        workaround=None,
    )

    assert code == 1
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    records = read_jsonl(run_dir / "phases.jsonl")
    assert [(item["id"], item["status"]) for item in records] == [
        ("setup", "passed"),
        ("diagnostic_failure", "failed"),
        ("still_runs", "passed"),
        ("teardown", "passed"),
    ]
    diagnostic = records[1]
    assert [item["id"] for item in diagnostic["commands"]] == [
        "fail_one",
        "fail_two",
        "after_failures",
    ]
    assert diagnostic["failed_command"] == "fail_one"
    assert diagnostic["failed_commands"] == ["fail_one", "fail_two"]
    candidates = read_jsonl(run_dir / "issue-candidates" / "candidates.jsonl")
    assert candidates[0]["fingerprint"] == "diagnostic-failure-fail-one"
    assert candidates[0]["phase"] == "diagnostic_failure"


def test_runner_skips_after_blocking_failure_but_runs_teardown(tmp_path: Path) -> None:
    phase_file = tmp_path / "phases.yaml"
    phase_file.write_text(
        """
schema_version: 1
name: test
phases:
  - id: fail_fast
    name: Fail fast
    category: test
    blocking: true
    commands:
      - id: fail
        run: exit 2
      - id: should_not_run
        run: echo should not run
  - id: should_skip
    name: Should skip
    category: test
    blocking: false
    commands:
      - id: ok
        run: echo skipped
  - id: teardown
    name: Teardown
    category: teardown
    blocking: false
    always_run: true
    commands:
      - id: ok
        run: echo down
""".lstrip(),
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"

    code = DiscoveryRunner(repo_root=repo_root(), output_dir=run_dir)._run_phase_file(
        mode="test",
        phase_path=phase_file,
        selected_phase_ids=None,
        workaround=None,
    )

    assert code == 1
    records = read_jsonl(run_dir / "phases.jsonl")
    assert [(item["id"], item["status"]) for item in records] == [
        ("fail_fast", "failed"),
        ("should_skip", "skipped"),
        ("teardown", "passed"),
    ]
    assert records[1]["reason"] == "blocked"
    assert [item["id"] for item in records[0]["commands"]] == ["fail"]
    body = (run_dir / "issue-candidates" / "fail-fast-fail.md").read_text(
        encoding="utf-8"
    )
    assert "Run `./scripts/issue-discovery test`." in body


def test_issue_list_and_show_read_generated_candidates(tmp_path: Path, capsys) -> None:
    phase_file = tmp_path / "phases.yaml"
    phase_file.write_text(
        """
schema_version: 1
name: test
phases:
  - id: fail_fast
    name: Fail fast
    category: test
    blocking: true
    commands:
      - id: fail
        run: exit 2
""".lstrip(),
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"
    runner = DiscoveryRunner(repo_root=repo_root(), output_dir=run_dir)
    runner._run_phase_file(
        mode="test",
        phase_path=phase_file,
        selected_phase_ids=None,
        workaround=None,
    )
    capsys.readouterr()

    assert runner.issue_list(run_dir) == 0
    listed = capsys.readouterr().out
    assert "fail-fast-fail" in listed

    assert runner.issue_show(run_dir, "fail-fast-fail") == 0
    shown = capsys.readouterr().out
    assert "# Fail fast failed" in shown


def test_runner_applies_multiple_workarounds_in_order(tmp_path: Path) -> None:
    phase_file = tmp_path / "phases.yaml"
    phase_file.write_text(
        """
schema_version: 1
name: test
phases:
  - id: env_check
    name: Env check
    category: test
    blocking: true
    commands:
      - id: check_env
        run: test "$FIRST" = "1" && test "$SECOND" = "2"
""".lstrip(),
        encoding="utf-8",
    )
    first = WorkaroundSpec(
        id="first",
        status="active",
        reason="first",
        removal_condition="remove first",
        env={"FIRST": "1"},
        commands=(CommandSpec(id="first_command", run="echo first"),),
    )
    second = WorkaroundSpec(
        id="second",
        status="active",
        reason="second",
        removal_condition="remove second",
        env={"SECOND": "2"},
        commands=(CommandSpec(id="second_command", run="echo second"),),
    )
    run_dir = tmp_path / "run"

    code = DiscoveryRunner(repo_root=repo_root(), output_dir=run_dir)._run_phase_file(
        mode="continue",
        phase_path=phase_file,
        selected_phase_ids=None,
        workaround=(first, second),
    )

    assert code == 0
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in manifest["workarounds"]] == ["first", "second"]
    workaround_records = read_jsonl(run_dir / "workarounds.jsonl")
    assert [item["id"] for item in workaround_records] == ["first", "second"]


def test_runner_applies_profile_env_and_records_it(tmp_path: Path) -> None:
    phase_file = tmp_path / "phases.yaml"
    phase_file.write_text(
        """
schema_version: 1
name: test
phases:
  - id: env_check
    name: Env check
    category: test
    blocking: true
    commands:
      - id: check_env
        run: test "$PROFILE_ONLY" = "profile"
""".lstrip(),
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"

    code = DiscoveryRunner(repo_root=repo_root(), output_dir=run_dir)._run_phase_file(
        mode="profile:test",
        phase_path=phase_file,
        selected_phase_ids=None,
        workaround=None,
        profile_env={"PROFILE_ONLY": "profile"},
    )

    assert code == 0
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["profile_env"] == {"PROFILE_ONLY": "profile"}


def test_continuation_start_phase_assumes_prior_dependencies(tmp_path: Path) -> None:
    phase_file = tmp_path / "phases.yaml"
    phase_file.write_text(
        """
schema_version: 1
name: test
phases:
  - id: setup
    name: Setup
    category: test
    blocking: true
    commands:
      - id: setup
        run: echo setup
  - id: build
    name: Build
    category: build
    blocking: true
    requires:
      - setup
    commands:
      - id: build
        run: echo build
  - id: runtime
    name: Runtime
    category: runtime
    blocking: true
    requires:
      - build
    commands:
      - id: runtime
        run: echo runtime
  - id: stack_tests
    name: Stack tests
    category: stack_test
    blocking: false
    requires:
      - runtime
    commands:
      - id: stack_tests
        run: echo stack tests
  - id: teardown
    name: Teardown
    category: teardown
    blocking: false
    always_run: true
    commands:
      - id: teardown
        run: echo teardown
""".lstrip(),
        encoding="utf-8",
    )
    runtime_workaround = WorkaroundSpec(
        id="runtime_workaround",
        status="active",
        reason="runtime workaround",
        removal_condition="runtime fixed",
        start_phase="runtime",
    )
    run_dir = tmp_path / "run"

    code = DiscoveryRunner(repo_root=repo_root(), output_dir=run_dir)._run_phase_file(
        mode="continue",
        phase_path=phase_file,
        selected_phase_ids=None,
        workaround=runtime_workaround,
    )

    assert code == 0
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["phase_scope_start"] == "runtime"
    assert manifest["assumed_passed_phases"] == ["setup", "build"]
    records = read_jsonl(run_dir / "phases.jsonl")
    assert [(item["id"], item["status"]) for item in records] == [
        ("setup", "assumed_passed"),
        ("build", "assumed_passed"),
        ("runtime", "passed"),
        ("stack_tests", "passed"),
        ("teardown", "passed"),
    ]


def test_capacity_validate_and_hash_emit_stable_json(capsys) -> None:
    runner = DiscoveryRunner(repo_root=repo_root())

    assert runner.capacity_validate(capacity_scenario_path()) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["command"] == "capacity.validate"
    assert validated["status"] == "ok"
    assert validated["result"] == {"valid": True}

    assert runner.capacity_hash(capacity_scenario_path()) == 0
    first = capsys.readouterr().out
    assert runner.capacity_hash(capacity_scenario_path()) == 0
    second = capsys.readouterr().out
    assert first == second
    hashed = json.loads(first)
    assert hashed["result"]["sha256"] == scenario_sha256(capacity_scenario())


@pytest.mark.parametrize(
    "kind",
    ["market", "wallet", "cloud", "host", "provisioning", "github-mutation"],
)
def test_capacity_live_adapters_fail_before_reading_inputs(kind: str, capsys) -> None:
    runner = DiscoveryRunner(repo_root=repo_root())
    missing = repo_root() / "does-not-exist.json"

    code = runner.capacity_evaluate(
        missing,
        missing,
        **{**capacity_context(), "adapters": (f"{kind}=live",)},
    )

    output = json.loads(capsys.readouterr().out)
    assert code == 3
    assert output["error"] == {"code": "invalid-adapter-selection"}


@pytest.mark.parametrize(
    "adapters",
    [
        (),
        ("market=mock", "market=fake"),
        ("unknown=mock",),
        ("market=unknown",),
        ("market",),
    ],
)
def test_capacity_adapter_selection_is_closed(
    adapters: tuple[str, ...], capsys
) -> None:
    runner = DiscoveryRunner(repo_root=repo_root())
    missing = repo_root() / "does-not-exist.json"

    code = runner.capacity_finding(
        missing,
        missing,
        **{**capacity_context(), "adapters": adapters},
    )

    assert code == 3
    assert json.loads(capsys.readouterr().out)["error"]["code"] == (
        "invalid-adapter-selection"
    )


@pytest.mark.parametrize(
    ("override", "expected_error"),
    [
        ({"branch": "synthetic/agent-orchestration-ref"}, "invalid-public-context"),
        ({"branch": "origin/dev"}, "invalid-public-context"),
        ({"branch": "refs/heads/main"}, "invalid-public-context"),
        ({"branch": "HEAD"}, "invalid-public-context"),
        ({"branch": "feat/../dev"}, "invalid-public-context"),
        ({"branch": "feat//dev"}, "invalid-public-context"),
        ({"branch": "feat/name.lock"}, "invalid-public-context"),
        ({"branch": "feat/foo.lock/bar"}, "invalid-public-context"),
        ({"branch": "feat/name/"}, "invalid-public-context"),
        ({"run_id": "private-repository-ref"}, "invalid-run-context"),
    ],
)
def test_capacity_public_context_rejects_private_or_qualified_refs_before_input(
    capsys,
    override: dict[str, object],
    expected_error: str,
) -> None:
    missing = repo_root() / "private-path-that-must-not-be-read.json"

    code = DiscoveryRunner(repo_root=repo_root()).capacity_evaluate(
        missing,
        missing,
        **{**capacity_context(), **override},
    )

    output_text = capsys.readouterr().out
    output = json.loads(output_text)
    assert code == 2
    assert output["error"] == {"code": expected_error}
    assert str(next(iter(override.values()))) not in output_text
    assert str(missing) not in output_text


def test_capacity_evaluate_binds_context_and_returns_typed_exit_codes(
    tmp_path: Path,
    capsys,
) -> None:
    expected = capacity_result(
        [
            capacity_success(1),
            {
                "request_ordinal": 2,
                "outcome": "http-error",
                "http_status": 409,
                "detail": {
                    "error": "offer_unfulfillable",
                    "reason": "no_matching_inventory",
                },
            },
        ]
    )
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(expected), encoding="utf-8")
    runner = DiscoveryRunner(repo_root=repo_root())

    assert (
        runner.capacity_evaluate(
            capacity_scenario_path(), result_path, **capacity_context()
        )
        == 0
    )
    output = capsys.readouterr().out
    parsed = json.loads(output)
    assert parsed["status"] == "ok"
    assert parsed["result"]["counts"] == {
        "success": 1,
        "expected_scarcity": 1,
        "findings": 0,
    }
    assert "reservation-1" not in output
    assert "fulfillment-1" not in output

    failing = capacity_result([capacity_success(1), capacity_success(2)])
    result_path.write_text(json.dumps(failing), encoding="utf-8")
    assert (
        runner.capacity_evaluate(
            capacity_scenario_path(), result_path, **capacity_context()
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["status"] == "findings"

    mismatched = {**capacity_context(), "sha": "b" * 40}
    assert (
        runner.capacity_evaluate(capacity_scenario_path(), result_path, **mismatched)
        == 2
    )
    assert json.loads(capsys.readouterr().out)["error"] == {"code": "context-mismatch"}


def test_capacity_finding_and_issue_plan_use_supplied_snapshot_only(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    result = capacity_result([capacity_success(1), capacity_success(2)])
    evaluation = evaluate_capacity_result(
        capacity_scenario(),
        result,
        repo_root(),
    )
    finding = evaluation["findings"][0]
    finding_path = tmp_path / "finding.json"
    finding_path.write_text(json.dumps(finding), encoding="utf-8")
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    context = {**capacity_context(), "adapters": ("github-mutation=dry-run",)}
    snapshot_path = tmp_path / "issues.json"
    snapshot_path.write_text("[]\n", encoding="utf-8")

    def fail_external(*args, **kwargs):
        raise AssertionError("capacity planning cannot use an execution path")

    monkeypatch.setattr("issue_discovery.runner.run_shell_command", fail_external)
    monkeypatch.setattr("issue_discovery.runner.IssueRepository.create", fail_external)
    runner = DiscoveryRunner(repo_root=repo_root())
    assert (
        runner.capacity_finding(capacity_scenario_path(), finding_path, **context) == 0
    )
    assert (
        json.loads(capsys.readouterr().out)["result"]["fingerprint"]
        == finding["fingerprint"]
    )

    assert (
        runner.capacity_issue_plan(
            capacity_scenario_path(),
            result_path,
            snapshot_path,
            None,
            None,
            **context,
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)
    plan = created["result"]["issue_decisions"]["plans"][0]
    assert plan["action"] == "create"
    assert plan["dry_run"] is True

    snapshot_path.write_text(
        json.dumps(
            [
                {
                    "number": 101,
                    "state": "OPEN",
                    "body": plan["operations"][0]["body"],
                }
            ]
        ),
        encoding="utf-8",
    )
    assert (
        runner.capacity_issue_plan(
            capacity_scenario_path(),
            result_path,
            snapshot_path,
            None,
            None,
            **context,
        )
        == 0
    )
    repeated = json.loads(capsys.readouterr().out)
    assert repeated["result"]["issue_decisions"]["plans"][0]["action"] == "no-op"


def test_capacity_issue_plan_needs_no_snapshot_when_evaluation_has_no_findings(
    tmp_path: Path,
    capsys,
) -> None:
    result = capacity_result(
        [
            capacity_success(1),
            {
                "request_ordinal": 2,
                "outcome": "http-error",
                "http_status": 409,
                "detail": {
                    "error": "offer_unfulfillable",
                    "reason": "no_matching_inventory",
                },
            },
        ]
    )
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")

    code = DiscoveryRunner(repo_root=repo_root()).capacity_issue_plan(
        capacity_scenario_path(),
        result_path,
        tmp_path / "missing-and-unread-snapshot.json",
        None,
        None,
        **{**capacity_context(), "adapters": ("github-mutation=dry-run",)},
    )

    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert output["result"]["issue_decisions"] == {
        "schema_version": 1,
        "kind": "capacity-issue-decisions",
        "decision": "suppressed",
        "reason": "expected-scarcity",
        "plans": [],
    }


def test_capacity_issue_plan_groups_fingerprints_and_selects_fix_deterministically(
    tmp_path: Path,
    capsys,
) -> None:
    result = capacity_result([capacity_failure(1), capacity_failure(2)])
    evaluation = evaluate_capacity_result(capacity_scenario(), result, repo_root())
    fingerprints = {finding["fingerprint"] for finding in evaluation["findings"]}
    assert len(evaluation["findings"]) == 2
    assert len(fingerprints) == 1
    fingerprint = next(iter(fingerprints))
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    snapshot_path = tmp_path / "issues.json"
    snapshot_path.write_text("[]\n", encoding="utf-8")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "ownership": "public-harness",
                "summary": "Correct the bounded capacity result adapter.",
                "paths": ["tools/issue-discovery/src/issue_discovery/runner.py"],
            }
        ),
        encoding="utf-8",
    )

    code = DiscoveryRunner(repo_root=repo_root()).capacity_issue_plan(
        capacity_scenario_path(),
        result_path,
        snapshot_path,
        proposal_path,
        fingerprint,
        **{**capacity_context(), "adapters": ("github-mutation=dry-run",)},
    )

    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert len(output["result"]["issue_decisions"]["plans"]) == 1
    plan = output["result"]["issue_decisions"]["plans"][0]
    assert plan["fingerprint"] == fingerprint
    assert len(plan["occurrence_markers"]) == 2
    draft = output["result"]["draft_fix"]
    assert draft["status"] == "candidate"
    assert draft["head"] == f"fix/{fingerprint}"
    assert draft["executed"] is False


def test_capacity_issue_plan_preserves_distinct_findings_and_withholds_cleanup(
    tmp_path: Path,
    capsys,
) -> None:
    distinct = capacity_result(
        [
            capacity_failure(1, code="synthetic-first-failure"),
            capacity_failure(2, code="synthetic-second-failure"),
        ]
    )
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(distinct), encoding="utf-8")
    snapshot_path = tmp_path / "issues.json"
    snapshot_path.write_text("[]\n", encoding="utf-8")
    runner = DiscoveryRunner(repo_root=repo_root())
    context = {**capacity_context(), "adapters": ("github-mutation=dry-run",)}

    assert (
        runner.capacity_issue_plan(
            capacity_scenario_path(),
            result_path,
            snapshot_path,
            None,
            None,
            **context,
        )
        == 0
    )
    planned = json.loads(capsys.readouterr().out)
    assert len(planned["result"]["issue_decisions"]["plans"]) == 2

    cleanup_failure = capacity_result(
        [
            capacity_success(1),
            {
                "request_ordinal": 2,
                "outcome": "http-error",
                "http_status": 409,
                "detail": {
                    "error": "offer_unfulfillable",
                    "reason": "no_matching_inventory",
                },
            },
        ]
    )
    cleanup_failure["cleanup"] = {
        "attempted": True,
        "status": "failed",
        "zero_residue": False,
        "failure": {
            "code": "cleanup-failed",
            "location": "cleanup",
            "evidence_summary": "The bounded cleanup receipt did not prove zero residue.",
        },
    }
    result_path.write_text(json.dumps(cleanup_failure), encoding="utf-8")
    assert (
        runner.capacity_issue_plan(
            capacity_scenario_path(),
            result_path,
            tmp_path / "missing-and-unread-snapshot.json",
            None,
            None,
            **context,
        )
        == 0
    )
    withheld = json.loads(capsys.readouterr().out)
    decisions = withheld["result"]["issue_decisions"]
    assert decisions["decision"] == "withheld"
    assert all(plan["action"] == "withhold" for plan in decisions["plans"])


def test_capacity_cancel_and_cleanup_are_typed_idempotent_surfaces(
    tmp_path: Path,
    capsys,
) -> None:
    dry_runner = DiscoveryRunner(repo_root=repo_root(), dry_run=True)

    assert (
        dry_runner.capacity_cancel(
            capacity_scenario_path(),
            termination="timeout",
            receipt=None,
            **capacity_context(),
        )
        == 0
    )
    first = capsys.readouterr().out
    assert (
        dry_runner.capacity_cancel(
            capacity_scenario_path(),
            termination="timeout",
            receipt=None,
            **capacity_context(),
        )
        == 0
    )
    second = capsys.readouterr().out
    assert first == second
    cancel_key = json.loads(first)["result"]["idempotency_key"]

    assert (
        dry_runner.capacity_cleanup(
            capacity_scenario_path(),
            termination="timeout",
            receipt=None,
            **capacity_context(),
        )
        == 0
    )
    cleanup_key = json.loads(capsys.readouterr().out)["result"]["idempotency_key"]
    assert cleanup_key != cancel_key

    failure = {
        "code": "bounded-cancel-failed",
        "location": "controller",
        "evidence_summary": "The bounded cancellation attempt did not complete.",
    }
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(
        json.dumps(
            capacity_bound_receipt(
                operation="cancel",
                termination="timeout",
                idempotency_key=cancel_key,
                receipt={"attempted": True, "status": "failed", "failure": failure},
            )
        ),
        encoding="utf-8",
    )
    runner = DiscoveryRunner(repo_root=repo_root())
    assert (
        runner.capacity_cancel(
            capacity_scenario_path(),
            termination="timeout",
            receipt=receipt_path,
            **capacity_context(),
        )
        == 1
    )
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "negative-evidence"
    assert "evidence_summary" not in output

    receipt_path.write_text(
        json.dumps(
            capacity_bound_receipt(
                operation="cleanup",
                termination="timeout",
                idempotency_key=cleanup_key,
                receipt={
                    "attempted": False,
                    "status": "not-attempted",
                    "zero_residue": False,
                    "failure": {
                        "code": "cleanup-not-attempted",
                        "location": "cleanup",
                        "evidence_summary": "Cleanup could not be attempted.",
                    },
                },
            )
        ),
        encoding="utf-8",
    )
    assert (
        runner.capacity_cleanup(
            capacity_scenario_path(),
            termination="timeout",
            receipt=receipt_path,
            **capacity_context(),
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["status"] == "negative-evidence"


def test_capacity_bound_receipt_rejects_cross_run_replay_and_private_fields(
    tmp_path: Path,
    capsys,
) -> None:
    dry_runner = DiscoveryRunner(repo_root=repo_root(), dry_run=True)
    assert (
        dry_runner.capacity_cancel(
            capacity_scenario_path(),
            termination="timeout",
            receipt=None,
            **capacity_context(),
        )
        == 0
    )
    idempotency_key = json.loads(capsys.readouterr().out)["result"]["idempotency_key"]
    envelope = capacity_bound_receipt(
        operation="cancel",
        termination="timeout",
        idempotency_key=idempotency_key,
        receipt={"attempted": True, "status": "succeeded", "failure": None},
    )
    receipt_path = tmp_path / "receipt.json"
    envelope["run"]["run_id"] = "another-run"
    receipt_path.write_text(json.dumps(envelope), encoding="utf-8")
    runner = DiscoveryRunner(repo_root=repo_root())

    assert (
        runner.capacity_cancel(
            capacity_scenario_path(),
            termination="timeout",
            receipt=receipt_path,
            **capacity_context(),
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["error"] == {
        "code": "receipt-context-mismatch"
    }

    envelope = capacity_bound_receipt(
        operation="cancel",
        termination="timeout",
        idempotency_key=idempotency_key,
        receipt={"attempted": True, "status": "succeeded", "failure": None},
    )
    envelope["adapters"] = {"github-mutation": "dry-run"}
    receipt_path.write_text(json.dumps(envelope), encoding="utf-8")
    assert (
        runner.capacity_cancel(
            capacity_scenario_path(),
            termination="timeout",
            receipt=receipt_path,
            **capacity_context(),
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["error"] == {
        "code": "receipt-context-mismatch"
    }

    private_value = "private-repository-ref"
    private_receipt = capacity_bound_receipt(
        operation="cancel",
        termination="timeout",
        idempotency_key=idempotency_key,
        receipt={
            "attempted": True,
            "status": "failed",
            "failure": {
                "code": private_value,
                "location": "controller",
                "evidence_summary": "A bounded synthetic cancellation failed.",
            },
        },
    )
    receipt_path.write_text(json.dumps(private_receipt), encoding="utf-8")
    assert (
        runner.capacity_cancel(
            capacity_scenario_path(),
            termination="timeout",
            receipt=receipt_path,
            **capacity_context(),
        )
        == 2
    )
    output_text = capsys.readouterr().out
    assert json.loads(output_text)["error"] == {"code": "validation-failed"}
    assert private_value not in output_text


@pytest.mark.parametrize("adapters", [True, 0, 1.25])
def test_capacity_runner_rejects_noncollection_adapter_values(
    adapters: object,
    capsys,
) -> None:
    code = DiscoveryRunner(repo_root=repo_root()).capacity_evaluate(
        repo_root() / "must-not-be-read-scenario.json",
        repo_root() / "must-not-be-read-result.json",
        **{**capacity_context(), "adapters": adapters},
    )

    output = json.loads(capsys.readouterr().out)
    assert code == 3
    assert output["error"] == {"code": "invalid-adapter-selection"}


@pytest.mark.parametrize(
    "termination",
    [
        "timeout",
        "cancelled",
        "partial-launch",
        "role-failure",
        "controller-failure",
    ],
)
def test_capacity_noncompleted_bound_receipts_accept_cancel_and_cleanup_attempts(
    tmp_path: Path,
    capsys,
    termination: str,
) -> None:
    dry_runner = DiscoveryRunner(repo_root=repo_root(), dry_run=True)
    keys: dict[str, str] = {}
    for operation in ("cancel", "cleanup"):
        method = getattr(dry_runner, f"capacity_{operation}")
        assert (
            method(
                capacity_scenario_path(),
                termination=termination,
                receipt=None,
                **capacity_context(),
            )
            == 0
        )
        keys[operation] = json.loads(capsys.readouterr().out)["result"][
            "idempotency_key"
        ]

    runner = DiscoveryRunner(repo_root=repo_root())
    receipts = {
        "cancel": {"attempted": True, "status": "succeeded", "failure": None},
        "cleanup": {
            "attempted": True,
            "status": "succeeded",
            "zero_residue": True,
            "failure": None,
        },
    }
    for operation, receipt in receipts.items():
        receipt_path = tmp_path / f"{operation}.json"
        receipt_path.write_text(
            json.dumps(
                capacity_bound_receipt(
                    operation=operation,
                    termination=termination,
                    idempotency_key=keys[operation],
                    receipt=receipt,
                )
            ),
            encoding="utf-8",
        )
        method = getattr(runner, f"capacity_{operation}")
        assert (
            method(
                capacity_scenario_path(),
                termination=termination,
                receipt=receipt_path,
                **capacity_context(),
            )
            == 0
        )
        assert json.loads(capsys.readouterr().out)["status"] == "ok"


@pytest.mark.parametrize(
    "termination",
    [
        "timeout",
        "cancelled",
        "partial-launch",
        "role-failure",
        "controller-failure",
    ],
)
def test_capacity_noncompleted_termination_requires_cancellation_attempt(
    tmp_path: Path,
    capsys,
    termination: str,
) -> None:
    dry_runner = DiscoveryRunner(repo_root=repo_root(), dry_run=True)
    assert (
        dry_runner.capacity_cancel(
            capacity_scenario_path(),
            termination=termination,
            receipt=None,
            **capacity_context(),
        )
        == 0
    )
    idempotency_key = json.loads(capsys.readouterr().out)["result"]["idempotency_key"]
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(
        json.dumps(
            capacity_bound_receipt(
                operation="cancel",
                termination=termination,
                idempotency_key=idempotency_key,
                receipt={
                    "attempted": False,
                    "status": "not-required",
                    "failure": None,
                },
            )
        ),
        encoding="utf-8",
    )

    code = DiscoveryRunner(repo_root=repo_root()).capacity_cancel(
        capacity_scenario_path(),
        termination=termination,
        receipt=receipt_path,
        **capacity_context(),
    )

    assert code == 2
    assert json.loads(capsys.readouterr().out)["error"] == {"code": "validation-failed"}


@pytest.mark.parametrize(
    ("contents", "expected_error"),
    [
        ("{", "input-unavailable-or-invalid"),
        ("[]", "validation-failed"),
        ("{}", "validation-failed"),
    ],
)
def test_capacity_invalid_scenario_emits_one_sanitized_json_result(
    tmp_path: Path,
    capsys,
    contents: str,
    expected_error: str,
) -> None:
    scenario_path = tmp_path / "private-looking-scenario-name.json"
    scenario_path.write_text(contents, encoding="utf-8")

    code = DiscoveryRunner(repo_root=repo_root()).capacity_validate(scenario_path)

    lines = capsys.readouterr().out.splitlines()
    assert code == 2
    assert len(lines) == 1
    output = json.loads(lines[0])
    assert output == {
        "schema_version": 1,
        "command": "capacity.validate",
        "status": "error",
        "context": None,
        "result": None,
        "error": {"code": expected_error},
    }
    assert str(scenario_path) not in lines[0]


def test_capacity_oversized_json_integer_emits_stable_invalid_input(
    tmp_path: Path,
    capsys,
) -> None:
    scenario_path = tmp_path / "oversized-integer.json"
    scenario_path.write_text('{"value":' + "9" * 5_000 + "}", encoding="utf-8")

    code = DiscoveryRunner(repo_root=repo_root()).capacity_validate(scenario_path)

    output = json.loads(capsys.readouterr().out)
    assert code == 2
    assert output["status"] == "error"
    assert output["error"] == {"code": "input-unavailable-or-invalid"}


def test_capacity_deeply_nested_json_emits_stable_invalid_input(
    tmp_path: Path,
    capsys,
) -> None:
    scenario_path = tmp_path / "deeply-nested.json"
    scenario_path.write_text("[" * 20_000 + "0" + "]" * 20_000, encoding="utf-8")

    code = DiscoveryRunner(repo_root=repo_root()).capacity_validate(scenario_path)

    output = json.loads(capsys.readouterr().out)
    assert code == 2
    assert output["status"] == "error"
    assert output["error"] == {"code": "input-unavailable-or-invalid"}


def test_capacity_over_nested_json_emits_invalid_input_without_recursion(
    tmp_path: Path,
    capsys,
) -> None:
    scenario_path = tmp_path / "over-nested.json"
    depth = MAX_JSON_NESTING_DEPTH + 1
    scenario_path.write_text("[" * depth + "0" + "]" * depth, encoding="utf-8")

    code = DiscoveryRunner(repo_root=repo_root()).capacity_validate(scenario_path)

    output = json.loads(capsys.readouterr().out)
    assert code == 2
    assert output["status"] == "error"
    assert output["error"] == {"code": "input-unavailable-or-invalid"}


def test_local_phase_workdirs_use_current_repository_entrypoints() -> None:
    phase_file = load_yaml(
        repo_root() / "tools" / "issue-discovery" / "config" / "phases" / "local.yaml"
    )
    phases = {phase["id"]: phase for phase in phase_file["phases"]}
    assert phases["shared_service_tests"]["commands"][0]["workdir"] == "core"
    assert phases["policy_tests"]["commands"][0]["workdir"] == "kit/policy"
    assert phases["buyer_tests"]["commands"][0]["workdir"] == "domains/vms/buyer"
    for phase in phases.values():
        for command in phase["commands"]:
            assert (repo_root() / command.get("workdir", ".")).is_dir()
