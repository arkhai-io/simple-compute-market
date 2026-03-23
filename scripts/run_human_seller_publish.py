#!/usr/bin/env python3
"""Publish a seller offer from live advertised inventory with a shared artifact."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from role_contracts import build_artifact


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value.strip().strip("'").strip('"')
    return values


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


def fetch_portfolio(seller_agent_url: str) -> list[dict[str, object]]:
    payload = _request_json(f"{seller_agent_url.rstrip('/')}/resources/portfolio")
    resources = payload.get("resources")
    if not isinstance(resources, list):
        raise SystemExit("Seller portfolio response was missing resources")
    return [resource for resource in resources if isinstance(resource, dict)]


def select_resource(
    *,
    resources: list[dict[str, object]],
    resource_id: str | None,
    gpu_model: str | None,
    region: str | None,
    quantity: int,
) -> dict[str, object]:
    for resource in resources:
        if resource_id and str(resource.get("resource_id")) != resource_id:
            continue
        if gpu_model and str(resource.get("gpu_model")) != gpu_model:
            continue
        if region and str(resource.get("region")) != region:
            continue
        try:
            available_quantity = int(resource.get("quantity", 0))
        except (TypeError, ValueError):
            continue
        if available_quantity < quantity:
            continue
        return resource
    raise SystemExit("Could not find a live seller resource matching the requested filters")


def build_publish_payload(
    *,
    selected_resource: dict[str, object],
    token: str,
    amount: str,
    duration_hours: int,
    quantity: int,
) -> dict[str, object]:
    return {
        "offer": {
            "gpu_model": str(selected_resource["gpu_model"]),
            "quantity": quantity,
            "sla": selected_resource["sla"],
            "region": str(selected_resource["region"]),
        },
        "demand": {
            "token": token,
            "amount": amount,
        },
        "duration_hours": duration_hours,
    }


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


def create_order(
    *,
    request_url: str,
    auth_url: str,
    private_key: str,
    payload: dict[str, object],
) -> dict[str, object]:
    return _request_json(
        f"{request_url.rstrip('/')}/orders/create",
        method="POST",
        headers={
            "Accept": "application/json",
            **_get_auth_headers("create_order", auth_url.rstrip("/"), private_key),
        },
        payload=payload,
    )


def build_seller_artifact(
    *,
    request_url: str,
    auth_url: str,
    response: dict[str, object],
    selected_resource: dict[str, object],
    payload: dict[str, object],
) -> dict[str, Any]:
    return build_artifact(
        role="seller",
        action="publish",
        status=str(response.get("status") or "unknown"),
        request_url=request_url,
        auth_url=auth_url,
        correlation={
            "order_id": str(response.get("order_id") or ""),
            "vm_target": selected_resource.get("resource_id"),
        },
        details={
            "selected_resource": selected_resource,
            "publish_payload": payload,
            "seller_order_id": response.get("order_id"),
            "event_id": response.get("event_id"),
        },
    )


def publish_human_seller_offer(
    *,
    env_path: Path,
    resource_id: str | None,
    gpu_model: str | None,
    region: str | None,
    quantity: int,
    token: str,
    amount: str,
    duration_hours: int,
    artifact_path: Path | None = None,
) -> dict[str, object]:
    env = _parse_env_file(env_path)
    request_url = env.get("AGENT_URL") or env.get("BASE_URL_OVERRIDE")
    auth_url = env.get("AGENT_AUTH_URL") or request_url
    private_key = env.get("AGENT_PRIV_KEY")
    if not request_url or not auth_url or not private_key:
        raise SystemExit("seller env is missing AGENT_URL/BASE_URL_OVERRIDE, AGENT_AUTH_URL, or AGENT_PRIV_KEY")

    resources = fetch_portfolio(request_url)
    selected_resource = select_resource(
        resources=resources,
        resource_id=resource_id,
        gpu_model=gpu_model,
        region=region,
        quantity=quantity,
    )
    payload = build_publish_payload(
        selected_resource=selected_resource,
        token=token,
        amount=amount,
        duration_hours=duration_hours,
        quantity=quantity,
    )
    response = create_order(
        request_url=request_url,
        auth_url=auth_url,
        private_key=private_key,
        payload=payload,
    )
    artifact = build_seller_artifact(
        request_url=request_url,
        auth_url=auth_url,
        response=response,
        selected_resource=selected_resource,
        payload=payload,
    )
    if artifact_path is None:
        artifact_path = env_path.parent / f"seller-publish-{response.get('order_id')}.json"
    artifact_path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    return {
        "seller_order_id": str(response.get("order_id") or ""),
        "order_id": str(response.get("order_id") or ""),
        "status": str(response.get("status") or ""),
        "artifact": artifact,
        "artifact_path": str(artifact_path),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish a seller offer from live portfolio inventory.")
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--resource-id")
    parser.add_argument("--gpu-model")
    parser.add_argument("--region")
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--token", default="WETH")
    parser.add_argument("--amount", default="0.0001")
    parser.add_argument("--duration-hours", type=int, default=1)
    parser.add_argument("--artifact-path", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = publish_human_seller_offer(
        env_path=args.env.expanduser(),
        resource_id=args.resource_id,
        gpu_model=args.gpu_model,
        region=args.region,
        quantity=args.quantity,
        token=args.token,
        amount=args.amount,
        duration_hours=args.duration_hours,
        artifact_path=args.artifact_path.expanduser() if args.artifact_path else None,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
