"""The bundle validates what it names and spells the domain's storefront names from it."""

from dataclasses import FrozenInstanceError, replace

import pytest
from pydantic import BaseModel

from tests.bundles import EXAMPLE


def test_names_are_spelled_from_the_kind_and_table_prefix():
    assert EXAMPLE.schema_name == "example"
    assert EXAMPLE.settlement_evidence_kind == "example.settlement-evidence.v1"
    assert EXAMPLE.listing_source_kind == "example.quota-listing.v1"
    assert EXAMPLE.table("issuance_progress") == "example_issuance_progress"


def test_a_table_prefix_is_hyphenated_for_the_credentials_reference():
    assert replace(EXAMPLE, table_prefix="some_shop").credentials_ref_prefix == "some-shop-credential.v1"


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "example"},
        {"kind": "Example.v1"},
        {"table_prefix": "example; DROP TABLE x"},
        {"offering_mode": " "},
        {"contribution_id": ""},
    ],
)
def test_an_unusable_name_is_refused(change):
    with pytest.raises(ValueError):
        replace(EXAMPLE, **change)


def test_a_listing_schema_without_a_listing_resource_is_refused():
    class Bare(BaseModel):
        product: str

    with pytest.raises(ValueError, match="listing_resource"):
        replace(EXAMPLE, listing_schema=Bare)


def test_the_bundle_is_frozen_and_its_optional_fields_default_absent():
    with pytest.raises(FrozenInstanceError):
        EXAMPLE.kind = "other.v1"  # type: ignore[misc]
    assert EXAMPLE.publication_guards == ()
    assert EXAMPLE.acceptance_hook is None
    assert EXAMPLE.public_result_extension is None
