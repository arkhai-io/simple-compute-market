#!/usr/bin/env python3
"""Production canary smoke test for the deployed full stack."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def _env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


def _require(value: str | None, label: str) -> str:
    if value:
        return value
    raise SystemExit(f"Missing required value for {label}")


def _normalize_base_url(raw_url: str) -> str:
    return raw_url.rstrip("/")


def _request_json(
    method: str,
    url: str,
    *,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> dict:
    body = None
    request_headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read().decode("utf-8")
            return json.loads(data) if data else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if exc.fp else str(exc)
        raise SystemExit(f"{method} {url} failed with {exc.code}: {detail}") from exc


def _sign_headers(operation: str, resource_id: str, private_key: str) -> dict[str, str]:
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
    except ImportError as exc:
        raise SystemExit(
            "eth-account is required for signed canary requests. "
            "Run this script with `cd cli && uv run python ../scripts/prod_canary_smoke.py ...`."
        ) from exc

    timestamp = int(time.time())
    message = f"{operation}:{resource_id}:{timestamp}"
    signature = Account.sign_message(
        encode_defunct(text=message),
        private_key,
    ).signature.hex()
    return {
        "X-Signature": signature,
        "X-Timestamp": str(timestamp),
    }


def _check_health(label: str, url: str) -> dict:
    print(f"[health] {label}: {url}")
    return _request_json("GET", url)


def _create_order(
    *,
    agent_url: str,
    private_key: str,
    offer: dict,
    demand: dict,
    duration_hours: int,
) -> None:
    url = f"{_normalize_base_url(agent_url)}/orders/create"
    headers = _sign_headers("create_order", _normalize_base_url(agent_url), private_key)
    payload = {
        "offer": offer,
        "demand": demand,
        "duration_hours": duration_hours,
    }
    response = _request_json("POST", url, payload=payload, headers=headers, timeout=120.0)
    status = response.get("status")
    if status not in {"queued", "created"}:
        raise SystemExit(f"Unexpected order creation status from {agent_url}: {response}")


def _fetch_agent_orders(registry_url: str, agent_id: str) -> list[dict]:
    encoded = urllib.parse.quote(agent_id, safe="")
    response = _request_json("GET", f"{_normalize_base_url(registry_url)}/agents/{encoded}/orders")
    return response.get("items", [])


def _wait_for_new_order(
    *,
    registry_url: str,
    agent_id: str,
    baseline_ids: set[str],
    timeout: int,
    poll_interval: int,
) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        items = _fetch_agent_orders(registry_url, agent_id)
        current_ids = {item["order_id"] for item in items}
        new_ids = sorted(current_ids - baseline_ids)
        if new_ids:
            return new_ids[-1]
        time.sleep(poll_interval)
    raise SystemExit(f"Timed out waiting for a new registry order for {agent_id}")


def _fetch_order(registry_url: str, order_id: str) -> dict:
    response = _request_json("GET", f"{_normalize_base_url(registry_url)}/orders/{order_id}")
    return response["order"]


def _wait_for_orders_closed(
    *,
    registry_url: str,
    order_ids: list[str],
    timeout: int,
    poll_interval: int,
) -> dict[str, dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        orders = {order_id: _fetch_order(registry_url, order_id) for order_id in order_ids}
        if all(order.get("status") == "closed" for order in orders.values()):
            return orders
        time.sleep(poll_interval)
    raise SystemExit(f"Timed out waiting for orders to close: {order_ids}")


def _list_jobs(provisioning_url: str, agent_id: str) -> list[dict]:
    response = _request_json(
        "GET",
        f"{_normalize_base_url(provisioning_url)}/api/v1/jobs?limit=100",
        headers={"X-Agent-ID": agent_id},
    )
    return response.get("jobs", [])


def _wait_for_new_succeeded_job(
    *,
    provisioning_url: str,
    seller_agent_id: str,
    baseline_job_ids: set[str],
    timeout: int,
    poll_interval: int,
) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        jobs = _list_jobs(provisioning_url, seller_agent_id)
        for job in jobs:
            job_id = job.get("job_id")
            if not job_id or job_id in baseline_job_ids:
                continue
            if job.get("status") == "succeeded":
                return job
        time.sleep(poll_interval)
    raise SystemExit("Timed out waiting for a new succeeded provisioning job")


def _fetch_credentials(provisioning_url: str, job_id: str, agent_id: str) -> list[dict]:
    response = _request_json(
        "GET",
        f"{_normalize_base_url(provisioning_url)}/api/v1/jobs/{job_id}/credentials",
        headers={"X-Agent-ID": agent_id},
    )
    return response.get("credentials", [])


def _verify_ssh(credentials: list[dict], ssh_private_key_path: str | None) -> None:
    if not ssh_private_key_path:
        print("[ssh] skipped: no --ssh-private-key-path provided")
        return

    tenant_credential = next((cred for cred in credentials if cred.get("role") == "tenant"), None)
    if not tenant_credential:
        raise SystemExit("Tenant credential not returned by provisioning service")

    ssh_commands = tenant_credential.get("ssh_commands") or {}
    external = ssh_commands.get("external")
    if not external:
        raise SystemExit("Tenant credential did not include an external SSH command")

    command = external.replace("<your_private_key>", ssh_private_key_path)
    parts = shlex.split(command)
    if parts and parts[0] == "ssh" and "-i" not in parts:
        parts[1:1] = ["-i", ssh_private_key_path]
    if parts and parts[0] == "ssh":
        parts[1:1] = [
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
        ]
    parts.extend(["hostname"])

    print(f"[ssh] verifying remote access via: {' '.join(parts)}")
    subprocess.run(parts, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-url", default=_env("REGISTRY_URL"))
    parser.add_argument("--provisioning-url", default=_env("PROVISIONING_SERVICE_URL"))
    parser.add_argument("--seller-agent-url", default=_env("SELLER_AGENT_URL"))
    parser.add_argument("--buyer-agent-url", default=_env("BUYER_AGENT_URL"))
    parser.add_argument("--seller-agent-id", default=_env("SELLER_AGENT_ID"))
    parser.add_argument("--buyer-agent-id", default=_env("BUYER_AGENT_ID"))
    parser.add_argument("--seller-private-key", default=_env("SELLER_PRIVATE_KEY"))
    parser.add_argument("--buyer-private-key", default=_env("BUYER_PRIVATE_KEY"))
    parser.add_argument("--ssh-private-key-path", default=_env("SSH_PRIVATE_KEY_PATH"))
    parser.add_argument("--gpu-model", default=_env("CANARY_GPU_MODEL", "H200"))
    parser.add_argument("--region", default=_env("CANARY_REGION", "California, US"))
    parser.add_argument("--token-symbol", default=_env("CANARY_TOKEN_SYMBOL", "USDC"))
    parser.add_argument("--token-amount", type=float, default=float(_env("CANARY_TOKEN_AMOUNT", "1.0")))
    parser.add_argument("--quantity", type=int, default=int(_env("CANARY_GPU_QUANTITY", "1")))
    parser.add_argument("--sla", type=float, default=float(_env("CANARY_SLA", "90.0")))
    parser.add_argument("--duration-hours", type=int, default=int(_env("CANARY_DURATION_HOURS", "1")))
    parser.add_argument("--timeout", type=int, default=int(_env("CANARY_TIMEOUT_SECONDS", "600")))
    parser.add_argument("--poll-interval", type=int, default=int(_env("CANARY_POLL_INTERVAL", "5")))
    args = parser.parse_args()

    registry_url = _normalize_base_url(_require(args.registry_url, "registry-url"))
    provisioning_url = _normalize_base_url(_require(args.provisioning_url, "provisioning-url"))
    seller_agent_url = _normalize_base_url(_require(args.seller_agent_url, "seller-agent-url"))
    buyer_agent_url = _normalize_base_url(_require(args.buyer_agent_url, "buyer-agent-url"))
    seller_agent_id = _require(args.seller_agent_id, "seller-agent-id")
    buyer_agent_id = _require(args.buyer_agent_id, "buyer-agent-id")
    seller_private_key = _require(args.seller_private_key, "seller-private-key")
    buyer_private_key = _require(args.buyer_private_key, "buyer-private-key")

    _check_health("registry", f"{registry_url}/health")
    _check_health("provisioning", f"{provisioning_url}/health")
    _request_json("GET", f"{seller_agent_url}/.well-known/agent-card.json")
    _request_json("GET", f"{buyer_agent_url}/.well-known/agent-card.json")

    seller_baseline_orders = {item["order_id"] for item in _fetch_agent_orders(registry_url, seller_agent_id)}
    buyer_baseline_orders = {item["order_id"] for item in _fetch_agent_orders(registry_url, buyer_agent_id)}
    seller_baseline_jobs = {job["job_id"] for job in _list_jobs(provisioning_url, seller_agent_id)}

    compute_resource = {
        "gpu_model": args.gpu_model,
        "quantity": args.quantity,
        "sla": args.sla,
        "region": args.region,
    }
    token_resource = {
        "token": args.token_symbol,
        "amount": args.token_amount,
    }

    print("[order] creating seller canary order")
    _create_order(
        agent_url=seller_agent_url,
        private_key=seller_private_key,
        offer=compute_resource,
        demand=token_resource,
        duration_hours=args.duration_hours,
    )
    seller_order_id = _wait_for_new_order(
        registry_url=registry_url,
        agent_id=seller_agent_id,
        baseline_ids=seller_baseline_orders,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
    )
    print(f"[order] seller order: {seller_order_id}")

    print("[order] creating buyer canary order")
    _create_order(
        agent_url=buyer_agent_url,
        private_key=buyer_private_key,
        offer=token_resource,
        demand=compute_resource,
        duration_hours=args.duration_hours,
    )
    buyer_order_id = _wait_for_new_order(
        registry_url=registry_url,
        agent_id=buyer_agent_id,
        baseline_ids=buyer_baseline_orders,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
    )
    print(f"[order] buyer order: {buyer_order_id}")

    job = _wait_for_new_succeeded_job(
        provisioning_url=provisioning_url,
        seller_agent_id=seller_agent_id,
        baseline_job_ids=seller_baseline_jobs,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
    )
    print(f"[provisioning] succeeded job: {job['job_id']}")

    credentials = _fetch_credentials(provisioning_url, job["job_id"], buyer_agent_id)
    tenant_credentials = [cred for cred in credentials if cred.get("role") == "tenant"]
    if not tenant_credentials:
        raise SystemExit("No tenant credentials returned for buyer agent")
    _verify_ssh(credentials, args.ssh_private_key_path)

    orders = _wait_for_orders_closed(
        registry_url=registry_url,
        order_ids=[seller_order_id, buyer_order_id],
        timeout=args.timeout,
        poll_interval=args.poll_interval,
    )
    print("[success] canary completed")
    print(json.dumps({"job": job, "orders": orders}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
