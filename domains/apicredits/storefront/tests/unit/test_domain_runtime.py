from __future__ import annotations

import pytest
from pydantic import BaseModel

from apicredits_storefront.domain_runtime import (
    APICREDITS_STOREFRONT_DOMAIN,
    get_market_domain_contract,
)
from domains.apicredits.domain_runtime import market_domain
from domains.apicredits.schema import API_CREDITS_SCHEMA_KIND
from market_core import (
    DomainCapability,
    DomainCodecExample,
    DomainConformanceCase,
    assert_domain_conformance,
)


def test_domain_runtime_normalizes_api_credits_schema_slots() -> None:
    runtime = market_domain()

    listing = runtime.codecs.listing({
        "service_name": "Acme Inference",
        "resource_id": "quota-a",
    })
    message = runtime.codecs.message({
        "kind": "api_credits.v1",
        "payload": {"quantity": "5", "key": {"mode": "new"}},
    })
    terms = runtime.codecs.terms({
        "kind": "api_credits.v1",
        "payload": {
            "quantity": 7,
            "key": {"mode": "existing", "key_id": "ak_123"},
        },
        "listing_ref": "listing-1",
    })
    materialization = runtime.codecs.materialization({
        "kind": "api_credits.v1",
        "escrow_uid": "escrow-1",
        "quantity": 5,
    })
    receipt = runtime.codecs.receipt({
        "kind": "api_credits.v1",
        "status": "fulfilled",
        "fulfillment_uid": "fulfill-1",
    })
    result = runtime.codecs.result({
        "kind": "api_credits.v1",
        "action": "issue_credits",
    })

    assert runtime.identity == API_CREDITS_SCHEMA_KIND
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

    assert_domain_conformance(
        DomainConformanceCase(
            contract=runtime,
            listing=DomainCodecExample(listing, listing),
            message=DomainCodecExample(message, message),
            terms=DomainCodecExample(terms, terms),
            materialization=DomainCodecExample(
                materialization,
                materialization,
            ),
            receipt=DomainCodecExample(receipt, receipt),
            result=DomainCodecExample(result, result),
            capabilities=frozenset(),
        )
    )
    assert not runtime.has_capability(
        DomainCapability.COMPUTE_PROVISIONING,
    )
    assert runtime.compute_provisioning is None


def test_domain_runtime_normalizes_offer_resource_from_foreign_model() -> None:
    """Accept models loaded through a second source/wheel import path."""

    class ForeignApiCreditsResource(BaseModel):
        kind: str
        service_name: str
        resource_id: str

    listing = market_domain().codecs.listing({
        "offer_resource": ForeignApiCreditsResource(
            kind="api_credits.v1",
            service_name="Acme Inference",
            resource_id="quota-a",
        ),
    })

    assert listing.offer_resource.service_name == "Acme Inference"
    assert listing.offer_resource.resource_id == "quota-a"


def test_domain_runtime_normalizes_json_encoded_offer_resource() -> None:
    listing = market_domain().codecs.listing({
        "offer_resource": (
            '{"kind":"api_credits.v1","service_name":"Acme Inference",'
            '"resource_id":"quota-a"}'
        ),
    })

    assert listing.offer_resource.service_name == "Acme Inference"
    assert listing.offer_resource.resource_id == "quota-a"


def test_domain_runtime_surfaces_api_credits_validation_errors() -> None:
    runtime = market_domain()

    with pytest.raises(ValueError, match="quantity"):
        runtime.codecs.message({
            "kind": "api_credits.v1",
            "payload": {"quantity": 0, "key": {"mode": "new"}},
        })


def test_storefront_resolves_api_credits_domain_runtime() -> None:
    runtime = get_market_domain_contract()
    assert runtime is APICREDITS_STOREFRONT_DOMAIN

    assert runtime.identity == "api_credits.v1"
    assert runtime.codecs.message({
        "kind": "api_credits.v1",
        "payload": {"quantity": 1},
    }).quantity == 1
