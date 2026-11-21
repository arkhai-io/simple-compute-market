"""The seller-authored listing details: one model, its limits, and the projection
of what a seller stated.

Every consumer — the registry's served schema and publish checks, the storefront
request models, the pool-override terms — takes its limits from this model, so
each bound is proven here at and one past its edge.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from market_core.listing_details import ListingDetails, supplied_listing_details


def _refused_at(fields: dict) -> list[tuple]:
    with pytest.raises(ValidationError) as caught:
        ListingDetails.model_validate(fields)
    return [error["loc"] for error in caught.value.errors()]


@pytest.mark.parametrize(
    ("field", "limit"),
    [("title", 200), ("description", 4000)],
)
def test_prose_is_admitted_at_its_limit_and_refused_one_past(field, limit):
    assert getattr(ListingDetails.model_validate({field: "x" * limit}), field) == "x" * limit
    assert _refused_at({field: "x" * (limit + 1)}) == [(field,)]


def test_metadata_holds_at_most_fifty_keys():
    at_limit = {f"key{index}": index for index in range(50)}
    assert ListingDetails.model_validate({"metadata": at_limit}).metadata == at_limit

    over = {**at_limit, "key50": 50}
    assert _refused_at({"metadata": over}) == [("metadata",)]


@pytest.mark.parametrize("key", ["a", "k" * 40, "Az09_.-"])
def test_a_metadata_key_within_its_length_and_class_is_admitted(key):
    assert ListingDetails.model_validate({"metadata": {key: "v"}}).metadata == {key: "v"}


@pytest.mark.parametrize("key", ["", "k" * 41, "has space", "slash/", "colon:", "ünicode"])
def test_a_metadata_key_outside_its_length_or_class_is_refused(key):
    loc = _refused_at({"metadata": {key: "v"}})
    assert loc and all(entry[0] == "metadata" for entry in loc)


def test_a_string_value_is_admitted_at_its_limit_and_refused_one_past():
    assert ListingDetails.model_validate({"metadata": {"k": "v" * 500}}).metadata == {"k": "v" * 500}

    loc = _refused_at({"metadata": {"k": "v" * 501}})
    assert loc and all(entry[:2] == ("metadata", "k") for entry in loc)


@pytest.mark.parametrize("value", [0, -7, 2**70, 1.5, -0.25, True, False])
def test_finite_numbers_and_booleans_are_admitted_as_values(value):
    admitted = ListingDetails.model_validate({"metadata": {"k": value}}).metadata["k"]
    assert admitted == value
    assert type(admitted) is type(value)


@pytest.mark.parametrize(
    "value",
    [None, [1, 2], ["a"], {"nested": "map"}, math.nan, math.inf, -math.inf],
    ids=["null", "number-array", "string-array", "object", "nan", "infinity", "negative-infinity"],
)
def test_null_arrays_objects_and_non_finite_numbers_are_refused_as_values(value):
    loc = _refused_at({"metadata": {"k": value}})
    assert loc and all(entry[:2] == ("metadata", "k") for entry in loc)


def test_the_metadata_schema_is_closed_to_keys_outside_the_class():
    """The key class reaches JSON Schema as a pattern property; the object is
    closed beside it, so a schema reader refuses what the model refuses."""
    variants = ListingDetails.model_json_schema()["properties"]["metadata"]["anyOf"]
    (metadata,) = [variant for variant in variants if variant.get("type") == "object"]

    assert metadata["additionalProperties"] is False
    assert list(metadata["patternProperties"]) == ["^[A-Za-z0-9_.-]+$"]
    assert metadata["maxProperties"] == 50


def test_every_field_is_optional():
    assert ListingDetails.model_validate({}) == ListingDetails()


def test_the_projection_keeps_only_stated_details():
    stated = supplied_listing_details(
        {
            "title": "",
            "description": None,
            "metadata": {},
            "listing_resource": {"region": "example"},
        }
    )

    # An empty string and an empty map are statements; null and absence are not,
    # and fields outside the details are not details.
    assert stated == {"title": "", "metadata": {}}


def test_the_projection_of_nothing_stated_is_empty():
    assert supplied_listing_details({}) == {}
    assert supplied_listing_details({"title": None, "description": None, "metadata": None}) == {}
