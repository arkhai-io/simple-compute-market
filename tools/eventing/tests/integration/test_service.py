"""The read and status service against a real SQLite file: events by kind, severity,
subject and reference, in sequence order; each destination's delivery state; and
resuming a parked destination.

Library integration: the framework-free service over a store a recorder and
consumers wrote; no web framework is involved.
"""

from __future__ import annotations

import pytest

from eventing import Consumer, Envelope, EventService, EventServiceError, Recorder, Reference
from tests.fixtures.kinds import SHIPMENT_DELAYED, Clock, Store, job


class Failing:
    def deliver(self, envelope: Envelope) -> None:
        raise ConnectionError("refused")


class Collect:
    def deliver(self, envelope: Envelope) -> None:
        pass


@pytest.fixture
def service(store: Store, clock: Clock) -> EventService:
    return EventService(store.sessions, clock=clock)


def record_mixed(store: Store, recorder: Recorder) -> None:
    depot = Reference(type="depot", id="d-02")
    with store.sessions.begin() as session:
        recorder.record(session, job("j-1", related=(depot,)))
        recorder.record(session, SHIPMENT_DELAYED.draft(
            subject=Reference(type="shipment", id="sh-1"), details={"reason": "fog", "attempt": 1},
            related=[depot, Reference(type="order", id="o-1")]))
        recorder.record(session, job("j-2"))


def subjects(answer: dict[str, object]) -> list[str]:
    return [event["subject"]["id"] for event in answer["events"]]  # type: ignore[attr-defined, index]


def test_events_are_listed_in_sequence_order_by_each_filter(
        service: EventService, store: Store, recorder: Recorder) -> None:
    record_mixed(store, recorder)

    assert subjects(service.list_events()) == ["j-1", "sh-1", "j-2"]
    assert subjects(service.list_events(kind="jobs.finished")) == ["j-1", "j-2"]
    assert subjects(service.list_events(severity="action_required")) == ["sh-1"]
    assert subjects(service.list_events(subject="job:j-2")) == ["j-2"]
    assert subjects(service.list_events(reference="depot:d-02")) == ["j-1", "sh-1"]
    assert subjects(service.list_events(reference="depot:d-02", kind="jobs.finished")) == ["j-1"]
    assert subjects(service.list_events(reference="order:o-9")) == []


def test_events_are_paged_after_a_sequence(service: EventService, store: Store,
                                           recorder: Recorder) -> None:
    record_mixed(store, recorder)

    page = service.list_events(limit=2)
    rest = service.list_events(after=page["next_after"], limit=2)

    assert subjects(page) == ["j-1", "sh-1"]
    assert page["next_after"] == 2
    assert subjects(rest) == ["j-2"]
    assert rest["next_after"] is None


def test_a_listed_event_is_its_whole_envelope(service: EventService, store: Store,
                                              recorder: Recorder) -> None:
    record_mixed(store, recorder)

    (event,) = service.list_events(subject="shipment:sh-1")["events"]

    assert event["kind"] == "orders.shipment_delayed"
    assert event["related"] == [{"type": "depot", "id": "d-02"}, {"type": "order", "id": "o-1"}]
    assert event["occurred_at"] == "2026-11-25T17:00:00Z"
    assert event["details"] == {"reason": "fog", "attempt": 1}


def test_each_destination_shows_its_state_and_its_deliveries(
        service: EventService, store: Store, recorder: Recorder, clock: Clock) -> None:
    notify = Consumer("notify", session_factory=store.sessions, clock=clock,
                      destinations={"chat": Failing(), "mail": Collect()})
    notify.register()
    record_mixed(store, recorder)
    notify.run_cycle()

    destinations = service.deliveries()["destinations"]

    assert [(d["consumer"], d["destination"], d["state"]) for d in destinations] == [
        ("notify", "chat", "active"), ("notify", "mail", "active")]
    chat, mail = destinations
    assert (chat["pending"], chat["delivered"], chat["consumer_position"]) == (3, 0, 3)
    assert chat["head"] == {"sequence": 1, "attempts": 1, "last_error": "ConnectionError: refused",
                            "next_attempt_at": "2026-11-25T17:00:10Z"}
    assert (mail["pending"], mail["delivered"], mail["head"]) == (0, 3, None)


def test_a_parked_destination_is_resumed(service: EventService, store: Store, clock: Clock) -> None:
    notify = Consumer("notify", session_factory=store.sessions, clock=clock,
                      destinations={"peer": Collect()})
    notify.register()
    notify.park("peer", "unsupported")

    parked = service.deliveries()["destinations"][0]
    answer = service.resume("peer")

    assert (parked["state"], parked["state_reason"]) == ("parked", "unsupported")
    assert answer == {"consumer": "notify", "destination": "peer", "state": "active"}
    assert service.deliveries()["destinations"][0]["state"] == "active"


def test_resuming_an_active_destination_answers_it_as_it_is(
        service: EventService, store: Store, clock: Clock) -> None:
    Consumer("notify", session_factory=store.sessions, clock=clock,
             destinations={"peer": Collect()}).register()

    assert service.resume("peer") == {"consumer": "notify", "destination": "peer",
                                      "state": "active"}
    assert service.deliveries()["destinations"][0]["state"] == "active"


def test_resuming_an_unknown_destination_is_refused(service: EventService) -> None:
    with pytest.raises(EventServiceError) as refused:
        service.resume("nowhere")

    assert (refused.value.status_code, refused.value.code) == (404, "unknown_destination")


def test_a_name_two_consumers_share_is_resumed_only_with_its_consumer(
        service: EventService, store: Store, clock: Clock) -> None:
    for name in ("notify", "audit"):
        consumer = Consumer(name, session_factory=store.sessions, clock=clock,
                            destinations={"peer": Collect()})
        consumer.register()
        consumer.park("peer", "hold")

    with pytest.raises(EventServiceError) as refused:
        service.resume("peer")
    answer = service.resume("peer", consumer="audit")

    assert (refused.value.status_code, refused.value.code) == (409, "ambiguous_destination")
    assert answer["consumer"] == "audit"
    states = {(d["consumer"], d["state"]) for d in service.deliveries()["destinations"]}
    assert states == {("audit", "active"), ("notify", "parked")}


def test_resuming_a_retired_destination_is_refused(service: EventService, store: Store,
                                                   clock: Clock) -> None:
    Consumer("notify", session_factory=store.sessions, clock=clock,
             destinations={"old": Collect()}).register()
    Consumer("notify", session_factory=store.sessions, clock=clock, destinations={}).register()

    with pytest.raises(EventServiceError) as refused:
        service.resume("old")

    assert (refused.value.status_code, refused.value.code) == (409, "destination_retired")
