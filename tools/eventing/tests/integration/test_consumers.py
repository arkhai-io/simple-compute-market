"""Consumers against a real SQLite file: delivery in order and at least once per
destination, park and resume, new and retired destinations, and abandonment to the
finally sink.

Library integration: a consumer through its public API over its store, with the
destinations it is given as the collaborators it does not own.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from sqlalchemy import select

from eventing import (
    ABANDONED,
    ACTIVE,
    DELIVERED,
    PARKED,
    PENDING,
    RETIRED,
    Consumer,
    Envelope,
    ParkDestination,
    Pruner,
    Recorder,
    Retention,
    RetryPolicy,
    Route,
    Routes,
    UnknownDestination,
)
from eventing import schema
from tests.fixtures.kinds import Clock, Store, catalogue, job


class Collect:
    """A destination recording what it receives, failing while `failing` is set."""

    def __init__(self) -> None:
        self.received: list[Envelope] = []
        self.failing: str | None = None
        self.park_with: str | None = None

    def deliver(self, envelope: Envelope) -> None:
        if self.park_with is not None:
            raise ParkDestination(self.park_with)
        if self.failing is not None:
            raise ConnectionError(self.failing)
        self.received.append(envelope)

    @property
    def subjects(self) -> list[str]:
        return [envelope.subject.id for envelope in self.received]


class Stop(BaseException):
    """The process stopping: not an exception a consumer handles."""


class DeliverThenStop(Collect):
    def deliver(self, envelope: Envelope) -> None:
        super().deliver(envelope)
        raise Stop


class Finally:
    """A finally sink keeping each abandoned delivery's destination, subject and error."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    def abandoned(self, *, consumer: str, destination: str, envelope: Envelope,
                  last_error: str | None) -> None:
        self.calls.append((destination, envelope.subject.id, last_error))


def record(store: Store, recorder: Recorder, *job_ids: str) -> list[Envelope]:
    with store.sessions.begin() as session:
        return [recorder.record(session, job(job_id)) for job_id in job_ids]


def delivery(store: Store, consumer: str, destination: str, sequence: int) -> dict[str, object]:
    with store.engine.connect() as connection:
        row = connection.execute(
            select(schema.deliveries).where(
                schema.deliveries.c.consumer == consumer,
                schema.deliveries.c.destination == destination,
                schema.deliveries.c.event_sequence == sequence)
        ).mappings().one()
    return dict(row)


def destination_state(store: Store, consumer: str, destination: str) -> str:
    with store.engine.connect() as connection:
        return str(connection.execute(
            select(schema.destinations.c.state).where(
                schema.destinations.c.consumer == consumer,
                schema.destinations.c.name == destination)
        ).scalar_one())


def consumer(store: Store, clock: Clock, finally_sink: Finally | None = None,
             retry: RetryPolicy | None = None, **destinations: Collect) -> Consumer:
    return Consumer("notify", session_factory=store.sessions, destinations=destinations,
                    clock=clock, retry=retry, finally_sink=finally_sink)


