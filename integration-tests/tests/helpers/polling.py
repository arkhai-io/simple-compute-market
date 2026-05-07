"""Polling / wait utilities for e2e tests."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, TypeVar

from tests.helpers.registry_helpers import query_registry_orders
from tests.helpers.sqlite_reader import get_all_orders

log = logging.getLogger(__name__)

T = TypeVar("T")


def poll_until(
    predicate: Callable[[], T],
    timeout_s: float = 120,
    interval_s: float = 3,
    description: str = "",
) -> T:
    """Call *predicate* repeatedly until it returns a truthy value or timeout."""
    deadline = time.monotonic() + timeout_s
    last_exc: Exception | None = None

    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except Exception as exc:
            last_exc = exc
            log.debug("poll_until(%s): %s", description, exc)
        time.sleep(interval_s)

    msg = f"Timed out after {timeout_s}s waiting for: {description}"
    if last_exc:
        msg += f" (last error: {last_exc})"
    raise TimeoutError(msg)


def poll_registry_orders(
    registry_url: str,
    status: str,
    min_count: int,
    timeout_s: float = 120,
    interval_s: float = 3,
) -> list[dict[str, Any]]:
    """Poll GET /orders?status={status} until count >= min_count."""

    def _check() -> list[dict[str, Any]] | None:
        data = query_registry_orders(registry_url, status=status)
        items = data.get("items", [])
        if len(items) >= min_count:
            return items
        return None

    desc = f"registry has >= {min_count} orders with status={status}"
    return poll_until(_check, timeout_s=timeout_s, interval_s=interval_s, description=desc)


def poll_sqlite_order_status(
    db_path: str,
    expected_status: str,
    timeout_s: float = 120,
    interval_s: float = 3,
) -> list[dict[str, Any]]:
    """Poll SQLite until at least one order has *expected_status*."""

    def _check() -> list[dict[str, Any]] | None:
        orders = get_all_orders(db_path)
        matching = [o for o in orders if o["status"] == expected_status]
        return matching or None

    desc = f"sqlite {db_path} has order with status={expected_status}"
    return poll_until(_check, timeout_s=timeout_s, interval_s=interval_s, description=desc)