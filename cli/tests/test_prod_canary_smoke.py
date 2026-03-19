from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts/prod_canary_smoke.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("prod_canary_smoke", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_canary_module():
    import market.canary as canary

    return canary


def test_verify_ssh_skips_without_private_key() -> None:
    module = _load_canary_module()
    module._verify_ssh([], None)


def test_verify_ssh_builds_expected_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_canary_module()
    ssh_key = tmp_path / "id_ed25519"
    ssh_key.write_text("key", encoding="utf-8")
    observed: list[list[str]] = []

    def fake_run(parts: list[str], check: bool) -> None:
        assert check is True
        observed.append(parts)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    module._verify_ssh(
        [
            {
                "role": "tenant",
                "ssh_commands": {"external": "ssh ubuntu@100.64.0.55"},
            }
        ],
        str(ssh_key),
    )

    assert observed == [
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-i",
            str(ssh_key),
            "ubuntu@100.64.0.55",
            "hostname",
        ]
    ]


def test_main_runs_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_canary_module()
    created_orders: list[dict] = []
    requested_urls: list[str] = []
    verified_credentials: list[list[dict]] = []

    monkeypatch.setattr(module, "_check_health", lambda label, url: {"label": label, "url": url})
    monkeypatch.setattr(
        module,
        "_request_json",
        lambda method, url, **kwargs: requested_urls.append(url) or {},
    )
    monkeypatch.setattr(module, "_fetch_agent_orders", lambda registry_url, agent_id: [])
    monkeypatch.setattr(module, "_list_jobs", lambda provisioning_url, agent_id: [])
    monkeypatch.setattr(
        module,
        "_create_order",
        lambda **kwargs: created_orders.append(kwargs),
    )
    monkeypatch.setattr(
        module,
        "_wait_for_new_order",
        lambda **kwargs: "seller-order" if kwargs["agent_id"] == "seller-agent" else "buyer-order",
    )
    monkeypatch.setattr(
        module,
        "_wait_for_new_succeeded_job",
        lambda **kwargs: {"job_id": "job-1", "status": "succeeded"},
    )
    monkeypatch.setattr(
        module,
        "_fetch_credentials",
        lambda provisioning_url, job_id, agent_id: [
            {"role": "tenant", "ssh_commands": {"external": "ssh ubuntu@100.64.0.55"}}
        ],
    )
    monkeypatch.setattr(
        module,
        "_verify_ssh",
        lambda credentials, ssh_private_key_path: verified_credentials.append(credentials),
    )
    monkeypatch.setattr(
        module,
        "_wait_for_orders_closed",
        lambda **kwargs: {
            "seller-order": {"status": "closed"},
            "buyer-order": {"status": "closed"},
        },
    )

    exit_code = module.main(
        [
            "--registry-url",
            "http://100.64.0.10:8080",
            "--provisioning-url",
            "http://100.64.0.11:8081",
            "--seller-agent-url",
            "http://100.64.0.50:8001",
            "--buyer-agent-url",
            "http://100.64.0.51:8000",
            "--seller-agent-id",
            "seller-agent",
            "--buyer-agent-id",
            "buyer-agent",
            "--seller-private-key",
            "0xcccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            "--buyer-private-key",
            "0xdddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        ]
    )

    assert exit_code == 0
    assert len(created_orders) == 2
    assert requested_urls == [
        "http://100.64.0.50:8001/.well-known/agent-card.json",
        "http://100.64.0.51:8000/.well-known/agent-card.json",
    ]
    assert len(verified_credentials) == 1


def test_main_creates_seller_then_buyer_orders_with_expected_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_canary_module()
    created_orders: list[dict] = []

    monkeypatch.setattr(module, "_check_health", lambda label, url: {"label": label, "url": url})
    monkeypatch.setattr(module, "_request_json", lambda method, url, **kwargs: {})
    monkeypatch.setattr(module, "_fetch_agent_orders", lambda registry_url, agent_id: [])
    monkeypatch.setattr(module, "_list_jobs", lambda provisioning_url, agent_id: [])
    monkeypatch.setattr(module, "_create_order", lambda **kwargs: created_orders.append(kwargs))
    monkeypatch.setattr(
        module,
        "_wait_for_new_order",
        lambda **kwargs: "seller-order" if kwargs["agent_id"] == "seller-agent" else "buyer-order",
    )
    monkeypatch.setattr(
        module,
        "_wait_for_new_succeeded_job",
        lambda **kwargs: {"job_id": "job-1", "status": "succeeded"},
    )
    monkeypatch.setattr(
        module,
        "_fetch_credentials",
        lambda provisioning_url, job_id, agent_id: [
            {"role": "tenant", "ssh_commands": {"external": "ssh ubuntu@100.64.0.55"}}
        ],
    )
    monkeypatch.setattr(module, "_verify_ssh", lambda credentials, ssh_private_key_path: None)
    monkeypatch.setattr(
        module,
        "_wait_for_orders_closed",
        lambda **kwargs: {
            "seller-order": {"status": "closed"},
            "buyer-order": {"status": "closed"},
        },
    )

    exit_code = module.main(
        [
            "--registry-url",
            "http://100.64.0.10:8080",
            "--provisioning-url",
            "http://100.64.0.11:8081",
            "--seller-agent-url",
            "http://100.64.0.50:8001",
            "--buyer-agent-url",
            "http://100.64.0.51:8000",
            "--seller-agent-id",
            "seller-agent",
            "--buyer-agent-id",
            "buyer-agent",
            "--seller-private-key",
            "0xcccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            "--buyer-private-key",
            "0xdddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
            "--gpu-model",
            "RTX 5090",
            "--region",
            "Nevada, US",
            "--token-symbol",
            "USDC",
            "--token-amount",
            "2.5",
            "--quantity",
            "2",
            "--sla",
            "95.0",
        ]
    )

    assert exit_code == 0
    assert created_orders == [
        {
            "agent_url": "http://100.64.0.50:8001",
            "private_key": "0xcccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            "offer": {
                "gpu_model": "RTX 5090",
                "quantity": 2,
                "sla": 95.0,
                "region": "Nevada, US",
            },
            "demand": {"token": "USDC", "amount": 2.5},
            "duration_hours": 1,
        },
        {
            "agent_url": "http://100.64.0.51:8000",
            "private_key": "0xdddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
            "offer": {"token": "USDC", "amount": 2.5},
            "demand": {
                "gpu_model": "RTX 5090",
                "quantity": 2,
                "sla": 95.0,
                "region": "Nevada, US",
            },
            "duration_hours": 1,
        },
    ]


def test_script_wrapper_delegates_to_market_canary_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str] | None] = []
    stub = types.ModuleType("market.canary")

    def fake_main(argv=None):
        calls.append(list(argv) if argv is not None else None)
        return 17

    stub.main = fake_main
    monkeypatch.setitem(sys.modules, "market.canary", stub)

    module = _load_script_module()

    assert module.main(["--timeout", "42"]) == 17
    assert calls == [["--timeout", "42"]]
