#!/usr/bin/env python3
"""Inspect and clean up support cases for live market runs."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_NAME = "run_market_support"
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cleanup_human_purchase import (
    build_order_close_command,
    submit_reclaim_job,
    wait_for_job_terminal_state,
)
from role_contracts import build_artifact
from wait_for_human_purchase import fetch_job, fetch_order, list_jobs, select_create_job


def _load_context(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _run_command(command: list[str]) -> None:
    subprocess.run(command, check=True)


def _select_job(
    *,
    provisioning_url: str,
    seller_agent_id: str,
    buyer_agent_id: str,
    seller_order_created_at: str | None,
    job_id: str | None,
) -> dict[str, object]:
    if job_id:
        return fetch_job(provisioning_url, seller_agent_id, job_id)

    jobs = list_jobs(provisioning_url, seller_agent_id, limit=100)
    selected = select_create_job(
        jobs=jobs,
        buyer_agent_id=buyer_agent_id,
        order_created_at=seller_order_created_at,
    )
    return fetch_job(provisioning_url, seller_agent_id, str(selected["job_id"]))


def inspect_support_case(
    *,
    context_path: Path,
    seller_order_id: str,
    buyer_order_id: str,
    job_id: str | None = None,
    artifact_path: Path | None = None,
) -> dict[str, Any]:
    context = _load_context(context_path)
    registry_url = context["registry_url"]
    provisioning_url = context["provisioning_url"]
    seller_agent_id = context["seller_agent_id"]
    buyer_agent_id = context["buyer_agent_id"]

    seller_order = fetch_order(registry_url, seller_order_id)
    buyer_order = fetch_order(registry_url, buyer_order_id)
    selected_job = _select_job(
        provisioning_url=provisioning_url,
        seller_agent_id=seller_agent_id,
        buyer_agent_id=buyer_agent_id,
        seller_order_created_at=seller_order.get("created_at")
        if isinstance(seller_order.get("created_at"), str)
        else None,
        job_id=job_id,
    )
    params = selected_job.get("params") if isinstance(selected_job.get("params"), dict) else {}
    result = selected_job.get("result") if isinstance(selected_job.get("result"), dict) else {}
    vm_target = params.get("vm_target") if isinstance(params, dict) else None
    vm_host = params.get("vm_host") if isinstance(params, dict) else None
    job_status = str(selected_job.get("status") or "unknown")

    artifact = build_artifact(
        role="support",
        action="inspect",
        status=job_status,
        request_url=registry_url,
        auth_url=provisioning_url,
        correlation={
            "order_id": buyer_order_id,
            "job_id": str(selected_job.get("job_id") or job_id or ""),
            "vm_target": vm_target,
        },
        details={
            "seller_order_id": seller_order_id,
            "buyer_order_id": buyer_order_id,
            "seller_order_status": seller_order.get("status"),
            "buyer_order_status": buyer_order.get("status"),
            "job_status": selected_job.get("status"),
            "vm_host": vm_host,
            "vm_target": vm_target,
            "job_result": result,
        },
    )
    if artifact_path is None:
        artifact_path = context_path.parent / f"support-inspect-{buyer_order_id}.json"
    artifact["artifact_path"] = str(_write_json(artifact_path, artifact))
    return artifact


def cleanup_support_case(
    *,
    context_path: Path,
    seller_order_id: str,
    buyer_order_id: str,
    job_id: str | None = None,
    timeout_seconds: float = 180.0,
    poll_seconds: float = 3.0,
    artifact_path: Path | None = None,
) -> dict[str, Any]:
    context = _load_context(context_path)
    registry_url = context["registry_url"]
    provisioning_url = context["provisioning_url"]
    seller_agent_id = context["seller_agent_id"]
    buyer_agent_id = context["buyer_agent_id"]
    sandbox_dir = Path(context["sandbox_dir"])

    seller_order = fetch_order(registry_url, seller_order_id)
    buyer_order = fetch_order(registry_url, buyer_order_id)
    selected_job = _select_job(
        provisioning_url=provisioning_url,
        seller_agent_id=seller_agent_id,
        buyer_agent_id=buyer_agent_id,
        seller_order_created_at=seller_order.get("created_at")
        if isinstance(seller_order.get("created_at"), str)
        else None,
        job_id=job_id,
    )
    params = selected_job.get("params") if isinstance(selected_job.get("params"), dict) else {}
    vm_host = str(params.get("vm_host") or "")
    vm_target = str(params.get("vm_target") or "")
    if not vm_host or not vm_target:
        raise SystemExit(f"Create job {selected_job.get('job_id')} was missing vm_host/vm_target")

    close_commands = [
        build_order_close_command(
            sandbox_dir=sandbox_dir,
            order_id=seller_order_id,
            agent_url=context["seller_agent_url"],
            side="seller",
        ),
        build_order_close_command(
            sandbox_dir=sandbox_dir,
            order_id=buyer_order_id,
            agent_url=context["buyer_agent_url"],
            side="buyer",
        ),
    ]
    for command in close_commands:
        _run_command(command)

    reclaim_actions: list[dict[str, object]] = []
    for vm_action in ("destroy", "undefine"):
        submitted = submit_reclaim_job(
            provisioning_url=provisioning_url,
            seller_agent_id=seller_agent_id,
            vm_host=vm_host,
            vm_target=vm_target,
            vm_action=vm_action,
        )
        terminal = wait_for_job_terminal_state(
            provisioning_url=provisioning_url,
            agent_id=seller_agent_id,
            job_id=str(submitted["job_id"]),
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )
        reclaim_actions.append(
            {
                "job_id": terminal.get("job_id"),
                "status": terminal.get("status"),
            }
        )

    artifact = build_artifact(
        role="support",
        action="cleanup",
        status="succeeded",
        request_url=registry_url,
        auth_url=provisioning_url,
        correlation={
            "order_id": buyer_order_id,
            "job_id": str(selected_job.get("job_id") or job_id or ""),
            "vm_target": vm_target,
        },
        details={
            "seller_order_id": seller_order_id,
            "buyer_order_id": buyer_order_id,
            "seller_order_status": seller_order.get("status"),
            "buyer_order_status": buyer_order.get("status"),
            "create_job_id": selected_job.get("job_id"),
            "vm_host": vm_host,
            "vm_target": vm_target,
            "reclaim_actions": reclaim_actions,
        },
    )
    if artifact_path is None:
        artifact_path = context_path.parent / f"support-cleanup-{selected_job.get('job_id')}.json"
    artifact["artifact_path"] = str(_write_json(artifact_path, artifact))
    return artifact


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect or clean up a support case.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect a live run and write a support artifact.")
    inspect_parser.add_argument("--context-path", type=Path, required=True)
    inspect_parser.add_argument("--seller-order-id", required=True)
    inspect_parser.add_argument("--buyer-order-id", required=True)
    inspect_parser.add_argument("--job-id")
    inspect_parser.add_argument("--artifact-path", type=Path)

    cleanup_parser = subparsers.add_parser("cleanup", help="Close orders and reclaim the VM for a live run.")
    cleanup_parser.add_argument("--context-path", type=Path, required=True)
    cleanup_parser.add_argument("--seller-order-id", required=True)
    cleanup_parser.add_argument("--buyer-order-id", required=True)
    cleanup_parser.add_argument("--job-id")
    cleanup_parser.add_argument("--timeout-seconds", type=float, default=180.0)
    cleanup_parser.add_argument("--poll-seconds", type=float, default=3.0)
    cleanup_parser.add_argument("--artifact-path", type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "inspect":
        result = inspect_support_case(
            context_path=args.context_path.expanduser(),
            seller_order_id=args.seller_order_id,
            buyer_order_id=args.buyer_order_id,
            job_id=args.job_id,
            artifact_path=args.artifact_path.expanduser() if args.artifact_path else None,
        )
    else:
        result = cleanup_support_case(
            context_path=args.context_path.expanduser(),
            seller_order_id=args.seller_order_id,
            buyer_order_id=args.buyer_order_id,
            job_id=args.job_id,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
            artifact_path=args.artifact_path.expanduser() if args.artifact_path else None,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
