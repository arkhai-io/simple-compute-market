"""VM delivery ordering and physical effects over the shared end journal."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from market_deal_servicing import EndSession
from market_deal_servicing.end import PhysicalResult
from market_deal_servicing.evidence import transaction
from market_deal_servicing.journal import atomic

from market_storefront.delivery_records import record_delivery_end
from market_storefront.services.capacity_client import (
    build_capacity_runtime, build_fulfillment_client, capacity_binding_for_listing,
)
from market_storefront.services.fulfillment_service import terminate_vm_lease


class VmPhysicalEnd:
    def __init__(self, db, *, capacity=None, fulfillment=None):
        self.db = db
        self.capacity = capacity
        self.fulfillment = fulfillment

    async def reservation(self, negotiation_id):
        thread = await self.db.load_thread_binding(negotiation_id=negotiation_id)
        binding = await capacity_binding_for_listing(self.db, thread.listing_id)
        if binding.site_id != thread.site_id:
            raise ValueError("delivery end site differs from accepted binding")
        capacity = self.capacity or build_capacity_runtime(lambda: self.db)
        delivery = await self.db.load_vm_delivery(negotiation_id=negotiation_id)
        hold = await self.db.load_capacity_hold(negotiation_id=negotiation_id)
        reservation = (delivery or {}).get("capacity_reservation_id") or (hold or {}).get("capacity_reservation_id")
        # Recovery also covers a crash between site allocation and local checkpoint.
        site = capacity.client()._sites[binding.site_id]
        rows = await site.list_reservations()
        matching = [row for row in rows if
                    (row.get("deal_ref") or {}).get("negotiation_id") == negotiation_id]
        if reservation:
            matching = [row for row in rows if row["capacity_reservation_id"] == reservation]
        if len(matching) > 1:
            raise ValueError("deal has ambiguous site reservation bindings")
        return capacity, binding, matching[0] if matching else None

    async def apply_end(self, negotiation_id, *, terminate, at, operation_key):
        capacity, binding, reservation = await self.reservation(negotiation_id)
        # The delivery record's status is left to the delivery path's next
        # drive, which records the end once nothing is left for it to do: an
        # available deal's continuation still runs after an end.
        delivery = await self.db.load_vm_delivery(negotiation_id=negotiation_id)
        if reservation is None and not terminate:
            return PhysicalResult(progress="end_recorded", done=False)
        if reservation is None:
            # An admitted remote allocation may still be returning. Do not
            # acknowledge physical completion while its local owner is active.
            pending = delivery is not None and delivery.get("processing_owner") is not None
            return PhysicalResult(progress="end_recorded" if pending else "released", done=not pending)
        if reservation["state"] == "released":
            with transaction(self.db.db_path) as conn:
                record = EndSession(conn).read(negotiation_id)
            # For delivered access, only the separately acknowledged capacity
            # callback closes teardown; a termination receipt cannot do so.
            if record.available_at is not None and record.progress != "released":
                return PhysicalResult(progress="tearing_down", done=False)
            return PhysicalResult(progress="released", done=True)
        reservation_id = reservation["capacity_reservation_id"]
        if not terminate:
            await capacity.truncate_lease(
                binding, capacity_reservation_id=reservation_id,
                lease_end_utc=datetime.fromtimestamp(at, timezone.utc).isoformat(),
            )
            return PhysicalResult(progress="end_recorded", done=True)
        with transaction(self.db.db_path) as conn:
            available = EndSession(conn).read(negotiation_id).available_at is not None
        # Delivered leases must use lease lifecycle, whose separate callback
        # proves capacity return. A direct guarded release has no such receipt.
        released = None
        if not available:
            released = await capacity.release(
                binding, capacity_reservation_id=reservation_id, failure_reason=operation_key,
            )
        if released is not None:
            return PhysicalResult(progress="released", done=True)
        fulfillment = self.fulfillment or build_fulfillment_client(capacity.client())
        await terminate_vm_lease(
            fulfillment, capacity_reservation_id=reservation_id,
            site_id=binding.site_id, reason=operation_key,
        )
        # A terminate acknowledgement is not capacity-release proof.
        return PhysicalResult(progress="tearing_down", done=False)


async def request_delivery_end(db, negotiation_id, *, source_ref, cause, clock=lambda: int(time.time())):
    now = clock()
    with transaction(db.db_path) as conn, atomic(conn):
        return record_delivery_end(conn, negotiation_id, source_ref=source_ref, cause=cause, now=now)
