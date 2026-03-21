from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts/prod_canary_rollback.py"
SELLER_AGENT_ID = "eip155:84532:0x1111111111111111111111111111111111111111:101"
BUYER_AGENT_ID = "eip155:84532:0x1111111111111111111111111111111111111111:202"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("prod_canary_rollback", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_rollback_module():
    import market.canary_rollback as rollback

    return rollback


def test_extract_state_from_log_reads_emitted_ids() -> None:
    module = _load_rollback_module()

    state = module._extract_state_from_log(
        "\n".join(
            [
                "[order] seller order: seller-order",
                "noise",
                "[order] buyer order: buyer-order",
                "[provisioning] succeeded job: job-1",
            ]
        )
    )

    assert state == module.RollbackState(
        seller_order_id="seller-order",
        buyer_order_id="buyer-order",
        provisioning_job_id="job-1",
        vm_host=None,
        vm_target=None,
    )


def test_rollback_coordinator_cancels_running_job_and_closes_only_open_orders() -> None:
    module = _load_rollback_module()
    events: list[object] = []

    class FakeGateway(module.CanaryRollbackGateway):
        def fetch_job(self, provisioning_url: str, job_id: str, agent_id: str) -> dict:
            events.append(("job:get", provisioning_url, job_id, agent_id))
            return {
                "job_id": job_id,
                "status": "running",
                "params": {"vm_host": "btc1", "vm_target": "tenant-d908"},
            }

        def cancel_job(self, provisioning_url: str, job_id: str, agent_id: str) -> dict:
            events.append(("job:cancel", provisioning_url, job_id, agent_id))
            return {"job_id": job_id, "status": "cancelled", "message": "Job cancelled successfully"}

        def submit_job(self, *, provisioning_url: str, agent_id: str, payload: dict) -> dict:
            raise AssertionError("reclaim jobs should not run after a successful cancel")

        def fetch_order(self, registry_url: str, order_id: str) -> dict:
            events.append(("order:get", registry_url, order_id))
            status = "open" if order_id == "seller-order" else "closed"
            return {"order_id": order_id, "status": status}

        def close_order(
            self,
            *,
            registry_url: str,
            order_id: str,
            signer_agent_id: str,
            private_key: str,
        ) -> dict:
            events.append(("order:close", registry_url, order_id, signer_agent_id, private_key))
            return {"order": {"order_id": order_id, "status": "closed"}}

    config = module.RollbackConfig(
        registry_url="http://100.64.0.10:8080",
        provisioning_url="http://100.64.0.11:8081",
        seller_agent_id=SELLER_AGENT_ID,
        buyer_agent_id=BUYER_AGENT_ID,
        seller_private_key="0x" + ("c" * 64),
        buyer_private_key="0x" + ("d" * 64),
        seller_order_id="seller-order",
        buyer_order_id="buyer-order",
        provisioning_job_id="job-1",
    )

    result = module.RollbackCoordinator(config=config, gateway=FakeGateway()).run()

    assert result == {
        "status": "completed",
        "state": {
            "seller_order_id": "seller-order",
            "buyer_order_id": "buyer-order",
            "provisioning_job_id": "job-1",
            "vm_host": "btc1",
            "vm_target": "tenant-d908",
        },
        "provisioning": {
            "initial_status": "running",
            "cancel_result": {
                "job_id": "job-1",
                "status": "cancelled",
                "message": "Job cancelled successfully",
            },
            "reclaim_actions": [],
        },
        "orders": {
            "seller": {
                "order_id": "seller-order",
                "status_before": "open",
                "closed": True,
            },
            "buyer": {
                "order_id": "buyer-order",
                "status_before": "closed",
                "closed": False,
            },
        },
    }
    assert events == [
        ("job:get", "http://100.64.0.11:8081", "job-1", SELLER_AGENT_ID),
        ("job:cancel", "http://100.64.0.11:8081", "job-1", SELLER_AGENT_ID),
        ("order:get", "http://100.64.0.10:8080", "seller-order"),
        (
            "order:close",
            "http://100.64.0.10:8080",
            "seller-order",
            SELLER_AGENT_ID,
            "0x" + ("c" * 64),
        ),
        ("order:get", "http://100.64.0.10:8080", "buyer-order"),
    ]


def test_rollback_coordinator_reclaims_vm_after_terminal_job() -> None:
    module = _load_rollback_module()
    events: list[object] = []

    class FakeGateway(module.CanaryRollbackGateway):
        def fetch_job(self, provisioning_url: str, job_id: str, agent_id: str) -> dict:
            events.append(("job:get", provisioning_url, job_id, agent_id))
            return {
                "job_id": job_id,
                "status": "succeeded",
                "params": {"vm_host": "btc1", "vm_target": "tenant-d908"},
                "result": {"vm_name": "tenant-d908"},
            }

        def cancel_job(self, provisioning_url: str, job_id: str, agent_id: str) -> dict:
            raise AssertionError("terminal jobs should not be cancelled")

        def submit_job(self, *, provisioning_url: str, agent_id: str, payload: dict) -> dict:
            events.append(("job:submit", provisioning_url, agent_id, payload))
            return {"job_id": f"{payload['vm_action']}-job", "status": "queued", "params": payload}

        def fetch_order(self, registry_url: str, order_id: str) -> dict:
            events.append(("order:get", registry_url, order_id))
            return {"order_id": order_id, "status": "open"}

        def close_order(
            self,
            *,
            registry_url: str,
            order_id: str,
            signer_agent_id: str,
            private_key: str,
        ) -> dict:
            events.append(("order:close", registry_url, order_id, signer_agent_id, private_key))
            return {"order": {"order_id": order_id, "status": "closed"}}

    config = module.RollbackConfig(
        registry_url="http://100.64.0.10:8080",
        provisioning_url="http://100.64.0.11:8081",
        seller_agent_id=SELLER_AGENT_ID,
        buyer_agent_id=BUYER_AGENT_ID,
        seller_private_key="0x" + ("c" * 64),
        buyer_private_key="0x" + ("d" * 64),
        seller_order_id="seller-order",
        buyer_order_id="buyer-order",
        provisioning_job_id="job-1",
    )

    result = module.RollbackCoordinator(config=config, gateway=FakeGateway()).run()

    assert result["provisioning"] == {
        "initial_status": "succeeded",
        "cancel_result": None,
        "reclaim_actions": [
            {
                "job_id": "destroy-job",
                "status": "queued",
                "params": {
                    "vm_host": "btc1",
                    "vm_target": "tenant-d908",
                    "vm_action": "destroy",
                },
            },
            {
                "job_id": "undefine-job",
                "status": "queued",
                "params": {
                    "vm_host": "btc1",
                    "vm_target": "tenant-d908",
                    "vm_action": "undefine",
                },
            },
        ],
    }
    assert events == [
        ("job:get", "http://100.64.0.11:8081", "job-1", SELLER_AGENT_ID),
        (
            "job:submit",
            "http://100.64.0.11:8081",
            SELLER_AGENT_ID,
            {"vm_host": "btc1", "vm_target": "tenant-d908", "vm_action": "destroy"},
        ),
        (
            "job:submit",
            "http://100.64.0.11:8081",
            SELLER_AGENT_ID,
            {"vm_host": "btc1", "vm_target": "tenant-d908", "vm_action": "undefine"},
        ),
        ("order:get", "http://100.64.0.10:8080", "seller-order"),
        (
            "order:close",
            "http://100.64.0.10:8080",
            "seller-order",
            SELLER_AGENT_ID,
            "0x" + ("c" * 64),
        ),
        ("order:get", "http://100.64.0.10:8080", "buyer-order"),
        (
            "order:close",
            "http://100.64.0.10:8080",
            "buyer-order",
            BUYER_AGENT_ID,
            "0x" + ("d" * 64),
        ),
    ]


def test_script_wrapper_delegates_to_market_canary_rollback_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str] | None] = []
    stub = types.ModuleType("market.canary_rollback")

    def fake_main(argv=None):
        calls.append(list(argv) if argv is not None else None)
        return 23

    stub.main = fake_main
    monkeypatch.setitem(sys.modules, "market.canary_rollback", stub)

    module = _load_script_module()

    assert module.main(["--log-path", "/tmp/prod-canary.log"]) == 23
    assert calls == [["--log-path", "/tmp/prod-canary.log"]]
