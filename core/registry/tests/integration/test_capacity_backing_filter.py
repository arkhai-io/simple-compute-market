"""Capacity backing through the canonical `RegistryClient` and the real app.

A compute listing publishes whether an admission authority stands behind it,
and a buyer can filter on it exactly: a listing that does not publish the field
is excluded from both values rather than classified as either.
"""

from __future__ import annotations

import pytest

from registry_client import ListingRequest

pytestmark = pytest.mark.asyncio


def _listing(listing_id: str, backing: str | None) -> ListingRequest:
    resource = {"gpu_model": "H200", "region": "us-west", "offering_mode": "vm"}
    if backing is not None:
        resource["capacity_backing"] = backing
    return ListingRequest(
        listing_id=listing_id,
        listing_resource=resource,
        accepted_escrows=[
            {
                "chain_name": "anvil",
                # Development fixture addresses; never used on a public network.
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "22" * 20},
            }
        ],
        storefront_url="http://seller",
    )


async def _ids(registry_client, **filters) -> set[str]:
    page = await registry_client.list_listings(limit=100, **filters)
    return {str(row.id) for row in page.listings}


async def test_backed_and_unbacked_listings_share_one_catalogue(registry_client):
    await registry_client.publish_listing(_listing("backed-1", "backed"))
    await registry_client.publish_listing(_listing("unbacked-1", "unbacked"))
    await registry_client.publish_listing(_listing("predates-1", None))

    assert await _ids(registry_client, capacity_backing="backed") == {"backed-1"}
    assert await _ids(registry_client, capacity_backing="unbacked") == {"unbacked-1"}
    assert {"backed-1", "unbacked-1", "predates-1"} <= await _ids(registry_client)


async def test_the_published_value_round_trips(registry_client):
    await registry_client.publish_listing(_listing("unbacked-2", "unbacked"))

    fetched = await registry_client.get_listing("unbacked-2")

    assert fetched.listing_resource["capacity_backing"] == "unbacked"


async def test_a_listing_republished_with_its_backing_becomes_findable(
    registry_client,
):
    """Republication discloses the value for a listing that predates the field."""
    await registry_client.publish_listing(_listing("legacy-1", None))
    assert "legacy-1" not in await _ids(registry_client, capacity_backing="backed")

    await registry_client.publish_listing(_listing("legacy-1", "backed"))

    assert "legacy-1" in await _ids(registry_client, capacity_backing="backed")
