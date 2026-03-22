from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/rollout_live_env.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("rollout_live_env", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_recreate_command_preserves_runtime_contract_for_agent_container() -> None:
    module = _load_script_module()
    inspect_payload = {
        "Name": "/sms-seller-agent",
        "Config": {
            "Image": "registry.example/core-agent:latest",
            "Cmd": ["./entrypoint.sh"],
            "Entrypoint": None,
            "Env": [
                "ENV_FILE=/etc/simple-market-service/seller-agent.env",
                "CHAIN_ID=84532",
            ],
        },
        "HostConfig": {
            "RestartPolicy": {"Name": "unless-stopped"},
            "NetworkMode": "host",
            "Binds": [
                "/etc/simple-market-service/seller-agent.env:/etc/simple-market-service/seller-agent.env",
                "/var/lib/market:/var/lib/market",
                "/var/log/market:/var/log/market",
            ],
            "CapAdd": ["NET_ADMIN", "SYS_MODULE"],
            "Devices": [
                {
                    "PathOnHost": "/dev/net/tun",
                    "PathInContainer": "/dev/net/tun",
                    "CgroupPermissions": "rwm",
                }
            ],
            "PortBindings": {},
        },
    }

    command = module._build_recreate_command(
        inspect_payload,
        env_file_path="/etc/simple-market-service/seller-agent.env",
    )

    assert "sudo docker rm -f sms-seller-agent" in command
    assert "sudo docker run -d --name sms-seller-agent" in command
    assert "--restart unless-stopped" in command
    assert "--network host" in command
    assert "--env-file /etc/simple-market-service/seller-agent.env" in command
    assert "-e ENV_FILE=/etc/simple-market-service/seller-agent.env" in command
    assert "-v /etc/simple-market-service/seller-agent.env:/etc/simple-market-service/seller-agent.env" in command
    assert "-v /var/lib/market:/var/lib/market" in command
    assert "-v /var/log/market:/var/log/market" in command
    assert "--cap-add NET_ADMIN" in command
    assert "--cap-add SYS_MODULE" in command
    assert "--device /dev/net/tun:/dev/net/tun:rwm" in command
    assert "registry.example/core-agent:latest ./entrypoint.sh" in command
    assert "CHAIN_ID=84532" not in command


def test_build_recreate_command_preserves_ports_for_bridge_container() -> None:
    module = _load_script_module()
    inspect_payload = {
        "Name": "/sms-registry",
        "Config": {
            "Image": "registry.example/erc-8004-registry:latest",
            "Cmd": ["sh", "-lc", "/app/.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8080}"],
            "Entrypoint": None,
            "Env": ["CHAIN_ID=84532"],
        },
        "HostConfig": {
            "RestartPolicy": {"Name": "unless-stopped"},
            "NetworkMode": "bridge",
            "Binds": [],
            "CapAdd": [],
            "Devices": [],
            "PortBindings": {
                "8080/tcp": [{"HostIp": "", "HostPort": "8080"}],
            },
        },
    }

    command = module._build_recreate_command(
        inspect_payload,
        env_file_path="/etc/simple-market-service/registry.env",
    )

    assert "--network host" not in command
    assert "--env-file /etc/simple-market-service/registry.env" in command
    assert "-p 8080:8080" in command
    assert "registry.example/erc-8004-registry:latest sh -lc" in command
    assert "CHAIN_ID=84532" not in command


def test_build_recreate_command_uses_explicit_image_override() -> None:
    module = _load_script_module()
    inspect_payload = {
        "Name": "/sms-seller-agent",
        "Config": {
            "Image": "registry.example/core-agent:stale",
            "Cmd": ["./entrypoint.sh"],
            "Entrypoint": None,
            "Env": ["ENV_FILE=/etc/simple-market-service/seller-agent.env"],
        },
        "HostConfig": {
            "RestartPolicy": {"Name": "unless-stopped"},
            "NetworkMode": "host",
            "Binds": [
                "/etc/simple-market-service/seller-agent.env:/etc/simple-market-service/seller-agent.env",
            ],
            "CapAdd": [],
            "Devices": [],
            "PortBindings": {},
        },
    }

    command = module._build_recreate_command(
        inspect_payload,
        env_file_path="/etc/simple-market-service/seller-agent.env",
        image_override="registry.example/core-agent:fresh",
    )

    assert "registry.example/core-agent:fresh ./entrypoint.sh" in command
    assert "registry.example/core-agent:stale ./entrypoint.sh" not in command


def test_rollout_target_uploads_installs_recreates_and_verifies_container(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script_module()
    commands: list[list[str]] = []
    rendered_env = tmp_path / "seller-agent.env"
    rendered_env.write_text("CHAIN_NAME=ethereum_sepolia\n", encoding="utf-8")

    target = module.RolloutTarget(
        name="seller",
        instance="sms-seller",
        container_name="sms-seller-agent",
        env_filename="seller-agent.env",
    )

    inspect_payload = {
        "Name": "/sms-seller-agent",
        "Config": {
            "Image": "registry.example/core-agent:latest",
            "Cmd": ["./entrypoint.sh"],
            "Entrypoint": None,
            "Env": ["ENV_FILE=/etc/simple-market-service/seller-agent.env"],
        },
        "HostConfig": {
            "RestartPolicy": {"Name": "unless-stopped"},
            "NetworkMode": "host",
            "Binds": [
                "/etc/simple-market-service/seller-agent.env:/etc/simple-market-service/seller-agent.env",
            ],
            "CapAdd": [],
            "Devices": [],
            "PortBindings": {},
        },
    }

    monkeypatch.setattr(module, "_inspect_container", lambda **kwargs: inspect_payload)
    monkeypatch.setattr(module, "_run_command", lambda command: commands.append(command))

    module.rollout_target(
        target=target,
        project="sms-canary-project",
        zone="us-east4-c",
        rendered_env_path=rendered_env,
    )

    assert commands[0] == [
        "gcloud",
        "compute",
        "scp",
        "--project",
        "sms-canary-project",
        "--zone",
        "us-east4-c",
        str(rendered_env),
        "sms-seller:/tmp/seller-agent.eth-sepolia.env",
    ]
    assert commands[1][:8] == [
        "gcloud",
        "compute",
        "ssh",
        "sms-seller",
        "--project",
        "sms-canary-project",
        "--zone",
        "us-east4-c",
    ]
    assert "sudo install -m 600 /tmp/seller-agent.eth-sepolia.env /etc/simple-market-service/seller-agent.env" in commands[1][-1]
    assert "sudo docker run -d --name sms-seller-agent" in commands[2][-1]
    assert commands[3][-1] == "sudo docker ps --filter name=sms-seller-agent --format '{{.Names}}'"


def test_rollout_target_recreates_container_with_target_image_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script_module()
    commands: list[list[str]] = []
    rendered_env = tmp_path / "buyer-agent.env"
    rendered_env.write_text("CHAIN_NAME=ethereum_sepolia\n", encoding="utf-8")

    target = module.RolloutTarget(
        name="buyer",
        instance="sms-buyer",
        container_name="sms-buyer-agent",
        env_filename="buyer-agent.env",
    )

    inspect_payload = {
        "Name": "/sms-buyer-agent",
        "Config": {
            "Image": "registry.example/core-agent:stale",
            "Cmd": ["./entrypoint.sh"],
            "Entrypoint": None,
            "Env": ["ENV_FILE=/etc/simple-market-service/buyer-agent.env"],
        },
        "HostConfig": {
            "RestartPolicy": {"Name": "unless-stopped"},
            "NetworkMode": "host",
            "Binds": [
                "/etc/simple-market-service/buyer-agent.env:/etc/simple-market-service/buyer-agent.env",
            ],
            "CapAdd": [],
            "Devices": [],
            "PortBindings": {},
        },
    }

    monkeypatch.setattr(module, "_inspect_container", lambda **kwargs: inspect_payload)
    monkeypatch.setattr(module, "_run_command", lambda command: commands.append(command))

    module.rollout_target(
        target=target,
        project="sms-canary-project",
        zone="us-east4-c",
        rendered_env_path=rendered_env,
        image_override="registry.example/core-agent:fresh",
    )

    assert "registry.example/core-agent:fresh ./entrypoint.sh" in commands[2][-1]
    assert "registry.example/core-agent:stale ./entrypoint.sh" not in commands[2][-1]
