"""Publication validation against the served compute listing shape.

`listing_validation_errors` and `validate_listing_publication` are what both
the publication route and the dry run apply to the complete received document.
These cases cover their error paths over the deployed compute specification:
which names are reserved, how a schema error names its field, and what the
`pricing` object admits. The routes that apply them are exercised in the
integration suite.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from core_registry.api import filter_spec as filter_spec_module
from core_registry.api.validate_routes import (
    RESERVED_LISTING_FIELDS,
    listing_validation_errors,
    reject_retired_listing_shape,
    validate_listing_publication,
)


@pytest.fixture(autouse=True)
def _compute_spec():
    filter_spec_module.reset_cache()
    yield
    filter_spec_module.reset_cache()


def _listing(**fields) -> dict:
    return {
        "listing_id": "listing-1",
        "storefront_url": "http://seller.example/",
        "listing_resource": {"region": "example"},
        "settlement_options": [
            {"option_id": "a" * 64, "settlement": {"schema": "example.payment.v1"}}
        ],
        **fields,
    }


_RATE = {"amount": "2.50", "asset": "usd", "period": "hour"}


def test_a_complete_listing_has_no_errors() -> None:
    assert listing_validation_errors(_listing()) == []


def test_the_reserved_names_are_exactly_the_registry_owned_response_fields() -> None:
    assert RESERVED_LISTING_FIELDS == {
        "publisher_id",
        "publisher_principals",
        "created_at",
        "updated_at",
        "publisher_publication",
        "publisher_updates",
    }


def test_each_reserved_name_is_reported_in_order_before_schema_errors() -> None:
    candidate = _listing(publisher_updates={}, created_at="now")
    del candidate["storefront_url"]

    errors = listing_validation_errors(candidate)

    assert errors[:2] == [
        "created_at: reserved registry metadata",
        "publisher_updates: reserved registry metadata",
    ]
    assert errors[2:] == ["<root>: 'storefront_url' is a required property"]


def test_a_schema_error_names_its_nested_field() -> None:
    errors = listing_validation_errors(
        _listing(listing_resource={"region": "example", "gpu_interconnect": "carrier-pigeon"})
    )

    (error,) = errors
    assert error.startswith("listing_resource.gpu_interconnect: ")


def test_a_schema_error_names_an_array_member_by_index() -> None:
    errors = listing_validation_errors(
        _listing(settlement_options=[{"option_id": "short", "settlement": {"schema": "x"}}])
    )

    (error,) = errors
    assert error.startswith("settlement_options[0].option_id: ")


def test_pricing_carries_an_asking_rate_and_a_rate_structure() -> None:
    structure = {"gpu": [{"asset": "usd", "rate": "80", "per": "hour"}]}

    assert listing_validation_errors(_listing(pricing={"asking_rate": _RATE})) == []
    assert listing_validation_errors(_listing(pricing={"rate_structure": structure})) == []
    assert listing_validation_errors(
        _listing(pricing={"asking_rate": _RATE, "rate_structure": structure})
    ) == []


def test_pricing_refuses_a_term_it_does_not_name() -> None:
    (error,) = listing_validation_errors(_listing(pricing={"asking_rates": [_RATE]}))

    assert error.startswith("pricing: ")
    assert "asking_rates" in error


def test_an_asking_rate_missing_its_period_is_refused_by_path() -> None:
    rate = {key: value for key, value in _RATE.items() if key != "period"}

    (error,) = listing_validation_errors(_listing(pricing={"asking_rate": rate}))

    assert error == "pricing.asking_rate: 'period' is a required property"


def test_a_rate_structure_entry_is_strict() -> None:
    structure = {"gpu": [{"asset": "usd", "rate": "80", "per": "hour", "model": "H100"}]}

    (error,) = listing_validation_errors(_listing(pricing={"rate_structure": structure}))

    assert error.startswith("pricing.rate_structure.gpu[0]: ")


def test_the_retired_shape_is_refused_with_its_replacement_named() -> None:
    with pytest.raises(HTTPException) as caught:
        validate_listing_publication(_listing(offer_resource={"region": "example"}))

    assert caught.value.status_code == 422
    assert caught.value.detail["error"] == "retired_listing_shape"
    assert caught.value.detail["retired_fields"] == ["offer_resource"]
    assert "`offer_resource`: the published shape is `listing_resource`" in (
        caught.value.detail["message"]
    )


@pytest.mark.parametrize(
    ("fields", "retired", "replacement"),
    [
        (
            {"listing_resource": {"region": "example", "asking_rate": _RATE}},
            "listing_resource.asking_rate",
            "`pricing.asking_rate`",
        ),
        (
            {"rate_structure": {"gpu": [{"asset": "usd", "rate": "80", "per": "hour"}]}},
            "rate_structure",
            "`pricing.rate_structure`",
        ),
    ],
)
def test_a_price_at_its_earlier_location_is_refused_naming_pricing(
    fields: dict, retired: str, replacement: str
) -> None:
    """A rate there would publish and match no rate bound, so it is refused
    rather than stored, and the refusal names where it now goes."""
    with pytest.raises(HTTPException) as caught:
        validate_listing_publication(_listing(**fields))

    assert caught.value.detail["error"] == "retired_listing_shape"
    assert caught.value.detail["retired_fields"] == [retired]
    assert replacement in caught.value.detail["message"]


def test_every_retired_field_is_named_in_order_with_its_replacement() -> None:
    with pytest.raises(HTTPException) as caught:
        validate_listing_publication(
            _listing(
                listing_resource={"region": "example", "asking_rate": _RATE},
                rate_structure={},
            )
        )

    assert caught.value.detail["retired_fields"] == [
        "listing_resource.asking_rate",
        "rate_structure",
    ]
    message = caught.value.detail["message"]
    assert message.index("`pricing.asking_rate`") < message.index("`pricing.rate_structure`")


def test_a_body_that_is_not_an_object_names_no_retired_field() -> None:
    assert reject_retired_listing_shape(["listing_resource"]) is None


def test_the_dry_run_reports_a_price_at_its_earlier_location() -> None:
    (error,) = listing_validation_errors(
        _listing(listing_resource={"region": "example", "asking_rate": _RATE})
    )

    assert error.startswith("listing_resource: ")


def test_publication_refuses_with_every_error() -> None:
    with pytest.raises(HTTPException) as caught:
        validate_listing_publication(_listing(publisher_id=1, pricing={"asking_rate": {}}))

    assert caught.value.status_code == 422
    assert caught.value.detail["error"] == "invalid_listing"
    assert caught.value.detail["errors"][0] == "publisher_id: reserved registry metadata"
    assert len(caught.value.detail["errors"]) == 4
