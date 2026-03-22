from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/refresh_canary_agent_ids.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("refresh_canary_agent_ids", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_agent_id_from_env_text() -> None:
    module = _load_script_module()
    env_text = (
        "CHAIN_NAME=ethereum_sepolia\n"
        "BASE_URL_OVERRIDE=http://10.243.0.10:8000/\n"
        "ONCHAIN_AGENT_ID=eip155:11155111:0x1111111111111111111111111111111111111111:7\n"
    )

    assert (
        module._extract_agent_id(env_text)
        == "eip155:11155111:0x1111111111111111111111111111111111111111:7"
    )


def test_update_canary_env_replaces_agent_ids_without_touching_other_values(tmp_path: Path) -> None:
    module = _load_script_module()
    canary_env = tmp_path / "prod-canary.env"
    canary_env.write_text(
        "CHAIN_NAME=ethereum_sepolia\n"
        "SELLER_AGENT_ID=<pending-ethereum-sepolia-registration>\n"
        "BUYER_AGENT_ID=eip155:84532:0xold:2\n"
        "CANARY_VM_HOSTS=btc1\n",
        encoding="utf-8",
    )

    module.update_canary_env(
        canary_env_path=canary_env,
        seller_agent_id="eip155:11155111:0x1111111111111111111111111111111111111111:7",
        buyer_agent_id="eip155:11155111:0x2222222222222222222222222222222222222222:8",
    )

    updated = canary_env.read_text(encoding="utf-8")
    assert "CHAIN_NAME=ethereum_sepolia" in updated
    assert (
        "SELLER_AGENT_ID=eip155:11155111:0x1111111111111111111111111111111111111111:7"
        in updated
    )
    assert (
        "BUYER_AGENT_ID=eip155:11155111:0x2222222222222222222222222222222222222222:8"
        in updated
    )
    assert "CANARY_VM_HOSTS=btc1" in updated


def test_refresh_agent_ids_updates_local_file_and_syncs_runner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script_module()
    commands: list[list[str]] = []
    canary_env = tmp_path / "prod-canary.env"
    canary_env.write_text(
        "SELLER_AGENT_ID=<pending>\nBUYER_AGENT_ID=<pending>\n",
        encoding="utf-8",
    )

    remote_envs = {
        "sms-seller": "ONCHAIN_AGENT_ID=eip155:11155111:0x1111111111111111111111111111111111111111:7\n",
        "sms-buyer": "ONCHAIN_AGENT_ID=eip155:11155111:0x2222222222222222222222222222222222222222:8\n",
    }

    monkeypatch.setattr(
        module,
        "_read_remote_env",
        lambda *, instance, **kwargs: remote_envs[instance],
    )
    monkeypatch.setattr(module, "_run_command", lambda command: commands.append(command))

    result = module.refresh_agent_ids(
        project="sms-canary-project",
        zone="us-east4-c",
        canary_env_path=canary_env,
        seller_instance="sms-seller",
        buyer_instance="sms-buyer",
        runner_instance="sms-runner",
    )

    assert result == {
        "seller_agent_id": "eip155:11155111:0x1111111111111111111111111111111111111111:7",
        "buyer_agent_id": "eip155:11155111:0x2222222222222222222222222222222222222222:8",
    }
    assert (
        "SELLER_AGENT_ID=eip155:11155111:0x1111111111111111111111111111111111111111:7"
        in canary_env.read_text(encoding="utf-8")
    )
    assert (
        "BUYER_AGENT_ID=eip155:11155111:0x2222222222222222222222222222222222222222:8"
        in canary_env.read_text(encoding="utf-8")
    )
    assert commands[0] == [
        "gcloud",
        "compute",
        "scp",
        "--project",
        "sms-canary-project",
        "--zone",
        "us-east4-c",
        str(canary_env),
        "sms-runner:/tmp/prod-canary.ethereum-sepolia.env",
    ]
    assert commands[1][:8] == [
        "gcloud",
        "compute",
        "ssh",
        "sms-runner",
        "--project",
        "sms-canary-project",
        "--zone",
        "us-east4-c",
    ]
    assert (
        "sudo install -m 600 /tmp/prod-canary.ethereum-sepolia.env /etc/simple-market-service/prod-canary.env"
        in commands[1][-1]
    )
