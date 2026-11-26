"""Signed lease-end reports: kept as the site's evidence, delivered to the
storefront peer by a consumer of ``site.lease_ended``.

The library tests run the site ledger, the event recorder carrying the signing
hook, the lease-end report consumer and the pruner over a SQLite database the
service's migration chain built, with no application. The application tests
drive the service through its typed clients. Either way the storefront peer is
the double at its client's transport. Identities and origins are public
deterministic development fixtures, never for a public network.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import injected_time
import pytest
import pytest_asyncio
from injected_time import InjectedTime
from market_identity import TrustedIdentitySet, canonical_json
from market_resource_pools import ResourcePoolFacts
from market_site.ledger import CapacityLedgerService

from compute_provisioning_contracts import (
    LeaseTermination,
    SignedLeaseEndedReport,
    verify_lease_end,
)
from compute_provisioning_service import container as _container_module
from compute_provisioning_service.db.models import LeaseEndReport
from compute_provisioning_service.identity import ProvisioningIdentityContext
from compute_provisioning_service.services.deal_event_sink import StorefrontPeer
from compute_provisioning_service.services.lease_end_reports import (
    LEASE_END_REPORT_CONSUMER,
    LeaseEndReports,
    lease_end_report_consumer,
    peer_destination,
)
from compute_provisioning_service.services.operator_events import (
    EventsSettings,
    event_catalogue,
    event_pruner,
    event_recorder,
    event_runner,
)

from .conftest import ADMIN_SIGNER, SERVICE_AUTHORITIES, SERVICE_SIGNER, STOREFRONT_SIGNER
from .storefront_peer_double import (
    LEASE_ENDED,
    LOST,
    UNSUPPORTED,
    StorefrontPeerDouble,
)
from .test_leases_api import _committed, seller  # noqa: F401  (``seller`` is a fixture)

PEER = "http://127.0.0.1:0"
SITE = "default"
IDENTITY = ProvisioningIdentityContext(
    signer=SERVICE_SIGNER,
    storefront_principal=STOREFRONT_SIGNER.identity,
    admin_principal=ADMIN_SIGNER.identity,
    storefront_site_id=SITE,
)


class _Principals:
    """The principal authority's seller set: the storefront's fixture identity."""

    def active_principals(self, role):
        return TrustedIdentitySet(identities=(STOREFRONT_SIGNER.identity,))


@pytest.fixture
def source() -> Iterator[InjectedTime]:
    """The process time source, held at the wall instant it is installed."""
    before = injected_time.installed()
    installed = InjectedTime()
    injected_time.install(installed)
    yield installed
    injected_time.install(before)


def _ledger(session_factory, signer=SERVICE_SIGNER) -> CapacityLedgerService:
    ledger = CapacityLedgerService(
        session_factory,
        pool_facts=ResourcePoolFacts(),
        site_id=SITE,
        unit_claim_keys=("units", "gpu_count"),
        mirror_dimension="gpu_count",
        event_recorder=event_recorder(event_catalogue(signer), instance=SITE),
    )
    ledger.register_resource(
        resource_id="compute-kvm1-001", total_units=8, host_id="kvm1", attributes={},
        pool_id="default",
    )
    return ledger


def _leased(ledger: CapacityLedgerService, escrow: str) -> str:
    reserved = ledger.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1, "host_id": "kvm1"},
        deal_ref={"escrow_uid": escrow},
    )
    ledger.commit(
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_start_utc="2030-01-01T00:00:00+00:00",
        lease_end_utc="2030-01-02T00:00:00+00:00",
    )
    return reserved["capacity_reservation_id"]


def _consumer(session_factory, double: StorefrontPeerDouble, url: str = PEER):
    peer = StorefrontPeer(url, IDENTITY, _Principals(), transport=double.transport)
    return lease_end_report_consumer(session_factory, peer, runner=event_runner(SITE)), peer


def _stored(session_factory, capacity_reservation_id: str) -> bytes:
    with session_factory() as db:
        (row,) = db.query(LeaseEndReport).filter_by(
            capacity_reservation_id=capacity_reservation_id
        ).all()
        return row.report.encode()


# ---------------------------------------------------------------------------
# Library integration: the ledger, the hook, the consumer and the pruner
# ---------------------------------------------------------------------------


def test_the_site_crashes_after_recording_an_end(session_factory, source):
    """Recovery delivers the stored event with its original identity, instant
    and cause, as signed when the end was recorded, though the restarted
    process's time has moved on."""
    ledger = _ledger(session_factory)
    reservation = _leased(ledger, "escrow-crash")
    ended_at = injected_time.now()
    ledger.release(capacity_reservation_id=reservation)
    stored = _stored(session_factory, reservation)
    # The process stops before sending, and restarts an hour later.
    source.set(ended_at + 3600)
    double = StorefrontPeerDouble(STOREFRONT_SIGNER)
    consumer, peer = _consumer(session_factory, double)

    report = consumer.run_cycle()
    peer.close()

    assert report.delivered == 1
    (sent,) = double.taken(LEASE_ENDED)
    assert sent.content == stored
    event = verify_lease_end(
        SignedLeaseEndedReport.model_validate_json(sent.content),
        capacity_reservation_id=reservation, site_id=SITE, expected_sites=SERVICE_AUTHORITIES,
    )
    assert (event.cause, event.effective_at) == ("release", ended_at)
    assert sent.resource == reservation
    assert consumer.run_cycle().delivered == 0


