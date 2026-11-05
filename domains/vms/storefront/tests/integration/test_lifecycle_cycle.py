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
from market_storefront.deal_lifecycle import VmDealLifecycle

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
@pytest.mark.parametrize("partial_push", [False, True])
async def test_released_delivery_recovers_a_lost_report_then_stops_polling(make, partial_push):
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
        later = sign_lease_end(LeaseEndedEvent(
            event_id="later-release-failure", capacity_reservation_id=RESERVATION, site_id=SITE_ID,
            effective_at=h.lifecycle.clock() + 1, cause="release_failed", source_state="releasing",
        ), SITE)
        if partial_push:
            h.lifecycle.ingress.site_report(NEGOTIATION, body=later.model_dump_json().encode(), headers={})
        get_lease = AsyncMock(return_value=SimpleNamespace(end_reports=[]))
        h.lifecycle.fulfillment = SimpleNamespace(get_lease=get_lease)
        await h.lifecycle.recover_site_reports(NEGOTIATION)
        get_lease.return_value = SimpleNamespace(end_reports=[report, later])
        await h.lifecycle.recover_site_reports(NEGOTIATION)
        await h.lifecycle.recover_site_reports(NEGOTIATION)
        assert get_lease.await_count == 2
        with transaction(h.lifecycle.path) as conn:
            end = EndSession(conn)
            view = end.view(NEGOTIATION)
            assert next(request for request in end.requests(NEGOTIATION)
                        if request.source_ref == "site-event:later-release-failure").cause == "release_failed"
        assert view.progress == "released"
        assert {item.evidence_id for item in view.site_reports} == {
            "site-event:recovered-end", "site-event:later-release-failure",
        }
        # A new composition must use the durable reconciliation marker too.
        restarted = VmDealLifecycle(h.db, h.lifecycle.signer, h.lifecycle.payments_coordinator,
                                    SimpleNamespace(config=h.lifecycle.dispute_config),
                                    fulfillment=h.lifecycle.fulfillment)
        await restarted.recover_site_reports(NEGOTIATION)
        assert get_lease.await_count == 2
        await restarted.close()
    finally:
        container.resolved_service_peer_trust = old
