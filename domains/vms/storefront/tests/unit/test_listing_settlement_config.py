from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from market_settlement_runtime import SettlementPublicationClause
from pydantic import ValidationError

from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.models.listing_models import VmCreateListingRequest
from market_storefront.services.listing_service import ListingService
from tests.fake_site import TEST_MARKETPLACE_SIGNER, TEST_SITE_AUTHORITIES
from tests.listing_service_fixtures import vm_listing_collaborators

_DOMAIN = build_vm_storefront_domain()
_REGISTRY = build_vm_storefront_registry(_DOMAIN)
_COLLABORATORS = vm_listing_collaborators(
    _REGISTRY,
    signer=TEST_MARKETPLACE_SIGNER,
    authorities=TEST_SITE_AUTHORITIES,
)


def _repository(**values):
    return SimpleNamespace(
        domain_registry=_REGISTRY,
        market_domain=_DOMAIN,
        **values,
    )


def test_vm_listing_request_rejects_removed_scalar_hosted_config() -> None:
    with pytest.raises(ValidationError, match="settlement_config"):
        VmCreateListingRequest(
            offer={"virtualization_type": "vm"},
            settlement_config={
                "account_ref": "acct-seller",
                "currency": "usd",
                "rate_minor_units": 125,
                "condition_profile": "vm-fulfillment",
            },
        )


def test_clause_only_listing_request_is_a_valid_publication_input() -> None:
    request = VmCreateListingRequest(
        offer={
            "resource_type": "compute",
            "resource_id": "resource-1",
            "gpu_model": "H200",
            "gpu_count": 1,
            "region": "California, US",
            "sla": 99.0,
            "virtualization_type": "vm",
        },
        settlements=[
            SettlementPublicationClause(
                mechanism="fiat.stripe.v1",
                asset="usd",
                rate="2",
                per="hour",
                mechanism_input={
                    "funding_profile": "card.v1",
                    "interaction": "interactive",
                    "funds_flow": "separate_charges_transfers",
                },
            )
        ],
    )
    service = ListingService(
        registry=_COLLABORATORS.registry,
        binding=_COLLABORATORS.binding,
        domain=_COLLABORATORS.domain,
        capacity_runtime=_COLLABORATORS.capacity_runtime,
        sqlite_client=_repository(),
        marketplace_signer=TEST_MARKETPLACE_SIGNER,
        alkahest_clients={},
        settlement_composition_provider=lambda: object(),
    )

    _offer, accepted, options, _demands = service._parse_offer_and_escrows(request)

    assert accepted == []
    assert options == []


@pytest.mark.asyncio
async def test_clause_only_create_persists_canonical_clause_before_publication(
    monkeypatch,
) -> None:
    clause = SettlementPublicationClause(
        mechanism="fiat.stripe.v1",
        asset="usd",
        rate="2",
        per="hour",
        mechanism_input={
            "funding_profile": "card.v1",
            "interaction": "interactive",
            "funds_flow": "separate_charges_transfers",
        },
    )
    option = {
        "option_id": "stripe-option",
        "mechanism": "fiat.stripe.v1",
        "asset": "usd",
        "rates": [{"field": "amount", "per": "hour", "value": "200"}],
        "params": {},
    }
    db = _repository(
        upsert_listing=AsyncMock(),
    )
    composition = SimpleNamespace(
        publication_artifacts=AsyncMock(return_value=([], [option], ()))
    )
    service = ListingService(
        registry=_COLLABORATORS.registry,
        binding=_COLLABORATORS.binding,
        domain=_COLLABORATORS.domain,
        capacity_runtime=_COLLABORATORS.capacity_runtime,
        sqlite_client=db,
        marketplace_signer=TEST_MARKETPLACE_SIGNER,
        alkahest_clients={},
        settlement_composition_provider=lambda: composition,
    )
    monkeypatch.setattr(
        service,
        "_compile_publication_clauses",
        lambda _request, *, composition: (clause,),
    )
    monkeypatch.setattr(
        "market_storefront.services.publication_service.publish_order_to_registry",
        AsyncMock(return_value={"status": "published"}),
    )
    request = VmCreateListingRequest(
        offer={
            "resource_type": "compute",
            "resource_id": "resource-1",
            "gpu_model": "H200",
            "gpu_count": 1,
            "region": "California, US",
            "sla": 99.0,
            "virtualization_type": "vm",
        },
        settlements=[clause],
    )

    result = await service.create_listing(request)

    assert result.status == "created"
    composition.publication_artifacts.assert_awaited_once_with(
        {
            "accepted_escrows": [],
            "claimant_principal": TEST_MARKETPLACE_SIGNER.identity,
        },
        clauses=[clause],
    )
    assert db.upsert_listing.await_args.kwargs["publication_clauses"] == [
        clause.model_dump(mode="json", exclude_defaults=True)
    ]


@pytest.mark.asyncio
async def test_direct_settlement_options_are_rejected() -> None:
    service = ListingService(
        registry=_COLLABORATORS.registry,
        binding=_COLLABORATORS.binding,
        domain=_COLLABORATORS.domain,
        capacity_runtime=_COLLABORATORS.capacity_runtime,
        sqlite_client=_repository(),
        marketplace_signer=TEST_MARKETPLACE_SIGNER,
        alkahest_clients={},
        settlement_composition_provider=lambda: object(),
    )
    request = VmCreateListingRequest(
        offer={"virtualization_type": "vm"},
        settlement_options=[
            {
                "option_id": "direct",
                "mechanism": "fiat.stripe.v1",
                "asset": "usd",
                "rates": [],
                "params": {},
            }
        ],
    )

    with pytest.raises(ValueError, match="derived from installed"):
        await service._derive_settlement_artifacts(request)


@pytest.mark.asyncio
async def test_registration_composition_receives_ordered_hosted_clauses() -> None:
    option = {
        "option_id": "hosted",
        "mechanism": "fiat.stripe.v1",
        "asset": "usd",
        "rates": [{"field": "amount", "per": "hour", "value": "125"}],
        "params": {
            "account_ref": "acct-seller",
            "funding_profile": "us_ach_debit.v1",
        },
    }
    composition = SimpleNamespace(
        publication_artifacts=AsyncMock(return_value=([], [option], ())),
    )
    service = ListingService(
        registry=_COLLABORATORS.registry,
        binding=_COLLABORATORS.binding,
        domain=_COLLABORATORS.domain,
        capacity_runtime=_COLLABORATORS.capacity_runtime,
        sqlite_client=_repository(),
        marketplace_signer=TEST_MARKETPLACE_SIGNER,
        alkahest_clients={},
        settlement_composition_provider=lambda: composition,
    )
    clauses = [
        SettlementPublicationClause(
            mechanism="fiat.stripe.v1",
            asset="usd",
            rate="125",
            per="hour",
            mechanism_input={
                "funding_profile": "us_ach_debit.v1",
                "interaction": "interactive",
                "funds_flow": "separate_charges_transfers",
            },
        )
    ]
    request = VmCreateListingRequest(
        offer={"virtualization_type": "vm"},
        settlements=clauses,
    )

    accepted, options = await service._derive_settlement_artifacts(
        request,
        clauses=tuple(clauses),
    )

    assert accepted == []
    assert options == [option]
    composition.publication_artifacts.assert_awaited_once_with(
        {
            "accepted_escrows": [],
            "claimant_principal": TEST_MARKETPLACE_SIGNER.identity,
        },
        clauses=clauses,
    )
