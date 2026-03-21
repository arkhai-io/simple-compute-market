from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts/prod_canary_smoke.py"
SELLER_AGENT_ID = "eip155:84532:0x1111111111111111111111111111111111111111:101"
BUYER_AGENT_ID = "eip155:84532:0x1111111111111111111111111111111111111111:202"
CANARY_ENV_KEYS = (
    "REGISTRY_URL",
    "PROVISIONING_SERVICE_URL",
    "SELLER_AGENT_URL",
    "BUYER_AGENT_URL",
    "FRP_DASHBOARD_URL",
    "FRP_DASHBOARD_PASSWORD",
    "SELLER_AGENT_ID",
    "BUYER_AGENT_ID",
    "SELLER_PRIVATE_KEY",
    "BUYER_PRIVATE_KEY",
    "SSH_PRIVATE_KEY_PATH",
    "CANARY_GPU_MODEL",
    "CANARY_REGION",
    "CANARY_TOKEN_SYMBOL",
    "CANARY_TOKEN_AMOUNT",
    "CANARY_GPU_QUANTITY",
    "CANARY_SLA",
    "CANARY_DURATION_HOURS",
    "CANARY_TIMEOUT_SECONDS",
    "CANARY_POLL_INTERVAL",
    "CANARY_MATCH_SALT",
    "CHAIN_RPC_URL",
    "CHAIN_NAME",
    "CANARY_VM_HOSTS",
)


