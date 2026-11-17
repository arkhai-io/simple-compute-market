"""VM servicing cycles run the kit's order: they preserve admission CAS, keep
filings independent of physical failures, resume from the durable page position
and finish report recovery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from compute_provisioning_contracts import LeaseEndedEvent, sign_lease_end
from core_storefront.service_peers import ServicePeerTrust
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_deal_lifecycle.terms import decode_terms
from market_deal_lifecycle_contracts.models import LifecycleCommand
from market_deal_servicing import EndSession, SellerSession
from market_deal_servicing.evidence import transaction
from market_identity import Ed25519Signer, TrustedIdentitySet, canonical_json
from market_storefront import container
from market_storefront.deal_lifecycle import VmDealLifecycle
from pydantic import SecretStr

from tests.integration.test_payment_settlement import LISTING, NEGOTIATION, SELLER, make

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


class UnreachableSite:
    """The end service's physical port when the site cannot be reached."""

    def __init__(self):
        self.calls = 0

    async def apply_end(self, negotiation_id, *, terminate, at, operation_key):
        self.calls += 1
        raise ConnectionError("site unreachable")


@pytest.mark.asyncio
async def test_a_physical_failure_does_not_skip_the_deals_filing(make):
    """A delivered deal ended by an administrator's failure end, its filing
    journaled, whose site cannot be reached: the cycle still dispatches the
    filing to the mediation authority and attempts the physical end again."""
    site = UnreachableSite()
    h = await make(physical=lambda *_: site)
    h.serve()
    await h.settle()
    await h.delivered()
    agreement, _ = h.lifecycle.accepted(NEGOTIATION)
    authority = decode_terms(agreement["settlement"]["lifecycle"]).adjudication.dispute
    mediation = MediationContractFake()
    h.lifecycle.clients[canonical_json(authority)] = MediationClient(
        authority, MediationCredential(authority.identity, token=SecretStr("fixture-payee")),
        transport=mediation.transport(),
    )
    h.lifecycle.credential_available = lambda candidate: candidate == authority
    h.lifecycle.seller.credential_available = h.lifecycle.credential_available
    command = LifecycleCommand(negotiation_id=NEGOTIATION, operation_key="operator-failure", kind="delivery_end")
    assert await h.lifecycle.seller.record_operator_end(
        command, actor=SELLER.identity, reason="fixture failure",
    ) is None
    assert site.calls == 0

    await h.lifecycle.cycle()

    assert site.calls == 2
    assert len(mediation.cases) == 1
    assert mediation.entries[0]["entry"]["filing"]["request"]["cause"] == "payee"
    with transaction(h.lifecycle.path) as conn:
        [filing] = [intent for intent in EndSession(conn).intents(NEGOTIATION) if intent.kind == "filing"]
    assert (filing.state, filing.result["status"]) == ("done", "accepted")


@pytest.mark.asyncio
async def test_the_page_position_survives_a_restart(make):
    """A restarted storefront's first cycle resumes after the page its last
    cycle serviced, and the page after the last starts again from the first."""
    h = await make()
    h.serve()
    await h.settle()
    await h.delivered()
    later = NEGOTIATION + "-later"
    now = h.lifecycle.clock()
    with transaction(h.lifecycle.path) as conn:
        end = EndSession(conn)
        # A second registered deal, past its Agreement's end, sorting after the first.
        end.register(end.read(NEGOTIATION).model_copy(update={
            "negotiation_id": later, "commitment_ref": "later-commitment", "start_at": now - 7200,
            "term_end": now - 3600, "committed_at": now - 7200, "delivery_deadline_seconds": None,
            "available_at": now - 7100, "progress": "active", "revision": 0,
        }))
        SellerSession(conn).register(SellerSession(conn).read(NEGOTIATION).model_copy(update={
            "negotiation_id": later, "commitment_ref": "later-commitment",
        }))

    assert await h.lifecycle.cycle(limit=1) == 1
    with transaction(h.lifecycle.path) as conn:
        assert not [request for request in EndSession(conn).requests(later)]
        assert conn.execute("SELECT loop, continuation FROM servicing_page_position").fetchall() == [
            ("deal-servicing", NEGOTIATION),
        ]

    restarted = VmDealLifecycle(h.db, h.lifecycle.signer, h.lifecycle.payments_coordinator,
                                SimpleNamespace(config=h.lifecycle.dispute_config),
                                fulfillment=h.lifecycle.fulfillment)
    try:
        assert await restarted.cycle(limit=1) == 1
        with transaction(h.lifecycle.path) as conn:
            assert [request.source_ref for request in EndSession(conn).requests(later)] == ["term-end"]
            assert conn.execute("SELECT loop, continuation FROM servicing_page_position").fetchall() == [
                ("deal-servicing", None),
            ]
        # After the last page, the next cycle starts again from the first deal.
        assert await restarted.cycle(limit=1) == 1
    finally:
        await restarted.close()
    with transaction(h.lifecycle.path) as conn:
        assert conn.execute("SELECT loop, continuation FROM servicing_page_position").fetchall() == [
            ("deal-servicing", NEGOTIATION),
        ]


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