def test_a_repeated_release_keeps_one_report(session_factory):
    """A release repeated after it committed records no second end, so no
    second report is signed or kept."""
    ledger = _ledger(session_factory)
    reservation = _leased(ledger, "escrow-refused")
    ledger.release(capacity_reservation_id=reservation)
    ledger.release(capacity_reservation_id=reservation)

    assert len(LeaseEndReports(session_factory).read(reservation)) == 1


def test_a_signed_report_is_kept_by_its_own_retention_and_while_its_event_is(
        session_factory, source):
    ledger = _ledger(session_factory)
    reservation = _leased(ledger, "escrow-retained")
    ledger.release(capacity_reservation_id=reservation)
    catalogue = event_catalogue(SERVICE_SIGNER)
    source.set(injected_time.now() + 3 * 86400)

    event_pruner(session_factory, catalogue, EventsSettings()).prune()
    assert len(LeaseEndReports(session_factory).read(reservation)) == 1

    report_a_day = EventsSettings.model_validate({"retention_days": {"lease_end_reports": 1}})
    event_pruner(session_factory, catalogue, report_a_day).prune()
    assert len(LeaseEndReports(session_factory).read(reservation)) == 1

    # Once both storefront consumers have read and delivered the end's events,
    # its event is prunable, and the report with it.
    double = StorefrontPeerDouble(STOREFRONT_SIGNER)
    peers = tuple(StorefrontPeer(PEER, IDENTITY, _Principals(), transport=double.transport)
                  for _ in range(2))
    for consumer in _container_module._make_storefront_consumers(
            session_factory, peers, IDENTITY):
        consumer.run_cycle()
    for peer in peers:
        peer.close()
    both_a_day = EventsSettings.model_validate(
        {"retention_days": {"events": 1, "lease_end_reports": 1}})
    event_pruner(session_factory, catalogue, both_a_day).prune()
    assert LeaseEndReports(session_factory).read(reservation) == []


