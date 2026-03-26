"""HTTP client for agent API with EIP-191 authentication."""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import urllib.error

from eth_account import Account
from eth_account.messages import encode_defunct

log = logging.getLogger(__name__)


def _build_auth_headers(private_key: str, operation: str, resource_id: str) -> dict[str, str]:
    """Build X-Signature + X-Timestamp headers (EIP-191)."""
    ts = int(time.time())
    message = f"{operation}:{resource_id}:{ts}"
    msg_hash = encode_defunct(text=message)
    sig = Account.sign_message(msg_hash, private_key).signature.hex()
    return {"X-Signature": sig, "X-Timestamp": str(ts)}


def create_order(
    base_url: str,
    private_key: str,
    wallet_address: str,
    offer: dict,
    demand: dict,
    duration_hours: int = 1,
    timeout: float = 120,
) -> dict:
    """POST /orders/create with signed headers. Returns response dict."""
    url = f"{base_url.rstrip('/')}/orders/create"
    headers = _build_auth_headers(private_key, "create_order", wallet_address)
    headers["Content-Type"] = "application/json"

    body = json.dumps({
        "offer": offer,
        "demand": demand,
        "duration_hours": duration_hours,
    }).encode()

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    log.info("POST %s (wallet=%s…)", url, wallet_address[:10])

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            log.info("  → status=%s order_id=%s", data.get("status"), data.get("order_id"))
            return data
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode(errors="replace")
        log.error("  → HTTP %s: %s", exc.code, error_body[:500])
        raise RuntimeError(f"HTTP {exc.code} from {url}: {error_body[:500]}") from exc


def query_registry_orders(
    registry_url: str,
    status: str | None = None,
    timeout: float = 10,
) -> dict:
    """GET /orders from the registry. Returns {items: [...], count: N}."""
    url = f"{registry_url.rstrip('/')}/orders"
    if status:
        url += f"?status={status}"

    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def get_registry_order(
    registry_url: str,
    order_id: str,
    timeout: float = 10,
) -> dict:
    """GET /orders/{order_id} from the registry. Returns {order: {...}}."""
    url = f"{registry_url.rstrip('/')}/orders/{order_id}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())
