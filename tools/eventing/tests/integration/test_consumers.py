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
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from eventing import (
    ABANDONED,
    ACTIVE,
    DELIVERED,
    PARKED,
    PENDING,
    RETIRED,
    AbandonDelivery,
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


def test_a_destination_added_while_an_event_is_unread_receives_no_event_before_it(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    mail, chat = Collect(), Collect()
    consumer(store, clock, mail=mail).run_cycle()
    record(store, recorder, "j-1")

    consumer(store, clock, mail=mail, chat=chat).run_cycle()
    record(store, recorder, "j-2")
    consumer(store, clock, mail=mail, chat=chat).run_cycle()

    assert mail.subjects == ["j-1", "j-2"]
    assert chat.subjects == ["j-2"]


def test_a_destination_replaced_while_an_event_is_unread_hands_it_to_the_finally_sink(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    old, new = Collect(), Collect()
    finally_sink = Finally()
    consumer(store, clock, finally_sink, old=old).run_cycle()
    (unread,) = record(store, recorder, "j-1")

    report = consumer(store, clock, finally_sink, new=new).run_cycle()
    record(store, recorder, "j-2")
    consumer(store, clock, finally_sink, new=new).run_cycle()

    assert report.retired == ["old"]
    assert finally_sink.calls == [("old", "j-1", "destination retired: not configured")]
    assert delivery(store, "notify", "old", unread.sequence)["state"] == ABANDONED
    assert old.received == []
    assert new.subjects == ["j-2"]


def test_the_destinations_a_consumer_is_first_registered_with_start_at_its_position(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    peer = Collect()
    consumer(store, clock).run_cycle()
    record(store, recorder, "j-1")

    consumer(store, clock, peer=peer).run_cycle()

    assert peer.subjects == ["j-1"]


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

    def by_subject(envelope: Envelope, candidates: frozenset[str]) -> set[str]:
        assert candidates == {"mail", "chat"}
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


def test_a_delivery_its_destination_refuses_is_abandoned_and_the_next_follows(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    class Refusing(Collect):
        def deliver(self, envelope: Envelope) -> None:
            if envelope.subject.id == "j-1":
                raise AbandonDelivery("refused: HTTP 404")
            super().deliver(envelope)

    peer = Refusing()
    finally_sink = Finally()
    consumer(store, clock, finally_sink, peer=peer).register()
    refused, _ = record(store, recorder, "j-1", "j-2")

    report = consumer(store, clock, finally_sink, peer=peer).run_cycle()

    assert (report.abandoned, report.delivered, report.parked) == (1, 1, [])
    assert peer.subjects == ["j-2"]
    assert finally_sink.calls == [("peer", "j-1", "refused: HTTP 404")]
    row = delivery(store, "notify", "peer", refused.sequence)
    assert (row["state"], row["attempts"], row["last_error"]) == (ABANDONED, 1, "refused: HTTP 404")
    assert destination_state(store, "notify", "peer") == ACTIVE


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


# One runner at a time. Each runner below has its own engine and sessions over the
# store's file, as a second process would.


@pytest.fixture
def other_sessions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'events.db'}")
    try:
        yield sessionmaker(engine, expire_on_commit=False)
    finally:
        engine.dispose()


class Overlapping(Collect):
    """A destination that, while it delivers the first event, runs `meanwhile` —
    another runner's cycle — before returning."""

    def __init__(self, meanwhile) -> None:
        super().__init__()
        self.meanwhile = meanwhile
        self.reports: list[object] = []

    def deliver(self, envelope: Envelope) -> None:
        if not self.reports:
            self.reports.append(self.meanwhile())
        super().deliver(envelope)


def holder(store: Store) -> tuple[str | None, object]:
    with store.engine.connect() as connection:
        row = connection.execute(
            select(schema.consumers.c.held_by, schema.consumers.c.held_until)
            .where(schema.consumers.c.name == "notify")
        ).one()
    return row.held_by, row.held_until


def test_a_second_runner_delivers_nothing_while_the_first_holds_the_consumer(
        store: Store, recorder: Recorder, clock: Clock, other_sessions) -> None:
    second_peer = Collect()
    second = Consumer("notify", session_factory=other_sessions, clock=clock,
                      destinations={"peer": second_peer})
    first_peer = Overlapping(second.run_cycle)
    first = Consumer("notify", session_factory=store.sessions, clock=clock,
                     destinations={"peer": first_peer})
    first.register()
    events = record(store, recorder, "j-1", "j-2")

    report = first.run_cycle()

    assert second_peer.received == []
    assert first_peer.subjects == ["j-1", "j-2"]
    (meanwhile,) = first_peer.reports
    assert meanwhile.held_elsewhere and meanwhile.delivered == 0 and meanwhile.read == 0
    assert (report.delivered, report.held_elsewhere) == (2, False)
    assert [delivery(store, "notify", "peer", e.sequence)["attempts"] for e in events] == [1, 1]
    # The cycle released the consumer, so the second runner takes it at once.
    assert holder(store) == (None, None)
    assert not second.run_cycle().held_elsewhere


class Raising(Collect):
    """A destination raising `error` once `meanwhile` — another runner's cycle — has
    run inside its first delivery."""

    def __init__(self, meanwhile, error: Exception | None) -> None:
        super().__init__()
        self.meanwhile = meanwhile
        self.error = error
        self.reports: list[object] = []

    def deliver(self, envelope: Envelope) -> None:
        if not self.reports:
            self.reports.append(self.meanwhile())
            if self.error is not None:
                raise self.error
        super().deliver(envelope)


@pytest.mark.parametrize(
    "error",
    [None, ConnectionError("refused"), ParkDestination("unsupported")],
    ids=["delivered", "failed", "parked"],
)
def test_a_runner_whose_hold_lapsed_applies_no_outcome(
        store: Store, recorder: Recorder, clock: Clock, other_sessions, error) -> None:
    """The hold lapses while the first runner is inside a destination's call: the
    second runner takes the consumer, fails the first event and delivers nothing
    more, and the first runner's outcome — delivered, failed or parked — is
    discarded and it stops. The stored delivery keeps the
    second runner's failure."""
    second_peer = Collect()
    second_peer.failing = "second runner's failure"
    second = Consumer("notify", session_factory=other_sessions, clock=clock,
                      destinations={"peer": second_peer}, hold=timedelta(minutes=1))

    def lapse_then_second_cycle() -> object:
        clock.advance(timedelta(minutes=2))
        return second.run_cycle()

    first_finally = Finally()
    first_peer = Raising(lapse_then_second_cycle, error)
    first = Consumer("notify", session_factory=store.sessions, clock=clock,
                     destinations={"peer": first_peer}, hold=timedelta(minutes=1),
                     finally_sink=first_finally)
    first.register()
    events = record(store, recorder, "j-1", "j-2")

    report = first.run_cycle()

    (meanwhile,) = first_peer.reports
    assert (meanwhile.failed, meanwhile.held_elsewhere) == (1, False)
    assert (report.delivered, report.failed, report.abandoned, report.parked,
            report.held_elsewhere) == (0, 0, 0, [], True)
    assert first_finally.calls == []
    assert destination_state(store, "notify", "peer") == ACTIVE
    head = delivery(store, "notify", "peer", events[0].sequence)
    assert (head["state"], head["attempts"], head["last_error"]) == (
        PENDING, 1, "ConnectionError: second runner's failure")
    assert delivery(store, "notify", "peer", events[1].sequence)["attempts"] == 0
    assert holder(store) == (None, None)


def test_a_runner_whose_hold_lapsed_abandons_nothing(
        store: Store, recorder: Recorder, clock: Clock, other_sessions) -> None:
    """A delivery already past the first runner's maximum age fails again while its
    hold lapses and the second runner takes the consumer: the first runner, which
    would abandon it, abandons nothing and hands nothing to its finally sink."""
    second_peer = Collect()
    second_peer.failing = "second runner's failure"
    second = Consumer("notify", session_factory=other_sessions, clock=clock,
                      destinations={"peer": second_peer}, hold=timedelta(minutes=1))

    def lapse_then_second_cycle() -> object:
        clock.advance(timedelta(minutes=2))
        return second.run_cycle()

    first_finally = Finally()
    first_peer = Raising(lapse_then_second_cycle, ConnectionError("refused"))
    first = Consumer("notify", session_factory=store.sessions, clock=clock,
                     destinations={"peer": first_peer}, hold=timedelta(minutes=1),
                     retry=RetryPolicy(max_age=timedelta(minutes=1)),
                     finally_sink=first_finally)
    first.register()
    (event_1,) = record(store, recorder, "j-1")
    first_peer.reports.append("an earlier cycle")  # its first attempt just fails
    first_peer.failing = "first attempt"
    assert first.run_cycle().failed == 1
    first_peer.failing = None
    first_peer.reports.clear()
    clock.advance(timedelta(seconds=90))  # past the maximum age, and the backoff

    report = first.run_cycle()

    (meanwhile,) = first_peer.reports
    assert (meanwhile.failed, meanwhile.held_elsewhere) == (1, False)
    assert (report.abandoned, report.failed, report.held_elsewhere) == (0, 0, True)
    assert first_finally.calls == []
    row = delivery(store, "notify", "peer", event_1.sequence)
    assert (row["state"], row["attempts"], row["last_error"]) == (
        PENDING, 2, "ConnectionError: second runner's failure")


def test_a_cycle_started_while_the_same_instance_runs_one_does_nothing(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    """A manual cycle beside the timer's, on one instance and so one runner
    identity, is kept apart by the instance itself."""
    peer = Overlapping(lambda: same.run_cycle())
    same = Consumer("notify", session_factory=store.sessions, clock=clock,
                    destinations={"peer": peer}, runner="pod-0")
    same.register()
    record(store, recorder, "j-1", "j-2")

    report = same.run_cycle()

    (meanwhile,) = peer.reports
    assert (meanwhile.held_elsewhere, meanwhile.delivered) == (True, 0)
    assert peer.subjects == ["j-1", "j-2"]
    assert report.delivered == 2


def test_a_runner_registering_a_consumer_another_registered_first_does_nothing(
        store: Store, recorder: Recorder, clock: Clock, tmp_path) -> None:
    """Two runners find the consumer unregistered; the second one's registration
    commits first, so the first's is refused by the consumer's key."""
    record(store, recorder, "j-0")
    other_engine = create_engine(f"sqlite:///{tmp_path / 'events.db'}")
    second_peer = Collect()
    second = Consumer("notify", session_factory=sessionmaker(other_engine), clock=clock,
                      destinations={"peer": second_peer})
    interleaved: list[object] = []

    def second_registers_first(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO eventing_consumers") and not interleaved:
            interleaved.append(second.run_cycle())

    first_peer = Collect()
    first = Consumer("notify", session_factory=store.sessions, clock=clock,
                     destinations={"peer": first_peer})
    event.listen(store.engine, "before_cursor_execute", second_registers_first)
    try:
        report = first.run_cycle()
    finally:
        event.remove(store.engine, "before_cursor_execute", second_registers_first)
        other_engine.dispose()

    (meanwhile,) = interleaved
    assert meanwhile.held_elsewhere is False
    assert report.held_elsewhere is True
    assert holder(store) == (None, None)
    record(store, recorder, "j-1")
    assert first.run_cycle().delivered == 1
    assert first_peer.subjects == ["j-1"]


def test_a_stopped_runners_hold_keeps_others_out_until_it_lapses(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    peer = Collect()
    record(store, recorder, "j-0")
    Consumer("notify", session_factory=store.sessions, clock=clock,
             destinations={"peer": Collect()}, runner="pod-0").register()
    record(store, recorder, "j-1")
    with store.sessions.begin() as session:  # the process stopped holding it
        session.execute(
            schema.consumers.update().values(
                held_by="pod-0", held_until=schema.to_stored(clock() + timedelta(minutes=5))))
    other = Consumer("notify", session_factory=store.sessions, clock=clock,
                     destinations={"peer": peer}, runner="pod-1")

    assert other.run_cycle().held_elsewhere
    clock.advance(timedelta(minutes=4))
    assert other.run_cycle().held_elsewhere
    assert peer.received == []

    # The same runner identity, restarted, takes its own hold back at once.
    restarted_peer = Collect()
    restarted = Consumer("notify", session_factory=store.sessions, clock=clock,
                         destinations={"peer": restarted_peer}, runner="pod-0")
    assert restarted.run_cycle().delivered == 1
    assert restarted_peer.subjects == ["j-1"]

    with store.sessions.begin() as session:
        session.execute(
            schema.consumers.update().values(
                held_by="pod-0", held_until=schema.to_stored(clock() + timedelta(minutes=5))))
    record(store, recorder, "j-2")
    clock.advance(timedelta(minutes=5))  # lapsed
    assert other.run_cycle().delivered == 1
    assert peer.subjects == ["j-2"]
