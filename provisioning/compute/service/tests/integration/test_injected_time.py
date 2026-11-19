"""The provisioning service's own stores stamp and decide by the process's time source.

Library integration: each store over a real SQLite database the service's
migration chain built, with the process source injected and held, so every
time a store writes or compares is the source's and none the wall clock's or
the database's.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import injected_time
import pytest
from injected_time import InjectedTime
from market_identity import Ed25519Signer, ReplayIdentity, ReplayReservation
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from compute_provisioning_service.db.database import migrate_database
from compute_provisioning_service.db.models import (
    CapacityReleaseCallbackOutbox,
    ProvisioningReplayReservation,
)
from compute_provisioning_service.middleware.auth import SqlAlchemyProvisioningReplayStore
from compute_provisioning_service.services.deal_event_sink import (
    SqlAlchemyCapacityReleaseOutbox,
)

#: The instant the injected source starts at.
START = 1794821400

_CALLER = Ed25519Signer(b"\x31" * 32).identity


@pytest.fixture
def source() -> Iterator[InjectedTime]:
    """The process time source, injected at ``START``; a test sets it forward."""
    before = injected_time.installed()
    installed = InjectedTime(start=START)
    injected_time.install(installed)
    yield installed
    injected_time.install(before)


@pytest.fixture
def sessions(tmp_path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'provisioning.db'}")
    migrate_database(engine)
    return sessionmaker(bind=engine)


def _utc(instant: int) -> datetime:
    return datetime.fromtimestamp(instant, timezone.utc)


def _stored(value: datetime) -> datetime:
    """A stored time as the UTC instant it denotes: SQLite returns it naive."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def test_a_release_callback_s_creation_attempts_and_delivery_are_the_source_s_instants(
    sessions: sessionmaker[Session], source: InjectedTime
):
    outbox = SqlAlchemyCapacityReleaseOutbox(sessions)
    outbox.reserve("reservation-1")
    source.set(START + 10)
    outbox.record_failure("reservation-1", "unreachable")
    with sessions() as db:
        row = db.get(CapacityReleaseCallbackOutbox, "reservation-1")
        assert _stored(row.created_at) == _utc(START)
        assert _stored(row.last_attempted_at) == _utc(START + 10)

    source.set(START + 20)
    outbox.mark_delivered("reservation-1")
    with sessions() as db:
        row = db.get(CapacityReleaseCallbackOutbox, "reservation-1")
        assert _stored(row.delivered_at) == _utc(START + 20)


def test_a_dispatch_lease_is_claimed_again_only_once_the_source_reaches_its_expiry(
    sessions: sessionmaker[Session], source: InjectedTime
):
    store = SqlAlchemyProvisioningReplayStore(sessions, dispatch_lease_seconds=30)
    reservation = ReplayReservation(
        identity=ReplayIdentity(principal=_CALLER, request_id="request-1"),
        request_hash="0" * 64,
    )
    assert store.reserve(reservation) is None
    with sessions() as db:
        row = db.query(ProvisioningReplayReservation).one()
        assert _stored(row.dispatch_lease_expires_at) == _utc(START + 30)

    source.set(START + 29)
    assert store.claim_stale(reservation) is False
    source.set(START + 30)
    assert store.claim_stale(reservation) is True

    source.set(START + 40)
    store.record_outcome(
        reservation, response_status=200, response_body={}, response_media_type=None
    )
    with sessions() as db:
        row = db.query(ProvisioningReplayReservation).one()
        assert _stored(row.dispatch_lease_expires_at) == _utc(START + 60)
        assert _stored(row.completed_at) == _utc(START + 40)
