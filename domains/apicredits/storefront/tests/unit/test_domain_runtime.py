from __future__ import annotations

import pytest
from pydantic import BaseModel

from apicredits_storefront.domain_runtime import get_storefront_domain_runtime
from domains.apicredits.domain_runtime import storefront_runtime
from domains.apicredits.schema import API_CREDITS_SCHEMA_KIND


def test_domain_runtime_normalizes_api_credits_schema_slots() -> None:
    runtime = storefront_runtime()

    listing = runtime.listing({
        "service_name": "Acme Inference",
        "resource_id": "quota-a",
    })
    message = runtime.message({
        "kind": "api_credits.v1",
        "payload": {"quantity": "5", "key": {"mode": "new"}},
    })
    terms = runtime.terms({
        "kind": "api_credits.v1",
        "payload": {
            "quantity": 7,
            "key": {"mode": "existing", "key_id": "ak_123"},
        },
        "listing_ref": "listing-1",
    })
    materialization = runtime.materialization({
        "kind": "api_credits.v1",
        "escrow_uid": "escrow-1",
        "quantity": 5,
    })
    receipt = runtime.receipt({
        "kind": "api_credits.v1",
        "status": "fulfilled",
        "fulfillment_uid": "fulfill-1",
    })
    result = runtime.result({
        "kind": "api_credits.v1",
        "action": "issue_credits",
    })

    assert runtime.schema_id == API_CREDITS_SCHEMA_KIND
    assert listing.offer_resource.service_name == "Acme Inference"
    assert listing.offer_resource.resource_id == "quota-a"
    assert message.quantity == 5
    assert message.key_mode == "new"
    assert terms.quantity == 7
    assert terms.key_id == "ak_123"
    assert terms.listing_ref == "listing-1"
    assert materialization.quantity == 5
    assert receipt.status == "fulfilled"
    assert result.status == "success"


def test_domain_runtime_normalizes_offer_resource_from_foreign_model() -> None:
    """Accept models loaded through a second source/wheel import path."""

    class ForeignApiCreditsResource(BaseModel):
        kind: str
        service_name: str
        resource_id: str

    listing = storefront_runtime().listing({
        "offer_resource": ForeignApiCreditsResource(
            kind="api_credits.v1",
            service_name="Acme Inference",
            resource_id="quota-a",
        ),
    })

    assert listing.offer_resource.service_name == "Acme Inference"
    assert listing.offer_resource.resource_id == "quota-a"


def test_domain_runtime_surfaces_api_credits_validation_errors() -> None:
    runtime = storefront_runtime()

    with pytest.raises(ValueError, match="quantity"):
        runtime.message({
            "kind": "api_credits.v1",
            "payload": {"quantity": 0, "key": {"mode": "new"}},
        })


def test_storefront_resolves_api_credits_domain_runtime() -> None:
    runtime = get_storefront_domain_runtime()

    assert runtime.schema_id == "api_credits.v1"
    assert runtime.message({
        "kind": "api_credits.v1",
        "payload": {"quantity": 1},
    }).quantity == 1
