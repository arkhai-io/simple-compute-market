"""Embedded site-authority adapter over the storefront's own tables.

The single-storefront degenerate deployment of the capacity topology
(docs/development/design-settlement-lifecycle-and-capacity.md, Part II):
the ``hosts``/``compute_allocations`` ledger still lives in this
storefront's SQLite, but every consumer goes through the
``core_storefront.capacity.CapacityClient`` boundary so the move to a
real site-authority service is a move, not a behavior change.

Embedded mode is for a provably single consumer — another storefront
must never reach this ledger through this process.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Mapping

from core_storefront.capacity import (
    CapacityDelta,
    CapacityEventBus,
    CapacitySubscriber,
)

logger = logging.getLogger(__name__)

SQLiteClientFactory = Callable[[], Any]


class EmbeddedCapacityClient:
    """``CapacityClient`` over the storefront's local allocation tables.

    Takes a factory rather than a client so it always sees the same
    SQLite handle its caller would have used directly (tests monkeypatch
    the module-level ``get_sqlite_client`` and expect every code path to
    follow it).
    """

    def __init__(
        self,
        sqlite_client_factory: SQLiteClientFactory,
        *,
        bus: CapacityEventBus | None = None,
    ) -> None:
        self._db_factory = sqlite_client_factory
        self._bus = bus or CapacityEventBus()

    @property
    def db_path(self) -> str:
        return self._db_factory().db_path

    async def snapshot(self) -> list[dict[str, Any]]:
        return await self._db_factory().list_resources() or []

    async def probe(
        self, *, claim: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return await self._db_factory().select_available_compute_vm(
            required_attributes=dict(claim) if claim else None,
        )

    async def reserve(
        self,
        *,
        claim: Mapping[str, Any] | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        ttl_seconds: float | None = None,
    ) -> dict[str, Any] | None:
        if ttl_seconds is not None:
            raise NotImplementedError(
                "TTL soft holds (two-phase reserve) are not implemented by "
                "the embedded adapter yet",
            )
        deal = dict(deal_ref or {})
        reserved = await self._db_factory().reserve_available_compute_vm(
            required_attributes=dict(claim) if claim else None,
            listing_id=deal.get("listing_id"),
            escrow_uid=deal.get("escrow_uid"),
        )
        if reserved:
            await self._emit(
                kind="reserved",
                resource_id=reserved.get("resource_id"),
                pool_id=reserved.get("pool_id"),
            )
        return reserved

    async def commit(
        self,
        *,
        resource_id: str,
        allocation_id: str | None = None,
        lease_end_utc: str,
        idempotency_ref: str | None = None,
    ) -> None:
        db = self._db_factory()
        ref = idempotency_ref or (allocation_id or resource_id)
        if allocation_id:
            await db.update_compute_allocation_state(
                allocation_id=allocation_id,
                state="leased",
            )
            await db.apply_resource_set_transition(
                resource_id=resource_id,
                event_type="lease_started_after_provisioning",
                idempotency_key=f"lease-attrs:{ref}:{resource_id}",
                set_attribute={"$.lease_end_utc": lease_end_utc},
            )
        else:
            # Legacy aggregate-state path for rows without an allocation.
            await db.apply_resource_set_transition(
                resource_id=resource_id,
                event_type="lease_started_after_provisioning",
                idempotency_key=f"lease:{ref}:{resource_id}",
                set_state="leased",
                set_attribute={"$.lease_end_utc": lease_end_utc},
            )
        await self._emit(kind="committed", resource_id=resource_id)

    async def release(
        self,
        *,
        allocation_id: str | None = None,
        deal_ref: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        deal = dict(deal_ref or {})
        released = await self._db_factory().update_compute_allocation_state(
            allocation_id=allocation_id,
            escrow_uid=None if allocation_id else deal.get("escrow_uid"),
            state="released",
        )
        if released:
            await self._emit(
                kind="released",
                resource_id=released.get("resource_id"),
                pool_id=released.get("pool_id"),
            )
        return released

    async def truncate_lease(
        self,
        *,
        allocation_id: str,
        lease_end_utc: str,
    ) -> dict[str, Any] | None:
        """Shorten an active lease; teardown stays with the lease watchdog.

        The settlement lifecycle's early-termination signal lands here;
        until the site authority owns the job queue (work item II.4), the
        watchdog picks the new ``lease_end_utc`` up through the existing
        expiry path.
        """
        truncated = await self._db_factory().update_compute_allocation_state(
            allocation_id=allocation_id,
            state="leased",
            lease_end_utc=lease_end_utc,
        )
        if truncated and truncated.get("resource_id"):
            await self._db_factory().apply_resource_set_transition(
                resource_id=str(truncated["resource_id"]),
                event_type="lease_truncated",
                idempotency_key=f"truncate:{allocation_id}:{lease_end_utc}",
                set_attribute={"$.lease_end_utc": lease_end_utc},
            )
            await self._emit(
                kind="lease_truncated",
                resource_id=truncated.get("resource_id"),
                pool_id=truncated.get("pool_id"),
            )
        return truncated

    def subscribe(self, subscriber: CapacitySubscriber) -> Callable[[], None]:
        return self._bus.subscribe(subscriber)

    async def _emit(
        self,
        *,
        kind: str,
        resource_id: Any = None,
        pool_id: Any = None,
    ) -> None:
        await self._bus.emit(CapacityDelta(
            kind=kind,
            version=self._bus.next_version(),
            resource_id=str(resource_id) if resource_id else None,
            pool_id=str(pool_id) if pool_id else None,
        ))


def build_capacity_client(
    sqlite_client_factory: SQLiteClientFactory,
) -> EmbeddedCapacityClient:
    """Assemble the storefront's capacity client with default subscribers."""
    return EmbeddedCapacityClient(sqlite_client_factory)
