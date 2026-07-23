"""Storefront transport adapter for versioned deal-scoped lifecycle events."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from compute_provisioning import LifecycleEvent

logger = logging.getLogger(__name__)


class StorefrontLifecycleEventSink:
    """Deliver each event identity once without exposing the full storefront client."""

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._delivered: set[str] = set()

    async def deliver(self, event: LifecycleEvent) -> bool:
        if event.event_id in self._delivered:
            return False
        from storefront_client import StorefrontClient, StorefrontClientError

        storefront_url = str(
            event.deal_ref.get("storefront_url")
            or getattr(self._settings, "storefront_url", "")
            or ""
        ).rstrip("/")
        storefront_admin_key = str(
            event.deal_ref.get("storefront_admin_key")
            or getattr(self._settings, "storefront_admin_key", "")
            or ""
        )
        if not storefront_url:
            logger.warning(
                "[LEASE_LIFECYCLE] no owning storefront URL for reservation %s; "
                "skipping %s event",
                event.capacity_reservation_id,
                event.event_kind,
            )
            return False
        try:
            async with StorefrontClient(
                base_url=storefront_url,
                admin_key=storefront_admin_key or None,
            ) as storefront:
                if event.event_kind == "capacity_released":
                    await storefront.notify_capacity_released(
                        event.capacity_reservation_id,
                        released_at=event.payload.get("released_at"),
                    )
                else:
                    raise ValueError(
                        f"unsupported storefront lifecycle event {event.event_kind!r}"
                    )
            self._delivered.add(event.event_id)
            return True
        except StorefrontClientError as exc:
            logger.warning(
                "[LEASE_LIFECYCLE] %s event rejected for reservation %s: %s",
                event.event_kind,
                event.capacity_reservation_id,
                exc,
            )
            return False
        except Exception as exc:
            logger.warning(
                "[LEASE_LIFECYCLE] could not deliver %s event for reservation %s: %s",
                event.event_kind,
                event.capacity_reservation_id,
                exc,
            )
            return False


async def notify_storefront_capacity_released(
    settings: Any,
    reservation: dict[str, Any],
    *,
    sink: StorefrontLifecycleEventSink | None = None,
) -> bool:
    """Translate a release fact into the versioned narrow event-sink contract."""
    released_at = reservation.get("released_at")
    event = LifecycleEvent(
        event_id=(
            f"capacity_released:{reservation['capacity_reservation_id']}:"
            f"{released_at or reservation.get('updated_at') or 'terminal'}"
        ),
        capacity_reservation_id=str(reservation["capacity_reservation_id"]),
        deal_ref=dict(reservation.get("deal_ref") or {}),
        executor_kind=str(reservation.get("executor_kind") or "vm"),
        event_kind="capacity_released",
        payload={"released_at": released_at},
        occurred_at=datetime.now(timezone.utc),
    )
    return await (sink or StorefrontLifecycleEventSink(settings)).deliver(event)
