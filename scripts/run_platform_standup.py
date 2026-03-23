#!/usr/bin/env python3
"""Orchestrate the live platform deploy, verify, and canary stages."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check_chain_profile import load_chain_profile
from role_contracts import build_artifact


DEFAULT_SHARED_SECRETS_DIR = Path("~/.config/web3-ops").expanduser()
DEFAULT_LOCAL_SECRETS_DIR = Path("~/.config/simple-market-service").expanduser()
DEFAULT_RENDER_OUTPUT_DIR = Path("/tmp/sms-rendered")
DEFAULT_ARTIFACTS_DIR = ROOT / "artifacts"
DEFAULT_CANARY_ENV_PATH = Path("~/.config/simple-market-service/prod-canary.env").expanduser()
DEFAULT_INVENTORY_PATH = ROOT / "compute-provisioning-iac/ansible/inventory/hosts"


def _run_command(command: list[str], *, cwd: Path = ROOT, capture_json: bool = False) -> dict[str, Any] | None:
    print(f"[run] ({cwd}) {' '.join(command)}")
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE if capture_json else None,
        stderr=subprocess.PIPE if capture_json else None,
        text=True,
    )
    if not capture_json:
        return None
    stdout = (completed.stdout or "").strip()
    if not stdout:
        return {}
    return json.loads(stdout)


def _write_artifact(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def build_deploy_commands(
    *,
    project: str,
    zone: str,
    shared_secrets_dir: Path,
    local_secrets_dir: Path,
    render_output_dir: Path,
    canary_env_path: Path,
    chain_name: str,
) -> list[list[str]]:
    return [
        [
            "python",
            "scripts/materialize_host_envs.py",
            "--shared-secrets-dir",
            str(shared_secrets_dir),
            "--local-secrets-dir",
            str(local_secrets_dir),
            "--output-dir",
            str(render_output_dir),
        ],
        [
            "python",
            "scripts/check_chain_profile.py",
            "--shared-secrets-dir",
            str(shared_secrets_dir),
            "--local-secrets-dir",
            str(local_secrets_dir),
            "--json",
        ],
        [
            "python",
            "scripts/rollout_live_env.py",
            "--project",
            project,
            "--zone",
            zone,
            "--render-output-dir",
            str(render_output_dir),
            "--chain-name",
            chain_name,
        ],
        [
            "python",
            "scripts/refresh_canary_agent_ids.py",
            "--project",
            project,
            "--zone",
            zone,
            "--canary-env-path",
            str(canary_env_path),
        ],
    ]


def build_verify_command(
    *,
    environment: str,
    render_output_dir: Path,
    inventory_path: Path,
    expected_chain_name: str,
    expected_chain_id: int,
) -> list[str]:
    return [
        "python",
        "scripts/run_deployment_gate_checks.py",
        "--environment",
        environment,
        "--seller-agent-env",
        str(render_output_dir / "seller-agent.env"),
        "--buyer-agent-env",
        str(render_output_dir / "buyer-agent.env"),
        "--provisioning-env",
        str(render_output_dir / "provisioning.env"),
        "--registry-env",
        str(render_output_dir / "registry.env"),
        "--inventory-path",
        str(inventory_path),
        "--expected-chain-name",
        expected_chain_name,
        "--expected-chain-id",
        str(expected_chain_id),
        "--skip-smoke-help",
    ]


def build_canary_command(
    *,
    environment: str,
    shared_secrets_dir: Path,
    local_secrets_dir: Path,
    render_output_dir: Path,
    artifacts_dir: Path,
    inventory_path: Path,
    apply_funding: bool,
    allow_mainnet: bool,
) -> list[str]:
    command = [
        "python",
        "scripts/run_repeatable_canary.py",
        "--environment",
        environment,
        "--shared-secrets-dir",
        str(shared_secrets_dir),
        "--local-secrets-dir",
        str(local_secrets_dir),
        "--output-dir",
        str(render_output_dir),
        "--artifacts-dir",
        str(artifacts_dir),
        "--inventory-path",
        str(inventory_path),
    ]
    if apply_funding:
        command.append("--apply-funding")
    if allow_mainnet:
        command.append("--allow-mainnet")
    return command


def build_platform_artifact(
    *,
    action: str,
    status: str,
    request_url: str,
    auth_url: str,
    render_output_dir: str,
    details: dict[str, object],
) -> dict[str, object]:
    merged_details = {"render_output_dir": render_output_dir, **details}
    return build_artifact(
        role="platform",
        action=action,
        status=status,
        request_url=request_url,
        auth_url=auth_url,
        correlation={},
        details=merged_details,
    )


def _extract_agent_ids_from_env(path: Path) -> dict[str, str | None]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key] = value
    return {
        "seller_agent_id": values.get("SELLER_AGENT_ID"),
        "buyer_agent_id": values.get("BUYER_AGENT_ID"),
    }


def _default_request_url(project: str, zone: str) -> str:
    return f"gcloud://{project}/{zone}"


def deploy_platform(
    *,
    project: str,
    zone: str,
    shared_secrets_dir: Path,
    local_secrets_dir: Path,
    render_output_dir: Path,
    canary_env_path: Path,
    artifact_path: Path | None,
) -> dict[str, object]:
    profile = load_chain_profile(
        shared_secrets_dir=shared_secrets_dir,
        local_secrets_dir=local_secrets_dir,
    )
    chain_result: dict[str, object] = {}
    commands = build_deploy_commands(
        project=project,
        zone=zone,
        shared_secrets_dir=shared_secrets_dir,
        local_secrets_dir=local_secrets_dir,
        render_output_dir=render_output_dir,
        canary_env_path=canary_env_path,
        chain_name=profile.chain_name,
    )
    for index, command in enumerate(commands):
        chain_result = _run_command(
            command,
            capture_json=index == 1,
        ) or chain_result

    agent_ids = _extract_agent_ids_from_env(canary_env_path)
    artifact = build_platform_artifact(
        action="deploy",
        status="succeeded",
        request_url=_default_request_url(project, zone),
        auth_url=_default_request_url(project, zone),
        render_output_dir=str(render_output_dir),
        details={
            "chain_name": profile.chain_name,
            "chain_id": profile.chain_id,
            "chain_profile": chain_result,
            **agent_ids,
        },
    )
    if artifact_path is not None:
        artifact["artifact_path"] = str(_write_artifact(artifact_path, artifact))
    return artifact


def verify_platform(
    *,
    environment: str,
    shared_secrets_dir: Path,
    local_secrets_dir: Path,
    render_output_dir: Path,
    inventory_path: Path,
    artifact_path: Path | None,
) -> dict[str, object]:
    profile = load_chain_profile(
        shared_secrets_dir=shared_secrets_dir,
        local_secrets_dir=local_secrets_dir,
    )
    _run_command(
        [
            "python",
            "scripts/materialize_host_envs.py",
            "--shared-secrets-dir",
            str(shared_secrets_dir),
            "--local-secrets-dir",
            str(local_secrets_dir),
            "--output-dir",
            str(render_output_dir),
        ]
    )
    _run_command(
        build_verify_command(
            environment=environment,
            render_output_dir=render_output_dir,
            inventory_path=inventory_path,
            expected_chain_name=profile.chain_name,
            expected_chain_id=profile.chain_id,
        )
    )
    artifact = build_platform_artifact(
        action="verify",
        status="succeeded",
        request_url=f"file://{render_output_dir}",
        auth_url=f"file://{inventory_path}",
        render_output_dir=str(render_output_dir),
        details={
            "chain_name": profile.chain_name,
            "chain_id": profile.chain_id,
            "inventory_path": str(inventory_path),
        },
    )
    if artifact_path is not None:
        artifact["artifact_path"] = str(_write_artifact(artifact_path, artifact))
    return artifact


def run_platform_canary(
    *,
    environment: str,
    shared_secrets_dir: Path,
    local_secrets_dir: Path,
    render_output_dir: Path,
    artifacts_dir: Path,
    inventory_path: Path,
    apply_funding: bool,
    allow_mainnet: bool,
    artifact_path: Path | None,
) -> dict[str, object]:
    _run_command(
        build_canary_command(
            environment=environment,
            shared_secrets_dir=shared_secrets_dir,
            local_secrets_dir=local_secrets_dir,
            render_output_dir=render_output_dir,
            artifacts_dir=artifacts_dir,
            inventory_path=inventory_path,
            apply_funding=apply_funding,
            allow_mainnet=allow_mainnet,
        )
    )
    artifact = build_platform_artifact(
        action="canary",
        status="succeeded",
        request_url=f"file://{render_output_dir}",
        auth_url=f"file://{artifacts_dir}",
        render_output_dir=str(render_output_dir),
        details={
            "artifacts_dir": str(artifacts_dir),
            "prod_canary_log": str(artifacts_dir / "prod-canary.log"),
        },
    )
    if artifact_path is not None:
        artifact["artifact_path"] = str(_write_artifact(artifact_path, artifact))
    return artifact


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    deploy_parser = subparsers.add_parser("deploy", help="Render envs, preflight the chain profile, roll out live targets, and refresh agent ids.")
    deploy_parser.add_argument("--project", required=True)
    deploy_parser.add_argument("--zone", required=True)
    deploy_parser.add_argument("--shared-secrets-dir", type=Path, default=DEFAULT_SHARED_SECRETS_DIR)
    deploy_parser.add_argument("--local-secrets-dir", type=Path, default=DEFAULT_LOCAL_SECRETS_DIR)
    deploy_parser.add_argument("--render-output-dir", type=Path, default=DEFAULT_RENDER_OUTPUT_DIR)
    deploy_parser.add_argument("--canary-env-path", type=Path, default=DEFAULT_CANARY_ENV_PATH)
    deploy_parser.add_argument("--artifact-path", type=Path)

    verify_parser = subparsers.add_parser("verify", help="Render envs and run the repo deployment gate checks against the rendered bundle.")
    verify_parser.add_argument("--environment", required=True)
    verify_parser.add_argument("--shared-secrets-dir", type=Path, default=DEFAULT_SHARED_SECRETS_DIR)
    verify_parser.add_argument("--local-secrets-dir", type=Path, default=DEFAULT_LOCAL_SECRETS_DIR)
    verify_parser.add_argument("--render-output-dir", type=Path, default=DEFAULT_RENDER_OUTPUT_DIR)
    verify_parser.add_argument("--inventory-path", type=Path, default=DEFAULT_INVENTORY_PATH)
    verify_parser.add_argument("--artifact-path", type=Path)

    canary_parser = subparsers.add_parser("canary", help="Run the repeatable canary through the existing repo orchestration path.")
    canary_parser.add_argument("--environment", required=True)
    canary_parser.add_argument("--shared-secrets-dir", type=Path, default=DEFAULT_SHARED_SECRETS_DIR)
    canary_parser.add_argument("--local-secrets-dir", type=Path, default=DEFAULT_LOCAL_SECRETS_DIR)
    canary_parser.add_argument("--render-output-dir", type=Path, default=DEFAULT_RENDER_OUTPUT_DIR)
    canary_parser.add_argument("--artifacts-dir", type=Path, default=DEFAULT_ARTIFACTS_DIR)
    canary_parser.add_argument("--inventory-path", type=Path, default=DEFAULT_INVENTORY_PATH)
    canary_parser.add_argument("--apply-funding", action="store_true")
    canary_parser.add_argument("--allow-mainnet", action="store_true")
    canary_parser.add_argument("--artifact-path", type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "deploy":
        result = deploy_platform(
            project=args.project,
            zone=args.zone,
            shared_secrets_dir=args.shared_secrets_dir.expanduser(),
            local_secrets_dir=args.local_secrets_dir.expanduser(),
            render_output_dir=args.render_output_dir.expanduser(),
            canary_env_path=args.canary_env_path.expanduser(),
            artifact_path=args.artifact_path.expanduser() if args.artifact_path else None,
        )
    elif args.command == "verify":
        result = verify_platform(
            environment=args.environment,
            shared_secrets_dir=args.shared_secrets_dir.expanduser(),
            local_secrets_dir=args.local_secrets_dir.expanduser(),
            render_output_dir=args.render_output_dir.expanduser(),
            inventory_path=args.inventory_path.expanduser(),
            artifact_path=args.artifact_path.expanduser() if args.artifact_path else None,
        )
    else:
        result = run_platform_canary(
            environment=args.environment,
            shared_secrets_dir=args.shared_secrets_dir.expanduser(),
            local_secrets_dir=args.local_secrets_dir.expanduser(),
            render_output_dir=args.render_output_dir.expanduser(),
            artifacts_dir=args.artifacts_dir.expanduser(),
            inventory_path=args.inventory_path.expanduser(),
            apply_funding=args.apply_funding,
            allow_mainnet=args.allow_mainnet,
            artifact_path=args.artifact_path.expanduser() if args.artifact_path else None,
        )

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