def test_a_pending_report_past_its_retention_is_still_delivered(session_factory, source):
    """A report outlives its retention while its event waits for a peer that
    is down, so the delivery finds it when the peer returns."""
    ledger = _ledger(session_factory)
    double = StorefrontPeerDouble(STOREFRONT_SIGNER)
    double.answer(LEASE_ENDED, 503)
    consumer, peer = _consumer(session_factory, double)
    consumer.register()
    reservation = _leased(ledger, "escrow-outage")
    ledger.release(capacity_reservation_id=reservation)
    stored = _stored(session_factory, reservation)
    assert consumer.run_cycle().failed == 1
    source.set(injected_time.now() + 3 * 86400)

    a_day = EventsSettings.model_validate(
        {"retention_days": {"events": 1, "lease_end_reports": 1}})
    event_pruner(session_factory, event_catalogue(SERVICE_SIGNER), a_day).prune()
    report = consumer.run_cycle()
    peer.close()

    assert report.delivered == 1
    assert [sent.content for sent in double.taken(LEASE_ENDED)] == [stored, stored]


def test_a_report_no_longer_kept_is_abandoned_and_the_next_follows(
        session_factory, source, caplog):
    ledger = _ledger(session_factory)
    double = StorefrontPeerDouble(STOREFRONT_SIGNER)
    consumer, peer = _consumer(session_factory, double)
    consumer.register()
    lost, kept = _leased(ledger, "escrow-lost"), _leased(ledger, "escrow-kept")
    ledger.release(capacity_reservation_id=lost)
    ledger.release(capacity_reservation_id=kept)
    with session_factory() as db, db.begin():
        db.query(LeaseEndReport).filter_by(capacity_reservation_id=lost).delete()

    with caplog.at_level(logging.WARNING, logger="eventing.finally"):
        report = consumer.run_cycle()
    peer.close()

    assert (report.abandoned, report.delivered) == (1, 1)
    assert [sent.resource for sent in double.taken(LEASE_ENDED)] == [kept]
    assert any("is not retained" in record.getMessage() for record in caplog.records)


def test_a_peer_replaced_before_its_report_is_read_never_sends_it_to_the_new_peer(
        session_factory, caplog):
    """The service stops after a lease end commits and before its consumer
    reads it, and restarts configured with another storefront: the report goes
    to the previous peer's finally sink, not to the new peer, which receives
    what is recorded after it."""
    ledger = _ledger(session_factory)
    previous = StorefrontPeerDouble(STOREFRONT_SIGNER)
    consumer, peer = _consumer(session_factory, previous)
    consumer.run_cycle()
    peer.close()
    unread = _leased(ledger, "escrow-unread")
    ledger.release(capacity_reservation_id=unread)

    moved = StorefrontPeerDouble(STOREFRONT_SIGNER)
    restarted, peer = _consumer(session_factory, moved, url="https://new-owner.example")
    with caplog.at_level(logging.WARNING, logger="eventing.finally"):
        report = restarted.run_cycle()
    later = _leased(ledger, "escrow-later")
    ledger.release(capacity_reservation_id=later)
    restarted.run_cycle()
    peer.close()

    assert report.retired == [peer_destination(PEER)]
    assert previous.requests == []
    assert [sent.resource for sent in moved.taken(LEASE_ENDED)] == [later]
    assert any(
        "delivery abandoned" in record.getMessage() and unread in record.getMessage()
        for record in caplog.records
    )
    assert len(LeaseEndReports(session_factory).read(unread)) == 1


def test_a_first_peer_receives_a_report_recorded_since_the_consumer_last_read(
        session_factory):
    """A site runs with no storefront peer, its consumer reading each event
    with no destination, then a lease end commits and the service restarts with
    a peer configured: the first peer starts at the consumer's position, so it
    receives that report and what is recorded after it, but nothing the
    consumer read before."""
    ledger = _ledger(session_factory)
    nobody = StorefrontPeerDouble(STOREFRONT_SIGNER)
    consumer, peer = _consumer(session_factory, nobody, url="")
    read = _leased(ledger, "escrow-read")
    ledger.release(capacity_reservation_id=read)
    consumer.run_cycle()
    peer.close()
    unread = _leased(ledger, "escrow-unread")
    ledger.release(capacity_reservation_id=unread)

    configured = StorefrontPeerDouble(STOREFRONT_SIGNER)
    restarted, peer = _consumer(session_factory, configured)
    restarted.run_cycle()
    later = _leased(ledger, "escrow-later")
    ledger.release(capacity_reservation_id=later)
    restarted.run_cycle()
    peer.close()

    assert nobody.requests == []
    assert [sent.resource for sent in configured.taken(LEASE_ENDED)] == [unread, later]
    assert len(LeaseEndReports(session_factory).read(read)) == 1


