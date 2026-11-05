"""Intended-end producer/outbox recovery, independent of capacity-return ACKs.

Identities and origins are public deterministic development fixtures, never for a
public network. The API, signing codec, ledger and SQLite are real; push delivery
is controlled at the storefront transport boundary.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from storefront_client import StorefrontClient
from market_identity import Ed25519Signer, TrustedIdentitySet, canonical_json

from compute_provisioning_contracts import LeaseForceRelease, LeaseTermination, verify_lease_end
from compute_provisioning_service import container
from compute_provisioning_service.db.models import LeaseEndReportOutbox
from compute_provisioning_service.services.lease_end_reports import LeaseEndReports
from compute_provisioning_service.services.deal_event_sink import StorefrontLifecycleEventSink
from compute_provisioning_service.identity import ProvisioningIdentityContext

from .conftest import ADMIN_SIGNER, SERVICE_AUTHORITIES, SERVICE_SIGNER, STOREFRONT_SIGNER
from .test_leases_api import _committed, seller


async def test_producer_causes_survive_restart_lost_ack_and_signed_lease_pull(client_and_queue, seller):
    clients, _ = client_and_queue
    ledger = container.resolved_capacity_ledger_service
    now = datetime.now(timezone.utc)
    ids = {name: _committed("fixture-" + name, end=now - timedelta(seconds=5) if name == "expiry"
                            else now + timedelta(hours=1))
           for name in ("expiry", "termination", "direct", "failure", "force")}
    # The normal API cycle records expiry, not just a direct ledger fixture.
    await clients.family.check_leases()
    await seller.terminate_lease(ids["termination"], LeaseTermination(reason="fixture maintenance"))
    await seller.terminate_lease(ids["termination"], LeaseTermination(reason="retry must not rewrite"))
    ledger.release(capacity_reservation_id=ids["direct"])
    ledger.begin_releasing(ids["failure"], release_job_id="fixture-release")
    ledger.record_release_failed(ids["failure"], reason="host unreachable", release_job_id="fixture-release")
    await clients.family.force_release_lease(ids["force"], LeaseForceRelease(reason="fixture host inspected"))
    await clients.family.force_release_lease(ids["force"], LeaseForceRelease(reason="retry"))
    expected = {"expiry": ["expiry"], "termination": ["termination"], "direct": ["release"],
                "failure": ["release", "release_failed"], "force": ["force_release"]}
    assert {name: sorted(event["cause"] for event in ledger.lease_end_events(reservation))
            for name, reservation in ids.items()} == expected
    assert ledger.get_reservation(ids["failure"])["state"] == "release_failed"
    factory = container.resolved_session_factory
    with factory() as db:
        rows = db.query(LeaseEndReportOutbox).all()
        assert len(rows) == 6
        before = {row.event_id: row.report.encode() for row in rows}
        assert all(row.delivered_at is None for row in rows)
    # A reconstructed sender may have rotated its local signer: stored proofs,
    # event identities and exact payload bytes must not be regenerated.
    restarted = LeaseEndReports(factory, signer=Ed25519Signer(b"\x63" * 32), peer=rows[0].peer)
    sent = []

    async def lost_ack(report):
        sent.append(canonical_json(report))
        raise OSError("reply lost after receiver persisted")

    await restarted.drain(lost_ack)
    assert set(sent) == set(before.values())
    with factory() as db:
        assert all(row.attempt_count == 1 and row.delivered_at is None
                   for row in db.query(LeaseEndReportOutbox))
    sent.clear()

    async def acknowledge(report):
        sent.append(canonical_json(report))
        return "delivered"

    await restarted.drain(acknowledge)
    assert set(sent) == set(before.values())
    sent.clear()
    await restarted.drain(acknowledge)
    assert sent == []
    for name, reservation in ids.items():
        pulled = (await seller.get_lease(reservation)).end_reports
        assert len(pulled) == len(expected[name])
        for report in pulled:
            event = verify_lease_end(report, capacity_reservation_id=reservation,
                                     site_id=ledger.lease_end_events(reservation)[0]["site_id"],
                                     expected_sites=SERVICE_AUTHORITIES)
            assert canonical_json(report) == before[event.event_id]
            if name == "termination":
                assert event.reason == "fixture maintenance"
                assert event.caller == STOREFRONT_SIGNER.identity
            if name == "expiry":
                assert event.deadline_phase == "lease"
                assert event.claimed_deadline == event.effective_at
    with factory() as db:
        assert all(row.attempt_count == 2 and row.delivered_at is not None
                   for row in db.query(LeaseEndReportOutbox))


@pytest.mark.parametrize("status", [404, 503])
async def test_http_receiver_refusal_parks_only_unsupported_push(client_and_queue, seller, status):
    ledger = container.resolved_capacity_ledger_service
    reservation = _committed("fixture-refused")
    ledger.release(capacity_reservation_id=reservation)
    factory = container.resolved_session_factory
    with factory() as db:
        row = db.query(LeaseEndReportOutbox).one()
        peer, before = row.peer, row.report.encode()
    requests = []

    def receiver(request):
        requests.append(request)
        return httpx.Response(status, json={"detail": "receiver unavailable"})

    async with StorefrontClient(
        peer, signer=SERVICE_SIGNER, caller_role="service",
        expected_publishers=TrustedIdentitySet(identities=(STOREFRONT_SIGNER.identity,)),
        transport=httpx.MockTransport(receiver),
    ) as client:
        class TransportSink(StorefrontLifecycleEventSink):
            async def _storefront(self):
                return client

        sink = TransportSink(
            SimpleNamespace(storefront_url=peer),
            ProvisioningIdentityContext(signer=SERVICE_SIGNER,
                storefront_principal=STOREFRONT_SIGNER.identity,
                admin_principal=ADMIN_SIGNER.identity, storefront_site_id="default"),
            SimpleNamespace(),
        )
        reports = LeaseEndReports(factory, signer=SERVICE_SIGNER, peer=peer)
        await reports.drain(sink.deliver_lease_end)
        await reports.drain(sink.deliver_lease_end)
    assert len(requests) == (1 if status == 404 else 2)
    assert all(request.content == before for request in requests)
    assert canonical_json((await seller.get_lease(reservation)).end_reports[0]) == before
    with factory() as db:
        row = db.query(LeaseEndReportOutbox).one()
        assert row.parked == (status == 404)
        assert row.delivered_at is None


async def test_unsupported_peer_parks_existing_and_future_events_but_preserves_pull(client_and_queue, seller):
    ledger = container.resolved_capacity_ledger_service
    first = _committed("fixture-first")
    second = _committed("fixture-second")
    ledger.release(capacity_reservation_id=first)
    ledger.release(capacity_reservation_id=second)
    factory = container.resolved_session_factory
    with factory() as db:
        peer = db.query(LeaseEndReportOutbox).first().peer
    reports = LeaseEndReports(factory, signer=Ed25519Signer(b"\x63" * 32), peer=peer)
    calls = []

    async def unsupported(report):
        calls.append(canonical_json(report))
        return "unsupported"

    await reports.drain(unsupported)
    assert len(calls) == 1
    third = _committed("fixture-after-parking")
    ledger.release(capacity_reservation_id=third)
    await LeaseEndReports(factory, signer=reports.signer, peer=peer).drain(unsupported)
    assert len(calls) == 1
    for reservation in (first, second, third):
        assert len((await seller.get_lease(reservation)).end_reports) == 1
    with factory() as db:
        assert all(row.parked and row.delivered_at is None for row in db.query(LeaseEndReportOutbox))
    # A changed owner never redirects old statements; explicit resume belongs
    # to the original peer after the coordinated receiver upgrade.
    moved = LeaseEndReports(factory, signer=reports.signer, peer="https://new-owner.example")
    moved.resume_peer()
    await moved.drain(unsupported)
    assert len(calls) == 1
    reports.resume_peer()

    async def acknowledge(report):
        calls.append(canonical_json(report))
        return "delivered"

    await reports.drain(acknowledge)
    assert len(calls) == 4
    with factory() as db:
        assert all(not row.parked and row.delivered_at is not None for row in db.query(LeaseEndReportOutbox))
