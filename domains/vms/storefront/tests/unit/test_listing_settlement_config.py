from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from market_settlement_runtime import SettlementPublicationClause
from pydantic import ValidationError

from market_storefront.models.listing_models import (
    HostedFiatSettlementConfig,
    VmCreateListingRequest,
)
from market_storefront.domain_runtime import build_vm_storefront_domain
from market_storefront.services.listing_service import ListingService
from tests.fake_site import TEST_MARKETPLACE_SIGNER
_DOMAIN = build_vm_storefront_domain()


_VALID_CONFIG = {
    "account_ref": "acct-seller",
    "currency": "usd",
    "rate_minor_units": 125,
    "condition_profile": "vm-fulfillment",
    "resolver_id": None,
}


@pytest.mark.parametrize(
    "update",
    [
        {"account_ref": " acct-seller"},
        {"currency": "USD"},
        {"rate_minor_units": True},
        {"rate_minor_units": 0},
        {"condition_profile": "vm-fulfillment "},
        {"resolver_id": ""},
        {"provider_secret": "must-not-cross-the-boundary"},
    ],
)
def test_hosted_fiat_settlement_config_rejects_malformed_payload(update) -> None:
    payload = {**_VALID_CONFIG, **update}

    with pytest.raises(ValidationError):
        HostedFiatSettlementConfig.model_validate(payload)


def test_vm_listing_request_validates_hosted_fiat_settlement_config() -> None:
    with pytest.raises(ValidationError):
        VmCreateListingRequest(
            offer={},
            settlement_config={**_VALID_CONFIG, "resolver_id": " resolver-main"},
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
        },
        settlements=[
            SettlementPublicationClause(
                mechanism="fiat.stripe.v1",
                asset="usd",
                rate="2",
                per="hour",
                mechanism_input={
                    "method": "card",
                    "funds_flow": "separate_charges_transfers",
                },
            )
        ],
    )
    service = ListingService(
        domain=_DOMAIN,
        sqlite_client=SimpleNamespace(market_domain=_DOMAIN),
        marketplace_signer=TEST_MARKETPLACE_SIGNER,
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
            "method": "card",
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
    db = SimpleNamespace(
        market_domain=_DOMAIN,
        upsert_listing=AsyncMock(),
    )
    composition = SimpleNamespace(
        publication_artifacts=AsyncMock(return_value=([], [option], ()))
    )
    service = ListingService(
        domain=_DOMAIN,
        sqlite_client=db,
        marketplace_signer=TEST_MARKETPLACE_SIGNER,
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
        domain=_DOMAIN,
        sqlite_client=SimpleNamespace(market_domain=_DOMAIN),
        marketplace_signer=TEST_MARKETPLACE_SIGNER,
        settlement_composition_provider=lambda: object(),
    )
    request = VmCreateListingRequest(
        offer={},
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
async def test_registration_composition_receives_valid_hosted_listing_input() -> None:
    option = {
        "option_id": "hosted",
        "mechanism": "fiat.stripe.v1",
        "asset": "usd",
        "rates": [{"field": "amount", "per": "hour", "value": "125"}],
        "params": {"account_ref": "acct-seller"},
    }
    composition = SimpleNamespace(
        settlement_config=SimpleNamespace(
            mechanism_config=lambda _key: SimpleNamespace(condition_profiles={})
        ),
        publication_artifacts=AsyncMock(return_value=([], [option], ())),
    )
    service = ListingService(
        domain=_DOMAIN,
        sqlite_client=SimpleNamespace(market_domain=_DOMAIN),
        marketplace_signer=TEST_MARKETPLACE_SIGNER,
        settlement_composition_provider=lambda: composition,
    )
    request = VmCreateListingRequest(offer={}, settlement_config=_VALID_CONFIG)

    accepted, options = await service._derive_settlement_artifacts(request)

    assert accepted == []
    assert options == [option]
    resources = composition.publication_artifacts.await_args.args[0]
    assert resources["account_ref"] == "acct-seller"
    assert resources["rate_minor_units"] == 125
    assert resources["claimant_principal"] == TEST_MARKETPLACE_SIGNER.identity