# ---------------------------------------------------------------------------
# Application integration: through the service's typed clients
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def clients(source, client_and_queue):
    yield client_and_queue[0]


def _status(deliveries, consumer: str = LEASE_END_REPORT_CONSUMER):
    (status,) = [item for item in deliveries.destinations if item.consumer == consumer]
    return status


async def test_the_storefront_recovers_by_reading_the_lease(clients, seller, storefront_peer_double):
    """The authenticated lease read returns the original report's payload and
    site proof, the bytes the peer was sent."""
    reservation = _committed("fixture-recover")

    await seller.terminate_lease(reservation, LeaseTermination(reason="fixture maintenance"))
    await seller.terminate_lease(reservation, LeaseTermination(reason="retry must not rewrite"))

    (sent,) = storefront_peer_double.taken(LEASE_ENDED)
    (pulled,) = (await seller.get_lease(reservation)).end_reports
    assert canonical_json(pulled) == sent.content
    event = verify_lease_end(
        pulled, capacity_reservation_id=reservation, site_id=SITE,
        expected_sites=SERVICE_AUTHORITIES,
    )
    assert (event.cause, event.reason) == ("termination", "fixture maintenance")
    assert event.caller == STOREFRONT_SIGNER.identity


async def test_an_acknowledgement_is_lost(clients, seller, source, storefront_peer_double):
    """The consumer retries the same event identity and payload until the
    storefront acknowledges it."""
    storefront_peer_double.answer(LEASE_ENDED, LOST)
    reservation = _committed("fixture-lost-ack")

    await seller.terminate_lease(reservation, LeaseTermination(reason="fixture maintenance"))
    status = _status(await clients.family.get_event_deliveries())
    assert (status.state, status.pending) == ("active", 1)

    source.set(injected_time.now() + 11)
    await clients.family.run_event_delivery_cycle()

    first, second = storefront_peer_double.taken(LEASE_ENDED)
    assert (first.request_id, first.content) == (second.request_id, second.content)
    status = _status(await clients.family.get_event_deliveries())
    assert (status.pending, status.delivered) == (0, 1)


@pytest.mark.parametrize("answer", [404, 405, 501, UNSUPPORTED])
async def test_an_older_receiver_is_unsupported(clients, seller, storefront_peer_double, answer):
    """The peer's destination parks, later reports wait behind it unsent, and
    every signed report stays readable through the lease read."""
    storefront_peer_double.answer(LEASE_ENDED, answer)
    first, second = _committed("fixture-unsupported-1"), _committed("fixture-unsupported-2")

    await seller.terminate_lease(first, LeaseTermination(reason="fixture"))
    await seller.terminate_lease(second, LeaseTermination(reason="fixture"))
    await clients.family.run_event_delivery_cycle()

    assert len(storefront_peer_double.taken(LEASE_ENDED)) == 1
    status = _status(await clients.family.get_event_deliveries())
    assert (status.destination, status.state, status.pending) == (
        peer_destination(PEER), "parked", 2,
    )
    for reservation in (first, second):
        assert len((await seller.get_lease(reservation)).end_reports) == 1


async def test_a_transient_failure_retries_rather_than_parking(
    clients, seller, source, storefront_peer_double
):
    storefront_peer_double.answer(LEASE_ENDED, 503)
    reservation = _committed("fixture-transient")

    await seller.terminate_lease(reservation, LeaseTermination(reason="fixture"))
    assert _status(await clients.family.get_event_deliveries()).state == "active"
    source.set(injected_time.now() + 11)
    await clients.family.run_event_delivery_cycle()

    assert len(storefront_peer_double.taken(LEASE_ENDED)) == 2
    assert _status(await clients.family.get_event_deliveries()).delivered == 1


