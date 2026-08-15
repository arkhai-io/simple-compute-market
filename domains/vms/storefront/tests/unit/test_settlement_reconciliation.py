from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.services.listing_service import ListingService
from tests.fake_site import TEST_MARKETPLACE_SIGNER, TEST_SITE_AUTHORITIES
from tests.listing_service_fixtures import vm_listing_collaborators


@pytest.mark.asyncio
async def test_readiness_reconciliation_preserves_listing_identity_and_accepted_terms(
    monkeypatch,
):
    domain = build_vm_storefront_domain()
    registry = build_vm_storefront_registry(domain)
    collaborators = vm_listing_collaborators(
        registry,
        signer=TEST_MARKETPLACE_SIGNER,
        authorities=TEST_SITE_AUTHORITIES,
    )
    accepted_terms = {
        "mechanism": "fiat.stripe.v1",
        "option_id": "accepted-option",
    }
    stored = {
        "listing_id": "listing-stable",
        "status": "open",
        "created_at": "2026-08-12T00:00:00",
        "updated_at": "2026-08-12T00:00:00",
        "storefront_url": "http://seller.test",
        "seller_principal": TEST_MARKETPLACE_SIGNER.identity.model_dump(mode="json"),
        "offer_resource": {
            "resource_type": "compute",
            "gpu_model": "H200",
            "gpu_count": 1,
            "region": "California, US",
            "sla": 99.0,
            "pool_id": "pool-a",
        },
        "accepted_escrows": [],
        "settlement_options": [],
        "publication_clauses": [
            {
                "mechanism": "fiat.stripe.v1",
                "asset": "usd",
                "rate": "1.25",
                "per": "hour",
                "mechanism_input": {
                    "funding_profile": "card.v1",
                    "interaction": "interactive",
                    "funds_flow": "separate_charges_transfers",
                },
            }
        ],
        "demands": [],
        "max_duration_seconds": 3600,
        "oracle_address": None,
        "accepted_terms": accepted_terms,
    }
    db = SimpleNamespace(
        domain_registry=registry,
        market_domain=domain,
        load_listing=AsyncMock(return_value=stored),
        update_listing=AsyncMock(),
    )
    new_option = {
        "option_id": "newly-ready-option",
        "mechanism": "fiat.stripe.v1",
        "asset": "usd",
        "rates": [{"field": "amount", "per": "hour", "value": "125"}],
        "params": {},
    }
    composition = SimpleNamespace(
        publication_artifacts=AsyncMock(return_value=([], [new_option], ()))
    )
    publish = AsyncMock(return_value={"status": "published"})
    monkeypatch.setattr(
        "market_storefront.services.publication_service.publish_order_to_registry",
        publish,
    )
    service = ListingService(
        registry=collaborators.registry,
        binding=collaborators.binding,
        domain=collaborators.domain,
        capacity_runtime=collaborators.capacity_runtime,
        sqlite_client=db,
        marketplace_signer=TEST_MARKETPLACE_SIGNER,
        alkahest_clients={},
        settlement_composition_provider=lambda: composition,
    )

    result = await service.reconcile_settlement_options(
        "listing-stable",
        resources={"rate_minor_units": 125},
    )

    assert result["listing_id"] == "listing-stable"
    db.update_listing.assert_awaited_once_with(
        listing_id="listing-stable",
        accepted_escrows=[],
        settlement_options=[new_option],
    )
    assert (
        composition.publication_artifacts.await_args.kwargs["clauses"]
        == stored["publication_clauses"]
    )
    assert stored["accepted_terms"] is accepted_terms
    assert stored["accepted_terms"]["option_id"] == "accepted-option"
    assert publish.await_args.args[0].listing_id == "listing-stable"
