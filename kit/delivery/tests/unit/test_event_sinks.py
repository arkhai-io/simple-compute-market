"""One sink layer serves introductions and events: what a sink is handed of an event."""

from __future__ import annotations

import smtplib
from datetime import datetime, timezone

from eventing import Envelope, Reference, Severity, Source
from market_delivery import (
    ConfiguredSink,
    deliver_one,
    introduction_delivery_event,
)
from market_delivery.builtin.smtp_sink import build_smtp_sink
from market_delivery.event_sinks import EventDeliverable


def _envelope() -> Envelope:
    return Envelope(
        envelope_version=1,
        id="01JDX9R6Q7Z3K2W8P4M5N6B7C8",
        kind="provisioning.lease_release_failed",
        kind_version=1,
        data_schema="urn:arkhai:event:provisioning.lease_release_failed:1",
        source=Source(service="compute-provisioning", instance="fixture"),
        sequence=7,
        occurred_at=datetime(2026, 11, 25, 17, 42, 10, tzinfo=timezone.utc),
        severity=Severity.ACTION_REQUIRED,
        subject=Reference(type="lease", id="cr-7f3a9c"),
        related=(Reference(type="lease", id="cr-7f3a9c"),),
        attributes={"reason": "teardown_failed"},
        summary="Lease cr-7f3a9c is release_failed (teardown_failed); an operator must act.",
        details={"capacity_reservation_id": "cr-7f3a9c"},
    )


def _introduction():
    return introduction_delivery_event(
        {"obligation_ref": "d" * 64, "revealed": True, "counterparty_contact": {"mail": "x"}},
        role="seller",
    )


def test_an_event_is_rendered_by_its_summary_referenced_by_its_subject_and_sent_whole() -> None:
    envelope = _envelope()
    deliverable = EventDeliverable(envelope)

    assert deliverable.rendered == envelope.summary
    assert deliverable.reference == "lease:cr-7f3a9c"
    assert deliverable.payload() == envelope.model_dump(mode="json")


def test_a_delivery_event_is_referenced_by_its_obligation() -> None:
    event = _introduction()
    assert event.reference == event.obligation_ref


def test_one_mail_sink_sends_an_introduction_and_an_event_each_under_its_reference(monkeypatch) -> None:
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def send_message(self, message):
            sent.append((message["Subject"], message.get_content()))

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    sink = build_smtp_sink({
        "host": "mail.example.invalid", "sender": "ops@example.invalid",
        "recipients": ["ops@example.invalid"], "start_tls": False,
    })
    introduction = _introduction()
    event = EventDeliverable(_envelope())

    sink(introduction)
    sink(event)

    assert [subject for subject, _ in sent] == [
        f"Introduction revealed: {introduction.reference}",
        "Introduction revealed: lease:cr-7f3a9c",
    ]
    assert sent[0][1].strip() == introduction.rendered.strip()
    assert sent[1][1].strip() == event.rendered


def test_an_installed_sink_reading_the_obligation_reference_fails_an_event_by_its_class() -> None:
    def legacy_sink(event) -> None:
        print(event.obligation_ref)

    configured = ConfiguredSink(name="legacy", sink=legacy_sink, timeout_seconds=5)

    assert deliver_one(configured, _introduction()) is None
    assert deliver_one(configured, EventDeliverable(_envelope())) == "AttributeError"
