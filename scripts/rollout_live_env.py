#!/usr/bin/env python3
"""Push rendered env files to the live canary hosts and recreate containers."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from pathlib import Path
from typing import NamedTuple


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RENDER_OUTPUT_DIR = Path("/tmp/sms-rendered")


class RolloutTarget(NamedTuple):
    name: str
    instance: str
    container_name: str
    env_filename: str


TARGETS = {
    "registry": RolloutTarget(
        name="registry",
        instance="sms-gateway",
        container_name="sms-registry",
        env_filename="registry.env",
    ),
    "seller": RolloutTarget(
        name="seller",
        instance="sms-seller",
        container_name="sms-seller-agent",
        env_filename="seller-agent.env",
    ),
    "buyer": RolloutTarget(
        name="buyer",
        instance="sms-buyer",
        container_name="sms-buyer-agent",
        env_filename="buyer-agent.env",
    ),
}
PRESERVED_ENV_KEYS = {"ENV_FILE"}
CHAIN_TEMP_FILE_SUFFIX = {
    "ethereum_sepolia": "eth-sepolia",
    "ethereum_mainnet": "eth-mainnet",
    "base_sepolia": "base-sepolia",
    "base": "base-mainnet",
}


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


def _quote_args(args: list[str]) -> str:
    return " ".join(shlex.quote(arg) for arg in args)


def _remote_temp_env_path(*, env_filename: str, chain_name: str) -> str:
    stem = Path(env_filename).stem
    suffix = CHAIN_TEMP_FILE_SUFFIX.get(chain_name, chain_name.replace("_", "-"))
    return f"/tmp/{stem}.{suffix}.env"


def _inspect_container(
    *,
    project: str,
    zone: str,
    instance: str,
    container_name: str,
) -> dict[str, object]:
    command = _gcloud_ssh_command(
        instance=instance,
        project=project,
        zone=zone,
        remote_command=f"sudo docker inspect {shlex.quote(container_name)}",
    )
    output = _capture_stdout(command)
    payload = json.loads(output)
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise SystemExit(f"Unexpected docker inspect payload for {container_name} on {instance}")
    return payload[0]


def _format_published_ports(inspect_payload: dict[str, object]) -> list[str]:
    host_config = inspect_payload.get("HostConfig") or {}
    network_mode = host_config.get("NetworkMode")
    if network_mode == "host":
        return []
    bindings = host_config.get("PortBindings") or {}
    if not isinstance(bindings, dict):
        return []

    flags: list[str] = []
    for container_port, entries in sorted(bindings.items()):
        if not isinstance(entries, list):
            continue
        container_port_number = str(container_port).split("/", 1)[0]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            host_ip = str(entry.get("HostIp") or "")
            host_port = str(entry.get("HostPort") or "")
            if not host_port:
                continue
            if host_ip and host_ip not in {"0.0.0.0", "::"}:
                flags.extend(["-p", f"{host_ip}:{host_port}:{container_port_number}"])
            else:
                flags.extend(["-p", f"{host_port}:{container_port_number}"])
    return flags


def _preserved_env_flags(inspect_payload: dict[str, object]) -> list[str]:
    config = inspect_payload.get("Config") or {}
    env_entries = config.get("Env") or []
    if not isinstance(env_entries, list):
        return []

    flags: list[str] = []
    for item in env_entries:
        if not isinstance(item, str) or "=" not in item:
            continue
        key, value = item.split("=", 1)
        if key in PRESERVED_ENV_KEYS:
            flags.extend(["-e", f"{key}={value}"])
    return flags


def _build_recreate_command(inspect_payload: dict[str, object], *, env_file_path: str) -> str:
    container_name = str(inspect_payload.get("Name") or "").lstrip("/")
    if not container_name:
        raise SystemExit("docker inspect payload is missing container Name")

    config = inspect_payload.get("Config") or {}
    image = config.get("Image")
    if not isinstance(image, str) or not image:
        raise SystemExit(f"docker inspect payload for {container_name} is missing Config.Image")

    host_config = inspect_payload.get("HostConfig") or {}
    command: list[str] = [
        "sudo",
        "docker",
        "run",
        "-d",
        "--name",
        container_name,
    ]

    restart_name = ((host_config.get("RestartPolicy") or {}).get("Name") or "").strip()
    if restart_name:
        command.extend(["--restart", restart_name])

    network_mode = str(host_config.get("NetworkMode") or "").strip()
    if network_mode and network_mode != "default":
        command.extend(["--network", network_mode])

    for capability in host_config.get("CapAdd") or []:
        command.extend(["--cap-add", str(capability)])

    for device in host_config.get("Devices") or []:
        if not isinstance(device, dict):
            continue
        host_path = device.get("PathOnHost")
        container_path = device.get("PathInContainer")
        permissions = device.get("CgroupPermissions")
        if host_path and container_path:
            spec = f"{host_path}:{container_path}"
            if permissions:
                spec = f"{spec}:{permissions}"
            command.extend(["--device", spec])

    command.extend(["--env-file", env_file_path])
    command.extend(_preserved_env_flags(inspect_payload))
    command.extend(_format_published_ports(inspect_payload))

    for bind in host_config.get("Binds") or []:
        command.extend(["-v", str(bind)])

    entrypoint = config.get("Entrypoint")
    if isinstance(entrypoint, str) and entrypoint:
        command.extend(["--entrypoint", entrypoint])
    elif isinstance(entrypoint, list) and entrypoint:
        command.extend(["--entrypoint", entrypoint[0]])
        if len(entrypoint) > 1:
            raise SystemExit(
                f"Unsupported multi-token entrypoint for {container_name}: {entrypoint}"
            )

    command.append(image)

    cmd = config.get("Cmd")
    if isinstance(cmd, str) and cmd:
        command.append(cmd)
    elif isinstance(cmd, list):
        command.extend(str(part) for part in cmd)

    remove = f"sudo docker rm -f {shlex.quote(container_name)} 2>/dev/null || true"
    return f"{remove} && {_quote_args(command)}"


def rollout_target(
    *,
    target: RolloutTarget,
    project: str,
    zone: str,
    rendered_env_path: Path,
    chain_name: str = "ethereum_sepolia",
) -> None:
    remote_temp_env_path = _remote_temp_env_path(
        env_filename=target.env_filename,
        chain_name=chain_name,
    )
    remote_env_path = f"/etc/simple-market-service/{target.env_filename}"

    _run_command(
        _gcloud_scp_command(
            local_path=rendered_env_path,
            instance=target.instance,
            remote_path=remote_temp_env_path,
            project=project,
            zone=zone,
        )
    )
    _run_command(
        _gcloud_ssh_command(
            instance=target.instance,
            project=project,
            zone=zone,
            remote_command=(
                f"sudo install -m 600 {shlex.quote(remote_temp_env_path)} "
                f"{shlex.quote(remote_env_path)}"
            ),
        )
    )

    inspect_payload = _inspect_container(
        project=project,
        zone=zone,
        instance=target.instance,
        container_name=target.container_name,
    )
    _run_command(
        _gcloud_ssh_command(
            instance=target.instance,
            project=project,
            zone=zone,
            remote_command=_build_recreate_command(
                inspect_payload,
                env_file_path=remote_env_path,
            ),
        )
    )
    _run_command(
        _gcloud_ssh_command(
            instance=target.instance,
            project=project,
            zone=zone,
            remote_command=(
                "sudo docker ps --filter "
                f"name={shlex.quote(target.container_name)} --format '{{{{.Names}}}}'"
            ),
        )
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--zone", required=True)
    parser.add_argument("--render-output-dir", type=Path, default=DEFAULT_RENDER_OUTPUT_DIR)
    parser.add_argument(
        "--targets",
        default="registry,seller,buyer",
        help="Comma-separated rollout targets: registry,seller,buyer",
    )
    parser.add_argument(
        "--chain-name",
        default="ethereum_sepolia",
        help="Chain name used to name the temporary uploaded env files.",
    )
    parser.add_argument("--registry-instance", default=TARGETS["registry"].instance)
    parser.add_argument("--seller-instance", default=TARGETS["seller"].instance)
    parser.add_argument("--buyer-instance", default=TARGETS["buyer"].instance)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    targets: dict[str, RolloutTarget] = {
        "registry": TARGETS["registry"]._replace(instance=args.registry_instance),
        "seller": TARGETS["seller"]._replace(instance=args.seller_instance),
        "buyer": TARGETS["buyer"]._replace(instance=args.buyer_instance),
    }

    selected_names = [name.strip() for name in args.targets.split(",") if name.strip()]
    invalid = sorted(set(selected_names) - targets.keys())
    if invalid:
        raise SystemExit(f"Unsupported rollout targets: {', '.join(invalid)}")

    render_output_dir = args.render_output_dir.expanduser()
    for name in selected_names:
        target = targets[name]
        rendered_env_path = render_output_dir / target.env_filename
        if not rendered_env_path.exists():
            raise SystemExit(f"Rendered env file not found for {name}: {rendered_env_path}")
        rollout_target(
            target=target,
            project=args.project,
            zone=args.zone,
            rendered_env_path=rendered_env_path,
            chain_name=args.chain_name,
        )

    print(f"[ok] rolled out targets: {', '.join(selected_names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
