#!/usr/bin/env python3
"""Run the repo-side deployment readiness gates."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]


def _run_command(command: list[str], *, cwd: Path) -> None:
    print(f"[run] ({cwd}) {' '.join(command)}")
    subprocess.run(command, cwd=cwd, check=True)


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", default="dev")
    parser.add_argument("--agent-env", type=Path)
    parser.add_argument("--seller-agent-env", type=Path)
    parser.add_argument("--buyer-agent-env", type=Path)
    parser.add_argument("--provisioning-env", type=Path)
    parser.add_argument("--registry-env", type=Path)
    parser.add_argument("--inventory-path", type=Path)
    parser.add_argument("--seller-agent-url")
    parser.add_argument("--buyer-agent-url")
    parser.add_argument("--seller-agent-id")
    parser.add_argument("--buyer-agent-id")
    parser.add_argument("--seller-private-key")
    parser.add_argument("--buyer-private-key")
    parser.add_argument("--ssh-private-key-path")
    parser.add_argument("--expected-chain-name")
    parser.add_argument("--expected-chain-id", type=int)
    parser.add_argument(
        "--skip-smoke-help",
        action="store_true",
        help="Skip the smoke-script CLI availability check",
    )
    return parser.parse_args(argv)


def _env_bundle_supplied(args: argparse.Namespace) -> bool:
    has_single = args.agent_env is not None
    has_dual = args.seller_agent_env is not None or args.buyer_agent_env is not None

    if has_single and has_dual:
        raise SystemExit(
            "Provide either --agent-env with --provisioning-env and --registry-env, "
            "or provide both --seller-agent-env and --buyer-agent-env with the same shared env files."
        )
    if has_single:
        if not (args.provisioning_env and args.registry_env):
            raise SystemExit(
                "Provide --agent-env, --provisioning-env, and --registry-env together."
            )
        return True
    if has_dual or args.provisioning_env or args.registry_env:
        if not (
            args.seller_agent_env
            and args.buyer_agent_env
            and args.provisioning_env
            and args.registry_env
        ):
            raise SystemExit(
                "Provide either --agent-env with --provisioning-env and --registry-env, "
                "or provide both --seller-agent-env and --buyer-agent-env with the same shared env files."
            )
        return True
    return False


def _validator_command(args: argparse.Namespace) -> list[str]:
    command = [
        "python",
        "scripts/validate_deployment_bundle.py",
        "--environment",
        args.environment,
    ]
    if args.agent_env:
        command.extend(["--agent-env", str(args.agent_env)])
    else:
        command.extend(
            [
                "--seller-agent-env",
                str(args.seller_agent_env),
                "--buyer-agent-env",
                str(args.buyer_agent_env),
            ]
        )
    command.extend(
        [
            "--provisioning-env",
            str(args.provisioning_env),
            "--registry-env",
            str(args.registry_env),
        ]
    )
    if args.inventory_path:
        command.extend(["--inventory-path", str(args.inventory_path)])
    if args.expected_chain_name:
        command.extend(["--expected-chain-name", args.expected_chain_name])
    if args.expected_chain_id is not None:
        command.extend(["--expected-chain-id", str(args.expected_chain_id)])
    optional_args = {
        "--seller-agent-url": args.seller_agent_url,
        "--buyer-agent-url": args.buyer_agent_url,
        "--seller-agent-id": args.seller_agent_id,
        "--buyer-agent-id": args.buyer_agent_id,
        "--seller-private-key": args.seller_private_key,
        "--buyer-private-key": args.buyer_private_key,
        "--ssh-private-key-path": args.ssh_private_key_path,
    }
    for flag, value in optional_args.items():
        if value:
            command.extend([flag, value])
    return command


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    has_env_bundle = _env_bundle_supplied(args)

    _run_command(
        [
            "uv",
            "--no-config",
            "run",
            "pytest",
            "tests/unit/test_repo_consistency.py",
            "tests/unit/test_validate_deployment_bundle.py",
            "tests/unit/test_deployment_gate_checks.py",
            "tests/unit/test_alkahest_config.py",
            "-q",
        ],
        cwd=ROOT / "core",
    )
    _run_command(
        ["uv", "--no-config", "run", "pytest", "tests/unit/test_alkahest.py", "-q"],
        cwd=ROOT / "service",
    )
    _run_command(
        [
            "uv",
            "--no-config",
            "run",
            "pytest",
            "tests/test_canary_actors.py",
            "tests/test_canary_rollback.py",
            "tests/test_prod_canary_smoke.py",
            "tests/test_config_init.py",
            "tests/test_order_auth.py",
            "-q",
        ],
        cwd=ROOT / "cli",
    )

    if has_env_bundle:
        _run_command(_validator_command(args), cwd=ROOT)
    else:
        print("[skip] Gate 1 env-bundle preflight skipped: no env bundle paths provided")

    if not args.skip_smoke_help:
        _run_command(
            ["uv", "--no-config", "run", "python", "../scripts/prod_canary_smoke.py", "--help"],
            cwd=ROOT / "cli",
        )

    print("[ok] deployment gate checks completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
