#!/usr/bin/env python3
"""Render, fund, validate, and run the deployed canary in one place.

This orchestration entrypoint keeps the repeatable path consistent across local
operators and the self-hosted isolated runner:

- scripts/materialize_host_envs.py
- scripts/pre_canary_fund.py
- scripts/run_deployment_gate_checks.py
- scripts/validate_deployment_bundle.py
- scripts/prod_canary_smoke.py
- scripts/prod_canary_rollback.py
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHARED_SECRETS_DIR = Path("~/.config/web3-ops").expanduser()
DEFAULT_LOCAL_SECRETS_DIR = Path("~/.config/simple-market-service").expanduser()
DEFAULT_OUTPUT_DIR = Path("/etc/simple-market-service")
DEFAULT_ARTIFACTS_DIR = ROOT / "artifacts"
DEFAULT_INVENTORY_PATH = ROOT / "compute-provisioning-iac/ansible/inventory/hosts"


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = _strip_matching_quotes(value.strip())
    return values


def _strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> None:
    print(f"[run] ({cwd}) {' '.join(command)}")
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _run_logged_command(
    command: list[str],
    *,
    cwd: Path,
    log_path: Path,
    env: dict[str, str] | None = None,
) -> int:
    print(f"[run] ({cwd}) {' '.join(command)} | tee {log_path}")
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(completed.stdout or "", encoding="utf-8")
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    return int(completed.returncode)


def _rendered_env_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "seller": output_dir / "seller-agent.env",
        "buyer": output_dir / "buyer-agent.env",
        "provisioning": output_dir / "provisioning.env",
        "registry": output_dir / "registry.env",
        "canary": output_dir / "prod-canary.env",
    }


def _load_chain_name(local_secrets_dir: Path) -> str:
    shared_env_path = local_secrets_dir / "shared.env"
    if not shared_env_path.exists():
        raise SystemExit(f"Missing shared.env: {shared_env_path}")
    shared = _parse_env_file(shared_env_path)
    chain_name = shared.get("CHAIN_NAME")
    if not chain_name:
        raise SystemExit(f"shared.env is missing CHAIN_NAME: {shared_env_path}")
    return chain_name


def _ensure_rendered_bundle(paths: dict[str, Path]) -> None:
    missing = sorted(str(path) for path in paths.values() if not path.exists())
    if missing:
        raise SystemExit(f"Rendered env bundle is incomplete: {', '.join(missing)}")


def _build_canary_process_env(canary_env_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(_parse_env_file(canary_env_path))
    return env


def _build_bundle_validation_command(
    *,
    environment: str,
    rendered_paths: dict[str, Path],
    inventory_path: Path,
    canary_env: dict[str, str],
) -> list[str]:
    required_keys = (
        "SELLER_AGENT_URL",
        "BUYER_AGENT_URL",
        "SELLER_AGENT_ID",
        "BUYER_AGENT_ID",
        "SELLER_PRIVATE_KEY",
        "BUYER_PRIVATE_KEY",
        "SSH_PRIVATE_KEY_PATH",
    )
    missing = sorted(key for key in required_keys if not canary_env.get(key))
    if missing:
        raise SystemExit(
            "Rendered prod-canary.env is missing validation inputs: "
            + ", ".join(missing)
        )

    command = [
        "python",
        "scripts/validate_deployment_bundle.py",
        "--environment",
        environment,
        "--seller-agent-env",
        str(rendered_paths["seller"]),
        "--buyer-agent-env",
        str(rendered_paths["buyer"]),
        "--provisioning-env",
        str(rendered_paths["provisioning"]),
        "--registry-env",
        str(rendered_paths["registry"]),
        "--inventory-path",
        str(inventory_path),
        "--seller-agent-url",
        canary_env["SELLER_AGENT_URL"],
        "--buyer-agent-url",
        canary_env["BUYER_AGENT_URL"],
        "--seller-agent-id",
        canary_env["SELLER_AGENT_ID"],
        "--buyer-agent-id",
        canary_env["BUYER_AGENT_ID"],
        "--seller-private-key",
        canary_env["SELLER_PRIVATE_KEY"],
        "--buyer-private-key",
        canary_env["BUYER_PRIVATE_KEY"],
        "--ssh-private-key-path",
        canary_env["SSH_PRIVATE_KEY_PATH"],
    ]
    if canary_env.get("CHAIN_NAME"):
        command.extend(["--expected-chain-name", canary_env["CHAIN_NAME"]])
    if canary_env.get("CHAIN_ID"):
        command.extend(["--expected-chain-id", canary_env["CHAIN_ID"]])
    return command
    return command


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Repeatable canary orchestration for isolated environments, including "
            "materialization, funding, validation, artifacts/prod-canary.log, and "
            "automatic rollback."
        )
    )
    parser.add_argument("--environment", required=True)
    parser.add_argument("--shared-secrets-dir", type=Path, default=DEFAULT_SHARED_SECRETS_DIR)
    parser.add_argument("--local-secrets-dir", type=Path, default=DEFAULT_LOCAL_SECRETS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--artifacts-dir", type=Path, default=DEFAULT_ARTIFACTS_DIR)
    parser.add_argument("--inventory-path", type=Path, default=DEFAULT_INVENTORY_PATH)
    parser.add_argument("--apply-funding", action="store_true")
    parser.add_argument(
        "--allow-mainnet",
        action="store_true",
        help="Explicitly allow a Base mainnet run. Required for mainnet funding or canary execution.",
    )
    parser.add_argument("--skip-deployment-gates", action="store_true")
    parser.add_argument("--skip-bundle-validation", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    shared_secrets_dir = args.shared_secrets_dir.expanduser()
    local_secrets_dir = args.local_secrets_dir.expanduser()
    output_dir = args.output_dir.expanduser()
    artifacts_dir = args.artifacts_dir.expanduser()
    inventory_path = args.inventory_path.expanduser()
    rendered_paths = _rendered_env_paths(output_dir)
    chain_name = _load_chain_name(local_secrets_dir)
    if chain_name == "base" and not args.allow_mainnet:
        raise SystemExit("Refusing to run base mainnet canary without --allow-mainnet")

    _run_command(
        [
            "python",
            "scripts/materialize_host_envs.py",
            "--shared-secrets-dir",
            str(shared_secrets_dir),
            "--local-secrets-dir",
            str(local_secrets_dir),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
    )
    _ensure_rendered_bundle(rendered_paths)

    funding_command = [
        "python",
        "scripts/pre_canary_fund.py",
        "--shared-secrets-dir",
        str(shared_secrets_dir),
        "--local-secrets-dir",
        str(local_secrets_dir),
    ]
    if args.apply_funding:
        funding_command.append("--apply")
    if args.allow_mainnet:
        funding_command.append("--allow-mainnet")
    _run_command(funding_command, cwd=ROOT)

    canary_env = _parse_env_file(rendered_paths["canary"])

    if not args.skip_deployment_gates:
        gate_command = [
            "python",
            "scripts/run_deployment_gate_checks.py",
            "--environment",
            args.environment,
            "--seller-agent-env",
            str(rendered_paths["seller"]),
            "--buyer-agent-env",
            str(rendered_paths["buyer"]),
            "--provisioning-env",
            str(rendered_paths["provisioning"]),
            "--registry-env",
            str(rendered_paths["registry"]),
            "--inventory-path",
            str(inventory_path),
            "--skip-smoke-help",
        ]
        if canary_env.get("CHAIN_NAME"):
            gate_command.extend(["--expected-chain-name", canary_env["CHAIN_NAME"]])
        if canary_env.get("CHAIN_ID"):
            gate_command.extend(["--expected-chain-id", canary_env["CHAIN_ID"]])
        _run_command(
            gate_command,
            cwd=ROOT,
        )

    if not args.skip_bundle_validation:
        _run_command(
            _build_bundle_validation_command(
                environment=args.environment,
                rendered_paths=rendered_paths,
                inventory_path=inventory_path,
                canary_env=canary_env,
            ),
            cwd=ROOT,
        )

    process_env = _build_canary_process_env(rendered_paths["canary"])
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    canary_log_path = artifacts_dir / "prod-canary.log"
    canary_exit_code = _run_logged_command(
        ["uv", "--no-config", "run", "python", "scripts/prod_canary_smoke.py"],
        cwd=ROOT,
        log_path=canary_log_path,
        env=process_env,
    )
    if canary_exit_code == 0:
        return 0

    _run_logged_command(
        [
            "uv",
            "--no-config",
            "run",
            "python",
            "scripts/prod_canary_rollback.py",
            "--log-path",
            str(canary_log_path),
        ],
        cwd=ROOT,
        log_path=artifacts_dir / "prod-canary-rollback.log",
        env=process_env,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
