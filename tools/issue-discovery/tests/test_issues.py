from __future__ import annotations

import json
from pathlib import Path

from issue_discovery.issues import IssuePacketGenerator


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def write_run(
    run_dir: Path,
    *,
    stderr_text: str,
    classifiers: list[str],
    phase_id: str = "compose_start_strict",
    command_id: str = "compose_up",
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
