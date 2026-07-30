from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from issue_discovery.capacity import CapacityValidationError
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


def test_capacity_scenario_sha256_prints_machine_readable_digest(
    capsys,
    monkeypatch,
) -> None:
    root = repo_root()
    scm_ref = "a" * 40
    scenario = "tools/issue-discovery/config/capacity/scenarios/b1-s1-g1.json"
    digest = "b" * 64
    call: dict[str, object] = {}

    def fake_resolve(
        repository: Path,
        selected_ref: str,
        relative_path: str,
        expected_sha256: str | None = None,
    ) -> SimpleNamespace:
        call.update(
            {
                "repository": repository,
                "selected_ref": selected_ref,
                "relative_path": relative_path,
                "expected_sha256": expected_sha256,
            }
        )
        return SimpleNamespace(
            scenario_id="b1-s1-g1",
            scm_ref=selected_ref,
            relative_path=relative_path,
            scenario_sha256=digest,
            scenario={"scenario_id": "b1-s1-g1"},
        )

    monkeypatch.setattr("issue_discovery.runner.resolve_pinned_scenario", fake_resolve)

    code = main(
        [
            "--repo-root",
            str(root),
            "capacity",
            "scenario-sha256",
            scenario,
            "--scm-ref",
            scm_ref,
        ]
    )

    output = capsys.readouterr().out.strip()
    assert code == 0
    assert output == digest
    assert call == {
        "repository": root,
        "selected_ref": scm_ref,
        "relative_path": scenario,
        "expected_sha256": None,
    }


def test_capacity_scenario_validate_prints_exact_pinned_identity(
    capsys,
    monkeypatch,
) -> None:
    root = repo_root()
    scm_ref = "c" * 40
    scenario = "tools/issue-discovery/config/capacity/scenarios/b2-s1-g1.json"
    digest = "d" * 64

    def fake_resolve(
        repository: Path,
        selected_ref: str,
        relative_path: str,
        expected_sha256: str | None = None,
    ) -> SimpleNamespace:
        assert repository == root
        assert selected_ref == scm_ref
        assert relative_path == scenario
        assert expected_sha256 == digest
        return SimpleNamespace(
            scenario_id="b2-s1-g1",
            scm_ref=selected_ref,
            relative_path=relative_path,
            scenario_sha256=digest,
            scenario={"scenario_id": "b2-s1-g1"},
        )

    monkeypatch.setattr("issue_discovery.runner.resolve_pinned_scenario", fake_resolve)

    code = main(
        [
            "--repo-root",
            str(root),
            "capacity",
            "scenario-validate",
            scenario,
            "--scm-ref",
            scm_ref,
            "--expected-sha256",
            digest,
        ]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {
        "relative_path": scenario,
        "scenario_id": "b2-s1-g1",
        "scenario_sha256": digest,
        "scm_ref": scm_ref,
    }


@pytest.mark.parametrize(
    "arguments",
    [
        [
            "capacity",
            "scenario-sha256",
            "tools/issue-discovery/config/capacity/scenarios/b1-s1-g1.json",
        ],
        [
            "capacity",
            "scenario-validate",
            "tools/issue-discovery/config/capacity/scenarios/b1-s1-g1.json",
            "--scm-ref",
            "a" * 40,
        ],
        [
            "capacity",
            "scenario-validate",
            "tools/issue-discovery/config/capacity/scenarios/b1-s1-g1.json",
            "--expected-sha256",
            "b" * 64,
        ],
    ],
)
def test_capacity_scenario_commands_require_explicit_authority(
    arguments: list[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(arguments)

    assert exc_info.value.code == 2


def test_capacity_scenario_cli_does_not_resolve_caller_path(
    capsys,
    monkeypatch,
) -> None:
    supplied_path = "/tmp/operator-selected.json"
    scm_ref = "a" * 40

    def reject_absolute(
        repository: Path,
        selected_ref: str,
        relative_path: str,
        expected_sha256: str | None = None,
    ) -> SimpleNamespace:
        assert repository == repo_root()
        assert selected_ref == scm_ref
        assert relative_path == supplied_path
        assert expected_sha256 is None
        raise CapacityValidationError("scenario path must be repository-relative")

    monkeypatch.setattr("issue_discovery.runner.resolve_pinned_scenario", reject_absolute)

    code = main(
        [
            "--repo-root",
            str(repo_root()),
            "capacity",
            "scenario-sha256",
            supplied_path,
            "--scm-ref",
            scm_ref,
        ]
    )

    assert code == 1
    assert capsys.readouterr().out == (
        "capacity scenario invalid: scenario path must be repository-relative\n"
    )


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
        "--with redis_no_host_port --with storefront_volume_chown"
        in captured.out
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
