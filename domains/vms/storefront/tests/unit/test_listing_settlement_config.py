from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from core_storefront.models.listing_models import CreateListingRequest
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
async def test_vm_preflight_rejects_malformed_opaque_config_before_resolution() -> None:
    service = ListingService(
        sqlite_client=object(),
        marketplace_signer=TEST_MARKETPLACE_SIGNER,
    )
    request = CreateListingRequest(
        offer={},
        settlement_config={**_VALID_CONFIG, "currency": "USD"},
    )

    with pytest.raises(ValidationError):
        await service._preflight_hosted_option(request)


@pytest.mark.asyncio
async def test_vm_preflight_preserves_valid_hosted_listing_option(monkeypatch) -> None:
    profile = {
        "condition_id": "vm-fulfillment",
        "evaluator": {"kind": "builtin.v1", "version": "1"},
        "demand": {"encoding": "application/jcs+json", "value": {}},
    }
    hosted_config = SimpleNamespace(
        enabled=True,
        condition_profiles={"vm-fulfillment": profile},
        expected_manifest_digest="sha256:test-manifest",
        contract_version="0.1.0",
        expected_schema_version=4,
        required_capabilities=(),
    )
    import market_storefront.utils.config as config_module

    monkeypatch.setattr(
        config_module,
        "settings",
        SimpleNamespace(settlement=SimpleNamespace(hosted=hosted_config)),
    )
    adapter = AsyncMock()
    service = ListingService(
        sqlite_client=object(),
        marketplace_signer=TEST_MARKETPLACE_SIGNER,
        settlement_composition_provider=lambda: SimpleNamespace(
            mechanism_clients={"fiat.stripe.v1": adapter}
        ),
    )
    request = VmCreateListingRequest(offer={}, settlement_config=_VALID_CONFIG)

    option = await service._preflight_hosted_option(request)

    assert option is not None
    assert option["mechanism"] == "fiat.stripe.v1"
    assert option["asset"] == "usd"
    assert option["params"]["account_ref"] == "acct-seller"
    assert option["rates"] == [{"field": "amount", "per": "hour", "value": "125"}]
    adapter.verify_ready.assert_awaited_once()
