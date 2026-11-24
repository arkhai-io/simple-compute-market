"""A listing's two capacity bounds: their validation and their per-field tiers.

The relative bound is the longest deal from its start and the absolute one the
last possible lease end; each resolves on its own through the tiers a storefront
passes, highest first, and a malformed stored hint is refused rather than
guessed (``capacity_bounds.py``).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from market_resource_pools_contracts.capacity_bounds import (
    CapacityBounds,
    capacity_bound_hint,
    positive_duration_bound,
    resolve_capacity_bounds,
    utc_availability,
    validate_capacity_bounds,
)

UNTIL = "2026-12-31T23:59:59Z"


@pytest.mark.parametrize("value", [
    "2026-12-31T23:59:59Z", "2026-12-31T23:59:59+00:00",
    datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
])
def test_an_absolute_bound_in_utc_reads_as_one_z_timestamp(value):
    assert utc_availability(value) == UNTIL


def test_an_absolute_bound_keeps_its_fractional_seconds():
    assert utc_availability("2026-12-31T23:59:59.250Z") == "2026-12-31T23:59:59.250000Z"


@pytest.mark.parametrize("value", [
    "2026-12-31T23:59:59",
    "2026-12-31T23:59:59+01:00",
    datetime(2026, 12, 31, 23, 59, 59),
    datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone(timedelta(hours=-5))),
    "tomorrow",
    1_798_761_599,
    None,
], ids=["naive", "offset", "naive-datetime", "offset-datetime", "text", "epoch", "null"])
def test_an_absolute_bound_that_is_not_timezone_aware_utc_is_refused(value):
    with pytest.raises(ValueError, match="available_until_utc"):
        utc_availability(value)


@pytest.mark.parametrize(("value", "expected"), [(7200, 7200), (1, 1), (0, None), (-60, None), (None, None)])
def test_a_nonpositive_relative_bound_means_no_relative_limit(value, expected):
    assert positive_duration_bound(value) == expected


@pytest.mark.parametrize("value", [True, 7200.0, "7200"])
def test_a_relative_bound_that_is_not_an_integer_is_refused(value):
    with pytest.raises(ValueError, match="max_duration_seconds must be an integer or null"):
        positive_duration_bound(value)


def test_a_tier_s_bounds_are_strict():
    assert CapacityBounds(max_duration_seconds=0).positive_max_duration_seconds is None
    assert CapacityBounds(max_duration_seconds=7200).positive_max_duration_seconds == 7200
    for invalid in (
        {"max_duration_seconds": True},
        {"max_duration_seconds": "7200"},
        {"max_duration_seconds": 7200.5},
        {"available_until_utc": "2026-12-31T23:59:59"},
        {"maximum_term_seconds": 7200},
    ):
        with pytest.raises(ValidationError):
            CapacityBounds.model_validate(invalid)


def test_a_pool_hint_is_read_for_the_listing_s_offering_mode():
    tags = {"capacity_bounds": {
        "reserved": {"max_duration_seconds": 7200},
        "on_demand": {"available_until_utc": UNTIL},
    }}
    assert capacity_bound_hint(tags, "reserved") == CapacityBounds(max_duration_seconds=7200)
    assert capacity_bound_hint(tags, "on_demand") == CapacityBounds(available_until_utc=UNTIL)
    assert capacity_bound_hint(tags, "spot") == CapacityBounds()
    assert capacity_bound_hint({}, "reserved") == CapacityBounds()
    assert validate_capacity_bounds(tags) == []


@pytest.mark.parametrize(("bounds", "named"), [
    ([7200], "capacity_bounds must map offering modes to bounds"),
    ({"": {}}, "non-empty trimmed strings"),
    ({" reserved": {}}, "non-empty trimmed strings"),
    ({"reserved": 7200}, "capacity_bounds.reserved must be a mapping of bounds"),
    ({"reserved": {"max_duration_seconds": "7200"}}, "capacity_bounds.reserved:"),
    ({"spot": {"available_until_utc": "2026-12-31T23:59:59"}}, "capacity_bounds.spot:"),
])
def test_a_malformed_hint_is_refused_naming_where_it_is_wrong(bounds, named):
    tags = {"capacity_bounds": bounds}
    # A malformed mode refuses every mode: the pool is held, not half-read.
    with pytest.raises(ValueError, match=named):
        capacity_bound_hint(tags, "on_demand")
    (problem,) = validate_capacity_bounds(tags)
    assert named in problem


def test_each_bound_resolves_from_the_highest_tier_stating_it():
    override = CapacityBounds(max_duration_seconds=3600)
    hint = CapacityBounds(max_duration_seconds=7200, available_until_utc=UNTIL)
    default = CapacityBounds(max_duration_seconds=86_400, available_until_utc="2027-06-30T00:00:00Z")
    # The override's relative bound, the hint's absolute one: field by field.
    assert resolve_capacity_bounds(override, hint, default) == CapacityBounds(
        max_duration_seconds=3600, available_until_utc=UNTIL,
    )
    # An override's absolute date wins over the hint's, the hint's relative
    # bound still standing beneath it.
    dated = CapacityBounds(available_until_utc="2026-06-30T00:00:00Z")
    assert resolve_capacity_bounds(dated, hint, default) == CapacityBounds(
        max_duration_seconds=7200, available_until_utc="2026-06-30T00:00:00Z",
    )
    assert resolve_capacity_bounds(CapacityBounds(), CapacityBounds(), default) == default
    assert resolve_capacity_bounds(CapacityBounds(), CapacityBounds()) == CapacityBounds()


def test_a_stated_nonpositive_relative_bound_masks_the_tiers_below_it():
    resolved = resolve_capacity_bounds(
        CapacityBounds(max_duration_seconds=0), CapacityBounds(max_duration_seconds=7200),
    )
    assert resolved.max_duration_seconds == 0
    assert resolved.positive_max_duration_seconds is None
