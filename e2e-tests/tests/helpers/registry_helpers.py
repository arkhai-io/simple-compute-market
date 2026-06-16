"""Lightweight polling helpers for the registry (indexer) REST API.

These are thin urllib-based functions used by polling fixtures and
discovery-stage tests.  They intentionally avoid httpx/aiohttp to keep
the dependency footprint minimal for fixtures that run synchronously
between async test steps.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)


def query_registry_orders(
    registry_url: str,
    status: str | None = None,
    timeout: float = 10,
) -> dict:
    """GET /listings from the registry.

    Returns ``{"items": [...], "count": N}``.
    """
    url = f"{registry_url.rstrip('/')}/listings"
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
    """GET /listings/{listing_id} from the registry.

    Returns ``{"listing": {...}}``.
    """
    url = f"{registry_url.rstrip('/')}/listings/{order_id}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())
