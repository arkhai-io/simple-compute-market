"""The ledger decides and stamps by its process's time source.

Library integration: the ledger over a real SQLite database its migration chain
built, with the process source injected, so every instant it compares or records
is the source's and none the wall clock's or the database's.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from injected_time import InjectedTime
from market_resource_pools import migrations as pool_migrations
from market_resource_pools.db import DEFAULT_POOL_ID, ResourcePool
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from market_site import migrations as site_migrations
from market_site.db import CapacityBucket, CapacityReservation, LeaseEndedEvent
from market_site.ledger import CapacityLedgerService

#: The instant a hold expires at.
EXPIRY = 1794822300
#: A held reservation's TTL.
TTL = 900
#: The instant each test starts at, a TTL before ``EXPIRY``.
START = EXPIRY - TTL


def _utc(instant: int) -> datetime:
    return datetime.fromtimestamp(instant, timezone.utc)


def _stored(value: datetime) -> datetime:
    """A stored time as the UTC instant it denotes: SQLite returns it naive."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@pytest.fixture
def ledger(source: InjectedTime, tmp_path) -> CapacityLedgerService:
    """A ledger declaring one resource of four units, with the source at ``START``."""
    source.set(START)
    engine = create_engine(f"sqlite:///{tmp_path / 'site.db'}")
    with engine.begin() as connection:
        pool_migrations.BASELINE.apply(connection)
        site_migrations.BASELINE.apply(connection)
        for migration in site_migrations.MIGRATIONS:
            migration.apply(connection)
    sessions = sessionmaker(bind=engine)
    with sessions() as db, db.begin():
        db.add(
            ResourcePool(
                id=DEFAULT_POOL_ID,
                label="Default Pool",
                provider="test",
                enabled=True,
                policy_tags={"deliverable_modes": ["vm"]},
            )
        )
    service = CapacityLedgerService(sessions)
    service.register_resource(
        host_id="host-1",
        resource_id="resource-1",
        total_units=4,
        attributes={},
        pool_id=DEFAULT_POOL_ID,
    )
    return service


def _hold(ledger: CapacityLedgerService, escrow: str) -> str:
    reserved = ledger.reserve(
        claim={"offering_mode": "vm", "units": 4},
        deal_ref={"escrow_uid": escrow},
        ttl_seconds=TTL,
    )
    assert reserved is not None
    return reserved["capacity_reservation_id"]


def test_a_hold_expires_at_the_set_instant_and_not_before(
    ledger: CapacityLedgerService, source: InjectedTime
):
    reservation_id = _hold(ledger, "0xhold")
    hold = ledger.get_reservation(reservation_id)
    assert datetime.fromisoformat(hold["hold_expires_at"]) == _utc(EXPIRY)

    source.set(EXPIRY - 1)
    ledger.expire_due_holds()
    assert ledger.get_reservation(reservation_id)["state"] == "reserved"

    source.set(EXPIRY)
    ledger.expire_due_holds()
    lapsed = ledger.get_reservation(reservation_id)
    assert (lapsed["state"], lapsed["failure_reason"]) == ("released", "hold_expired")
    assert datetime.fromisoformat(lapsed["released_at"]) == _utc(EXPIRY)


def test_a_lease_s_start_activation_and_release_are_the_source_s_instants(
    ledger: CapacityLedgerService, source: InjectedTime
):
    reservation_id = _hold(ledger, "0xlease")
    leased = ledger.commit(
        capacity_reservation_id=reservation_id,
        lease_end_utc=_utc(EXPIRY + 3600).isoformat(),
    )
    assert datetime.fromisoformat(leased["lease_start_utc"]) == _utc(START)

    source.set(EXPIRY)
    activated = ledger.activate_lease(reservation_id)
    assert datetime.fromisoformat(activated["activated_at_utc"]) == _utc(EXPIRY)

    source.set(EXPIRY + 60)
    releasing = ledger.begin_releasing(reservation_id, release_job_id="release-1")
    assert datetime.fromisoformat(releasing["release_requested_at"]) == _utc(EXPIRY + 60)
    with ledger._session_factory() as db:
        (ended,) = db.query(LeaseEndedEvent).filter_by(
            capacity_reservation_id=reservation_id
        ).all()
    assert ended.payload["effective_at"] == EXPIRY + 60


def test_the_columns_the_ledger_orders_by_hold_the_source_s_instant(
    ledger: CapacityLedgerService, source: InjectedTime
):
    """A reservation's creation, stamped on insert, and a declaration's last
    change, stamped on insert and again on update."""
    reservation_id = _hold(ledger, "0xcolumns")
    with ledger._session_factory() as db:
        assert _stored(db.query(CapacityBucket).one().updated_at) == _utc(START)

    source.set(EXPIRY)
    ledger.register_resource(
        host_id="host-1",
        resource_id="resource-1",
        total_units=4,
        attributes={"rack": "a"},
        pool_id=DEFAULT_POOL_ID,
    )

    with ledger._session_factory() as db:
        reservation = db.get(CapacityReservation, reservation_id)
        bucket = db.query(CapacityBucket).one()
        assert _stored(reservation.created_at) == _utc(START)
        assert _stored(bucket.updated_at) == _utc(EXPIRY)
