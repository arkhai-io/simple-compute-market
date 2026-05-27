from __future__ import annotations

import json
from pathlib import Path

from issue_discovery.commands import run_shell_command
from issue_discovery.redaction import Redactor
from issue_discovery.runner import DiscoveryRunner


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
