"""VM end admission and future physical ends over real persistence."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from market_deal_lifecycle_client import LifecycleClient
from market_deal_servicing import Classification, EndSession, FinalRequest
from market_deal_servicing.evidence import transaction
from market_identity import TrustedIdentitySet

from market_storefront.delivery_lifecycle import VmPhysicalEnd
from tests.fake_site import FakeSite, capacity_runtime_over
from tests.integration.test_abandon_truncation import _persist_terminal_negotiation
from tests.integration.test_abandon_truncation import db as db
from tests.integration.test_payment_settlement import (
    BUYER,
    NEGOTIATION,
    SELLER,
    _restart,
)
from tests.integration.test_payment_settlement import make as make


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["buyer_surrender", "ruling"])
async def test_final_end_before_dispatch_survives_reconciliation_and_restart(make, tmp_path, cause):
    h = await make()
    h.serve()
    # Record verified commitment without starting the delivery worker.
    checked = await h.coordinator.stage.check_receipt(
        h.lifecycle.accepted(NEGOTIATION)[0], h.data,
    )
    agreement, _ = h.lifecycle.accepted(NEGOTIATION)
    thread = await h.db.load_negotiation_thread_row(negotiation_id=NEGOTIATION)
    raw = thread["agreement_bytes"]
    await h.coordinator._record_verified(NEGOTIATION, raw, agreement, h.data, checked.receipt)
    async with LifecycleClient("http://test", BUYER, TrustedIdentitySet(identities=(SELLER.identity,)),
                               transport=h.transport) as buyer:
        if cause == "buyer_surrender":
            ack = await buyer.end_delivery(NEGOTIATION, operation_key="end")
            assert ack.delivery.progress == "released"
            assert ack.signed_delivery_end_claim["claim"]["delivered"] is True
        else:
            now = h.lifecycle.clock()
            with transaction(h.db.db_path) as conn:
                EndSession(conn).record_end(FinalRequest(
                    negotiation_id=NEGOTIATION, source_ref="ruling", ended_at=now, observed_at=now,
                    actor=SELLER.identity, cause="ruling", source="ruling",
                ), now=now, classification=Classification(kind="ruling", evidence_refs=["ruling"]))
            await h.lifecycle.end.drive_physical(NEGOTIATION)
        await h.coordinator.reconcile_once()
        assert (await h.settle()).status == "ended"
        assert h.delivery.starts == []
        assert await h.db.load_vm_delivery(negotiation_id=NEGOTIATION) is None
        restarted = await _restart(h, tmp_path, approved=True)
        await restarted.coordinator.reconcile_once()
        assert restarted.delivery.starts == []
        assert await restarted.db.load_vm_delivery(negotiation_id=NEGOTIATION) is None
        with transaction(h.db.db_path) as conn:
            end = EndSession(conn)
            record = end.read(NEGOTIATION)
            assert end.admit(NEGOTIATION, "dispatch", record.revision,
                             now=h.lifecycle.clock()).status == "ended"
            assert end.view(NEGOTIATION).progress == "released"


@pytest.mark.asyncio
async def test_surrender_during_dispatch_adopts_work_but_never_discloses_credentials(make):
    h = await make()
    h.serve()
    h.delivery.started, h.delivery.release = asyncio.Event(), asyncio.Event()
    await h.settle()
    try:
        await asyncio.wait_for(h.delivery.started.wait(), 5)
        async with LifecycleClient("http://test", BUYER, TrustedIdentitySet(identities=(SELLER.identity,)),
                                   transport=h.transport) as buyer:
            ack = await buyer.end_delivery(NEGOTIATION, operation_key="end")
            assert ack.selected_end.actor == BUYER.identity
    finally:
        h.delivery.release.set()
    await h.delivered()
    delivery = await h.db.load_vm_delivery(negotiation_id=NEGOTIATION)
    assert delivery["status"] == "ended"
    assert delivery["connection_details"] is None
    assert h.delivery.starts == [NEGOTIATION]
    assert h.lifecycle.seller.delivery_read(NEGOTIATION).delivery.progress == "tearing_down"


@pytest.mark.asyncio
async def test_future_end_sends_and_records_mid_minute_without_rounding(db):
    fake = FakeSite(deliverable_modes={"vm"})
    fake.add_resource("precision", 2, attributes={"vm_host": "kvm1"})
    capacity = capacity_runtime_over(fake)
    binding = await _persist_terminal_negotiation(
        db, agreement_ref="precision", listing_id="precision", pool_id="precision",
    )
    reserved = await capacity.reserve(binding, claim={"offering_mode": "vm"},
                                      deal_ref={"negotiation_id": "precision"})
    reservation = reserved["capacity_reservation_id"]
    await capacity.commit(binding, resource_id=None, capacity_reservation_id=reservation,
                          lease_start_utc="2099-01-01T00:00:00Z", lease_end_utc="2099-01-01 13:00")
    at = int(datetime(2099, 1, 1, 12, 0, 30, tzinfo=timezone.utc).timestamp())
    remote = AsyncMock()
    physical = VmPhysicalEnd(db, capacity=capacity, fulfillment=remote)
    result = await physical.apply_end("precision", terminate=False, at=at, operation_key="future-end")
    assert result.done
    assert fake.reservations[reservation]["lease_end_utc"] == "2099-01-01T12:00:30+00:00"
    remote.terminate_lease.assert_not_awaited()
