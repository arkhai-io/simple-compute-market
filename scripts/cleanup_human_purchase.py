#!/usr/bin/env python3
"""Close human purchase orders and reclaim the provisioned VM."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.request
from pathlib import Path


TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}


def _load_context(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


def _request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    data = None
    request_headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def _run_command(command: list[str]) -> None:
    subprocess.run(command, check=True)


def build_order_close_command(
    *,
    sandbox_dir: Path,
    order_id: str,
    agent_url: str,
    side: str,
) -> list[str]:
    return [
        str(sandbox_dir / "venv/bin/market"),
        "order",
        "close",
        order_id,
        "--agent-url",
        agent_url,
        "--env",
        str(sandbox_dir / f"{side}.env"),
    ]


def fetch_job(provisioning_url: str, agent_id: str, job_id: str) -> dict[str, object]:
    payload = _request_json(
        f"{provisioning_url.rstrip('/')}/api/v1/jobs/{job_id}",
        headers={"X-Agent-ID": agent_id},
    )
    if not isinstance(payload, dict):
        raise SystemExit(f"Provisioning response for job {job_id} was not a JSON object")
    return payload


def submit_reclaim_job(
    *,
    provisioning_url: str,
    seller_agent_id: str,
    vm_host: str,
    vm_target: str,
    vm_action: str,
) -> dict[str, object]:
    return _request_json(
        f"{provisioning_url.rstrip('/')}/api/v1/jobs",
        method="POST",
        headers={"X-Agent-ID": seller_agent_id},
        payload={
            "vm_host": vm_host,
            "vm_target": vm_target,
            "vm_action": vm_action,
        },
    )


def wait_for_job_terminal_state(
    *,
    provisioning_url: str,
    agent_id: str,
    job_id: str,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        payload = fetch_job(provisioning_url, agent_id, job_id)
        if str(payload.get("status")) in TERMINAL_JOB_STATUSES:
            return payload
        time.sleep(poll_seconds)
    raise SystemExit(f"Timed out waiting for provisioning job {job_id}")


def cleanup_purchase(
    *,
    context_path: Path,
    seller_order_id: str,
    buyer_order_id: str,
    job_id: str,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, object]:
    context = _load_context(context_path)
    sandbox_dir = Path(context["sandbox_dir"])
    _run_command(
        build_order_close_command(
            sandbox_dir=sandbox_dir,
            order_id=seller_order_id,
            agent_url=context["seller_agent_url"],
            side="seller",
        )
    )
    _run_command(
        build_order_close_command(
            sandbox_dir=sandbox_dir,
            order_id=buyer_order_id,
            agent_url=context["buyer_agent_url"],
            side="buyer",
        )
    )

    create_job = fetch_job(context["provisioning_url"], context["seller_agent_id"], job_id)
    params = create_job.get("params")
    if not isinstance(params, dict):
        raise SystemExit(f"Create job {job_id} was missing params")
    vm_host = str(params.get("vm_host") or "")
    vm_target = str(params.get("vm_target") or "")
    if not vm_host or not vm_target:
        raise SystemExit(f"Create job {job_id} was missing vm_host/vm_target")

    reclaim_actions: list[dict[str, object]] = []
    for vm_action in ("destroy", "undefine"):
        submitted = submit_reclaim_job(
            provisioning_url=context["provisioning_url"],
            seller_agent_id=context["seller_agent_id"],
            vm_host=vm_host,
            vm_target=vm_target,
            vm_action=vm_action,
        )
        terminal = wait_for_job_terminal_state(
            provisioning_url=context["provisioning_url"],
            agent_id=context["seller_agent_id"],
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

    result = {
        "seller_order_id": seller_order_id,
        "buyer_order_id": buyer_order_id,
        "create_job_id": job_id,
        "vm_host": vm_host,
        "vm_target": vm_target,
        "reclaim_actions": reclaim_actions,
    }
    artifact_path = context_path.parent / f"cleanup-{job_id}.json"
    artifact_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    result["artifact_path"] = str(artifact_path)
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Close human purchase orders and reclaim the provisioned VM."
    )
    parser.add_argument("--context-path", type=Path, required=True)
    parser.add_argument("--seller-order-id", required=True)
    parser.add_argument("--buyer-order-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = cleanup_purchase(
        context_path=args.context_path.expanduser(),
        seller_order_id=args.seller_order_id,
        buyer_order_id=args.buyer_order_id,
        job_id=args.job_id,
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
