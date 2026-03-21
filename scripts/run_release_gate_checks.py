#!/usr/bin/env python3
"""Run the expanded release gates for production readiness."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]


def _run_command(command: list[str], *, cwd: Path) -> None:
    print(f"[run] ({cwd}) {' '.join(command)}")
    subprocess.run(command, cwd=cwd, check=True)


def _extract_canary_result(log_path: Path) -> dict[str, object]:
    text = log_path.read_text(encoding="utf-8")
    marker = "[success] canary completed"
    if marker not in text:
        raise SystemExit(
            f"{log_path} does not prove a successful deployed canary: missing success marker"
        )

    payload = text.split(marker, 1)[1].strip()
    if not payload:
        raise SystemExit(
            f"{log_path} does not prove a successful deployed canary: missing JSON result payload"
        )

    try:
        result = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"{log_path} does not prove a successful deployed canary: invalid JSON payload"
        ) from exc

    if not isinstance(result, dict):
        raise SystemExit(
            f"{log_path} does not prove a successful deployed canary: JSON payload must be an object"
        )
    return result


def _validate_deployed_canary_log(log_path: Path) -> None:
    if not log_path.exists():
        raise SystemExit(f"Deployed canary log not found: {log_path}")

    result = _extract_canary_result(log_path)
    required_tokens = ("seller_order_id", "buyer_order_id", "provisioning_job_id")
    if result.get("status") != "succeeded" or any(not result.get(token) for token in required_tokens):
        raise SystemExit(
            f"{log_path} does not prove a successful deployed canary: "
            "expected status=succeeded with seller_order_id, buyer_order_id, and provisioning_job_id"
        )


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployed-canary-log", type=Path, help="Path to a successful isolated deployed-canary log (for example prod-canary.log).")
    args, gate_args = parser.parse_known_args(argv)
    if args.deployed_canary_log is None:
        raise SystemExit(
            "Provide --deployed-canary-log from a successful isolated deployed canary run."
        )
    return argparse.Namespace(
        deployed_canary_log=args.deployed_canary_log,
        gate_args=gate_args,
    )


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    _validate_deployed_canary_log(args.deployed_canary_log)

    _run_command(
        ["python", "scripts/run_deployment_gate_checks.py", *args.gate_args],
        cwd=ROOT,
    )
    _run_command(["python", "scripts/run_full_repo_validation.py"], cwd=ROOT)

    print(f"[ok] validated deployed canary proof from {args.deployed_canary_log}")
    print("[ok] release gate checks completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
