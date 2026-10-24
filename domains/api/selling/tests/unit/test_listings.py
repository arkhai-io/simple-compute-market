"""The listing service publishes the bundle's mapping of an operator's request, and nothing a guard refuses."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from market_core import ImmutableCodecCapability
from pydantic import BaseModel, ConfigDict, Field

from arkhai_api_selling.listings import ListingService
from tests.bundles import CLAIMANT, DOMAIN, EXAMPLE, ExampleResource

SITE = "quota"


class _PublishedListing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    listing_resource: ExampleResource
    accepted_escrows: list[dict[str, Any]] = Field(default_factory=list)
    settlement_options: list[dict[str, Any]] = Field(default_factory=list)
    demands: list[dict[str, Any]] = Field(default_factory=list)


_DOMAIN = replace(
    DOMAIN,
    codecs=ImmutableCodecCapability(
        normalize_listing=_PublishedListing.model_validate,
        normalize_message=DOMAIN.codecs.normalize_message,
        normalize_terms=DOMAIN.codecs.normalize_terms,
        normalize_materialization=DOMAIN.codecs.normalize_materialization,
        normalize_receipt=DOMAIN.codecs.normalize_receipt,
        normalize_result=DOMAIN.codecs.normalize_result,
    ),
)


class _Site:
    async def availability(self) -> dict:
        return {(SITE, "quota-a"): 5}

    def site_client(self, _site_id: str) -> "_Site":
        return self

    async def resource_pool_projection(self) -> dict:
        return {
            "resource_pools": [
                {
                    "pool_id": "default",
                    "resources": [{"physical_resource_id": "quota-a"}],
                    "pool_metadata": {
                        "enabled": True,
                        "policy_tags": {
                            "deliverable_modes": ["example"],
                            "advertisable_modes": ["example"],
                            "capacity_backing": "backed",
                        },
                    },
                }
            ]
        }


class _Capacity:
    def runtime(self, _factory) -> _Site:
        return _Site()


class _Stage:
    fulfils_through_capacity = True


class _Composition:
    stages = {"example.escrow.v1": _Stage()}

    async def readiness(self) -> tuple:
        return ()


class _Store:
    def __init__(self) -> None:
        self.written: list[dict] = []

    async def upsert_listing_with_binding(self, **listing) -> None:
        self.written.append(listing)

    async def load_listing(self, *, listing_id: str) -> dict:
        return {"listing_id": listing_id}


ESCROW = {"chain_name": "dev", "escrow_address": "0x" + "11" * 20}


def _service(store: _Store, contributions=EXAMPLE, **options) -> ListingService:
    async def publish(_listing):
        return {"status": "published"}

    async def close(_listing_id):
        return {"status": "closed"}

    return ListingService(
        contributions,
        sqlite_client=store,
        seller_principal=CLAIMANT,
        settlement_composition=_Composition(),
        domain=_DOMAIN,
        capacity=_Capacity(),
        publish=publish,
        close=close,
        settlement_defaults=lambda: (),
        storefront_url="https://seller.example",
        **options,
    )


async def test_a_listing_is_the_bundles_mapping_of_the_request_over_its_quota_resource():
    store = _Store()

    result = await _service(
        store,
        escrow_mechanism="example.escrow.v1",
        release_conditions=lambda escrows: [{"chain_name": escrows[0]["chain_name"]}],
    ).publish_from_quota(resource_id="quota-a", accepted_escrows=[ESCROW], product="Example")

    assert result["registry_status"] == "published"
    (written,) = store.written
    assert written["listing_resource"]["product"] == "Example"
    assert written["listing_resource"]["quota"] == "quota-a"
    assert written["demands"] == [{"chain_name": "dev"}]
    assert written["binding"].physical_resource_id == "quota-a"


async def test_a_publication_guard_refuses_the_listing_before_anything_is_written():
    store = _Store()
    guarded = replace(
        EXAMPLE,
        publication_guards=(
            lambda resource: None,
            lambda resource: f"{resource['product']} is not sold here",
        ),
    )

    with pytest.raises(ValueError, match="Example is not sold here"):
        await _service(
            store, guarded, escrow_mechanism="example.escrow.v1"
        ).publish_from_quota(resource_id="quota-a", accepted_escrows=[ESCROW], product="Example")
    assert store.written == []


async def test_accepted_escrows_need_a_composed_escrow_mechanism():
    with pytest.raises(ValueError, match="publishes no accepted escrows"):
        await _service(_Store()).publish_from_quota(
            resource_id="quota-a", accepted_escrows=[ESCROW], product="Example"
        )
