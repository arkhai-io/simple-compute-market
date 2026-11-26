"""The ledger records the site's events in its transitions' transactions.

Library integration: the real ledger and the real event recorder over one
SQLite database, built by the site's baseline and migrations and the eventing
component's own schema steps; the ledger reads its pool's facts through the
suite's pool-facts double.
"""

from __future__ import annotations

from collections.abc import Iterator

import injected_time
import pytest
from eventing import SCHEMA_STEPS, Catalogue, EventReader, Kind, Recorder, Reference, Severity, Source
from injected_time import InjectedTime
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from market_site import CapacityLedgerService, LedgerSiteAuthority
from market_site import migrations as site_migrations
from market_site.db import CapacityReservation
from market_site.events import SITE_KINDS, lease_reference
from pool_facts_double import PoolFactsDouble

LEASE = "fixture-lease"
DEFAULT_POOL_ID = "default"


class _FailureDetails(BaseModel):
    reason: str


#: A kind the site does not know, standing for a caller's prepared event.
CALLER_KIND = Kind(
    name="fixture.release_failed",
    version=1,
    severity=Severity.ACTION_REQUIRED,
    details=_FailureDetails,
    summary=lambda draft, details: f"release failed: {details.reason}",
    dedup_key=("subject",),
)


class _FailingRecorder:
    def __init__(self, recorder: Recorder) -> None:
        self._recorder = recorder

    def record(self, session, draft):
        self._recorder.record(session, draft)
        raise RuntimeError("recording failed")


@pytest.fixture
def store(source: InjectedTime) -> Iterator[tuple[sessionmaker, Recorder]]:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as connection:
        for migration in (site_migrations.BASELINE, *site_migrations.MIGRATIONS):
            migration.apply(connection)
        for step in SCHEMA_STEPS:
            step.apply(connection)
    sessions = sessionmaker(bind=engine)
    with sessions() as db, db.begin():
        db.add(CapacityReservation(capacity_reservation_id=LEASE, state="leased", offering_mode="vm"))
    recorder = Recorder(
        Catalogue((*SITE_KINDS, CALLER_KIND)),
        source=Source(service="fixture-site", instance="fixture"),
        clock=injected_time.now_datetime,
    )
    yield sessions, recorder
    engine.dispose()


def _ledger(sessions, recorder, **kwargs) -> CapacityLedgerService:
    pools = PoolFactsDouble()
    pools.declare(DEFAULT_POOL_ID, ("vm",))
    return CapacityLedgerService(
        sessions, pool_facts=pools, site_id="fixture-site", event_recorder=recorder, **kwargs
    )


def _events(sessions, kind: str | None = None):
    return EventReader(sessions).events(kind=kind, reference=lease_reference(LEASE), limit=500)


def test_a_lease_end_records_its_record_and_one_event_carrying_its_payload(store):
    sessions, recorder = store
    ledger = _ledger(sessions, recorder)

    assert ledger.begin_releasing(LEASE, release_job_id="fixture-release") is not None
    assert ledger.begin_releasing(LEASE, release_job_id="fixture-release") is not None

    (record,) = ledger.lease_end_events(LEASE)
    (event,) = _events(sessions, "site.lease_ended")
    assert event.details == record
    assert event.subject == Reference(type="lease", id=LEASE)
    assert event.attributes == {"cause": "release", "source_state": "leased", "transition_key": "end"}


def test_each_ending_transition_records_its_own_event(store):
    sessions, recorder = store
    ledger = _ledger(sessions, recorder)

    ledger.record_release_failed(LEASE, reason="fixture failure")
    ledger.release(capacity_reservation_id=LEASE, forced=True)

    ended = _events(sessions, "site.lease_ended")
    assert [e.attributes["transition_key"] for e in ended] == ["release_failure", "force_release"]
    assert sorted(e.details["event_id"] for e in ended) == sorted(
        record["event_id"] for record in ledger.lease_end_events(LEASE)
    )


def test_a_force_release_of_a_failed_release_records_capacity_released(store):
    sessions, recorder = store
    ledger = _ledger(sessions, recorder)
    ledger.record_release_failed(LEASE, reason="fixture failure")

    released = ledger.release(
        capacity_reservation_id=LEASE, forced=True, failure_reason="admin_force_release"
    )
    ledger.release(capacity_reservation_id=LEASE, forced=True)

    assert released is not None
    (event,) = _events(sessions, "site.capacity_released")
    assert event.attributes == {
        "forced": True, "after_release_failure": True, "lease_lifecycle": False}
    assert event.details["state"] == "force_released"
    assert event.details["failure_reason"] == "admin_force_release"


def test_a_guarded_release_records_capacity_released_unforced(store):
    sessions, recorder = store
    ledger = _ledger(sessions, recorder)

    assert ledger.release(capacity_reservation_id=LEASE) is not None

    (event,) = _events(sessions, "site.capacity_released")
    assert event.attributes == {
        "forced": False, "after_release_failure": False, "lease_lifecycle": False}
    assert event.details["state"] == "released"


def test_a_release_through_the_site_authority_port_is_marked_the_lease_lifecycles(store):
    sessions, recorder = store
    authority = LedgerSiteAuthority(_ledger(sessions, recorder))

    assert authority.record_release_success(LEASE) is not None

    (event,) = _events(sessions, "site.capacity_released")
    assert event.attributes["lease_lifecycle"] is True


def test_a_release_the_guard_refuses_records_no_capacity_released(store):
    sessions, recorder = store
    ledger = _ledger(sessions, recorder, release_guard=lambda db, reservation_id: False)

    assert ledger.release(capacity_reservation_id=LEASE) is None

    assert _events(sessions) == []
    assert ledger.get_reservation(LEASE)["state"] == "leased"


def test_an_accepted_release_failure_records_the_callers_prepared_event(store):
    sessions, recorder = store
    ledger = _ledger(sessions, recorder)
    prepared = CALLER_KIND.draft(
        subject=lease_reference(LEASE), details={"reason": "teardown_failed"},
        related=(lease_reference(LEASE),),
    )

    failed = ledger.record_release_failed(LEASE, reason="teardown_failed", event=prepared)

    assert failed is not None and failed["state"] == "release_failed"
    (event,) = _events(sessions, "fixture.release_failed")
    assert event.details == {"reason": "teardown_failed"}


def test_a_refused_release_failure_records_no_prepared_event(store):
    sessions, recorder = store
    ledger = _ledger(sessions, recorder)
    ledger.release(capacity_reservation_id=LEASE, forced=True)
    prepared = CALLER_KIND.draft(
        subject=lease_reference(LEASE), details={"reason": "teardown_failed"},
        related=(lease_reference(LEASE),),
    )

    assert ledger.record_release_failed(LEASE, reason="teardown_failed", event=prepared) is None

    assert _events(sessions, "fixture.release_failed") == []
    assert ledger.get_reservation(LEASE)["state"] == "force_released"


def test_a_recorder_that_fails_rolls_the_transition_back(store):
    sessions, recorder = store
    ledger = _ledger(sessions, _FailingRecorder(recorder))

    with pytest.raises(RuntimeError, match="recording failed"):
        ledger.release(capacity_reservation_id=LEASE)

    assert ledger.get_reservation(LEASE)["state"] == "leased"
    assert ledger.lease_end_events(LEASE) == []
    assert _events(sessions) == []
