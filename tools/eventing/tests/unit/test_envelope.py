"""The envelope: its severities, its tolerance of what a reader does not know, and a
reader meeting a kind version it was not built for."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from eventing import ENVELOPE_VERSION, Envelope, Route, Routes, Severity, severity_rank
from tests.fixtures.kinds import SHIPMENT_DELAYED, catalogue


def envelope(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "envelope_version": ENVELOPE_VERSION,
        "id": "01JDX9R6Q7Z3K2W8P4M5N6B7C8",
        "kind": SHIPMENT_DELAYED.name,
        "kind_version": 1,
        "data_schema": "urn:event:orders.shipment_delayed:1",
        "source": {"service": "orders", "instance": "eu-1"},
        "sequence": 48213,
        "occurred_at": "2026-11-25T17:42:10Z",
        "severity": "action_required",
        "subject": {"type": "shipment", "id": "sh-9e0d"},
        "related": [{"type": "depot", "id": "d-02"}],
        "correlation_id": "o-7f3a",
        "causation_id": None,
        "attributes": {"carrier": "rail", "delay_minutes": 95},
        "summary": "Shipment sh-9e0d is 95 minutes late.",
        "details": {"reason": "missed connection", "attempt": 1},
        "extensions": {},
    }
    document.update(overrides)
    return document


def test_severities_are_ordered_info_warning_action_required() -> None:
    assert [s.rank for s in Severity] == [0, 1, 2]
    assert [s.value for s in sorted(Severity, key=severity_rank)] == [
        "info", "warning", "action_required"]
    assert severity_rank("warning") == 1


def test_a_reader_ignores_an_envelope_field_it_does_not_know() -> None:
    read = Envelope.from_json(json.dumps(envelope(priority_lane="express")))

    assert "priority_lane" not in read.model_dump()
    assert read.kind == SHIPMENT_DELAYED.name


def test_an_unknown_extension_is_kept_unchanged_through_a_round_trip() -> None:
    extension = {"vendor.trace": {"span": "a1", "flags": [1, 2]}}

    read = Envelope.from_json(json.dumps(envelope(extensions=extension)))

    assert read.extensions == extension
    assert json.loads(Envelope.from_json(read.to_json()).to_json())["extensions"] == extension


@pytest.mark.parametrize("value", [{"nested": 1}, [1, 2]])
def test_an_attribute_holds_only_a_scalar(value: object) -> None:
    with pytest.raises(ValidationError):
        Envelope.model_validate(envelope(attributes={"carrier": value}))


def test_an_attribute_keeps_its_scalar_type() -> None:
    read = Envelope.model_validate(envelope(attributes={"a": True, "b": 1, "c": 1.5, "d": "x"}))

    assert [type(v) for v in read.attributes.values()] == [bool, int, float, str]


def test_a_reader_meeting_a_newer_kind_version_routes_and_renders_from_the_envelope() -> None:
    # Version 2 renamed `reason` and dropped `attempt`; version 1's model cannot read it.
    newer = Envelope.from_json(json.dumps(envelope(
        kind_version=2, details={"cause": "missed connection"})))
    kinds = catalogue()
    routes = Routes([Route("late-rail", "kind = 'orders.shipment_delayed' AND carrier = 'rail'",
                           ("ops",))], kinds, enabled={"ops"})

    assert kinds.decode_details(newer) is None
    assert routes.select(newer) == {"ops"}
    assert newer.summary == "Shipment sh-9e0d is 95 minutes late."
    assert newer.details == {"cause": "missed connection"}


def test_the_declared_kind_version_is_decoded_with_its_model() -> None:
    read = Envelope.from_json(json.dumps(envelope()))

    decoded = catalogue().decode_details(read)

    assert decoded == SHIPMENT_DELAYED.details(reason="missed connection", attempt=1)


def test_the_scalar_fields_flatten_source_and_subject_and_spell_the_instant_in_utc() -> None:
    fields = Envelope.from_json(json.dumps(envelope())).scalar_fields()

    assert fields["source_service"] == "orders"
    assert fields["subject_type"] == "shipment"
    assert fields["occurred_at"] == "2026-11-25T17:42:10Z"
    assert fields["severity_rank"] == 2
