"""Bare metal's ports for the compute family's re-drive of unfinished deliveries.

``recover_bare_metal_deliveries`` runs ``compute_delivery.recover_deliveries``
over the deals whose fulfillment lifecycle row shows a delivery started and not
finished, each skipped while its lock is held and re-checked through the
settlement's recovery gate. A deal is driven as every bare-metal delivery is,
through ``BareMetalFulfillmentService.deliver`` and so core's fulfillment hook,
which takes the deal's lock for the drive and drives its physical end after.
See openspec/specs/compute-delivery/spec.md, "Unfinished deliveries are
re-driven by one routine".
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from compute_delivery import recover_deliveries
from core_storefront import StorefrontFulfillmentLifecycle
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import in_transaction

#: End-service physical progress of a deal whose delivery may still move. A
#: deal whose physical end is recorded, under way or done, or that needs
#: repair, is the servicing cycle's to finish.
_DRIVABLE_PROGRESS = frozenset({"unstarted", "active"})


class BareMetalDeliveryRecovery:
    """Bare metal's recovery ports: its lifecycle-row query, its per-deal lock
    and its settlement's recovery gate.

    ``service`` builds the fulfillment service when a deal is re-checked, since
    a storefront with nothing to recover may compose no site authorities.
    """

    def __init__(self, db: Any, lifecycle: Any, service: Callable[[], Any]) -> None:
        self._db = db
        self._lifecycle = lifecycle
        self._service = service

    async def unfinished_deliveries(self, *, limit: int) -> list[str]:
        """Deals whose delivery started and has not finished.

        Started means the delivery path created the deal's lifecycle row; a
        deal not yet started is started by its settlement, through the payment
        reconciliation loop or the servicing worker. Finished means its row
        released, its physical end begun, or available with its result and
        receipt recorded, the continuation's last writes.
        """
        found: list[str] = []
        for negotiation_id in await self._db.list_unreleased_bare_metal_fulfillments():
            if await self._unfinished(negotiation_id):
                found.append(negotiation_id)
                if len(found) >= limit:
                    break
        return found

    async def _unfinished(self, negotiation_id: str) -> bool:
        # The path creates the lifecycle row under admission, so a row always
        # has the servicing record it was admitted on.
        record = await in_transaction(self._lifecycle.path, lambda conn: EndSession(conn).read(negotiation_id))
        if record.progress not in _DRIVABLE_PROGRESS:
            return False
        if record.available_at is None:
            return True
        result = await self._db.load_bare_metal_result(negotiation_id=negotiation_id)
        receipt = await self._db.load_bare_metal_receipt(negotiation_id=negotiation_id)
        return result is None or receipt is None

    @asynccontextmanager
    async def claim(self, negotiation_id: str) -> AsyncIterator[bool]:
        """Whether the deal's lock is free: held, another drive has the deal.

        The lock is taken by the fulfillment hook for the drive itself, since
        an ``asyncio.Lock`` is not re-entrant and the hook is the one entry to
        bare-metal delivery. A drive that takes the lock between this answer
        and the hook's is waited for, never overlapped.
        """
        yield not self._lifecycle.lock(negotiation_id).locked()

    async def revalidate(self, negotiation_id: str) -> bool:
        return await self._service().revalidate(negotiation_id)


class _HookDrive:
    """A re-drive through ``deliver``, which re-checks the evidence it hands the hook."""

    def __init__(self, service: Callable[[], Any]) -> None:
        self._service = service

    async def drive(self, negotiation_id: str) -> StorefrontFulfillmentLifecycle:
        return await self._service().redeliver(negotiation_id)


async def recover_bare_metal_deliveries(runtime: Any, *, limit: int = 50) -> int:
    """Re-drive the runtime's unfinished deliveries once; how many were driven."""
    recovery = BareMetalDeliveryRecovery(runtime.db, runtime.lifecycle, runtime.fulfillment_service)
    return await recover_deliveries(_HookDrive(runtime.fulfillment_service), recovery, limit=limit)
