"""Storefront transport adapter for versioned deal-scoped lifecycle events."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any
from market_identity import TrustedIdentitySet

from compute_provisioning import LifecycleEvent
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from compute_provisioning_service.db.models import CapacityReleaseCallbackOutbox

from compute_provisioning_service.identity import ProvisioningIdentityContext

logger = logging.getLogger(__name__)


class StorefrontLifecycleEventSink:
    """Deliver each event through one identity-pinned storefront client."""

    def __init__(
        self,
        settings: Any,
        identity: ProvisioningIdentityContext,
        principal_authority: Any,
    ) -> None:
        self._principal_authority = principal_authority
        self._identity = identity
        self._storefront_url = str(
            getattr(settings, "storefront_url", "") or ""
        ).rstrip("/")
        self._client = None
        self._expected_publishers: TrustedIdentitySet | None = None

    async def _storefront(self):
        if not self._storefront_url:
            raise RuntimeError("storefront_url is required")
        expected_publishers = self._principal_authority.active_principals(
            "seller"
        )
        if (
            self._client is None
            or self._expected_publishers != expected_publishers
        ):
            if self._client is not None:
                await self._client.close()
            from storefront_client import StorefrontClient

            self._client = StorefrontClient(
                base_url=self._storefront_url,
                signer=self._identity.signer,
                caller_role="service",
                expected_publishers=expected_publishers,
            )
            self._expected_publishers = expected_publishers
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def deliver(self, event: LifecycleEvent) -> bool:
        from storefront_client import StorefrontClientError

        request_id = "capacity-release-" + hashlib.sha256(
            event.event_id.encode("utf-8")
        ).hexdigest()
        try:
            if event.event_kind != "capacity_released":
                raise ValueError(
                    f"unsupported storefront lifecycle event {event.event_kind!r}"
                )
            await (await self._storefront()).notify_capacity_released(
                event.capacity_reservation_id,
                site_id=self._identity.storefront_site_id,
                released_at=event.payload.get("released_at"),
                request_id=request_id,
            )
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


class SqlAlchemyCapacityReleaseOutbox:
    """Durable pending/acknowledged callback state across service restarts."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def reserve(self, capacity_reservation_id: str) -> None:
        try:
            with self._session_factory() as session:
                session.add(
                    CapacityReleaseCallbackOutbox(
                        capacity_reservation_id=capacity_reservation_id
                    )
                )
                session.commit()
        except IntegrityError:
            return

    def pending(self) -> tuple[str, ...]:
        with self._session_factory() as session:
            rows = (
                session.query(CapacityReleaseCallbackOutbox)
                .filter(CapacityReleaseCallbackOutbox.delivered_at.is_(None))
                .order_by(CapacityReleaseCallbackOutbox.created_at)
                .all()
            )
            return tuple(str(row.capacity_reservation_id) for row in rows)

    def mark_delivered(self, capacity_reservation_id: str) -> None:
        with self._session_factory() as session:
            row = session.get(
                CapacityReleaseCallbackOutbox,
                capacity_reservation_id,
            )
            if row is None:
                raise RuntimeError("capacity release outbox reservation disappeared")
            row.attempt_count += 1
            row.last_attempted_at = datetime.now(timezone.utc)
            row.delivered_at = row.last_attempted_at
            row.last_error = None
            session.commit()

    def record_failure(
        self,
        capacity_reservation_id: str,
        error: str,
    ) -> None:
        with self._session_factory() as session:
            row = session.get(
                CapacityReleaseCallbackOutbox,
                capacity_reservation_id,
            )
            if row is None:
                raise RuntimeError("capacity release outbox reservation disappeared")
            row.attempt_count += 1
            row.last_attempted_at = datetime.now(timezone.utc)
            row.last_error = error
            session.commit()


async def notify_storefront_capacity_released(
    settings: Any,
    reservation: dict[str, Any],
    *,
    sink: StorefrontLifecycleEventSink,
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
    return await sink.deliver(event)
