"""The registry client carries a listing's seller details only when stated.

A request naming no detail sends the body it always sent, and a listing read
back parses whichever details it states, leaving the rest unstated.
"""

from __future__ import annotations

from market_identity import Ed25519Signer

from registry_client import ListingRequest, ListingSummary, ValidatePublishRequest

_DETAIL_FIELDS = {"title", "description", "metadata"}
_DETAILS = {
    "title": "Eight GPUs",
    "description": "Dedicated hosts.",
    "metadata": {"acme.tier": "gold", "ipv4": True, "cooldown_hours": 0},
}
# A deterministic development key, never for use on a public network.
_PRINCIPALS = {
    "identities": [Ed25519Signer(bytes(range(32))).identity.model_dump(mode="json")]
}


def _listing_request(**details) -> ListingRequest:
    return ListingRequest(
        listing_id="listing-1",
        listing_resource={"region": "example"},
        accepted_escrows=[],
        storefront_url="http://seller.example/",
        **details,
    )


def _validate_request(**details) -> ValidatePublishRequest:
    return ValidatePublishRequest(
        listing_id="listing-1",
        listing_resource={"region": "example"},
        accepted_escrows=[],
        storefront_url="http://seller.example/",
        **details,
    )


def test_a_listing_request_omits_every_unstated_detail():
    body = _listing_request().to_dict()

    assert not _DETAIL_FIELDS.intersection(body)
    assert set(body) == {
        "listing_id",
        "listing_resource",
        "accepted_escrows",
        "settlement_options",
        "demands",
        "max_duration_seconds",
        "storefront_url",
    }


def test_a_listing_request_carries_each_stated_detail_and_no_other():
    assert {
        key: value
        for key, value in _listing_request(**_DETAILS).to_dict().items()
        if key in _DETAIL_FIELDS
    } == _DETAILS

    titled = _listing_request(title="Eight GPUs").to_dict()
    assert titled["title"] == "Eight GPUs"
    assert not {"description", "metadata"}.intersection(titled)


def test_an_empty_detail_is_a_statement():
    body = _listing_request(title="", metadata={}).to_dict()

    assert body["title"] == ""
    assert body["metadata"] == {}
    assert "description" not in body


def test_a_validation_request_omits_every_unstated_detail():
    body = _validate_request().to_dict()

    assert not _DETAIL_FIELDS.intersection(body)
    assert {
        key: value
        for key, value in _validate_request(**_DETAILS).to_dict().items()
        if key in _DETAIL_FIELDS
    } == _DETAILS
    described = _validate_request(description="Dedicated hosts.").to_dict()
    assert described["description"] == "Dedicated hosts."
    assert not {"title", "metadata"}.intersection(described)


def test_a_listing_summary_parses_stated_details():
    summary = ListingSummary.from_dict(
        {"listing_id": "listing-1", "publisher_principals": _PRINCIPALS, **_DETAILS}
    )

    assert (summary.title, summary.description, summary.metadata) == (
        _DETAILS["title"], _DETAILS["description"], _DETAILS["metadata"],
    )
    # Parsed as named fields, not carried again among the unnamed terms.
    assert not _DETAIL_FIELDS.intersection(summary.extra)
    assert {key: summary.to_dict()[key] for key in _DETAIL_FIELDS} == _DETAILS


def test_a_listing_summary_without_details_states_none():
    summary = ListingSummary.from_dict(
        {"listing_id": "listing-1", "publisher_principals": _PRINCIPALS}
    )

    assert (summary.title, summary.description, summary.metadata) == (None, None, None)
    assert not _DETAIL_FIELDS.intersection(summary.to_dict())