@pytest.fixture(autouse=True)
def clear_canary_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in CANARY_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _load_script_module():
    spec = importlib.util.spec_from_file_location("prod_canary_smoke", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_canary_module():
    import market.canary as canary

    return canary


def _portfolio_resource(
    *,
    gpu_model: str = "H200",
    quantity: int = 1,
    sla: float = 90.0,
    region: str = "California, US",
) -> dict:
    return {
        "resources": [
            {
                "resource_id": "compute-canary-001",
                "resource_type": "compute.gpu",
                "gpu_model": gpu_model,
                "quantity": quantity,
                "sla": sla,
                "region": region,
            }
        ]
    }


def _request_json_with_portfolio(
    requested_urls: list[str] | None = None,
    *,
    portfolio: dict | None = None,
):
    portfolio = portfolio or _portfolio_resource()

    def _fake_request_json(method: str, url: str, **kwargs):
        if requested_urls is not None:
            requested_urls.append(url)
        if url.endswith("/.well-known/erc-8004-registration.json"):
            if "100.64.0.50" in url:
                return {
                    "registrations": [
                        {
                            "agentId": 101,
                            "agentRegistry": "eip155:84532:0x1111111111111111111111111111111111111111",
                        }
                    ]
                }
            return {
                "registrations": [
                    {
                        "agentId": 202,
                        "agentRegistry": "eip155:84532:0x1111111111111111111111111111111111111111",
                    }
                ]
            }
        if url.endswith("/resources/portfolio"):
            return portfolio
        return {}

    return _fake_request_json


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


def test_verify_ssh_retries_until_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_canary_module()
    ssh_key = tmp_path / "id_ed25519"
    ssh_key.write_text("key", encoding="utf-8")
    observed: list[list[str]] = []
    sleeps: list[int] = []

    def fake_run(parts: list[str], check: bool) -> None:
        assert check is True
        observed.append(parts)
        if len(observed) == 1:
            raise subprocess.CalledProcessError(255, parts)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    module._verify_ssh(
        [
            {
                "role": "tenant",
                "ssh_commands": {"external": "ssh ubuntu@100.64.0.55"},
            }
        ],
        str(ssh_key),
        ready_timeout=30,
        retry_interval=7,
    )

    assert len(observed) == 2
    assert sleeps == [7]


def test_verify_ssh_times_out_after_retry_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_canary_module()
    ssh_key = tmp_path / "id_ed25519"
    ssh_key.write_text("key", encoding="utf-8")

    def fake_run(parts: list[str], check: bool) -> None:
        raise subprocess.CalledProcessError(255, parts)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    with pytest.raises(SystemExit, match="SSH verification failed after 1 attempt"):
        module._verify_ssh(
            [
                {
                    "role": "tenant",
                    "ssh_commands": {"external": "ssh ubuntu@100.64.0.55"},
                }
            ],
            str(ssh_key),
            ready_timeout=0,
            retry_interval=0,
        )


def test_wait_for_new_succeeded_job_prefers_create_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_canary_module()

    monkeypatch.setattr(
        module,
        "_list_jobs",
        lambda provisioning_url, agent_id: [
            {
                "job_id": "job-lease-end",
                "status": "succeeded",
                "params": {"vm_action": "lease_end"},
            },
            {
                "job_id": "job-create",
                "status": "succeeded",
                "params": {"vm_action": "create"},
            },
        ],
    )
    monkeypatch.setattr(module.time, "time", lambda: 100)

    job = module._wait_for_new_succeeded_job(
        provisioning_url="http://100.64.0.11:8081",
        seller_agent_id="seller-agent",
        baseline_job_ids=set(),
        timeout=60,
        poll_interval=1,
    )

    assert job["job_id"] == "job-create"


def test_main_runs_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_canary_module()
    created_orders: list[dict] = []
    requested_urls: list[str] = []
    verified_credentials: list[list[dict]] = []

    monkeypatch.setattr(module, "_check_health", lambda label, url: {"label": label, "url": url})
    monkeypatch.setattr(module.time, "time", lambda: 100)
    monkeypatch.setattr(
        module,
        "_request_json",
        _request_json_with_portfolio(requested_urls),
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
        lambda **kwargs: "seller-order" if kwargs["agent_id"] == SELLER_AGENT_ID else "buyer-order",
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
        lambda credentials, ssh_private_key_path, **kwargs: verified_credentials.append(credentials),
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
            SELLER_AGENT_ID,
            "--buyer-agent-id",
            BUYER_AGENT_ID,
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
        "http://100.64.0.50:8001/.well-known/erc-8004-registration.json",
        "http://100.64.0.51:8000/.well-known/erc-8004-registration.json",
        "http://100.64.0.50:8001/resources/portfolio",
    ]
    assert len(verified_credentials) == 1


def test_main_emits_structured_canary_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_canary_module()

    monkeypatch.setattr(module, "_check_health", lambda label, url: {"label": label, "url": url})
    monkeypatch.setattr(module.time, "time", lambda: 100)
    monkeypatch.setattr(module, "_request_json", _request_json_with_portfolio())
    monkeypatch.setattr(module, "_fetch_agent_orders", lambda registry_url, agent_id: [])
    monkeypatch.setattr(module, "_list_jobs", lambda provisioning_url, agent_id: [])
    monkeypatch.setattr(module, "_create_order", lambda **kwargs: None)
    monkeypatch.setattr(
        module,
        "_wait_for_new_order",
        lambda **kwargs: "seller-order" if kwargs["agent_id"] == SELLER_AGENT_ID else "buyer-order",
    )
    monkeypatch.setattr(
        module,
        "_wait_for_new_succeeded_job",
        lambda **kwargs: {
            "job_id": "job-1",
            "status": "succeeded",
            "params": {"vm_host": "btc1", "vm_target": "tenant-d908"},
            "result": {"vm_host": "btc1", "vm_target": "tenant-d908"},
        },
    )
    monkeypatch.setattr(
        module,
        "_fetch_credentials",
        lambda provisioning_url, job_id, agent_id: [
            {"role": "tenant", "ssh_commands": {"external": "ssh ubuntu@100.64.0.55"}}
        ],
    )
    monkeypatch.setattr(module, "_verify_ssh", lambda credentials, ssh_private_key_path, **kwargs: None)
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
            SELLER_AGENT_ID,
            "--buyer-agent-id",
            BUYER_AGENT_ID,
            "--seller-private-key",
            "0xcccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            "--buyer-private-key",
            "0xdddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        ]
    )

    assert exit_code == 0
    stdout = capsys.readouterr().out
    result = json.loads(stdout.split("[success] canary completed\n", 1)[1])

    assert result["status"] == "succeeded"
    assert result["seller_order_id"] == "seller-order"
    assert result["buyer_order_id"] == "buyer-order"
    assert result["provisioning_job_id"] == "job-1"
    assert result["vm_host"] == "btc1"
    assert result["vm_target"] == "tenant-d908"
    assert result["cleanup"] == {
        "preexisting_closed_order_ids": {"seller": [], "buyer": []},
        "post_provisioning_closed_order_ids": {"seller": [], "buyer": []},
        "final_order_ids": ["seller-order", "buyer-order"],
    }


