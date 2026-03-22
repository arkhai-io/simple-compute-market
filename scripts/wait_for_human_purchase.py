#!/usr/bin/env python3
"""Wait for a human-triggered purchase to finish and print SSH access details."""

from __future__ import annotations

import argparse
import json
import shlex
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


def fetch_order(registry_url: str, order_id: str) -> dict[str, object]:
    payload = _request_json(f"{registry_url.rstrip('/')}/orders/{order_id}")
    order = payload.get("order")
    if not isinstance(order, dict):
        raise SystemExit(f"Registry response for order {order_id} was missing an order payload")
    return order


def list_jobs(provisioning_url: str, agent_id: str, *, limit: int = 100) -> list[dict[str, object]]:
    payload = _request_json(
        f"{provisioning_url.rstrip('/')}/api/v1/jobs?limit={limit}",
        headers={"X-Agent-ID": agent_id},
    )
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise SystemExit("Provisioning list response was missing jobs")
    return [job for job in jobs if isinstance(job, dict)]


def select_create_job(*, jobs: list[dict[str, object]], buyer_agent_id: str) -> dict[str, object]:
    for job in jobs:
        params = job.get("params")
        if not isinstance(params, dict):
            continue
        if params.get("vm_action") != "create":
            continue
        if params.get("buyer_agent_id") != buyer_agent_id:
            continue
        return job
    raise SystemExit(
        f"Could not find a create job for buyer agent {buyer_agent_id} in the latest provisioning jobs"
    )


def fetch_job(provisioning_url: str, agent_id: str, job_id: str) -> dict[str, object]:
    payload = _request_json(
        f"{provisioning_url.rstrip('/')}/api/v1/jobs/{job_id}",
        headers={"X-Agent-ID": agent_id},
    )
    if not isinstance(payload, dict):
        raise SystemExit(f"Provisioning response for job {job_id} was not a JSON object")
    return payload


def fetch_credentials(provisioning_url: str, agent_id: str, job_id: str) -> dict[str, object]:
    payload = _request_json(
        f"{provisioning_url.rstrip('/')}/api/v1/jobs/{job_id}/credentials",
        headers={"X-Agent-ID": agent_id},
    )
    if not isinstance(payload, dict):
        raise SystemExit(f"Credential response for job {job_id} was not a JSON object")
    return payload


def build_ssh_probe_command(
    *,
    ssh_command: str,
    ssh_private_key_path: str,
    known_hosts_path: Path,
) -> list[str]:
    rewritten = ssh_command.replace("<your_private_key>", ssh_private_key_path)
    parts = shlex.split(rewritten)
    if not parts or parts[0] != "ssh":
        raise SystemExit(f"Unsupported SSH command format: {ssh_command}")
    return [
        "ssh",
        "-i",
        ssh_private_key_path,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        f"UserKnownHostsFile={known_hosts_path}",
        *parts[3:],
        "echo connected && hostname && whoami",
    ]


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def _tenant_external_ssh_command(credentials_payload: dict[str, object]) -> str | None:
    credentials = credentials_payload.get("credentials")
    if not isinstance(credentials, list):
        return None
    for entry in credentials:
        if not isinstance(entry, dict) or entry.get("role") != "tenant":
            continue
        ssh_commands = entry.get("ssh_commands")
        if isinstance(ssh_commands, dict):
            command = ssh_commands.get("external")
            if isinstance(command, str) and command:
                return command
    return None


def _write_artifact(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def wait_for_human_purchase(
    *,
    context_path: Path,
    seller_order_id: str,
    buyer_order_id: str,
    timeout_seconds: float,
    poll_seconds: float,
    verify_ssh: bool = True,
    artifact_path: Path | None = None,
) -> dict[str, object]:
    context = _load_context(context_path)
    registry_url = context["registry_url"]
    provisioning_url = context["provisioning_url"]
    seller_agent_id = context["seller_agent_id"]
    buyer_agent_id = context["buyer_agent_id"]
    ssh_private_key_path = context.get("ssh_private_key_path", "")

    deadline = time.monotonic() + timeout_seconds
    selected_job: dict[str, object] | None = None
    seller_order: dict[str, object] | None = None
    buyer_order: dict[str, object] | None = None

    while time.monotonic() < deadline:
        seller_order = fetch_order(registry_url, seller_order_id)
        buyer_order = fetch_order(registry_url, buyer_order_id)
        jobs = list_jobs(provisioning_url, seller_agent_id, limit=100)
        try:
            selected_job = select_create_job(jobs=jobs, buyer_agent_id=buyer_agent_id)
        except SystemExit:
            selected_job = None

        if selected_job is not None:
            current = fetch_job(provisioning_url, seller_agent_id, str(selected_job["job_id"]))
            if str(current.get("status")) in TERMINAL_JOB_STATUSES:
                selected_job = current
                break
        time.sleep(poll_seconds)

    if seller_order is None or buyer_order is None or selected_job is None:
        raise SystemExit(
            f"Timed out waiting for purchase state for seller={seller_order_id} buyer={buyer_order_id}"
        )

    job_id = str(selected_job["job_id"])
    credentials_payload = fetch_credentials(provisioning_url, buyer_agent_id, job_id)
    ssh_command = _tenant_external_ssh_command(credentials_payload)
    artifact: dict[str, object] = {
        "seller_order_id": seller_order_id,
        "buyer_order_id": buyer_order_id,
        "seller_order_status": seller_order.get("status"),
        "buyer_order_status": buyer_order.get("status"),
        "job_id": job_id,
        "job_status": selected_job.get("status"),
        "vm_target": (selected_job.get("params") or {}).get("vm_target"),
        "ssh_command": ssh_command,
    }

    if verify_ssh and ssh_command and ssh_private_key_path:
        known_hosts_path = context_path.parent / "known_hosts"
        probe_command = build_ssh_probe_command(
            ssh_command=ssh_command,
            ssh_private_key_path=ssh_private_key_path,
            known_hosts_path=known_hosts_path,
        )
        completed = _run_command(probe_command)
        artifact["ssh_probe"] = {
            "command": probe_command,
            "output": completed.stdout.splitlines(),
        }

    if artifact_path is None:
        artifact_path = context_path.parent / f"purchase-{buyer_order_id}.json"
    artifact["artifact_path"] = str(_write_artifact(artifact_path, artifact))
    return artifact


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Wait for a human-triggered purchase to provision and print SSH details."
    )
    parser.add_argument("--context-path", type=Path, required=True)
    parser.add_argument("--seller-order-id", required=True)
    parser.add_argument("--buyer-order-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    parser.add_argument("--skip-ssh-check", action="store_true")
    parser.add_argument("--artifact-path", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = wait_for_human_purchase(
        context_path=args.context_path.expanduser(),
        seller_order_id=args.seller_order_id,
        buyer_order_id=args.buyer_order_id,
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
        verify_ssh=not args.skip_ssh_check,
        artifact_path=args.artifact_path.expanduser() if args.artifact_path else None,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
