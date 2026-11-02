"""VM recovery cycles preserve admission CAS and finish report recovery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from compute_provisioning_contracts import LeaseEndedEvent, sign_lease_end
from core_storefront.service_peers import ServicePeerTrust
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_storefront import container

from tests.integration.test_payment_settlement import LISTING, NEGOTIATION, make

# Public deterministic development identity; never use on a public network.
SITE = Ed25519Signer(b"\x51" * 32)
RESERVATION = "fixture-vm-reservation"
SITE_ID = "site-test"


@pytest.mark.asyncio
async def test_unchanged_cycles_preserve_a_concurrent_admission_revision(make):
    h = await make()
    h.serve()
    await h.settle()
    await h.delivered()
    with transaction(h.lifecycle.path) as conn:
        before = EndSession(conn).read(NEGOTIATION)
    await h.lifecycle.cycle()
    await h.lifecycle.cycle()
    with transaction(h.lifecycle.path) as conn:
        end = EndSession(conn)
        after = end.read(NEGOTIATION)
        assert after.revision == before.revision
        assert end.admit(NEGOTIATION, before.phase, before.revision, now=h.lifecycle.clock()).status == "admitted"


@pytest.mark.asyncio
async def test_released_delivery_recovers_a_lost_report_then_stops_polling(make):
    h = await make()
    h.serve()
    await h.settle()
    await h.delivered()
    await h.db.save_capacity_hold(negotiation_id=NEGOTIATION, listing_id=LISTING,
                                  capacity_reservation_id=RESERVATION)
    await h.db.update_vm_delivery(negotiation_id=NEGOTIATION, capacity_reservation_id=RESERVATION)
    trust = ServicePeerTrust(h.db.db_path, {
        "fixture-provisioner": ("service", SITE_ID, TrustedIdentitySet(identities=(SITE.identity,))),
    })
    trust.seed()
    old = container.resolved_service_peer_trust
    container.resolved_service_peer_trust = trust
    try:
        h.lifecycle.capacity_released(RESERVATION, SITE_ID)
        report = sign_lease_end(LeaseEndedEvent(
            event_id="recovered-end", capacity_reservation_id=RESERVATION, site_id=SITE_ID,
            effective_at=h.lifecycle.clock(), cause="expiry", source_state="active",
        ), SITE)
        get_lease = AsyncMock(return_value=SimpleNamespace(end_reports=[]))
        h.lifecycle.fulfillment = SimpleNamespace(get_lease=get_lease)
        await h.lifecycle.recover_site_reports(NEGOTIATION)
        get_lease.return_value = SimpleNamespace(end_reports=[report])
        await h.lifecycle.recover_site_reports(NEGOTIATION)
        await h.lifecycle.recover_site_reports(NEGOTIATION)
        assert get_lease.await_count == 2
        with transaction(h.lifecycle.path) as conn:
            view = EndSession(conn).view(NEGOTIATION)
        assert view.progress == "released"
        assert len(view.site_reports) == 1
    finally:
        container.resolved_service_peer_trust = old
