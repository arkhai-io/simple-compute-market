from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/run_market_support.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("run_market_support", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_inspect_support_case_builds_shared_artifact(tmp_path: Path, monkeypatch) -> None:
    module = _load_script_module()
    context_path = tmp_path / "context.json"
    _write_json(
        context_path,
        {
            "registry_url": "http://127.0.0.1:28080/",
            "provisioning_url": "http://127.0.0.1:28081/",
            "seller_agent_id": "seller-agent",
            "buyer_agent_id": "buyer-agent",
            "seller_agent_url": "http://10.243.0.68:8000/",
            "buyer_agent_url": "http://10.243.0.117:8000/",
        },
    )

    monkeypatch.setattr(
        module,
        "fetch_order",
        lambda registry_url, order_id: {
            "order_id": order_id,
            "status": "accepted",
            "created_at": "2026-03-23T10:00:00+00:00",
        },
    )
    monkeypatch.setattr(
        module,
        "list_jobs",
        lambda provisioning_url, agent_id, limit=100: [
            {
                "job_id": "job-1",
                "status": "succeeded",
                "params": {
                    "vm_action": "create",
                    "buyer_agent_id": "buyer-agent",
                    "vm_host": "ww1",
                    "vm_target": "tenant-1234",
                },
                "result": {"timestamp": "2026-03-23T10:05:00Z"},
            }
        ],
    )
    monkeypatch.setattr(
        module,
        "select_create_job",
        lambda *, jobs, buyer_agent_id, order_created_at=None: jobs[0],
    )
    monkeypatch.setattr(
        module,
        "fetch_job",
        lambda provisioning_url, agent_id, job_id: {
            "job_id": job_id,
            "status": "succeeded",
            "params": {"vm_host": "ww1", "vm_target": "tenant-1234"},
            "result": {"status": "success"},
        },
    )

    result = module.inspect_support_case(
        context_path=context_path,
        seller_order_id="seller-order-1",
        buyer_order_id="buyer-order-1",
    )

    assert result["role"] == "support"
    assert result["action"] == "inspect"
    assert result["status"] == "succeeded"
    assert result["correlation"]["order_id"] == "buyer-order-1"
    assert result["correlation"]["job_id"] == "job-1"
    assert result["correlation"]["vm_target"] == "tenant-1234"
    assert result["details"]["seller_order_status"] == "accepted"
    assert result["details"]["buyer_order_status"] == "accepted"
    assert result["details"]["job_status"] == "succeeded"
    assert Path(result["artifact_path"]).exists()


def test_cleanup_support_case_reclaims_vm_and_reports_artifact(tmp_path: Path, monkeypatch) -> None:
    module = _load_script_module()
    context_path = tmp_path / "context.json"
    _write_json(
        context_path,
        {
            "sandbox_dir": str(tmp_path),
            "registry_url": "http://127.0.0.1:28080/",
            "provisioning_url": "http://127.0.0.1:28081/",
            "seller_agent_id": "seller-agent",
            "buyer_agent_id": "buyer-agent",
            "seller_agent_url": "http://10.243.0.68:8000/",
            "buyer_agent_url": "http://10.243.0.117:8000/",
        },
    )
    (tmp_path / "seller.env").write_text("AGENT_PRIV_KEY=0xseller\n", encoding="utf-8")
    (tmp_path / "buyer.env").write_text("AGENT_PRIV_KEY=0xbuyer\n", encoding="utf-8")

    commands: list[list[str]] = []
    submitted: list[dict[str, str]] = []
    monkeypatch.setattr(module, "_run_command", lambda command: commands.append(command))
    monkeypatch.setattr(
        module,
        "fetch_order",
        lambda registry_url, order_id: {
            "order_id": order_id,
            "status": "accepted",
        },
    )
    monkeypatch.setattr(
        module,
        "fetch_job",
        lambda provisioning_url, agent_id, job_id: {
            "job_id": job_id,
            "params": {"vm_host": "ww1", "vm_target": "tenant-1234"},
        },
    )
    monkeypatch.setattr(
        module,
        "submit_reclaim_job",
        lambda *, provisioning_url, seller_agent_id, vm_host, vm_target, vm_action: submitted.append(
            {
                "provisioning_url": provisioning_url,
                "seller_agent_id": seller_agent_id,
                "vm_host": vm_host,
                "vm_target": vm_target,
                "vm_action": vm_action,
            }
        )
        or {"job_id": f"{vm_action}-job", "status": "queued"},
    )
    monkeypatch.setattr(
        module,
        "wait_for_job_terminal_state",
        lambda *, provisioning_url, agent_id, job_id, timeout_seconds, poll_seconds: {
            "job_id": job_id,
            "status": "succeeded",
        },
    )

    result = module.cleanup_support_case(
        context_path=context_path,
        seller_order_id="seller-order-1",
        buyer_order_id="buyer-order-1",
        job_id="create-job",
        timeout_seconds=60.0,
        poll_seconds=1.0,
    )

    assert commands == [
        [
            str(tmp_path / "venv/bin/market"),
            "order",
            "close",
            "seller-order-1",
            "--agent-url",
            "http://10.243.0.68:8000/",
            "--env",
            str(tmp_path / "seller.env"),
        ],
        [
            str(tmp_path / "venv/bin/market"),
            "order",
            "close",
            "buyer-order-1",
            "--agent-url",
            "http://10.243.0.117:8000/",
            "--env",
            str(tmp_path / "buyer.env"),
        ],
    ]
    assert submitted == [
        {
            "provisioning_url": "http://127.0.0.1:28081/",
            "seller_agent_id": "seller-agent",
            "vm_host": "ww1",
            "vm_target": "tenant-1234",
            "vm_action": "destroy",
        },
        {
            "provisioning_url": "http://127.0.0.1:28081/",
            "seller_agent_id": "seller-agent",
            "vm_host": "ww1",
            "vm_target": "tenant-1234",
            "vm_action": "undefine",
        },
    ]
    assert result["role"] == "support"
    assert result["action"] == "cleanup"
    assert result["status"] == "succeeded"
    assert result["correlation"]["order_id"] == "buyer-order-1"
    assert result["correlation"]["job_id"] == "create-job"
    assert result["correlation"]["vm_target"] == "tenant-1234"
    assert result["details"]["vm_host"] == "ww1"
    assert result["details"]["reclaim_actions"] == [
        {"job_id": "destroy-job", "status": "succeeded"},
        {"job_id": "undefine-job", "status": "succeeded"},
    ]
    assert Path(result["artifact_path"]).exists()