def test_each_destination_receives_every_event_in_sequence_order_under_its_id(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    mail, chat = Collect(), Collect()
    consumer(store, clock, mail=mail, chat=chat).register()
    recorded = record(store, recorder, "j-1", "j-2", "j-3")

    report = consumer(store, clock, mail=mail, chat=chat).run_cycle()

    assert [e.id for e in mail.received] == [e.id for e in recorded]
    assert [e.id for e in chat.received] == [e.id for e in recorded]
    assert (report.read, report.selected, report.delivered) == (3, 6, 6)


def test_a_failing_destination_stays_pending_and_holds_up_no_other(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    mail, chat = Collect(), Collect()
    chat.failing = "connection refused"
    notify = consumer(store, clock, mail=mail, chat=chat)
    notify.register()
    first, second = record(store, recorder, "j-1", "j-2")

    report = notify.run_cycle()

    assert mail.subjects == ["j-1", "j-2"]
    assert chat.received == []
    assert (report.delivered, report.failed) == (2, 1)
    failed = delivery(store, "notify", "chat", first.sequence)
    assert (failed["state"], failed["attempts"]) == (PENDING, 1)
    assert failed["last_error"] == "ConnectionError: connection refused"
    assert delivery(store, "notify", "chat", second.sequence)["attempts"] == 0
    assert delivery(store, "notify", "mail", first.sequence)["state"] == DELIVERED

    # Not retried before its backoff; delivered, in order, once it is due.
    chat.failing = None
    notify.run_cycle()
    assert chat.received == []
    clock.advance(timedelta(seconds=10))
    notify.run_cycle()
    assert chat.subjects == ["j-1", "j-2"]
    assert delivery(store, "notify", "chat", first.sequence)["attempts"] == 2


def test_an_event_delivered_before_the_process_stopped_is_delivered_again_under_its_id(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    stopping = DeliverThenStop()
    consumer(store, clock, peer=stopping).register()
    (recorded,) = record(store, recorder, "j-1")

    with pytest.raises(Stop):
        consumer(store, clock, peer=stopping).run_cycle()
    assert delivery(store, "notify", "peer", recorded.sequence)["state"] == PENDING

    restarted = Collect()
    consumer(store, clock, peer=restarted).run_cycle()

    assert [e.id for e in stopping.received] == [recorded.id]
    assert [e.id for e in restarted.received] == [recorded.id]
    assert delivery(store, "notify", "peer", recorded.sequence)["state"] == DELIVERED


def test_a_parked_destination_receives_nothing_until_resumed_then_receives_in_order(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    peer, other = Collect(), Collect()
    notify = consumer(store, clock, peer=peer, other=other)
    notify.register()
    notify.park("peer", "operator hold")
    record(store, recorder, "j-1", "j-2")

    notify.run_cycle()
    assert peer.received == []
    assert other.subjects == ["j-1", "j-2"]
    assert destination_state(store, "notify", "peer") == PARKED

    notify.resume("peer")
    notify.run_cycle()

    assert peer.subjects == ["j-1", "j-2"]


def test_a_destination_answering_unsupported_parks_itself_until_resumed(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    peer = Collect()
    peer.park_with = "unsupported"
    notify = consumer(store, clock, peer=peer)
    notify.register()
    first, _ = record(store, recorder, "j-1", "j-2")

    report = notify.run_cycle()
    peer.park_with = None
    clock.advance(timedelta(hours=2))
    notify.run_cycle()

    assert report.parked == ["peer"]
    assert peer.received == []
    assert destination_state(store, "notify", "peer") == PARKED
    assert delivery(store, "notify", "peer", first.sequence)["last_error"] == "unsupported"

    notify.resume("peer")
    notify.run_cycle()
    assert peer.subjects == ["j-1", "j-2"]


def test_a_destination_resumed_after_retention_receives_only_what_is_still_retained(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    peer = Collect()
    notify = consumer(store, clock, peer=peer)
    notify.register()
    notify.park("peer", "operator hold")
    record(store, recorder, "j-1")
    notify.run_cycle()
    clock.advance(timedelta(days=31))
    record(store, recorder, "j-2")
    notify.run_cycle()

    pruned = Pruner(catalogue(), session_factory=store.sessions, clock=clock,
                    retention=Retention(events=timedelta(days=30))).prune()
    notify.resume("peer")
    notify.run_cycle()

    assert pruned.removed["events"] == 1
    assert peer.subjects == ["j-2"]


def test_a_destination_removed_from_the_configuration_is_retired_to_the_finally_sink(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    old, new = Collect(), Collect()
    old.failing = "gone"
    finally_sink = Finally()
    consumer(store, clock, finally_sink, old=old).run_cycle()
    first, second = record(store, recorder, "j-1", "j-2")
    consumer(store, clock, finally_sink, old=old).run_cycle()

    report = consumer(store, clock, finally_sink, new=new).run_cycle()
    old.failing = None
    consumer(store, clock, finally_sink, new=new).run_cycle()

    assert report.retired == ["old"]
    assert destination_state(store, "notify", "old") == RETIRED
    assert finally_sink.calls == [("old", "j-1", "ConnectionError: gone"),
                                      ("old", "j-2", "destination retired: not configured")]
    assert old.received == []
    for recorded in (first, second):
        assert delivery(store, "notify", "old", recorded.sequence)["state"] == ABANDONED
    assert new.received == []


def test_parking_a_destination_the_consumer_does_not_have_is_refused(
        store: Store, clock: Clock) -> None:
    notify = consumer(store, clock, peer=Collect())
    notify.register()

    with pytest.raises(UnknownDestination, match="consumer notify has no destination chat"):
        notify.park("chat", "hold")


def test_a_retired_destination_configured_again_starts_at_the_current_position(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    peer = Collect()
    consumer(store, clock, peer=peer).run_cycle()
    consumer(store, clock).run_cycle()
    record(store, recorder, "j-1")
    consumer(store, clock).run_cycle()

    consumer(store, clock, peer=peer).run_cycle()
    record(store, recorder, "j-2")
    consumer(store, clock, peer=peer).run_cycle()

    assert destination_state(store, "notify", "peer") == ACTIVE
    assert peer.subjects == ["j-2"]


def test_a_failing_finally_sink_leaves_the_destination_to_retire_again(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    class Refusing(Finally):
        def abandoned(self, *, consumer: str, destination: str, envelope: Envelope,
                      last_error: str | None) -> None:
            raise OSError("log unwritable")

    old = Collect()
    old.failing = "gone"
    consumer(store, clock, old=old).run_cycle()
    (recorded,) = record(store, recorder, "j-1")
    consumer(store, clock, old=old).run_cycle()

    with pytest.raises(OSError, match="log unwritable"):
        consumer(store, clock, Refusing()).run_cycle()
    assert destination_state(store, "notify", "old") == ACTIVE
    assert delivery(store, "notify", "old", recorded.sequence)["state"] == PENDING

    finally_sink = Finally()
    consumer(store, clock, finally_sink).run_cycle()
    assert destination_state(store, "notify", "old") == RETIRED
    assert finally_sink.calls == [("old", "j-1", "ConnectionError: gone")]


def test_a_destination_added_receives_no_event_recorded_before_it(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    mail, chat = Collect(), Collect()
    consumer(store, clock, mail=mail).run_cycle()
    record(store, recorder, "j-1")
    consumer(store, clock, mail=mail).run_cycle()

    consumer(store, clock, mail=mail, chat=chat).run_cycle()
    record(store, recorder, "j-2")
    consumer(store, clock, mail=mail, chat=chat).run_cycle()

    assert mail.subjects == ["j-1", "j-2"]
    assert chat.subjects == ["j-2"]


def test_a_new_consumer_starts_after_the_events_already_recorded(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    record(store, recorder, "j-1")
    late = Collect()

    consumer(store, clock, late=late).run_cycle()
    record(store, recorder, "j-2")
    consumer(store, clock, late=late).run_cycle()

    assert late.subjects == ["j-2"]


def test_a_selection_sends_each_event_only_where_it_names(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    mail, chat = Collect(), Collect()

    def by_subject(envelope: Envelope) -> set[str]:
        return {"mail"} if envelope.subject.id == "j-1" else {"chat", "unknown"}

    def notify() -> Consumer:
        return Consumer("notify", session_factory=store.sessions, clock=clock,
                        destinations={"mail": mail, "chat": chat}, select=by_subject)

    notify().register()
    record(store, recorder, "j-1", "j-2")
    notify().run_cycle()

    assert mail.subjects == ["j-1"]
    assert chat.subjects == ["j-2"]


def test_an_event_a_route_selects_is_delivered_to_its_destinations_and_no_other(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    ops, audit = Collect(), Collect()
    routes = Routes([Route("long-jobs", "kind = 'jobs.finished' AND duration_seconds >= 1800",
                           ("ops",))], catalogue(), enabled={"ops", "audit"})

    def notify() -> Consumer:
        return Consumer("notify", session_factory=store.sessions, clock=clock,
                        destinations={"ops": ops, "audit": audit}, select=routes.select)

    notify().register()
    with store.sessions.begin() as session:
        recorder.record(session, job("j-long", duration=2832))
        recorder.record(session, job("j-short", duration=40))
    notify().run_cycle()

    assert ops.subjects == ["j-long"]
    assert audit.received == []


def test_a_destination_failing_past_the_maximum_age_is_abandoned_with_its_last_error(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    sink, finally_sink = Collect(), Finally()
    sink.failing = "503 from sink"
    policy = RetryPolicy(initial=timedelta(minutes=10), maximum=timedelta(hours=1),
                         max_age=timedelta(days=1))
    notify = consumer(store, clock, finally_sink, policy, ops=sink)
    notify.register()
    first, second = record(store, recorder, "j-1", "j-2")

    notify.run_cycle()
    clock.advance(timedelta(hours=23))
    notify.run_cycle()
    assert finally_sink.calls == []

    clock.advance(timedelta(hours=1))
    report = notify.run_cycle()

    assert report.abandoned == 2
    assert finally_sink.calls == [("ops", "j-1", "ConnectionError: 503 from sink"),
                                      ("ops", "j-2", "ConnectionError: 503 from sink")]
    abandoned = delivery(store, "notify", "ops", first.sequence)
    assert (abandoned["state"], abandoned["attempts"]) == (ABANDONED, 3)
    assert abandoned["last_error"] == "ConnectionError: 503 from sink"
    assert delivery(store, "notify", "ops", second.sequence)["state"] == ABANDONED


def test_with_no_maximum_age_a_failing_delivery_is_retried_without_limit(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    peer, finally_sink = Collect(), Finally()
    peer.failing = "timeout"
    notify = consumer(store, clock, finally_sink, RetryPolicy(maximum=timedelta(hours=1)), peer=peer)
    notify.register()
    (recorded,) = record(store, recorder, "j-1")

    for _ in range(5):
        notify.run_cycle()
        clock.advance(timedelta(days=10))

    assert finally_sink.calls == []
    assert delivery(store, "notify", "peer", recorded.sequence)["state"] == PENDING


def test_the_default_finally_sink_logs_the_abandoned_event(
        store: Store, recorder: Recorder, clock: Clock, caplog: pytest.LogCaptureFixture) -> None:
    sink = Collect()
    sink.failing = "down"
    notify = Consumer("notify", session_factory=store.sessions, destinations={"ops": sink},
                      clock=clock, retry=RetryPolicy(max_age=timedelta(0)))
    notify.register()
    (recorded,) = record(store, recorder, "j-1")

    with caplog.at_level(logging.WARNING, logger="eventing.finally"):
        notify.run_cycle()

    (logged,) = [r for r in caplog.records if r.name == "eventing.finally"]
    assert recorded.id in logged.getMessage()
    assert "ConnectionError: down" in logged.getMessage()
