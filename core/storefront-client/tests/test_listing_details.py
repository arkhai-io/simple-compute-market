"""The listing model reads a seller's stated details and keeps them out of ``extra``."""

from __future__ import annotations

from storefront_client.models import ListingListResponse, ListingSummary

_DETAILS = {
    "title": "Two H100s in Frankfurt",
    "description": "Dedicated hosts.",
    "metadata": {"acme.tier": "gold", "rack": 7, "ecc": True},
}


def test_stated_details_are_read() -> None:
    listing = ListingSummary.from_dict({"listing_id": "L1", **_DETAILS, "custom": 1})

    assert (listing.title, listing.description, listing.metadata) == (
        _DETAILS["title"],
        _DETAILS["description"],
        _DETAILS["metadata"],
    )
    assert listing.extra == {"custom": 1}


def test_unstated_details_read_as_none() -> None:
    listing = ListingSummary.from_dict({"listing_id": "L1"})

    assert (listing.title, listing.description, listing.metadata) == (None, None, None)
    assert listing.extra == {}


def test_a_listing_list_reads_each_listing_s_details() -> None:
    page = ListingListResponse.from_dict(
        {"listings": [{"listing_id": "L1", **_DETAILS}, {"listing_id": "L2"}]}
    )

    assert [listing.metadata for listing in page.listings] == [_DETAILS["metadata"], None]
