"""The storefront outboxes carried into the event store at upgrade.

Each database starts as the release's floor fixture built it, holding the
lease-end report and capacity-released callback outboxes, is seeded with rows
as a deployment would hold them — delivered, pending and parked — and is
brought forward by the chain. The storefront peer's consumers then run over it,
their peer the double at the storefront client's transport.

External boundary: file-backed SQLite migrated by the chain, the consumers over
it; no application. Identities and origins are public deterministic
development fixtures, never for a public network.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import injected_time
import pytest
from injected_time import InjectedTime
from market_identity import TrustedIdentitySet, canonical_json
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from compute_provisioning_contracts import LeaseEndedEvent, sign_lease_end
from compute_provisioning_service.db.database import migrate_database
from compute_provisioning_service.identity import ProvisioningIdentityContext
from compute_provisioning_service.services.deal_event_sink import (
    CAPACITY_RELEASED_CONSUMER,
    StorefrontPeer,
    capacity_release_request_id,
    capacity_released_consumer,
)
from compute_provisioning_service.services.lease_end_reports import (
    LEASE_END_REPORT_CONSUMER,
    lease_end_report_consumer,
    peer_destination,
)
from eventing import resume_destination
from market_schema_migrations import MigrationFailed

from .conftest import ADMIN_SIGNER, SERVICE_SIGNER, STOREFRONT_SIGNER
from .floor_database import create_floor_database
from .storefront_peer_double import CAPACITY_RELEASED, LEASE_ENDED, StorefrontPeerDouble

PEER = "http://storefront-a:8001"
FORMER_PEER = "http://storefront-b:8001"
SITE = "site-west"
IDENTITY = ProvisioningIdentityContext(
    signer=SERVICE_SIGNER,
    storefront_principal=STOREFRONT_SIGNER.identity,
    admin_principal=ADMIN_SIGNER.identity,
    storefront_site_id=SITE,
)


class _Principals:
    def active_principals(self, role):
        return TrustedIdentitySet(identities=(STOREFRONT_SIGNER.identity,))


def _end(db: sqlite3.Connection, event_id: str, reservation: str, transition_key: str = "end",
         *, cause: str = "release") -> str:
    """A recorded lease end and its signed report, as the release stored them."""
    payload = {
        "version": 1, "kind": "lease_ended", "event_id": event_id,
        "capacity_reservation_id": reservation, "site_id": SITE,
        "effective_at": 1794821400, "source_state": "leased", "cause": cause,
        "reason": None, "caller": None, "claimed_deadline": None, "deadline_phase": None,
    }
    db.execute(
        "INSERT INTO site_lease_ended_events (event_id, capacity_reservation_id, "
        "transition_key, payload) VALUES (?, ?, ?, ?)",
        (event_id, reservation, transition_key, json.dumps(payload)),
    )
    return canonical_json(sign_lease_end(LeaseEndedEvent.model_validate(payload), SERVICE_SIGNER)).decode()


def _report(db: sqlite3.Connection, event_id: str, reservation: str, *, peer: str = PEER,
            created_at: str, delivered: bool = False, parked: bool = False,
            attempts: int = 0, last_error: str | None = None) -> str:
    report = _end(db, event_id, reservation)
    db.execute(
        "INSERT INTO lease_end_report_outbox (event_id, capacity_reservation_id, peer, report, "
        "parked, attempt_count, last_error, created_at, last_attempted_at, delivered_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (event_id, reservation, peer, report, int(parked), attempts, last_error, created_at,
         created_at if attempts else None, created_at if delivered else None),
    )
    return report


def _reservation(db: sqlite3.Connection, reservation: str, state: str, *,
                 released_at: str | None = None) -> None:
    db.execute(
        "INSERT INTO capacity_reservations (capacity_reservation_id, units, state, released_at) "
        "VALUES (?, 1, ?, ?)",
        (reservation, state, released_at),
    )


def _callback(db: sqlite3.Connection, reservation: str, *, created_at: str,
              delivered: bool = False, attempts: int = 0, last_error: str | None = None) -> None:
    db.execute(
        "INSERT INTO capacity_release_callback_outbox (capacity_reservation_id, attempt_count, "
        "last_error, created_at, last_attempted_at, delivered_at) VALUES (?, ?, ?, ?, ?, ?)",
        (reservation, attempts, last_error, created_at, created_at if attempts else None,
         created_at if delivered else None),
    )


@pytest.fixture
def source() -> Iterator[InjectedTime]:
    """The process time source, held at the wall instant it is installed."""
    before = injected_time.installed()
    installed = InjectedTime()
    injected_time.install(installed)
    yield installed
    injected_time.install(before)


def _floor(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    path = create_floor_database(tmp_path / "provisioning.db")
    return path, sqlite3.connect(path)


def _upgraded(path: Path):
    engine = create_engine(f"sqlite:///{path}")
    migrate_database(engine)
    return engine, sessionmaker(bind=engine)


def _deliveries(engine, consumer: str) -> list[tuple]:
    with engine.connect() as connection:
        return connection.execute(text(
            "SELECT e.id, d.destination, d.state, d.attempts, d.last_error "
            "FROM eventing_deliveries d JOIN eventing_events e ON e.sequence = d.event_sequence "
            "WHERE d.consumer = :consumer ORDER BY d.event_sequence"
        ), {"consumer": consumer}).all()


def test_a_report_is_pending_at_upgrade(tmp_path):
    """After the upgrade the report is delivered under its original event
    identity and signed payload, its attempts carried; a delivered report is
    not sent again, and every signed report stays kept."""
    path, db = _floor(tmp_path)
    with db:
        _report(db, "end-delivered", "r-1", created_at="2026-11-20 10:00:00", delivered=True)
        later = _report(db, "end-later", "r-3", created_at="2026-11-20 10:02:00")
        pending = _report(db, "end-pending", "r-2", created_at="2026-11-20 10:01:00",
                          attempts=2, last_error="retry")
    db.close()

    engine, sessions = _upgraded(path)

    assert _deliveries(engine, LEASE_END_REPORT_CONSUMER) == [
        ("end-pending", peer_destination(PEER), "pending", 2, "retry"),
        ("end-later", peer_destination(PEER), "pending", 0, None),
    ]
    with engine.connect() as connection:
        kept = connection.execute(text(
            "SELECT event_id, envelope_id FROM lease_end_reports ORDER BY event_id"
        )).all()
        positions = dict(connection.execute(text("SELECT name, position FROM eventing_consumers")).all())
    # A moved report names the event it is kept for; a delivered one has none.
    assert [tuple(row) for row in kept] == [
        ("end-delivered", None), ("end-later", "end-later"), ("end-pending", "end-pending"),
    ]
    assert positions == {LEASE_END_REPORT_CONSUMER: 2, CAPACITY_RELEASED_CONSUMER: 2}
    tables = set(inspect(engine).get_table_names())
    assert not {"lease_end_report_outbox", "capacity_release_callback_outbox"} & tables

    double = StorefrontPeerDouble(STOREFRONT_SIGNER)
    peer = StorefrontPeer(PEER, IDENTITY, _Principals(), transport=double.transport)
    report = lease_end_report_consumer(sessions, peer, runner="upgraded").run_cycle()
    peer.close()

    assert report.delivered == 2
    first, second = double.taken(LEASE_ENDED)
    assert (first.content, second.content) == (pending.encode(), later.encode())
    assert (first.resource, second.resource) == ("r-2", "r-3")


def test_a_parked_report_stays_parked_at_upgrade(tmp_path):
    path, db = _floor(tmp_path)
    with db:
        _report(db, "end-parked-delivered", "r-1", created_at="2026-11-20 10:00:00",
                delivered=True, parked=True)
        parked = _report(db, "end-parked", "r-2", created_at="2026-11-20 10:01:00",
                         parked=True, attempts=1, last_error="unsupported")
    db.close()

    _, sessions = _upgraded(path)
    double = StorefrontPeerDouble(STOREFRONT_SIGNER)
    peer = StorefrontPeer(PEER, IDENTITY, _Principals(), transport=double.transport)
    consumer = lease_end_report_consumer(sessions, peer, runner="upgraded")

    assert consumer.run_cycle().delivered == 0
    assert double.requests == []
    with sessions.begin() as session:
        resume_destination(session, LEASE_END_REPORT_CONSUMER, peer_destination(PEER),
                           injected_time.now_datetime())
    assert consumer.run_cycle().delivered == 1
    peer.close()
    (sent,) = double.taken(LEASE_ENDED)
    assert sent.content == parked.encode()


def test_a_former_peer_s_pending_report_is_retired_not_redirected(tmp_path):
    path, db = _floor(tmp_path)
    with db:
        _report(db, "end-former", "r-1", peer=FORMER_PEER, created_at="2026-11-20 10:00:00")
    db.close()

    engine, sessions = _upgraded(path)
    double = StorefrontPeerDouble(STOREFRONT_SIGNER)
    peer = StorefrontPeer(PEER, IDENTITY, _Principals(), transport=double.transport)
    report = lease_end_report_consumer(sessions, peer, runner="upgraded").run_cycle()
    peer.close()

    assert (report.retired, report.abandoned) == ([peer_destination(FORMER_PEER)], 1)
    assert double.requests == []


def test_a_callback_is_pending_at_upgrade(tmp_path, source):
    """The callback of a released reservation is delivered after the upgrade
    under the same reservation and the request identity its release gives; a
    delivered one and one whose reservation never released are not."""
    path, db = _floor(tmp_path)
    released_at = "2026-11-20T10:00:00+00:00"
    with db:
        for reservation, state in (("c-delivered", "released"), ("c-pending", "force_released"),
                                   ("c-unreleased", "leased")):
            _reservation(db, reservation, state,
                         released_at=None if state == "leased" else released_at)
        _end(db, "end-c-delivered", "c-delivered")
        _end(db, "end-c-failed", "c-pending", "release_failure", cause="release_failed")
        _end(db, "end-c-pending", "c-pending", "force_release", cause="force_release")
        _callback(db, "c-delivered", created_at="2026-11-20 10:00:00", delivered=True)
        _callback(db, "c-pending", created_at="2026-11-20 10:01:00", attempts=3,
                  last_error="signed storefront acknowledgement was not received")
        _callback(db, "c-unreleased", created_at="2026-11-20 10:02:00")
    db.close()

    engine, sessions = _upgraded(path)

    (moved,) = _deliveries(engine, CAPACITY_RELEASED_CONSUMER)
    assert moved[1:] == ("storefront", "pending", 3,
                         "signed storefront acknowledgement was not received")
    with engine.connect() as connection:
        envelope = json.loads(connection.execute(text(
            "SELECT envelope FROM eventing_events WHERE kind = 'site.capacity_released'"
        )).scalar_one())
    assert envelope["attributes"] == {
        "forced": True, "after_release_failure": True, "lease_lifecycle": True}
    assert envelope["source"] == {"service": "compute-provisioning", "instance": SITE}

    double = StorefrontPeerDouble(STOREFRONT_SIGNER)
    # The upgraded service first starts with no storefront URL: the moved
    # callback stays pending rather than being retired.
    unconfigured = StorefrontPeer("", IDENTITY, _Principals(), transport=double.transport)
    gap = capacity_released_consumer(sessions, unconfigured, runner="upgraded").run_cycle()
    assert (gap.retired, gap.abandoned, gap.failed) == ([], 0, 1)
    assert _deliveries(engine, CAPACITY_RELEASED_CONSUMER)[0][2] == "pending"
    peer = StorefrontPeer(PEER, IDENTITY, _Principals(), transport=double.transport)
    source.set(injected_time.now() + 3600)  # past the attempt's backoff
    assert capacity_released_consumer(sessions, peer, runner="upgraded").run_cycle().delivered == 1
    peer.close()
    (callback,) = double.taken(CAPACITY_RELEASED)
    assert callback.body == {
        "capacity_reservation_id": "c-pending", "site_id": SITE, "released_at": released_at,
    }
    assert callback.request_id == capacity_release_request_id("c-pending", released_at)


def test_a_fresh_database_registers_the_storefront_consumers_at_its_start(tmp_path):
    engine, _ = _upgraded(tmp_path / "fresh.db")
    with engine.connect() as connection:
        assert dict(connection.execute(text("SELECT name, position FROM eventing_consumers")).all()) == {
            LEASE_END_REPORT_CONSUMER: 0, CAPACITY_RELEASED_CONSUMER: 0,
        }


def test_a_pending_report_naming_no_recorded_end_refuses_the_upgrade(tmp_path):
    """Nothing is guessed: the migration refuses and writes nothing, the
    outbox kept for the operator to restore from."""
    path, db = _floor(tmp_path)
    with db:
        report = _end(db, "end-orphan", "r-1")
        db.execute("DELETE FROM site_lease_ended_events")
        db.execute(
            "INSERT INTO lease_end_report_outbox (event_id, capacity_reservation_id, peer, "
            "report) VALUES ('end-orphan', 'r-1', ?, ?)",
            (PEER, report),
        )
    db.close()

    with pytest.raises(MigrationFailed, match="end-orphan"):
        migrate_database(create_engine(f"sqlite:///{path}"))

    connection = sqlite3.connect(path)
    try:
        assert connection.execute("SELECT count(*) FROM lease_end_report_outbox").fetchone() == (1,)
        assert "lease_end_reports" not in {
            row[0] for row in connection.execute("SELECT name FROM sqlite_master")
        }
    finally:
        connection.close()


def test_a_pending_callback_whose_release_recorded_no_lease_end_refuses_the_upgrade(tmp_path):
    path, db = _floor(tmp_path)
    with db:
        _reservation(db, "c-orphan", "released", released_at="2026-11-20T10:00:00+00:00")
        _callback(db, "c-orphan", created_at="2026-11-20 10:01:00")
    db.close()

    with pytest.raises(MigrationFailed, match="c-orphan"):
        migrate_database(create_engine(f"sqlite:///{path}"))

    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            "SELECT count(*) FROM capacity_release_callback_outbox"
        ).fetchone() == (1,)
    finally:
        connection.close()
