from __future__ import annotations

import json
from pathlib import Path

import pytest

from issue_discovery.cli import build_parser, main


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_parser_requires_subcommand() -> None:
    parser = build_parser()
    try:
        parser.parse_args([])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover
        raise AssertionError("parser accepted missing subcommand")


def test_strict_dry_run_prints_repo_root(capsys) -> None:
    root = repo_root()
    code = main(["--repo-root", str(root), "--dry-run", "strict"])

    captured = capsys.readouterr()
    assert code == 0
    assert "issue-discovery command: strict" in captured.out
    assert f"repo_root: {root}" in captured.out
    assert "dry_run: yes" in captured.out


def test_continue_requires_workaround() -> None:
    parser = build_parser()
    try:
        parser.parse_args(["continue"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover
        raise AssertionError("parser accepted continuation without workaround")


def test_continue_accepts_multiple_workarounds() -> None:
    parser = build_parser()
    args = parser.parse_args(["continue", "--with", "one", "--with", "two"])

    assert args.workarounds == ["one", "two"]


def test_runtime_continuation_dry_run_starts_at_runtime_scope(capsys) -> None:
    root = repo_root()
    code = main(
        [
            "--repo-root",
            str(root),
            "--dry-run",
            "continue",
            "--with",
            "redis_no_host_port",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "phase_scope_start: compose_preexisting_stack_check" in captured.out
    assert "assumed_passed_phases:" in captured.out
    assert "  - build" in captured.out
    assert "  - root_service_tests" not in captured.out
    assert "  - compose_preexisting_stack_check" in captured.out
    phase_lines = captured.out.split("\nphases:\n", 1)[1]
    assert "  - root_service_tests" not in phase_lines


def test_profile_dry_run_prints_profile_env(capsys) -> None:
    root = repo_root()
    code = main(["--repo-root", str(root), "--dry-run", "profile", "fresh-volumes"])

    captured = capsys.readouterr()
    assert code == 0
    assert "issue-discovery command: profile:fresh-volumes" in captured.out
    assert "profile_env:" in captured.out
    assert (
        "ISSUE_DISCOVERY_COMPOSE_ARGS=-f docker-compose.yml -f /tmp/scm-no-redis-port.yml"
        in captured.out
    )
    assert "  - redis_no_host_port_override" in captured.out


def _install_capacity_runner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    return_code: int = 17,
) -> tuple[
    list[dict[str, object]],
    list[tuple[str, tuple[object, ...], dict[str, object]]],
]:
    initializations: list[dict[str, object]] = []
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    class RecordingRunner:
        def __init__(
            self,
            repo_root: Path,
            output_dir: Path | None = None,
            dry_run: bool = False,
        ) -> None:
            initializations.append(
                {
                    "repo_root": repo_root,
                    "output_dir": output_dir,
                    "dry_run": dry_run,
                }
            )

        def _record(self, name: str, *args: object, **kwargs: object) -> int:
            calls.append((name, args, kwargs))
            return return_code

        def capacity_validate(self, *args: object, **kwargs: object) -> int:
            return self._record("capacity_validate", *args, **kwargs)

        def capacity_hash(self, *args: object, **kwargs: object) -> int:
            return self._record("capacity_hash", *args, **kwargs)

        def capacity_evaluate(self, *args: object, **kwargs: object) -> int:
            return self._record("capacity_evaluate", *args, **kwargs)

        def capacity_finding(self, *args: object, **kwargs: object) -> int:
            return self._record("capacity_finding", *args, **kwargs)

        def capacity_issue_plan(self, *args: object, **kwargs: object) -> int:
            return self._record("capacity_issue_plan", *args, **kwargs)

        def capacity_cancel(self, *args: object, **kwargs: object) -> int:
            return self._record("capacity_cancel", *args, **kwargs)

        def capacity_cleanup(self, *args: object, **kwargs: object) -> int:
            return self._record("capacity_cleanup", *args, **kwargs)

    monkeypatch.setattr("issue_discovery.cli.DiscoveryRunner", RecordingRunner)
    return initializations, calls


def test_capacity_parser_has_exact_preparation_commands() -> None:
    parser = build_parser()
    root_commands = next(
        action for action in parser._actions if action.dest == "command"
    )
    assert isinstance(root_commands.choices, dict)
    capacity_parser = root_commands.choices["capacity"]
    capacity_commands = next(
        action
        for action in capacity_parser._actions
        if action.dest == "capacity_command"
    )
    assert isinstance(capacity_commands.choices, dict)

    assert tuple(capacity_commands.choices) == (
        "validate",
        "hash",
        "evaluate",
        "finding",
        "issue-plan",
        "cancel",
        "cleanup",
    )
    assert {"run", "execute"}.isdisjoint(capacity_commands.choices)


def test_capacity_help_lists_the_seven_preparation_commands(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["capacity", "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "{validate,hash,evaluate,finding,issue-plan,cancel,cleanup}" in output
    assert "Validate a capacity scenario." in output
    assert "Plan or record cleanup for a capacity scenario." in output


def test_capacity_commands_dispatch_paths_context_and_global_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initializations, calls = _install_capacity_runner(monkeypatch)
    repo = tmp_path / "repo"
    context_arguments = [
        "--repository",
        "example/public-repository",
        "--branch",
        "replacement-branch",
        "--sha",
        "a" * 40,
        "--run-id",
        "capacity-run",
        "--timeout-seconds",
        "45",
        "--adapter",
        "market=mock",
        "--adapter",
        "wallet=mock",
    ]
    context = {
        "repository": "example/public-repository",
        "branch": "replacement-branch",
        "sha": "a" * 40,
        "run_id": "capacity-run",
        "timeout_seconds": "45",
        "adapters": ("market=mock", "wallet=mock"),
    }
    cases = [
        (
            "capacity_validate",
            ["validate", "scenario.json"],
            (repo / "scenario.json",),
            {},
        ),
        (
            "capacity_hash",
            ["hash", "scenario.json"],
            (repo / "scenario.json",),
            {},
        ),
        (
            "capacity_evaluate",
            [
                "evaluate",
                "result.json",
                "--scenario",
                "scenario.json",
                *context_arguments,
            ],
            (repo / "scenario.json", repo / "result.json"),
            context,
        ),
        (
            "capacity_finding",
            [
                "finding",
                "finding.json",
                "--scenario",
                "scenario.json",
                *context_arguments,
            ],
            (repo / "scenario.json", repo / "finding.json"),
            context,
        ),
        (
            "capacity_issue_plan",
            [
                "issue-plan",
                "result.json",
                "--scenario",
                "scenario.json",
                "--issues-snapshot",
                "issues.json",
                "--fix-proposal",
                "proposal.json",
                "--fix-fingerprint",
                "f" * 64,
                *context_arguments,
            ],
            (
                repo / "scenario.json",
                repo / "result.json",
                repo / "issues.json",
                repo / "proposal.json",
                "f" * 64,
            ),
            context,
        ),
        (
            "capacity_cancel",
            [
                "cancel",
                "--scenario",
                "scenario.json",
                "--termination",
                "timeout",
                "--receipt",
                "cancel.json",
                *context_arguments,
            ],
            (repo / "scenario.json",),
            {
                "termination": "timeout",
                "receipt": repo / "cancel.json",
                **context,
            },
        ),
        (
            "capacity_cleanup",
            [
                "cleanup",
                "--scenario",
                "scenario.json",
                "--termination",
                "completed",
                *context_arguments,
            ],
            (repo / "scenario.json",),
            {"termination": "completed", "receipt": None, **context},
        ),
    ]

    for method, arguments, expected_args, expected_kwargs in cases:
        calls.clear()
        code = main(
            [
                "--repo-root",
                str(repo),
                "--dry-run",
                "capacity",
                *arguments,
            ]
        )

        assert code == 17
        assert calls == [(method, expected_args, expected_kwargs)]
        assert initializations[-1] == {
            "repo_root": repo,
            "output_dir": None,
            "dry_run": True,
        }


def test_capacity_cli_forwards_all_live_adapters_for_runner_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, calls = _install_capacity_runner(monkeypatch, return_code=3)
    live_adapters = (
        "market=live",
        "wallet=live",
        "cloud=live",
        "host=live",
        "provisioning=live",
        "github-mutation=live",
    )
    adapter_arguments = [
        item for adapter in live_adapters for item in ("--adapter", adapter)
    ]

    code = main(
        [
            "--repo-root",
            str(tmp_path),
            "capacity",
            "evaluate",
            "result.json",
            "--scenario",
            "scenario.json",
            "--repository",
            "example/public-repository",
            "--branch",
            "replacement-branch",
            "--sha",
            "a" * 40,
            "--run-id",
            "capacity-run",
            "--timeout-seconds",
            "45",
            *adapter_arguments,
        ]
    )

    assert code == 3
    assert calls[0][2]["adapters"] == live_adapters


def test_capacity_context_requires_at_least_one_adapter() -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(
            [
                "capacity",
                "evaluate",
                "result.json",
                "--scenario",
                "scenario.json",
                "--repository",
                "example/public-repository",
                "--branch",
                "replacement-branch",
                "--sha",
                "a" * 40,
                "--run-id",
                "capacity-run",
                "--timeout-seconds",
                "45",
            ]
        )

    assert exc_info.value.code == 2


def test_capacity_cli_emits_real_stable_json_and_typed_invalid_input(
    tmp_path: Path,
    capsys,
) -> None:
    root = repo_root()
    scenario = "tools/issue-discovery/config/capacity/b2-g1-contention.json"

    assert main(["--repo-root", str(root), "capacity", "validate", scenario]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["command"] == "capacity.validate"
    assert validated["status"] == "ok"
    assert validated["result"] == {"valid": True}

    assert main(["--repo-root", str(root), "capacity", "hash", scenario]) == 0
    first = capsys.readouterr().out
    assert main(["--repo-root", str(root), "capacity", "hash", scenario]) == 0
    assert capsys.readouterr().out == first

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    assert (
        main(
            [
                "--repo-root",
                str(root),
                "capacity",
                "validate",
                str(malformed),
            ]
        )
        == 2
    )
    invalid = json.loads(capsys.readouterr().out)
    assert invalid["status"] == "error"
    assert invalid["error"] == {"code": "input-unavailable-or-invalid"}

    assert (
        main(
            [
                "--repo-root",
                str(root),
                "capacity",
                "evaluate",
                "missing-result.json",
                "--scenario",
                scenario,
                "--repository",
                "arkhai-io/simple-compute-market",
                "--branch",
                "feat/issue-discovery-harness-post-pools",
                "--sha",
                "a" * 40,
                "--run-id",
                "capacity-run",
                "--timeout-seconds",
                "not-a-number",
                "--adapter",
                "market=mock",
            ]
        )
        == 2
    )
    invalid_timeout = json.loads(capsys.readouterr().out)
    assert invalid_timeout["command"] == "capacity.evaluate"
    assert invalid_timeout["status"] == "error"
    assert invalid_timeout["error"] == {"code": "invalid-run-context"}


def test_issue_create_has_independent_dry_run(tmp_path: Path, capsys) -> None:
    run_dir = tmp_path / "run"
    issue_dir = run_dir / "issue-candidates"
    issue_dir.mkdir(parents=True)
    (issue_dir / "candidate.md").write_text("# Candidate\n", encoding="utf-8")
    (issue_dir / "candidates.jsonl").write_text(
        '{"fingerprint":"fingerprint","title":"Candidate","labels":["bug"],'
        '"classification":"test","phase":"phase","body_file":"issue-candidates/candidate.md",'
        '"evidence":[],"state":"ready_to_file"}\n',
        encoding="utf-8",
    )

    code = main(
        [
            "--repo-root",
            str(tmp_path),
            "issue",
            "create",
            str(run_dir),
            "fingerprint",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "gh issue create" in captured.out
    assert f"cd {tmp_path}" in captured.out
    assert "--body-file" in captured.out


def test_issue_create_force_allows_non_ready_dry_run(tmp_path: Path, capsys) -> None:
    run_dir = tmp_path / "run"
    issue_dir = run_dir / "issue-candidates"
    issue_dir.mkdir(parents=True)
    (issue_dir / "candidate.md").write_text("# Candidate\n", encoding="utf-8")
    (issue_dir / "candidates.jsonl").write_text(
        '{"fingerprint":"fingerprint","title":"Candidate","labels":["bug"],'
        '"classification":"test","phase":"phase","body_file":"issue-candidates/candidate.md",'
        '"evidence":[],"state":"needs_targeted_repro"}\n',
        encoding="utf-8",
    )

    code = main(
        [
            "--repo-root",
            str(tmp_path),
            "issue",
            "create",
            str(run_dir),
            "fingerprint",
            "--dry-run",
            "--force",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "gh issue create" in captured.out


def test_issue_commands_resolve_relative_run_dir_from_repo_root(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    run_dir = repo / ".scm-local" / "issue-discovery" / "runs" / "run"
    issue_dir = run_dir / "issue-candidates"
    issue_dir.mkdir(parents=True)
    (issue_dir / "candidate.md").write_text("# Candidate\n", encoding="utf-8")
    (issue_dir / "candidates.jsonl").write_text(
        '{"fingerprint":"fingerprint","title":"Candidate","labels":["bug"],'
        '"classification":"test","phase":"phase","body_file":"issue-candidates/candidate.md",'
        '"evidence":[],"state":"ready_to_file"}\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "--repo-root",
            str(repo),
            "issue",
            "list",
            ".scm-local/issue-discovery/runs/run",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "fingerprint" in captured.out


def test_clean_room_plan_prints_ladder(capsys) -> None:
    code = main(["--repo-root", str(repo_root()), "clean-room", "plan", "local-vm"])

    captured = capsys.readouterr()
    assert code == 0
    assert "clean-room sequence: local-vm" in captured.out
    assert "strict: ./scripts/issue-discovery strict" in captured.out
    assert (
        "continue-build-redis-and-storefront-volume: "
        "./scripts/issue-discovery continue --with local_stack_build_without_zerotier "
        "--with redis_no_host_port --with storefront_volume_chown" in captured.out
    )


def test_clean_room_script_prints_executable_shell(capsys) -> None:
    code = main(["--repo-root", str(repo_root()), "clean-room", "script", "local-vm"])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.startswith("#!/usr/bin/env bash")
    assert "run_step strict true ./scripts/issue-discovery strict" in captured.out
    assert "SCM_CLEAN_ROOM_STATUS_FILE" in captured.out


def test_clean_room_unknown_sequence_exits_nonzero(capsys) -> None:
    code = main(["--repo-root", str(repo_root()), "clean-room", "plan", "missing"])

    captured = capsys.readouterr()
    assert code == 2
    assert "unknown clean-room sequence: missing" in captured.out