async def test_the_owning_storefront_s_peer_is_reconfigured(
    clients, seller, storefront_peer_double, monkeypatch, caplog
):
    """None of the previous peer's pending reports goes to the new peer: the
    previous peer's destination is retired, its pending reports written to the
    finally sink and still readable through the lease read; the new peer
    receives what is recorded after it."""
    storefront_peer_double.answer(LEASE_ENDED, 503)
    before = _committed("fixture-before-move")
    await seller.terminate_lease(before, LeaseTermination(reason="fixture"))

    # The service restarts configured with another storefront URL.
    moved = StorefrontPeerDouble(STOREFRONT_SIGNER)
    new_url = "https://new-owner.example"
    sessions = _container_module.resolved_session_factory
    restarted = _container_module._make_event_delivery_worker(
        _container_module._make_storefront_consumers(
            sessions,
            tuple(StorefrontPeer(new_url, IDENTITY, _Principals(), transport=moved.transport)
                  for _ in range(2)),
            IDENTITY,
        ),
        event_pruner(sessions, event_catalogue(SERVICE_SIGNER), EventsSettings()),
        EventsSettings(),
    )
    monkeypatch.setattr(_container_module, "resolved_event_delivery_worker", restarted)
    with caplog.at_level(logging.WARNING, logger="eventing.finally"):
        await clients.family.run_event_delivery_cycle()

    assert moved.requests == []
    assert any("delivery abandoned" in record.getMessage() for record in caplog.records)
    states = {
        item.destination: item.state
        for item in (await clients.family.get_event_deliveries()).destinations
        if item.consumer == LEASE_END_REPORT_CONSUMER
    }
    assert states == {peer_destination(PEER): "retired", peer_destination(new_url): "active"}
    assert len((await seller.get_lease(before)).end_reports) == 1

    # Ended through the site directly: the harness's lifecycle still holds the
    # worker composed before the restart.
    after = _committed("fixture-after-move")
    _container_module.resolved_capacity_ledger_service.release(capacity_reservation_id=after)
    await clients.family.run_event_delivery_cycle()

    assert [request.resource for request in moved.taken(LEASE_ENDED)] == [after]
    assert len(storefront_peer_double.taken(LEASE_ENDED)) == 1


@pytest.mark.parametrize("events_config", [{"retention_days": {"events": 1}}])
async def test_an_administrator_resumes_a_parked_peer(
    clients, seller, source, storefront_peer_double, events_config
):
    """Resuming delivers, in order, the reports the peer missed whose events
    are still retained; a report whose event was pruned while the peer was
    parked stays readable through the lease read."""
    storefront_peer_double.answer(LEASE_ENDED, 404)
    pruned = _committed("fixture-parked-pruned")
    await seller.terminate_lease(pruned, LeaseTermination(reason="fixture"))
    source.set(injected_time.now() + 2 * 86400)
    cycle = await clients.family.run_event_delivery_cycle()
    assert cycle.pruned.get("events", 0) >= 1
    retained = [_committed(f"fixture-parked-{index}") for index in (1, 2)]
    for reservation in retained:
        await seller.terminate_lease(reservation, LeaseTermination(reason="fixture"))
    assert len(storefront_peer_double.taken(LEASE_ENDED)) == 1

    resumed = await clients.family.resume_event_destination(
        peer_destination(PEER), consumer=LEASE_END_REPORT_CONSUMER
    )
    await clients.family.run_event_delivery_cycle()

    assert resumed.state == "active"
    assert [request.resource for request in storefront_peer_double.taken(LEASE_ENDED)] == [
        pruned, *retained,
    ]
    assert _status(await clients.family.get_event_deliveries()).pending == 0
    assert len((await seller.get_lease(pruned)).end_reports) == 1