def test_main_creates_seller_then_buyer_orders_with_expected_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_canary_module()
    created_orders: list[dict] = []

    monkeypatch.setattr(module, "_check_health", lambda label, url: {"label": label, "url": url})
    monkeypatch.setattr(module.time, "time", lambda: 100)
    monkeypatch.setattr(
        module,
        "_request_json",
        _request_json_with_portfolio(
            portfolio=_portfolio_resource(
                gpu_model="RTX 5090",
                quantity=2,
                sla=95.0,
                region="Nevada, US",
            )
        ),
    )
    monkeypatch.setattr(module, "_fetch_agent_orders", lambda registry_url, agent_id: [])
    monkeypatch.setattr(module, "_list_jobs", lambda provisioning_url, agent_id: [])
    monkeypatch.setattr(module, "_create_order", lambda **kwargs: created_orders.append(kwargs))
    monkeypatch.setattr(
        module,
        "_wait_for_new_order",
        lambda **kwargs: "seller-order" if kwargs["agent_id"] == SELLER_AGENT_ID else "buyer-order",
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
    monkeypatch.setattr(module, "_verify_ssh", lambda credentials, ssh_private_key_path, **kwargs: None)
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
            SELLER_AGENT_ID,
            "--buyer-agent-id",
            BUYER_AGENT_ID,
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
            "demand": {"token": "USDC", "amount": 2.500001},
            "duration_hours": 1,
            "timeout": 600,
        },
        {
            "agent_url": "http://100.64.0.51:8000",
            "private_key": "0xdddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
            "offer": {"token": "USDC", "amount": 2.500001},
            "demand": {
                "gpu_model": "RTX 5090",
                "quantity": 2,
                "sla": 95.0,
                "region": "Nevada, US",
            },
            "duration_hours": 1,
            "timeout": 600,
        },
    ]


def test_main_uses_match_salt_to_isolate_each_canary_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_canary_module()
    created_orders: list[dict] = []

    monkeypatch.setattr(module, "_check_health", lambda label, url: {"label": label, "url": url})
    monkeypatch.setattr(module.time, "time", lambda: 42)
    monkeypatch.setattr(module, "_request_json", _request_json_with_portfolio())
    monkeypatch.setattr(module, "_fetch_agent_orders", lambda registry_url, agent_id: [])
    monkeypatch.setattr(module, "_list_jobs", lambda provisioning_url, agent_id: [])
    monkeypatch.setattr(module, "_create_order", lambda **kwargs: created_orders.append(kwargs))
    monkeypatch.setattr(
        module,
        "_wait_for_new_order",
        lambda **kwargs: "seller-order" if kwargs["agent_id"] == SELLER_AGENT_ID else "buyer-order",
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
    monkeypatch.setattr(module, "_verify_ssh", lambda credentials, ssh_private_key_path, **kwargs: None)
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
            SELLER_AGENT_ID,
            "--buyer-agent-id",
            BUYER_AGENT_ID,
            "--seller-private-key",
            "0xcccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            "--buyer-private-key",
            "0xdddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
            "--token-amount",
            "0.0001",
            "--match-salt",
            "42",
        ]
    )

    assert exit_code == 0
    assert created_orders[0]["demand"]["amount"] == 0.00010042
    assert created_orders[1]["offer"]["amount"] == 0.00010042


def test_main_passes_configured_timeout_to_order_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_canary_module()
    created_orders: list[dict] = []

    monkeypatch.setattr(module, "_check_health", lambda label, url: {"label": label, "url": url})
    monkeypatch.setattr(module.time, "time", lambda: 100)
    monkeypatch.setattr(module, "_request_json", _request_json_with_portfolio())
    monkeypatch.setattr(module, "_fetch_agent_orders", lambda registry_url, agent_id: [])
    monkeypatch.setattr(module, "_list_jobs", lambda provisioning_url, agent_id: [])
    monkeypatch.setattr(module, "_create_order", lambda **kwargs: created_orders.append(kwargs))
    monkeypatch.setattr(
        module,
        "_wait_for_new_order",
        lambda **kwargs: "seller-order" if kwargs["agent_id"] == SELLER_AGENT_ID else "buyer-order",
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
    monkeypatch.setattr(module, "_verify_ssh", lambda credentials, ssh_private_key_path, **kwargs: None)
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
            SELLER_AGENT_ID,
            "--buyer-agent-id",
            BUYER_AGENT_ID,
            "--seller-private-key",
            "0xcccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            "--buyer-private-key",
            "0xdddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
            "--timeout",
            "900",
        ]
    )

    assert exit_code == 0
    assert [kwargs["timeout"] for kwargs in created_orders] == [900, 900]


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
