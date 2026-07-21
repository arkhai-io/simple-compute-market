"""Unit tests for opaque ID generation."""

import uuid

from market_physical_settlement import (
    new_capacity_reservation_id,
    new_fulfillment_id,
    new_provisioned_resource_id,
    new_result_id,
    new_settlement_resource_id,
)

_FACTORIES = [
    new_capacity_reservation_id,
    new_fulfillment_id,
    new_provisioned_resource_id,
    new_result_id,
    new_settlement_resource_id,
]


def test_every_factory_returns_a_parseable_uuid_string():
    for factory in _FACTORIES:
        value = factory()
        assert isinstance(value, str)
        parsed = uuid.UUID(value)
        # UUIDv7 sets version nibble to 7.
        assert parsed.version == 7


def test_every_factory_is_globally_unique_across_calls():
    for factory in _FACTORIES:
        first = factory()
        second = factory()
        assert first != second


def test_close_in_time_ids_sort_close_together():
    # UUIDv7's leading bits are a millisecond timestamp, so successive IDs
    # from the same factory should already be in ascending lexical order
    # without any extra sort key -- the index-locality property that
    # motivated choosing UUIDv7 over uuid4 (ids.py module docstring).
    ordered = [new_fulfillment_id() for _ in range(5)]
    assert ordered == sorted(ordered)
