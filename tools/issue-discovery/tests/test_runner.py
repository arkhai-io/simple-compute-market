from __future__ import annotations

import json
from pathlib import Path

from issue_discovery.commands import run_shell_command
from issue_discovery.phases import CommandSpec
from issue_discovery.redaction import Redactor
from issue_discovery.runner import DiscoveryRunner
from issue_discovery.workarounds import WorkaroundSpec


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


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
    body = (run_dir / "issue-candidates" / "fail-fast-fail.md").read_text(encoding="utf-8")
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
