"""The retained pricing record is checked against the publication a registry served.

A registry accepts a shape-priced listing's family rates only as
``pricing.rate_structure``, and the seller signs that body. The buyer's domain
record holds the same rates in ``rate_structure``, so the check reads each side
where it lives.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from arkhai_vms_negotiation.amounts import rate_structure_digest
from market_identity import RequestEnvelope, canonical_body_hash, sign_request

from arkhai_vms_buyer.pricing_record import (
    retained_pricing_record,
    verified_pricing_publication,
    verify_pricing_reply,
)
from arkhai_vms_buyer.registry_listing import domain_listing_record
from identity_helpers import SELLER_SIGNER, seller_principals
from test_negotiation_amounts import RATE_STRUCTURE, TOKEN, shape_priced_listing


def _publication(**overrides: Any) -> dict[str, Any]:
    """A shape-priced publication body in the shape the compute schema accepts."""
    listing = shape_priced_listing()
    body = {
        key: listing[key]
        for key in (
            "listing_id", "storefront_url", "listing_resource",
            "accepted_escrows", "settlement_options",
        )
    }
    body["pricing"] = {"rate_structure": RATE_STRUCTURE}
    body.update(overrides)
    return {key: value for key, value in body.items() if value is not None}


def _served(body: dict[str, Any], **served_fields: Any) -> dict[str, Any]:
    """The listing a registry serves for ``body``, with the seller's signed publication."""
    request = sign_request(signer=SELLER_SIGNER, envelope=RequestEnvelope(
        principal=SELLER_SIGNER.identity, role="seller", method="POST",
        operation="listing.publish", resource="listings",
        request_id="publication-1", timestamp=1_793_966_340,
        body_hash=canonical_body_hash(body),
    ))
    return {
        **body,
        **served_fields,
        "publisher_principals": seller_principals().model_dump(mode="json"),
        "publisher_publication": {
            "body_base64": base64.b64encode(json.dumps(body).encode()).decode(),
            "request": request.model_dump(mode="json"),
        },
    }


def _record(served: dict[str, Any]) -> dict[str, Any]:
    return retained_pricing_record(domain_listing_record(served))


def test_a_registry_shaped_publication_verifies_against_its_retained_record() -> None:
    body = _publication()
    record = _record(_served(body))

    assert "rate_structure" not in body
    assert record["rate_structure"] == RATE_STRUCTURE
    assert verified_pricing_publication(record) == body


def test_a_reply_is_pinned_to_the_published_pricing_rates() -> None:
    record = _record(_served(_publication()))
    digest = rate_structure_digest({"rate_structure": RATE_STRUCTURE})

    verify_pricing_reply(record, {"action": "counter", "rate_structure_digest": digest})
    with pytest.raises(ValueError, match="changed the published rate-structure identity"):
        verify_pricing_reply(record, {"action": "counter", "rate_structure_digest": "0" * 64})


def test_a_publication_with_top_level_family_rates_is_refused() -> None:
    record = _record(_served(_publication(rate_structure=RATE_STRUCTURE)))

    with pytest.raises(ValueError, match="top-level rate_structure"):
        verified_pricing_publication(record)


def test_retained_rates_other_than_the_published_ones_are_refused() -> None:
    other = {"gpu": [{"asset": TOKEN, "rate": "1", "per": "hour"}]}
    record = {**_record(_served(_publication())), "rate_structure": other}

    with pytest.raises(ValueError, match="differs from seller publication: pricing.rate_structure"):
        verified_pricing_publication(record)


def test_a_publication_carrying_no_family_rates_proves_none() -> None:
    record = _record(_served(_publication(pricing=None), rate_structure=RATE_STRUCTURE))

    with pytest.raises(ValueError, match="differs from seller publication: pricing.rate_structure"):
        verified_pricing_publication(record)
