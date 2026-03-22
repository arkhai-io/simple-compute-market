from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/cleanup_human_purchase.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("cleanup_human_purchase", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_order_close_command_uses_sandbox_market_binary_and_env_file(tmp_path: Path) -> None:
    module = _load_script_module()

    command = module.build_order_close_command(
        sandbox_dir=tmp_path,
        order_id="order-1",
        agent_url="http://127.0.0.1:28001/",
        side="buyer",
    )

    assert command == [
        str(tmp_path / "venv/bin/market"),
        "order",
        "close",
        "order-1",
        "--agent-url",
        "http://127.0.0.1:28001/",
        "--env",
        str(tmp_path / "buyer.env"),
    ]


def test_cleanup_purchase_closes_orders_and_reclaims_vm(tmp_path: Path, monkeypatch) -> None:
    module = _load_script_module()
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir()
    context_path = sandbox_dir / "context.json"
    context_path.write_text(
        json.dumps(
            {
                "sandbox_dir": str(sandbox_dir),
                "provisioning_url": "http://127.0.0.1:28081/",
                "buyer_agent_url": "http://127.0.0.1:28001/",
                "seller_agent_url": "http://127.0.0.1:28002/",
                "seller_agent_id": "seller-id",
            }
        ),
        encoding="utf-8",
    )

    commands: list[list[str]] = []
    submitted: list[dict[str, str]] = []
    monkeypatch.setattr(module, "_run_command", lambda command: commands.append(command))
    monkeypatch.setattr(
        module,
        "fetch_job",
        lambda provisioning_url, agent_id, job_id: {
            "job_id": job_id,
            "params": {"vm_host": "btc1", "vm_target": "tenant-4e71"},
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

    result = module.cleanup_purchase(
        context_path=context_path,
        seller_order_id="seller-order",
        buyer_order_id="buyer-order",
        job_id="create-job",
        timeout_seconds=60.0,
        poll_seconds=1.0,
    )

    assert commands == [
        [
            str(sandbox_dir / "venv/bin/market"),
            "order",
            "close",
            "seller-order",
            "--agent-url",
            "http://127.0.0.1:28002/",
            "--env",
            str(sandbox_dir / "seller.env"),
        ],
        [
            str(sandbox_dir / "venv/bin/market"),
            "order",
            "close",
            "buyer-order",
            "--agent-url",
            "http://127.0.0.1:28001/",
            "--env",
            str(sandbox_dir / "buyer.env"),
        ],
    ]
    assert submitted == [
        {
            "provisioning_url": "http://127.0.0.1:28081/",
            "seller_agent_id": "seller-id",
            "vm_host": "btc1",
            "vm_target": "tenant-4e71",
            "vm_action": "destroy",
        },
        {
            "provisioning_url": "http://127.0.0.1:28081/",
            "seller_agent_id": "seller-id",
            "vm_host": "btc1",
            "vm_target": "tenant-4e71",
            "vm_action": "undefine",
        },
    ]
    assert result["create_job_id"] == "create-job"
    assert result["reclaim_actions"] == [
        {"job_id": "destroy-job", "status": "succeeded"},
        {"job_id": "undefine-job", "status": "succeeded"},
    ]
