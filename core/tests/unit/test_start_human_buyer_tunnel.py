from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/start_human_buyer_tunnel.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("start_human_buyer_tunnel", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_tunnel_command_uses_expected_iap_and_port_forward_contract() -> None:
    module = _load_script_module()

    command = module.build_tunnel_command(
        project="sms-project",
        zone="us-east4-c",
        instance="sms-seller",
    )

    assert command[:8] == [
        "gcloud",
        "compute",
        "ssh",
        "sms-seller",
        "--project",
        "sms-project",
        "--zone",
        "us-east4-c",
    ]
    assert "--tunnel-through-iap" in command
    assert command[9:13] == [
        "--",
        "-N",
        "-o",
        "ExitOnForwardFailure=yes",
    ]
    assert "28080:10.243.0.219:18080" in command
    assert "28081:10.243.0.115:8081" in command
    assert "28001:10.243.0.117:8000" in command
    assert "28002:10.243.0.68:8000" in command


def test_check_tunnel_health_verifies_all_forwarded_services(monkeypatch) -> None:
    module = _load_script_module()
    seen: list[str] = []

    def fake_fetch_status(url: str, timeout: float) -> int:
        seen.append(url)
        return 200

    monkeypatch.setattr(module, "_fetch_status", fake_fetch_status)

    result = module.check_tunnel_health(timeout=3.5)

    assert result == {
        "registry": 200,
        "provisioning": 200,
        "buyer_agent_card": 200,
        "seller_agent_card": 200,
    }
    assert seen == [
        "http://127.0.0.1:28080/health",
        "http://127.0.0.1:28081/health",
        "http://127.0.0.1:28001/.well-known/agent-card.json",
        "http://127.0.0.1:28002/.well-known/agent-card.json",
    ]
