"""The event-sink consumer over a real event store.

Library integration: the eventing component's recorder and consumer over a
SQLite file its schema steps build, with sinks that record what they are
handed. The consumer's clock is a held instant the test moves.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest
from eventing import (
    SCHEMA_STEPS,
    Catalogue,
    EventService,
    Kind,
    Recorder,
    Reference,
    Route,
    RouteRefused,
    Severity,
    Source,
)
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from market_delivery import ConfiguredSink, DeliveryConfigurationError, DeliveryError
from market_delivery.event_sinks import EVENT_SINK_CONSUMER, build_event_sink_consumer


class _Details(BaseModel):
    note: str


HELD = Kind(
    name="fixture.held",
    version=1,
    severity=Severity.ACTION_REQUIRED,
    details=_Details,
    summary=lambda draft, details: f"held: {details.note}",
    attributes={"host": str},
)


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 25, 17, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


class _Sink:
    def __init__(self, *, failing: bool = False) -> None:
        self.received: list = []
        self.failing = failing

    def __call__(self, deliverable) -> None:
        if self.failing:
            raise DeliveryError("the configured endpoint returned status 503")
        self.received.append((deliverable.reference, deliverable.rendered, deliverable.payload()))


@pytest.fixture
def store(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'events.db'}")
    with engine.begin() as connection:
        for step in SCHEMA_STEPS:
            step.apply(connection)
    yield sessionmaker(bind=engine)
    engine.dispose()


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


def _catalogue() -> Catalogue:
    return Catalogue((HELD,))


def _record(store, clock, note: str = "bm-02 refused", host: str = "bm-02") -> None:
    recorder = Recorder(_catalogue(), source=Source(service="fixture", instance="one"), clock=clock)
    with store.begin() as session:
        recorder.record(session, HELD.draft(
            subject=Reference(type="job", id=note), details={"note": note},
            attributes={"host": host},
        ))


def _consumer(store, clock, sinks: dict, routes, **kwargs):
    return build_event_sink_consumer(
        session_factory=store,
        sinks=[ConfiguredSink(name=name, sink=sink, timeout_seconds=5) for name, sink in sinks.items()],
        routes=routes,
        catalogue=_catalogue(),
        clock=clock,
        max_age=timedelta(hours=1),
        runner="fixture-runner",
        **kwargs,
    )


def _states(store, clock) -> dict[str, dict]:
    return {
        status["destination"]: status
        for status in EventService(store, clock=clock).deliveries()["destinations"]
    }


def test_an_event_a_route_selects_reaches_both_sinks_once_each(store, clock) -> None:
    push, mail, other = _Sink(), _Sink(), _Sink()
    consumer = _consumer(store, clock, {"ops-push": push, "ops-mail": mail, "other": other}, [
        Route("held-work", "severity = 'action_required'", ("ops-push", "ops-mail")),
        Route("other-host", "host = 'bm-09'", ("other",)),
    ])
    consumer.run_cycle()
    _record(store, clock)

    consumer.run_cycle()
    consumer.run_cycle()

    for sink in (push, mail):
        (reference, rendered, payload) = sink.received[0]
        assert len(sink.received) == 1
        assert (reference, rendered) == ("job:bm-02 refused", "held: bm-02 refused")
        assert payload["kind"] == "fixture.held"
    assert other.received == []
    states = _states(store, clock)
    assert {name: (s["delivered"], s["pending"]) for name, s in states.items()} == {
        "ops-push": (1, 0), "ops-mail": (1, 0), "other": (0, 0),
    }
    assert {s["consumer"] for s in states.values()} == {EVENT_SINK_CONSUMER}


def test_a_failing_sink_is_retried_and_holds_up_no_other(store, clock) -> None:
    down, up = _Sink(failing=True), _Sink()
    consumer = _consumer(store, clock, {"down": down, "up": up}, [
        Route("all", "TRUE", ("down", "up")),
    ])
    consumer.run_cycle()
    _record(store, clock)

    consumer.run_cycle()

    states = _states(store, clock)
    assert len(up.received) == 1
    assert states["down"]["pending"] == 1
    assert states["down"]["head"]["last_error"] == (
        "DeliveryError: the configured endpoint returned status 503"
    )
    down.failing = False
    clock.now += timedelta(minutes=5)
    consumer.run_cycle()
    assert len(down.received) == 1


def test_a_sink_down_past_the_maximum_age_abandons_to_the_log(store, clock, caplog) -> None:
    down = _Sink(failing=True)
    consumer = _consumer(store, clock, {"down": down}, [Route("all", "TRUE", ("down",))])
    consumer.run_cycle()
    _record(store, clock)
    consumer.run_cycle()

    clock.now += timedelta(hours=2)
    with caplog.at_level(logging.WARNING, logger="eventing.finally"):
        consumer.run_cycle()

    assert _states(store, clock)["down"]["abandoned"] == 1
    assert any("delivery abandoned" in record.getMessage() for record in caplog.records)


def test_a_sink_down_past_the_maximum_age_abandons_to_a_named_finally_sink(store, clock) -> None:
    down, audit = _Sink(failing=True), _Sink()
    consumer = _consumer(store, clock, {"down": down, "audit": audit},
                         [Route("down-only", "TRUE", ("down",))], finally_sink="audit")
    consumer.run_cycle()
    _record(store, clock)
    consumer.run_cycle()

    clock.now += timedelta(hours=2)
    consumer.run_cycle()

    assert [reference for reference, _, _ in audit.received] == ["job:bm-02 refused"]
    assert _states(store, clock)["down"]["abandoned"] == 1


def test_a_route_naming_a_sink_not_enabled_is_refused(store, clock) -> None:
    with pytest.raises(RouteRefused, match="held-work"):
        _consumer(store, clock, {"ops-push": _Sink()},
                  [Route("held-work", "severity = 'action_required'", ("ops-mail",))])


def test_a_finally_sink_naming_no_enabled_sink_is_refused(store, clock) -> None:
    with pytest.raises(DeliveryConfigurationError, match="ops-mail"):
        _consumer(store, clock, {"ops-push": _Sink()}, [], finally_sink="ops-mail")


def test_a_sink_replaced_before_the_consumer_reads_abandons_its_event_to_the_finally_sink(
        store, clock, caplog) -> None:
    old, new = _Sink(), _Sink()
    _consumer(store, clock, {"old": old}, [Route("all", "TRUE", ("old",))]).run_cycle()
    _record(store, clock, note="unread")

    replaced = _consumer(store, clock, {"new": new}, [Route("all", "TRUE", ("new",))])
    with caplog.at_level(logging.WARNING, logger="eventing.finally"):
        report = replaced.run_cycle()
    _record(store, clock, note="later")
    replaced.run_cycle()

    assert report.retired == ["old"]
    assert report.abandoned == 1
    assert any("delivery abandoned" in record.getMessage() for record in caplog.records)
    assert old.received == []
    assert [reference for reference, _, _ in new.received] == ["job:later"]
    assert _states(store, clock)["old"]["abandoned"] == 1


def test_a_sink_removed_beside_a_kept_one_abandons_its_unread_event_to_the_finally_sink(
        store, clock) -> None:
    kept, gone, audit = _Sink(), _Sink(), _Sink()
    _consumer(store, clock, {"kept": kept, "gone": gone, "audit": audit},
              [Route("all", "TRUE", ("kept", "gone"))]).run_cycle()
    _record(store, clock, note="unread")

    _consumer(store, clock, {"kept": kept, "audit": audit},
              [Route("all", "TRUE", ("kept",))], finally_sink="audit").run_cycle()

    assert [reference for reference, _, _ in kept.received] == ["job:unread"]
    assert [reference for reference, _, _ in audit.received] == ["job:unread"]
    assert gone.received == []
