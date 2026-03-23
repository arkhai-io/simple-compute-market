#!/usr/bin/env python3
"""Buyer-facing wrapper for discovering a live offer and purchasing compute."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from role_contracts import build_artifact
from wait_for_human_purchase import (
    TERMINAL_JOB_STATUSES,
    _run_command as run_probe_command,
    _tenant_external_ssh_command,
    build_ssh_probe_command,
    fetch_credentials,
    fetch_job,
    fetch_order,
    list_jobs,
    select_create_job,
)


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
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def list_open_offers(registry_url: str, *, limit: int = 50) -> list[dict[str, object]]:
    params = urllib.parse.urlencode({"status": "open", "limit": limit, "offset": 0})
    payload = _request_json(f"{registry_url.rstrip('/')}/orders?{params}")
    items = payload.get("items")
    if not isinstance(items, list):
        raise SystemExit("Registry response was missing open order items")
    return [item for item in items if isinstance(item, dict)]


def _normalize_registry_resource(resource: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(resource, dict):
        return resource
    token = resource.get("token")
    amount = resource.get("amount")
    if isinstance(token, dict) and "decimals" in token and amount is not None:
        try:
            decimals = int(token["decimals"])
            amount_value = Decimal(str(amount))
        except (TypeError, ValueError, InvalidOperation):
            return resource
        human_amount = amount_value / (Decimal(10) ** decimals)
        normalized = dict(resource)
        normalized["amount"] = str(human_amount.normalize())
        return normalized
    return resource


def _offer_price(order: dict[str, object]) -> Decimal | None:
    demand = order.get("demand_resource")
    if not isinstance(demand, dict):
        return None
    normalized = _normalize_registry_resource(demand)
    try:
        return Decimal(str(normalized.get("amount")))
    except (InvalidOperation, TypeError):
        return None


def _is_compute_offer(order: dict[str, object]) -> bool:
    offer = order.get("offer_resource")
    demand = order.get("demand_resource")
    return (
        isinstance(offer, dict)
        and isinstance(demand, dict)
        and ("gpu_model" in offer or offer.get("type") == "compute")
        and ("token" in demand or demand.get("type") == "token")
    )


def select_offer(
    *,
    offers: list[dict[str, object]],
    order_id: str | None,
    gpu_model: str | None,
    region: str | None,
    max_price: str | None,
) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    max_price_value = Decimal(max_price) if max_price is not None else None
    for offer in offers:
        if not _is_compute_offer(offer):
            continue
        if order_id and str(offer.get("order_id")) != order_id:
            continue
        offer_resource = offer.get("offer_resource")
        if not isinstance(offer_resource, dict):
            continue
        if gpu_model and str(offer_resource.get("gpu_model")) != gpu_model:
            continue
        if region and str(offer_resource.get("region")) != region:
            continue
        price = _offer_price(offer)
        if max_price_value is not None:
            if price is None or price > max_price_value:
                continue
        candidates.append(offer)

    if order_id:
        if not candidates:
            raise SystemExit(f"Could not find open offer {order_id}")
        return candidates[0]

    if not candidates:
        raise SystemExit("Could not find any open compute offers matching the requested filters")

    def _sort_key(item: dict[str, object]) -> tuple[Decimal, str]:
        price = _offer_price(item)
        return (price if price is not None else Decimal("999999999"), str(item.get("order_id") or ""))

    candidates.sort(key=_sort_key)
    return candidates[0]


def _get_auth_headers(operation: str, resource_id: str, private_key: str | None) -> dict[str, str]:
    if not private_key:
        return {}
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
    except ImportError:
        return {}
    ts = int(time.time())
    message = f"{operation}:{resource_id}:{ts}"
    signature = Account.sign_message(encode_defunct(text=message), private_key).signature.hex()
    return {"X-Signature": signature, "X-Timestamp": str(ts)}


def create_buyer_order(
    *,
    buyer_agent_url: str,
    buyer_auth_url: str,
    buyer_private_key: str,
    target_order: dict[str, object],
    duration_hours: int | None = None,
) -> dict[str, object]:
    offer_resource = _normalize_registry_resource(dict(target_order["demand_resource"]))
    demand_resource = dict(target_order["offer_resource"])
    duration = duration_hours if duration_hours is not None else int(target_order.get("duration_hours", 1))
    payload = {
        "offer": offer_resource,
        "demand": demand_resource,
        "duration_hours": duration,
    }
    return _request_json(
        f"{buyer_agent_url.rstrip('/')}/orders/create",
        method="POST",
        headers={
            "Accept": "application/json",
            **_get_auth_headers("create_order", buyer_auth_url.rstrip("/"), buyer_private_key),
        },
        payload=payload,
    )


def build_buyer_artifact(
    *,
    action: str,
    status: str,
    request_url: str,
    auth_url: str,
    order_id: str,
    job_id: str | None,
    vm_target: str | None,
    details: dict[str, object],
) -> dict[str, object]:
    return build_artifact(
        role="buyer",
        action=action,
        status=status,
        request_url=request_url,
        auth_url=auth_url,
        correlation={
            "order_id": order_id,
            "job_id": job_id,
            "vm_target": vm_target,
        },
        details=details,
    )


def _wait_for_buyer_order(registry_url: str, order_id: str, *, timeout_seconds: float, poll_seconds: float) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return fetch_order(registry_url, order_id)
        except Exception as exc:  # pragma: no cover - network timing only
            last_error = exc
            time.sleep(poll_seconds)
    raise SystemExit(f"Timed out waiting for buyer order {order_id}: {last_error}")


def _write_artifact(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def run_human_buyer_purchase(
    *,
    registry_url: str,
    buyer_agent_url: str,
    buyer_auth_url: str,
    provisioning_url: str,
    buyer_private_key: str,
    artifacts_dir: Path,
    order_id: str | None = None,
    gpu_model: str | None = None,
    region: str | None = None,
    max_price: str | None = None,
    timeout_seconds: float = 180.0,
    poll_seconds: float = 3.0,
    ssh_private_key_path: str | None = None,
) -> dict[str, object]:
    offers = list_open_offers(registry_url)
    selected_offer = select_offer(
        offers=offers,
        order_id=order_id,
        gpu_model=gpu_model,
        region=region,
        max_price=max_price,
    )
    seller_order_id = str(selected_offer["order_id"])
    seller_agent_id = str(selected_offer["agent_id"])

    create_response = create_buyer_order(
        buyer_agent_url=buyer_agent_url,
        buyer_auth_url=buyer_auth_url,
        buyer_private_key=buyer_private_key,
        target_order=selected_offer,
    )
    buyer_order_id = str(create_response.get("order_id") or "")
    if not buyer_order_id:
        raise SystemExit("Buyer create response did not include order_id")

    buyer_order = _wait_for_buyer_order(
        registry_url,
        buyer_order_id,
        timeout_seconds=timeout_seconds,
        poll_seconds=poll_seconds,
    )
    buyer_agent_id = str(buyer_order["agent_id"])

    jobs = list_jobs(provisioning_url, seller_agent_id, limit=100)
    selected_job = select_create_job(
        jobs=jobs,
        buyer_agent_id=buyer_agent_id,
        order_created_at=buyer_order.get("created_at") if isinstance(buyer_order.get("created_at"), str) else None,
    )
    job_id = str(selected_job["job_id"])

    deadline = time.monotonic() + timeout_seconds
    current_job = selected_job
    while time.monotonic() < deadline:
        current_job = fetch_job(provisioning_url, seller_agent_id, job_id)
        if str(current_job.get("status")) in TERMINAL_JOB_STATUSES:
            break
        time.sleep(poll_seconds)
    else:
        raise SystemExit(f"Timed out waiting for provisioning job {job_id}")

    credentials_payload = fetch_credentials(provisioning_url, buyer_agent_id, job_id)
    ssh_command = _tenant_external_ssh_command(credentials_payload)
    vm_target = None
    params = current_job.get("params")
    if isinstance(params, dict):
        vm_target = str(params.get("vm_target") or "") or None

    artifact = build_buyer_artifact(
        action="purchase",
        status=str(current_job.get("status") or create_response.get("status") or "unknown"),
        request_url=buyer_agent_url,
        auth_url=buyer_auth_url,
        order_id=buyer_order_id,
        job_id=job_id,
        vm_target=vm_target,
        details={
            "selected_seller_order_id": seller_order_id,
            "seller_agent_id": seller_agent_id,
            "buyer_agent_id": buyer_agent_id,
            "selected_offer": selected_offer,
            "buyer_order_status": buyer_order.get("status"),
            "job_status": current_job.get("status"),
            "ssh_command": ssh_command,
        },
    )

    if ssh_private_key_path and ssh_command:
        known_hosts_path = artifacts_dir / "known_hosts"
        probe_command = build_ssh_probe_command(
            ssh_command=ssh_command,
            ssh_private_key_path=ssh_private_key_path,
            known_hosts_path=known_hosts_path,
        )
        completed = run_probe_command(probe_command)
        artifact["details"]["ssh_probe"] = {
            "command": probe_command,
            "output": completed.stdout.splitlines(),
        }

    artifact_path = artifacts_dir / f"buyer-purchase-{buyer_order_id}.json"
    artifact["artifact_path"] = str(_write_artifact(artifact_path, artifact))
    return artifact


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover a live offer and purchase compute as a buyer.")
    parser.add_argument("--registry-url", required=True)
    parser.add_argument("--buyer-agent-url", required=True)
    parser.add_argument("--buyer-auth-url", required=True)
    parser.add_argument("--provisioning-url", required=True)
    parser.add_argument("--buyer-private-key")
    parser.add_argument("--buyer-private-key-env", default="BUYER_PRIVATE_KEY")
    parser.add_argument("--order-id")
    parser.add_argument("--gpu-model")
    parser.add_argument("--region")
    parser.add_argument("--max-price")
    parser.add_argument("--artifacts-dir", type=Path, default=Path("/tmp/market-buyer-artifacts"))
    parser.add_argument("--ssh-private-key-path")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    buyer_private_key = args.buyer_private_key or os.getenv(args.buyer_private_key_env)
    if not buyer_private_key:
        raise SystemExit(
            f"Missing buyer private key: pass --buyer-private-key or set {args.buyer_private_key_env}"
        )

    result = run_human_buyer_purchase(
        registry_url=args.registry_url,
        buyer_agent_url=args.buyer_agent_url,
        buyer_auth_url=args.buyer_auth_url,
        provisioning_url=args.provisioning_url,
        buyer_private_key=buyer_private_key,
        artifacts_dir=args.artifacts_dir.expanduser(),
        order_id=args.order_id,
        gpu_model=args.gpu_model,
        region=args.region,
        max_price=args.max_price,
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
        ssh_private_key_path=args.ssh_private_key_path,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
