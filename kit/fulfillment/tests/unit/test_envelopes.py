import pytest
from pydantic import BaseModel, ValidationError

from market_fulfillment import VersionedEnvelope, envelope


class Payload(BaseModel):
    capacity_reservation_id: str


def test_schema_version_must_be_positive():
    with pytest.raises(ValidationError):
        VersionedEnvelope[dict](kind="fulfillment.request", schema_version=0, payload={})


def test_kind_must_not_be_empty():
    with pytest.raises(ValidationError):
        VersionedEnvelope[dict](kind="", schema_version=1, payload={})


def test_typed_payload_is_validated():
    with pytest.raises(ValidationError):
        VersionedEnvelope[Payload](kind="fulfillment.request", schema_version=1, payload={})


def test_envelope_round_trip_and_frozen_behavior():
    original = envelope("fulfillment.request", 1, {"capacity_reservation_id": "r-1"})
    restored = VersionedEnvelope[dict].model_validate_json(original.model_dump_json())
    assert restored == original
    with pytest.raises(ValidationError):
        original.kind = "changed"
