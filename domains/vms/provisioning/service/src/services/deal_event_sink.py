"""Storefront-owned deal event delivery for released allocations."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def notify_storefront_capacity_released(
    settings: Any, allocation: dict[str, Any]
) -> bool:
    """Notify only the storefront recorded as the allocation's owner."""
    from storefront_client import StorefrontClient, StorefrontClientError

    deal_ref = allocation.get("deal_ref") or {}
    storefront_url = str(
        deal_ref.get("storefront_url")
        or getattr(settings, "storefront_url", "")
        or ""
    ).rstrip("/")
    storefront_admin_key = str(
        deal_ref.get("storefront_admin_key")
        or getattr(settings, "storefront_admin_key", "")
        or ""
    )
    if not storefront_url:
        logger.warning(
            "[LEASE_LIFECYCLE] no owning storefront URL for allocation %s; "
            "skipping capacity-released deal event",
            allocation.get("allocation_id"),
        )
        return False
    try:
        async with StorefrontClient(
            base_url=storefront_url,
            admin_key=storefront_admin_key or None,
        ) as storefront:
            await storefront.notify_capacity_released(
                str(allocation["allocation_id"]),
                resource_id=allocation.get("resource_id"),
                released_at=allocation.get("released_at"),
            )
        return True
    except StorefrontClientError as exc:
        logger.warning(
            "[LEASE_LIFECYCLE] capacity-released deal event rejected for "
            "allocation %s: %s",
            allocation.get("allocation_id"),
            exc,
        )
        return False
    except Exception as exc:
        logger.warning(
            "[LEASE_LIFECYCLE] could not deliver capacity-released deal event "
            "for allocation %s: %s",
            allocation.get("allocation_id"),
            exc,
        )
        return False
