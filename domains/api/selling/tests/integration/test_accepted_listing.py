"""The listing a buyer accepted is recorded with the negotiation, against the storefront's real persistence."""

from __future__ import annotations

import pytest
from core_storefront.domain_registry import StorefrontDomainBindingError
from core_storefront.sqlite_client import SQLiteClient
from market_resource_pools import ResolvedPool
from market_resource_pools_contracts.backing import BACKED

from arkhai_api_selling.quota_listing import (
    QuotaPool,
    accepted_listing_resource,
    prepare_listing_binding,
    record_accepted_listing,
)
from tests.bundles import BUYER, CLAIMANT, DOMAIN, EXAMPLE


ACCEPTED = {"product": "alpha", "quota": "quota-a", "url": "https://alpha.example"}


async def _storefront(tmp_path) -> SQLiteClient:
    client = SQLiteClient(str(tmp_path / "storefront.db"))
    binding = prepare_listing_binding(
        EXAMPLE,
        listing_id="L-1",
        site_id="quota",
        listing_resource=ACCEPTED,
        pool=QuotaPool("default", ResolvedPool(BACKED, frozenset({"example"}), True)),
        domain=DOMAIN,
    )
    await client.upsert_listing_with_binding(
        binding=binding,
        status="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        listing_resource={**ACCEPTED, "offering_mode": "example"},
        fulfillment_resource=None,
        max_duration_seconds=None,
        storefront_url="https://seller.example",
        seller_principal=CLAIMANT,
    )
    for negotiation_id in ("neg-recorded", "neg-before-recording"):
        await client.create_negotiation_thread(
            negotiation_id=negotiation_id,
            our_listing_id="L-1",
            their_listing_id="buyer-listing",
            our_agent_id="https://seller.example",
            their_agent_id="https://buyer.example",
            buyer_principal=BUYER,
            seller_principal=CLAIMANT,
            owner_id="seller",
        )
    return client


async def _republish_in_place(client: SQLiteClient, **changes) -> None:
    await client.update_listing(listing_id="L-1", listing_resource={**ACCEPTED, "offering_mode": "example", **changes})


async def test_a_listing_changed_after_acceptance_does_not_change_what_was_accepted(tmp_path):
    client = await _storefront(tmp_path)
    await record_accepted_listing(
        EXAMPLE, client, domain=DOMAIN, negotiation_id="neg-recorded", listing_id="L-1",
        listing_record=await client.load_listing(listing_id="L-1"),
    )

    # Another service under the same quota resource: the source check cannot see it.
    await _republish_in_place(client, product="beta", url="https://beta.example")

    accepted = await accepted_listing_resource(
        EXAMPLE, client, domain=DOMAIN, negotiation_id="neg-recorded", listing_id="L-1"
    )
    assert (accepted["product"], accepted["quota"], accepted["url"]) == (
        "alpha", "quota-a", "https://alpha.example",
    )


async def test_a_negotiation_accepted_before_recording_reads_the_stored_listing(tmp_path):
    client = await _storefront(tmp_path)
    await _republish_in_place(client, product="beta")

    accepted = await accepted_listing_resource(
        EXAMPLE, client, domain=DOMAIN, negotiation_id="neg-before-recording", listing_id="L-1"
    )
    assert accepted["product"] == "beta"


async def test_the_record_is_written_once(tmp_path):
    client = await _storefront(tmp_path)
    record = await client.load_listing(listing_id="L-1")
    await record_accepted_listing(EXAMPLE, client, domain=DOMAIN, negotiation_id="neg-recorded", listing_id="L-1", listing_record=record)
    await record_accepted_listing(EXAMPLE, client, domain=DOMAIN, negotiation_id="neg-recorded", listing_id="L-1", listing_record=record)

    await _republish_in_place(client, product="beta")
    with pytest.raises(StorefrontDomainBindingError, match="conflicts with durable state"):
        await record_accepted_listing(
            EXAMPLE, client, domain=DOMAIN, negotiation_id="neg-recorded", listing_id="L-1",
            listing_record=await client.load_listing(listing_id="L-1"),
        )


async def test_a_bound_negotiation_without_its_record_is_refused(tmp_path):
    client = await _storefront(tmp_path)
    await client.copy_listing_binding_to_thread(negotiation_id="neg-recorded", listing_id="L-1")

    with pytest.raises(ValueError, match="no record of its accepted listing"):
        await accepted_listing_resource(
            EXAMPLE, client, domain=DOMAIN, negotiation_id="neg-recorded", listing_id="L-1"
        )


async def test_a_bound_negotiation_is_refused_for_another_listing(tmp_path):
    client = await _storefront(tmp_path)
    await record_accepted_listing(
        EXAMPLE, client, domain=DOMAIN, negotiation_id="neg-recorded", listing_id="L-1",
        listing_record=await client.load_listing(listing_id="L-1"),
    )

    with pytest.raises(ValueError, match="accepted listing 'L-1', not 'L-2'"):
        await accepted_listing_resource(
            EXAMPLE, client, domain=DOMAIN, negotiation_id="neg-recorded", listing_id="L-2"
        )
