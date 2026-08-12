from __future__ import annotations

import pytest

from core_storefront.models.listing_models import CreateListingRequest
from market_storefront.domain_runtime import get_market_domain_contract
from market_storefront.services.listing_service import ListingService
from tests.fake_site import TEST_MARKETPLACE_SIGNER


_ACCEPTED_ESCROWS = [{
    "chain_name": "anvil",
    "escrow_address": "0x" + "11" * 20,
    "literal_fields": {"token": "0x0000000000000000000000000000000000000001"},
    "rates": [{"field": "amount", "per": "hour", "value": "5000"}],
}]


def test_storefront_resolves_vm_domain_runtime() -> None:
    runtime = get_market_domain_contract()

    assert runtime.identity == "compute.v1"
    assert runtime.codecs.listing({"gpu_model": "H200", "gpu_count": 1}).offer_resource == {
        "gpu_model": "H200",
        "gpu_count": 1,
    }


def test_listing_service_validates_offer_through_domain_runtime() -> None:
    svc = ListingService(
        sqlite_client=object(),
        alkahest_clients=None,
        marketplace_signer=TEST_MARKETPLACE_SIGNER,
    )

    with pytest.raises(ValueError, match="offer_resource must include gpu_model"):
        svc._parse_offer_and_escrows(
            CreateListingRequest(
                offer={"gpu_count": 1},
                accepted_escrows=_ACCEPTED_ESCROWS,
            )
        )

