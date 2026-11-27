"""Kind declarations and the catalogue: what a declaration may say, and how a draft
is held to it."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from eventing import Catalogue, EventRefused, Kind, KindRefused, Reference, Severity
from tests.fixtures.kinds import (
    JOB_FINISHED,
    NOTE_ADDED,
    SHIPMENT_DELAYED,
    DelayDetails,
    JobDetails,
    catalogue,
)


def kind(**overrides: object) -> Kind[JobDetails]:
    fields: dict[str, object] = {
        "name": "jobs.other", "version": 1, "severity": Severity.INFO, "details": JobDetails,
        "summary": lambda draft, details: "", "attributes": {}, "dedup_key": (),
    }
    fields.update(overrides)
    return Kind(**fields)  # type: ignore[arg-type]


def test_the_catalogue_lists_every_declared_kind_by_name() -> None:
    assert [k.name for k in catalogue().kinds()] == [
        "jobs.finished", "notes.added", "orders.shipment_delayed"]


def test_an_undeclared_kind_is_refused() -> None:
    with pytest.raises(EventRefused) as refused:
        catalogue().require("jobs.unknown")

    assert refused.value.code == "undeclared_kind"


def test_a_kind_declared_twice_is_refused() -> None:
    with pytest.raises(KindRefused, match="declared twice"):
        Catalogue([JOB_FINISHED, kind(name=JOB_FINISHED.name)])


def test_a_kind_version_below_one_is_refused() -> None:
    with pytest.raises(KindRefused, match="version must be at least 1"):
        Catalogue([kind(version=0)])


def test_an_attribute_named_as_an_envelope_field_is_refused() -> None:
    with pytest.raises(KindRefused, match="attribute severity is an envelope field"):
        Catalogue([kind(attributes={"severity": str})])


def test_an_attribute_of_a_type_a_route_cannot_read_is_refused() -> None:
    with pytest.raises(KindRefused, match="an attribute is a str, int, float or bool"):
        Catalogue([kind(attributes={"tags": list})])


def test_one_attribute_name_declared_with_two_types_is_refused() -> None:
    with pytest.raises(KindRefused, match="another kind declares it int"):
        Catalogue([JOB_FINISHED, kind(attributes={"duration_seconds": str})])


@pytest.mark.parametrize("path", ["details.missing", "attributes.missing", "occurred_at", "related"])
def test_a_dedup_key_naming_no_field_is_refused(path: str) -> None:
    with pytest.raises(KindRefused, match=f"dedup key names {path}"):
        Catalogue([kind(dedup_key=(path,))])


def test_an_undeclared_attribute_is_refused() -> None:
    with pytest.raises(EventRefused, match="declares no attribute colour") as refused:
        JOB_FINISHED.validate_attributes({"colour": "red"})

    assert refused.value.code == "invalid_attributes"


@pytest.mark.parametrize(("name", "value"), [
    ("duration_seconds", "forty"), ("duration_seconds", True), ("expedited", 1)])
def test_an_attribute_of_another_type_is_refused(name: str, value: object) -> None:
    owner = JOB_FINISHED if name == "duration_seconds" else SHIPMENT_DELAYED
    with pytest.raises(EventRefused) as refused:
        owner.validate_attributes({name: value})  # type: ignore[dict-item]

    assert refused.value.code == "invalid_attributes"


def test_a_null_or_absent_attribute_is_accepted_and_an_int_reads_as_a_float() -> None:
    measured = kind(attributes={"ratio": float, "status": str})

    assert measured.validate_attributes({"ratio": 2, "status": None}) == {"ratio": 2, "status": None}
    assert measured.validate_attributes({}) == {}


def test_details_failing_the_model_are_refused() -> None:
    with pytest.raises(EventRefused) as refused:
        SHIPMENT_DELAYED.validate_details({"reason": "late"})

    assert refused.value.code == "invalid_details"


def test_details_of_another_model_are_refused() -> None:
    class Other(BaseModel):
        reason: str

    with pytest.raises(EventRefused, match="details are DelayDetails, not Other"):
        SHIPMENT_DELAYED.validate_details(Other(reason="late"))


def test_the_dedup_value_reads_each_named_field() -> None:
    keyed = kind(attributes={"status": str},
                 dedup_key=("subject", "attributes.status", "details.queue", "related.depot",
                            "correlation_id"))
    draft = keyed.draft(subject=Reference(type="job", id="j-1"), details={"queue": "q"},
                        attributes={"status": "done"}, correlation_id="c-1",
                        related=[Reference(type="depot", id="d-02")])

    value = keyed.dedup_value(draft, JobDetails(queue="q"))

    assert value is not None
    assert json.loads(value) == ["job:j-1", "done", "q", "d-02", "c-1"]


def test_a_kind_with_no_dedup_key_has_no_dedup_value() -> None:
    draft = NOTE_ADDED.draft(subject=Reference(type="note", id="n-1"), details={"queue": "q"})

    assert NOTE_ADDED.dedup_value(draft, JobDetails(queue="q")) is None


def test_a_draft_carries_the_kind_name_and_the_kind_renders_its_summary() -> None:
    draft = SHIPMENT_DELAYED.draft(subject=Reference(type="shipment", id="sh-1"),
                                   details={"reason": "fog", "attempt": 2})

    assert draft.kind == "orders.shipment_delayed"
    assert SHIPMENT_DELAYED.summary(draft, DelayDetails(reason="fog", attempt=2)) == (
        "Shipment sh-1 delayed: fog (attempt 2).")


def test_the_data_schema_is_the_prefix_the_kind_and_its_version() -> None:
    assert Catalogue(schema_prefix="urn:example:event").data_schema(JOB_FINISHED) == (
        "urn:example:event:jobs.finished:1")
