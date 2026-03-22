#!/usr/bin/env python3
"""Refresh canary agent ids from the live seller and buyer hosts."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


DEFAULT_CANARY_ENV_PATH = Path("~/.config/simple-market-service/prod-canary.env").expanduser()
AGENT_ID_RE = re.compile(r"^ONCHAIN_AGENT_ID=(?P<value>eip155:\d+:0x[0-9a-fA-F]{40}:\d+)$", re.MULTILINE)


def _run_command(command: list[str]) -> None:
    print(f"[run] {' '.join(command)}")
    subprocess.run(command, check=True)


def _capture_stdout(command: list[str]) -> str:
    print(f"[run] {' '.join(command)}")
    completed = subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout


def _gcloud_ssh_command(
    *,
    instance: str,
    project: str,
    zone: str,
    remote_command: str,
) -> list[str]:
    return [
        "gcloud",
        "compute",
        "ssh",
        instance,
        "--project",
        project,
        "--zone",
        zone,
        "--command",
        remote_command,
    ]


def _gcloud_scp_command(
    *,
    local_path: Path,
    instance: str,
    remote_path: str,
    project: str,
    zone: str,
) -> list[str]:
    return [
        "gcloud",
        "compute",
        "scp",
        "--project",
        project,
        "--zone",
        zone,
        str(local_path),
        f"{instance}:{remote_path}",
    ]


def _extract_agent_id(env_text: str) -> str:
    match = AGENT_ID_RE.search(env_text)
    if not match:
        raise SystemExit("Remote env file is missing ONCHAIN_AGENT_ID")
    return match.group("value")


def _read_remote_env(
    *,
    instance: str,
    env_path: str,
    project: str,
    zone: str,
) -> str:
    command = _gcloud_ssh_command(
        instance=instance,
        project=project,
        zone=zone,
        remote_command=f"cat {env_path}",
    )
    return _capture_stdout(command)


def update_canary_env(
    *,
    canary_env_path: Path,
    seller_agent_id: str,
    buyer_agent_id: str,
) -> None:
    text = canary_env_path.read_text(encoding="utf-8")
    replacements = {
        "SELLER_AGENT_ID": seller_agent_id,
        "BUYER_AGENT_ID": buyer_agent_id,
    }
    updated_lines: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if "=" not in stripped or stripped.startswith("#"):
            updated_lines.append(line)
            continue
        key, _ = stripped.split("=", 1)
        if key in replacements:
            updated_lines.append(f"{key}={replacements[key]}")
            seen.add(key)
        else:
            updated_lines.append(line)
    for key, value in replacements.items():
        if key not in seen:
            updated_lines.append(f"{key}={value}")
    canary_env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def refresh_agent_ids(
    *,
    project: str,
    zone: str,
    canary_env_path: Path,
    seller_instance: str,
    buyer_instance: str,
    runner_instance: str,
) -> dict[str, str]:
    seller_env = _read_remote_env(
        instance=seller_instance,
        env_path="/etc/simple-market-service/seller-agent.env",
        project=project,
        zone=zone,
    )
    buyer_env = _read_remote_env(
        instance=buyer_instance,
        env_path="/etc/simple-market-service/buyer-agent.env",
        project=project,
        zone=zone,
    )
    seller_agent_id = _extract_agent_id(seller_env)
    buyer_agent_id = _extract_agent_id(buyer_env)

    update_canary_env(
        canary_env_path=canary_env_path,
        seller_agent_id=seller_agent_id,
        buyer_agent_id=buyer_agent_id,
    )

    remote_temp_path = "/tmp/prod-canary.ethereum-sepolia.env"
    remote_canary_env_path = "/etc/simple-market-service/prod-canary.env"
    _run_command(
        _gcloud_scp_command(
            local_path=canary_env_path,
            instance=runner_instance,
            remote_path=remote_temp_path,
            project=project,
            zone=zone,
        )
    )
    _run_command(
        _gcloud_ssh_command(
            instance=runner_instance,
            project=project,
            zone=zone,
            remote_command=(
                f"sudo install -m 600 {remote_temp_path} {remote_canary_env_path}"
            ),
        )
    )

    return {
        "seller_agent_id": seller_agent_id,
        "buyer_agent_id": buyer_agent_id,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--zone", required=True)
    parser.add_argument("--canary-env-path", type=Path, default=DEFAULT_CANARY_ENV_PATH)
    parser.add_argument("--seller-instance", default="sms-seller")
    parser.add_argument("--buyer-instance", default="sms-buyer")
    parser.add_argument("--runner-instance", default="sms-runner")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    result = refresh_agent_ids(
        project=args.project,
        zone=args.zone,
        canary_env_path=args.canary_env_path.expanduser(),
        seller_instance=args.seller_instance,
        buyer_instance=args.buyer_instance,
        runner_instance=args.runner_instance,
    )
    print(f"[ok] seller_agent_id={result['seller_agent_id']}")
    print(f"[ok] buyer_agent_id={result['buyer_agent_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
