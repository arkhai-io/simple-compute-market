from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/wait_for_human_purchase.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("wait_for_human_purchase", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_select_create_job_prefers_latest_match_for_buyer_agent() -> None:
    module = _load_script_module()
    jobs = [
        {
            "job_id": "latest-match",
            "status": "running",
            "params": {"vm_action": "create", "buyer_agent_id": "buyer-7"},
        },
        {
            "job_id": "other-buyer",
            "status": "running",
            "params": {"vm_action": "create", "buyer_agent_id": "buyer-8"},
        },
        {
            "job_id": "older-match",
            "status": "succeeded",
            "params": {"vm_action": "create", "buyer_agent_id": "buyer-7"},
        },
    ]

    selected = module.select_create_job(jobs=jobs, buyer_agent_id="buyer-7")

    assert selected["job_id"] == "latest-match"


def test_select_create_job_ignores_terminal_jobs_older_than_current_order() -> None:
    module = _load_script_module()
    jobs = [
        {
            "job_id": "stale-terminal",
            "status": "succeeded",
            "params": {"vm_action": "create", "buyer_agent_id": "buyer-7"},
            "result": {"timestamp": "2026-03-22T20:10:48Z"},
        },
        {
            "job_id": "fresh-running",
            "status": "running",
            "params": {"vm_action": "create", "buyer_agent_id": "buyer-7"},
        },
    ]

    selected = module.select_create_job(
        jobs=jobs,
        buyer_agent_id="buyer-7",
        order_created_at="2026-03-22T20:46:51.027026+00:00",
    )

    assert selected["job_id"] == "fresh-running"


def test_build_ssh_probe_command_uses_local_key_and_known_hosts_path(tmp_path: Path) -> None:
    module = _load_script_module()
    known_hosts = tmp_path / "known_hosts"

    command = module.build_ssh_probe_command(
        ssh_command="ssh -i <your_private_key> -p 7004 tenant4e71@example.nip.io",
        ssh_private_key_path="/tmp/tenant-key",
        known_hosts_path=known_hosts,
    )

    assert command[:6] == [
        "ssh",
        "-i",
        "/tmp/tenant-key",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
    ]
    assert f"UserKnownHostsFile={known_hosts}" in command
    assert "-p" in command
    assert "7004" in command
    assert command[-1] == "echo connected && hostname && whoami"
