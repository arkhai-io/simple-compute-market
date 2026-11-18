"""A seller publishes a model-card listing from its quota, which closes when sold out and reopens."""

from __future__ import annotations

import pytest
from storefront_client.client import StorefrontClientError

from inference_storefront import container
from tests.cards import model_card
from tests.integration.conftest import ESCROW, SELLER_SIGNER, SITE, running


def _publish_request(**card_fields):
    return {
        "resource_id": "svc-quota",
        "accepted_escrows": [dict(ESCROW)],
        "model_card": model_card(**card_fields),
    }


async def test_a_published_listing_and_its_registry_publication_carry_the_card(
    storefront, quota_site, registries, monkeypatch
):
    async with running(monkeypatch) as clients:
        created = await clients.seller.publish_from_quota(_publish_request())
        listing = await clients.public.get_listing(created.listing_id)

    assert created.status == "created"
    card = listing.listing_resource
    assert card["served_model_name"] == "stub-instruct"
    assert (card["resource_id"], card["capacity_site_id"], card["offering_mode"]) == (
        "svc-quota",
        SITE,
        "inference",
    )
    assert card["rate_card"]["request_credits"] == "3"
    (published,) = registries.published
    assert published.listing_id == created.listing_id
    assert published.listing_resource == card


async def test_a_quota_with_no_units_is_refused(storefront, quota_site, registries, monkeypatch):
    quota_site.units["svc-quota"] = 0
    async with running(monkeypatch) as clients:
        with pytest.raises(StorefrontClientError) as refused:
            await clients.seller.publish_from_quota(_publish_request())

    assert refused.value.status_code == 400
    assert "no sellable units" in str(refused.value)
    assert registries.published == []


async def test_a_sold_out_listing_closes_and_reopens_when_its_quota_is_replenished(
    storefront, quota_site, registries, monkeypatch
):
    async with running(monkeypatch) as clients:
        created = await clients.seller.publish_from_quota(_publish_request())
        db = container.resolved_sqlite_client

        closed = await container.QUOTA_PUBLICATION.close_after_capacity_change(
            db, {(SITE, "svc-quota"): 0}
        )
        sold_out = await clients.public.get_listing(created.listing_id)
        reopened = await container.QUOTA_PUBLICATION.reopen_after_capacity_change(
            db, {(SITE, "svc-quota"): 42}
        )
        replenished = await clients.public.get_listing(created.listing_id)

    assert closed == [created.listing_id]
    assert sold_out.status == "closed"
    assert reopened == [created.listing_id]
    assert replenished.status == "open"
    # The reopen's last word to the registry reopens the listing.
    assert registries.published[-1].updates == {"status": "open"}


async def test_the_sweep_closes_an_unheld_inference_listing_and_leaves_an_api_credit_one(
    storefront, quota_site, registries, monkeypatch
):
    """The registry is read under the storefront's own identity, which another
    storefront may publish under too: only this one's offering mode is swept."""
    async with running(monkeypatch) as clients:
        created = await clients.seller.publish_from_quota(_publish_request())
        registries.plant(created.listing_id, "inference")
        registries.plant("inference-unheld", "inference")
        registries.plant("credits-1", "api_credits")

        await container.QUOTA_PUBLICATION.retire_unheld(container.resolved_sqlite_client)
        held = await clients.public.get_listing(created.listing_id)

    assert [item.id for item in registries.open] == [created.listing_id, "credits-1"]
    assert registries.publisher_reads == [SELLER_SIGNER.identity]
    assert held.status == "open"
