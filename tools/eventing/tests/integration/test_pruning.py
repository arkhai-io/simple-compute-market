"""Pruning against a real SQLite file: each table by its own retention, and never an
event a destination is still owed.

Library integration: the pruner through its public API over a store a recorder and
a consumer wrote.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from eventing import (
    Catalogue,
    Consumer,
    Envelope,
    Kind,
    PrunedTable,
    Pruner,
    Recorder,
    RecordHook,
    Reference,
    Retention,
    Severity,
    Source,
)
from eventing import schema
from tests.fixtures.kinds import Clock, JobDetails, Store, catalogue, job

MONTH = timedelta(days=30)


class Failing:
    def __init__(self) -> None:
        self.received: list[str] = []
        self.failing = True

    def deliver(self, envelope: Envelope) -> None:
        if self.failing:
            raise ConnectionError("down")
        self.received.append(envelope.subject.id)


def sequences(store: Store) -> list[int]:
    with store.engine.connect() as connection:
        return list(connection.execute(
            select(schema.events.c.sequence).order_by(schema.events.c.sequence)).scalars())


def pruner(store: Store, clock: Clock, retention: Retention, kinds: Catalogue | None = None) -> Pruner:
    return Pruner(kinds or catalogue(), session_factory=store.sessions, clock=clock,
                  retention=retention)


def test_an_old_event_still_pending_is_kept_until_its_destination_is_no_longer_pending(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    peer = Failing()
    notify = Consumer("notify", session_factory=store.sessions, destinations={"peer": peer},
                      clock=clock)
    notify.register()
    with store.sessions.begin() as session:
        pending = recorder.record(session, job("j-1", related=(Reference(type="queue", id="q"),)))
    notify.run_cycle()
    clock.advance(MONTH + timedelta(days=1))

    kept = pruner(store, clock, Retention(events=MONTH)).prune()
    peer.failing = False
    notify.run_cycle()
    removed = pruner(store, clock, Retention(events=MONTH)).prune()

    assert kept.removed["events"] == 0
    assert peer.received == ["j-1"]
    assert removed.removed["events"] == 1
    assert sequences(store) == []
    with store.engine.connect() as connection:
        assert connection.execute(select(schema.related)).all() == []
        assert connection.execute(
            select(schema.deliveries).where(schema.deliveries.c.event_sequence == pending.sequence)
        ).all() == []


def test_a_parked_destination_does_not_hold_back_an_event_past_retention(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    peer = Failing()
    notify = Consumer("notify", session_factory=store.sessions, destinations={"peer": peer},
                      clock=clock)
    notify.register()
    notify.park("peer", "operator hold")
    with store.sessions.begin() as session:
        recorder.record(session, job("j-1"))
    notify.run_cycle()
    clock.advance(timedelta(days=10))

    within = pruner(store, clock, Retention(events=MONTH)).prune()
    clock.advance(MONTH)
    past = pruner(store, clock, Retention(events=MONTH)).prune()

    assert within.removed["events"] == 0
    assert past.removed["events"] == 1


def test_a_retired_destination_does_not_hold_back_an_event(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    Consumer("notify", session_factory=store.sessions, destinations={"old": Failing()},
             clock=clock).run_cycle()
    with store.sessions.begin() as session:
        recorder.record(session, job("j-1"))
    Consumer("notify", session_factory=store.sessions, destinations={"old": Failing()},
             clock=clock).run_cycle()
    clock.advance(MONTH + timedelta(days=1))
    held = pruner(store, clock, Retention(events=MONTH)).prune()

    Consumer("notify", session_factory=store.sessions, destinations={}, clock=clock).run_cycle()
    released = pruner(store, clock, Retention(events=MONTH)).prune()

    assert held.removed["events"] == 0
    assert released.removed["events"] == 1


def test_an_event_a_consumer_has_not_read_is_kept(store: Store, recorder: Recorder,
                                                  clock: Clock) -> None:
    notify = Consumer("notify", session_factory=store.sessions, destinations={"peer": Failing()},
                      clock=clock)
    notify.register()
    with store.sessions.begin() as session:
        recorder.record(session, job("j-1"))
    clock.advance(MONTH + timedelta(days=1))

    assert pruner(store, clock, Retention(events=MONTH)).prune().removed["events"] == 0


def test_with_no_retention_every_row_is_kept(store: Store, recorder: Recorder, clock: Clock) -> None:
    with store.sessions.begin() as session:
        recorder.record(session, job("j-1"))
    clock.advance(timedelta(days=3650))

    report = pruner(store, clock, Retention()).prune()

    assert report.removed == {}
    assert sequences(store) == [1]


def test_finished_deliveries_are_pruned_by_their_own_retention(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    peer = Failing()
    peer.failing = False
    notify = Consumer("notify", session_factory=store.sessions, destinations={"peer": peer},
                      clock=clock)
    notify.register()
    with store.sessions.begin() as session:
        recorder.record(session, job("j-1"))
    notify.run_cycle()
    clock.advance(timedelta(days=8))

    report = pruner(store, clock, Retention(events=MONTH, deliveries=timedelta(days=7))).prune()

    assert report.removed == {"events": 0, "deliveries": 1, "retired_destinations": 0}
    assert sequences(store) == [1]


def test_a_retired_destination_with_no_deliveries_left_is_pruned_with_the_deliveries(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    Consumer("notify", session_factory=store.sessions, destinations={"old": Failing()},
             clock=clock).run_cycle()
    with store.sessions.begin() as session:
        recorder.record(session, job("j-1"))
    Consumer("notify", session_factory=store.sessions, destinations={"old": Failing()},
             clock=clock).run_cycle()
    Consumer("notify", session_factory=store.sessions, destinations={}, clock=clock).run_cycle()
    clock.advance(timedelta(days=8))

    report = pruner(store, clock, Retention(deliveries=timedelta(days=7))).prune()

    assert report.removed == {"deliveries": 1, "retired_destinations": 1}
    with store.engine.connect() as connection:
        assert connection.execute(select(schema.destinations)).all() == []


def notices_catalogue() -> Catalogue:
    def write_notice(session: Session, envelope: Envelope) -> None:
        session.execute(text("INSERT INTO notices (event_id, written_at) VALUES (:id, :at)"),
                        {"id": envelope.id,
                         "at": schema.to_stored(envelope.occurred_at).isoformat(" ")})

    return Catalogue([Kind(
        name="jobs.noticed", version=1, severity=Severity.INFO, details=JobDetails,
        summary=lambda draft, details: "noticed",
        hook=RecordHook(write_notice, tables=(PrunedTable("notices", "written_at"),)),
    )])


@pytest.mark.parametrize(("retention", "kept"), [(timedelta(days=7), 0), (None, 1)])
def test_a_hooks_table_is_pruned_by_its_own_retention(
        store: Store, clock: Clock, retention: timedelta | None, kept: int) -> None:
    with store.engine.begin() as connection:
        connection.execute(text("CREATE TABLE notices (event_id VARCHAR, written_at TIMESTAMP)"))
    kinds = notices_catalogue()
    recorder = Recorder(kinds, source=Source(service="s", instance="i"), clock=clock)
    with store.sessions.begin() as session:
        recorder.record(session, kinds.require("jobs.noticed").draft(
            subject=Reference(type="job", id="j-1"), details={"queue": "q"}))
    clock.advance(timedelta(days=8))

    pruner(store, clock, Retention(tables={"notices": retention}), kinds).prune()

    with store.engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM notices")).scalar_one() == kept
    assert sequences(store) == [1]


def test_a_retention_naming_a_table_no_hook_writes_is_refused(store: Store, clock: Clock) -> None:
    with pytest.raises(ValueError, match="retention names reports, which no declared kind's hook"):
        pruner(store, clock, Retention(tables={"reports": None}))
