#!/usr/bin/env python3
"""Seed a fresh seller offer for the human buyer flow using live advertised inventory."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path


def _load_context(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def build_create_payload(
    *,
    resource: dict[str, object],
    token: str,
    amount: str,
    duration_hours: int,
    quantity: int,
) -> dict[str, object]:
    return {
        "offer": {
            "gpu_model": str(resource["gpu_model"]),
            "quantity": quantity,
            "sla": resource["sla"],
            "region": str(resource["region"]),
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


def seed_human_seller_offer(
    *,
    context_path: Path,
    token: str,
    amount: str,
    duration_hours: int,
    quantity: int,
    resource_id: str | None = None,
    gpu_model: str | None = None,
    region: str | None = None,
    artifact_path: Path | None = None,
) -> dict[str, object]:
    context = _load_context(context_path)
    sandbox_dir = Path(context["sandbox_dir"])
    seller_env = _parse_env_file(sandbox_dir / "seller.env")
    request_url = str(context["seller_agent_url"])
    auth_url = seller_env.get("AGENT_AUTH_URL")
    private_key = seller_env.get("AGENT_PRIV_KEY")
    if not auth_url or not private_key:
        raise SystemExit("seller.env is missing AGENT_AUTH_URL or AGENT_PRIV_KEY")

    resources = fetch_portfolio(request_url)
    selected_resource = select_resource(
        resources=resources,
        resource_id=resource_id,
        gpu_model=gpu_model,
        region=region,
        quantity=quantity,
    )
    payload = build_create_payload(
        resource=selected_resource,
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
    order_id = str(response.get("order_id") or "")
    if not order_id:
        raise SystemExit("Seller create response did not include order_id")

    result = {
        "seller_order_id": order_id,
        "status": response.get("status"),
        "event_id": response.get("event_id"),
        "selected_resource": selected_resource,
        "order_request": payload,
    }
    if artifact_path is None:
        artifact_path = context_path.parent / f"seller-offer-{order_id}.json"
    artifact_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    result["artifact_path"] = str(artifact_path)
    result["order_id"] = order_id
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a fresh seller order for the human buyer flow from live advertised inventory."
    )
    parser.add_argument("--context-path", type=Path, required=True)
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
    result = seed_human_seller_offer(
        context_path=args.context_path.expanduser(),
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
