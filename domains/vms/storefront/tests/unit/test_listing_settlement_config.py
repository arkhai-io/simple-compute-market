from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from market_storefront.models.listing_models import (
    HostedFiatSettlementConfig,
    VmCreateListingRequest,
)
from market_storefront.services.listing_service import ListingService
from tests.fake_site import TEST_MARKETPLACE_SIGNER

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


@pytest.mark.asyncio
async def test_direct_settlement_options_are_rejected() -> None:
    service = ListingService(
        sqlite_client=object(),
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
        sqlite_client=object(),
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
