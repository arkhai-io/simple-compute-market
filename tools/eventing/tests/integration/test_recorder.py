"""The recorder against a real SQLite file: an event commits and rolls back with its
producer's transaction, a hook runs inside it, an occurrence is written once, and
no event commits below one already visible.

Library integration: the recorder through its public API, on sessions of its own
store's engine, with the schema the steps build.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from eventing import (
    Catalogue,
    Consumer,
    Envelope,
    EventRefused,
    Kind,
    PrunedTable,
    Recorder,
    RecordHook,
    Reference,
    Severity,
    Source,
)
from eventing import schema
from tests.fixtures.kinds import (
    JOB_FINISHED,
    NOTE_ADDED,
    SHIPMENT_DELAYED,
    Clock,
    JobDetails,
    Store,
    job,
)


def create_jobs_table(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE jobs (id VARCHAR PRIMARY KEY, status VARCHAR)"))
        connection.execute(text("CREATE TABLE notices (event_id VARCHAR, written_at TIMESTAMP)"))


def count(store: Store, table: str) -> int:
    with store.engine.connect() as connection:
        return int(connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())


def finish_job(session: Session, job_id: str) -> None:
    session.execute(text("INSERT INTO jobs (id, status) VALUES (:id, 'finished')"), {"id": job_id})


def test_an_event_commits_with_its_producers_state_change(store: Store, recorder: Recorder) -> None:
    create_jobs_table(store.engine)

    with store.sessions.begin() as session:
        finish_job(session, "j-1")
        recorded = recorder.record(session, job("j-1", related=(Reference(type="queue", id="q"),)))

    assert count(store, "jobs") == 1
    assert recorded.sequence == 1
    assert recorded.severity is Severity.INFO
    assert recorded.summary == "Job j-1 finished on default."
    assert recorded.data_schema == "urn:event:jobs.finished:1"
    with store.engine.connect() as connection:
        stored = connection.execute(select(schema.events.c.envelope)).scalar_one()
        references = connection.execute(select(schema.related.c.type, schema.related.c.id)).all()
    assert Envelope.from_json(stored) == recorded
    assert references == [("queue", "q")]


def test_a_rolled_back_transaction_leaves_no_event_and_no_consumer_receives_one(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    create_jobs_table(store.engine)
    received: list[Envelope] = []

    class Collect:
        def deliver(self, envelope: Envelope) -> None:
            received.append(envelope)

    consumer = Consumer("audit", session_factory=store.sessions, destinations={"log": Collect()},
                        clock=clock)
    consumer.register()

    with pytest.raises(RuntimeError, match="later step failed"):
        with store.sessions.begin() as session:
            finish_job(session, "j-1")
            recorder.record(session, job("j-1"))
            raise RuntimeError("later step failed")
    consumer.run_cycle()

    assert count(store, "jobs") == 0
    assert count(store, "eventing_events") == 0
    assert received == []


def hooked_catalogue(hook: Callable[[Session, Envelope], None]) -> Catalogue:
    return Catalogue([Kind(
        name="jobs.noticed", version=1, severity=Severity.INFO, details=JobDetails,
        summary=lambda draft, details: "noticed", dedup_key=("subject",),
        hook=RecordHook(hook, tables=(PrunedTable("notices", "written_at"),)),
    )])


def noticed(job_id: str) -> object:
    return hooked_catalogue(lambda s, e: None).require("jobs.noticed").draft(
        subject=Reference(type="job", id=job_id), details={"queue": "q"})


def test_a_hook_writes_in_the_recording_transaction(store: Store, clock: Clock) -> None:
    create_jobs_table(store.engine)

    def write_notice(session: Session, envelope: Envelope) -> None:
        session.execute(text("INSERT INTO notices (event_id, written_at) VALUES (:id, :at)"),
                        {"id": envelope.id, "at": schema.to_stored(envelope.occurred_at).isoformat(" ")})

    recorder = Recorder(hooked_catalogue(write_notice), source=Source(service="s", instance="i"),
                        clock=clock)
    with store.sessions.begin() as session:
        recorded = recorder.record(session, noticed("j-1"))  # type: ignore[arg-type]

    with store.engine.connect() as connection:
        assert connection.execute(text("SELECT event_id FROM notices")).scalar_one() == recorded.id


def test_a_failing_hook_rolls_back_the_producers_state_change(store: Store, clock: Clock) -> None:
    create_jobs_table(store.engine)

    def refuse(session: Session, envelope: Envelope) -> None:
        raise ValueError("the notice cannot be signed")

    recorder = Recorder(hooked_catalogue(refuse), source=Source(service="s", instance="i"),
                        clock=clock)
    with pytest.raises(ValueError, match="cannot be signed"):
        with store.sessions.begin() as session:
            finish_job(session, "j-1")
            recorder.record(session, noticed("j-1"))  # type: ignore[arg-type]

    assert count(store, "jobs") == 0
    assert count(store, "eventing_events") == 0


def test_a_repeated_occurrence_returns_the_existing_event_and_writes_nothing(
        store: Store, clock: Clock) -> None:
    calls: list[str] = []
    recorder = Recorder(hooked_catalogue(lambda s, e: calls.append(e.id)),
                        source=Source(service="s", instance="i"), clock=clock)

    with store.sessions.begin() as session:
        first = recorder.record(session, noticed("j-1"))  # type: ignore[arg-type]
    with store.sessions.begin() as session:
        again = recorder.record(session, noticed("j-1"))  # type: ignore[arg-type]
        other = recorder.record(session, noticed("j-2"))  # type: ignore[arg-type]

    assert again == first
    assert other.id != first.id
    assert count(store, "eventing_events") == 2
    assert calls == [first.id, other.id]


def test_occurrences_differing_in_a_key_field_are_both_written(store: Store, recorder: Recorder) -> None:
    def delayed(attempt: int) -> object:
        return SHIPMENT_DELAYED.draft(subject=Reference(type="shipment", id="sh-1"),
                                      details={"reason": "fog", "attempt": attempt})

    with store.sessions.begin() as session:
        recorder.record(session, delayed(1))  # type: ignore[arg-type]
        recorder.record(session, delayed(2))  # type: ignore[arg-type]
        recorder.record(session, delayed(1))  # type: ignore[arg-type]

    assert count(store, "eventing_events") == 2


def test_a_kind_with_no_dedup_key_writes_every_event(store: Store, recorder: Recorder) -> None:
    draft = NOTE_ADDED.draft(subject=Reference(type="note", id="n-1"), details={"queue": "q"})

    with store.sessions.begin() as session:
        recorder.record(session, draft)
        recorder.record(session, draft)

    assert count(store, "eventing_events") == 2


@pytest.mark.parametrize("draft", [
    JOB_FINISHED.draft(subject=Reference(type="job", id="j"), details={"queue": "q"},
                       attributes={"duration_seconds": "long"}),
    JOB_FINISHED.draft(subject=Reference(type="job", id="j"), details={"lane": "q"}),
    NOTE_ADDED.draft(subject=Reference(type="job", id="j"), details={"queue": "q"}),
])
def test_a_refused_draft_writes_nothing(store: Store, clock: Clock, draft: object) -> None:
    # The note kind is not in this recorder's catalogue.
    recorder = Recorder(Catalogue([JOB_FINISHED]), source=Source(service="s", instance="i"),
                        clock=clock)

    with pytest.raises(EventRefused):
        with store.sessions.begin() as session:
            recorder.record(session, draft)  # type: ignore[arg-type]

    assert count(store, "eventing_events") == 0
    with store.engine.connect() as connection:
        assert connection.execute(select(func.max(schema.events.c.sequence))).scalar_one() is None


def test_no_second_recording_allocates_while_a_first_holds_the_counter(
        store: Store, recorder: Recorder, clock: Clock, tmp_path: Path) -> None:
    # A second producer whose database will not wait is refused while the first
    # transaction holds its allocation, and records after it commits, above it: no
    # event can commit with a lower sequence than one already visible.
    impatient_engine = create_engine(f"sqlite:///{tmp_path / 'events.db'}",
                                     connect_args={"timeout": 0})
    impatient = sessionmaker(impatient_engine)
    received: list[str] = []

    class Collect:
        def deliver(self, envelope: Envelope) -> None:
            received.append(envelope.subject.id)

    consumer = Consumer("audit", session_factory=store.sessions, destinations={"log": Collect()},
                        clock=clock)
    consumer.register()
    try:
        with store.sessions.begin() as first:
            first_event = recorder.record(first, job("j-1"))
            with pytest.raises(OperationalError, match="locked"):
                with impatient.begin() as second:
                    recorder.record(second, job("j-2"))
            consumer.run_cycle()  # nothing is committed yet
            assert received == []
        with impatient.begin() as second:
            second_event = recorder.record(second, job("j-2"))
    finally:
        impatient_engine.dispose()
    consumer.run_cycle()

    assert second_event.sequence > first_event.sequence
    assert received == ["j-1", "j-2"]


def test_an_extension_is_kept_in_what_is_stored_and_delivered(
        store: Store, recorder: Recorder, clock: Clock) -> None:
    extension = {"vendor.trace": {"span": "a1", "flags": [1, 2]}}
    received: list[Envelope] = []

    class Collect:
        def deliver(self, envelope: Envelope) -> None:
            received.append(envelope)

    consumer = Consumer("audit", session_factory=store.sessions, destinations={"log": Collect()},
                        clock=clock)
    consumer.register()
    draft = JOB_FINISHED.draft(subject=Reference(type="job", id="j-1"), details={"queue": "q"},
                               extensions=extension)
    with store.sessions.begin() as session:
        recorder.record(session, draft)
    consumer.run_cycle()

    with store.engine.connect() as connection:
        stored = Envelope.from_json(connection.execute(select(schema.events.c.envelope)).scalar_one())
    assert stored.extensions == extension
    assert [envelope.extensions for envelope in received] == [extension]
