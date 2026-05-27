from __future__ import annotations

import json
from pathlib import Path

from issue_discovery.cli import main


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def write_failed_run(
    run_dir: Path,
    *,
    stderr_text: str,
    classifiers: list[str],
) -> None:
    phase_id = "compose_start_strict"
    command_id = "compose_up"
    command_dir = run_dir / "commands" / phase_id
    command_dir.mkdir(parents=True)
    (command_dir / f"{command_id}.stdout.txt").write_text("", encoding="utf-8")
    (command_dir / f"{command_id}.stderr.txt").write_text(stderr_text, encoding="utf-8")
    (command_dir / f"{command_id}.meta.json").write_text(
        json.dumps({"exit_code": 1, "timed_out": False}),
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "synthetic-run",
                "mode": "strict",
                "status": "failed",
                "phase_file": "tools/issue-discovery/config/phases/local.yaml",
                "output_dir": str(run_dir),
                "started_at": "2026-05-26T00:00:00Z",
                "completed_at": "2026-05-26T00:00:01Z",
            }
        ),
        encoding="utf-8",
    )
    write_jsonl(
        run_dir / "phases.jsonl",
        [
            {
                "id": phase_id,
                "name": "Strict compose startup",
                "category": "runtime",
                "blocking": True,
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


def assert_tracking_flow(
    tmp_path: Path,
    capsys,
    *,
    stderr_text: str,
    classifiers: list[str],
    expected_fingerprint: str,
) -> None:
    run_dir = tmp_path / "run"
    repo_root = tmp_path / "repo"
    run_dir.mkdir()
    repo_root.mkdir()
    write_failed_run(run_dir, stderr_text=stderr_text, classifiers=classifiers)

    list_code = main(["--repo-root", str(repo_root), "issue", "list", str(run_dir)])
    list_output = capsys.readouterr().out
    assert list_code == 0
    assert expected_fingerprint in list_output
    assert "runtime" in list_output
    assert "compose_start_strict" in list_output

    show_code = main(["--repo-root", str(repo_root), "issue", "show", str(run_dir), expected_fingerprint])
    show_output = capsys.readouterr().out
    assert show_code == 0
    assert "Run `./scripts/issue-discovery strict`." in show_output
    assert "The phase failed at command `compose_up`." in show_output
    assert "`commands/compose_start_strict/compose_up.stderr.txt`" in show_output
    assert "super-secret-admin-key" not in show_output

    create_code = main(
        [
            "--repo-root",
            str(repo_root),
            "issue",
            "create",
            str(run_dir),
            expected_fingerprint,
            "--dry-run",
        ]
    )
    create_output = capsys.readouterr().out
    assert create_code == 0
    assert f"cd {repo_root}" in create_output
    assert "gh issue create" in create_output
    assert f"--body-file {run_dir}/issue-candidates/{expected_fingerprint}.md" in create_output
    assert "--label runtime" in create_output
    assert "super-secret-admin-key" not in create_output


def test_issue_tracking_flow_for_known_classifier(tmp_path: Path, capsys) -> None:
    assert_tracking_flow(
        tmp_path,
        capsys,
        stderr_text=(
            "Error response from daemon: driver failed programming external connectivity "
            "on endpoint redis: Bind for 0.0.0.0:6379 failed: port is already allocated; "
            "super-secret-admin-key"
        ),
        classifiers=["redis_host_port_conflict", "storefront_volume_ownership"],
        expected_fingerprint="redis-host-port-conflict",
    )


def test_issue_tracking_flow_for_generic_fallback(tmp_path: Path, capsys) -> None:
    assert_tracking_flow(
        tmp_path,
        capsys,
        stderr_text="compose failed for an unexpected reason; super-secret-admin-key",
        classifiers=["redis_host_port_conflict", "storefront_volume_ownership"],
        expected_fingerprint="compose-start-strict-compose-up",
    )
