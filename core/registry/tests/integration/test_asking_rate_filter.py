"""Asking rates through the canonical `RegistryClient` and the real app.

The compute spec publishes a seller's asking rate as exact decimal text with
the asset and period it is quoted in. A rate bound compares exactly, matches
only listings quoted in the named asset and period, and is refused by the
registry itself when supplied without them.
"""

from __future__ import annotations

import pytest
from market_core.schemas import derive_settlement_option_id

from registry_client import ListingRequest, RegistryClientError, compile_resource_query

pytestmark = pytest.mark.asyncio


def _listing(
    listing_id: str,
    amount: str | None,
    *,
    asset: str = "usd",
    period: str = "hour",
) -> ListingRequest:
    resource: dict = {"gpu_model": "H200", "region": "us-west", "offering_mode": "vm"}
    if amount is not None:
        resource["asking_rate"] = {"amount": amount, "asset": asset, "period": period}
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


async def _ids(registry_client, source: str) -> set[str]:
    spec = await registry_client.get_filter_spec()
    compiled = compile_resource_query(
        source, filter_spec=spec, registry_url="http://test"
    )
    page = await registry_client.list_listings(
        limit=100, etag=compiled.etag, **compiled.as_params()
    )
    return {str(row.id) for row in page.listings}


async def test_a_rate_bound_compares_exact_decimal_text(registry_client):
    # Differ only past the 17th significant digit, where a double cannot.
    await registry_client.publish_listing(_listing("at", "16.00000000000000000"))
    await registry_client.publish_listing(_listing("above", "16.00000000000000001"))

    under = await _ids(
        registry_client,
        "asking_rate<=16 asking_rate_asset=usd asking_rate_period=hour",
    )

    assert under == {"at"}


async def test_a_lower_bound_reads_the_same_amount(registry_client):
    await registry_client.publish_listing(_listing("cheap", "0.10"))
    await registry_client.publish_listing(_listing("dear", "9.50"))

    over = await _ids(
        registry_client,
        "asking_rate_min>=1 asking_rate_asset=usd asking_rate_period=hour",
    )

    assert over == {"dear"}


async def test_another_asset_or_a_missing_rate_is_excluded(registry_client):
    await registry_client.publish_listing(_listing("usd-1", "2.10"))
    await registry_client.publish_listing(_listing("eur-1", "1.00", asset="eur"))
    await registry_client.publish_listing(_listing("rateless-1", None))

    matched = await _ids(
        registry_client,
        "asking_rate<=100 asking_rate_asset=usd asking_rate_period=hour",
    )

    assert matched == {"usd-1"}
    # Unbounded, every listing stays discoverable.
    page = await registry_client.list_listings(limit=100)
    assert {"usd-1", "eur-1", "rateless-1"} <= {str(row.id) for row in page.listings}


async def test_the_registry_refuses_a_bound_without_its_asset_and_period(
    registry_client,
):
    """The client's `list_listings` does not compile its filters, so this is
    the registry's own refusal, not the buyer compiler's."""
    with pytest.raises(RegistryClientError) as caught:
        await registry_client.list_listings(asking_rate_max="16")

    assert caught.value.status_code == 400
    assert "asking_rate_asset" in caught.value.body


async def test_the_published_rate_round_trips(registry_client):
    await registry_client.publish_listing(_listing("round-1", "16.00"))

    fetched = await registry_client.get_listing("round-1")

    assert fetched.listing_resource["asking_rate"] == {
        "amount": "16.00",
        "asset": "usd",
        "period": "hour",
    }


def _introduction_listing(listing_id: str, amount: str) -> ListingRequest:
    """A listing whose only settlement option is a rateless introduction.

    The option is built as the contact-exchange mechanism publishes it: no
    rates, its identity derived from mechanism, asset, rates, and params. The
    mechanism's name and asset are stated here rather than imported, because the
    registry depends on no settlement mechanism.
    """
    params = {"profile": "default", "channel": "email", "terms": "introduction only"}
    option = {
        "option_id": derive_settlement_option_id(
            mechanism="contact-exchange.v1", asset="introduction", rates=[], params=params
        ),
        "mechanism": "contact-exchange.v1",
        "asset": "introduction",
        "rates": [],
        "params": params,
    }
    return ListingRequest(
        listing_id=listing_id,
        listing_resource={
            "gpu_model": "H200",
            "region": "us-west",
            "offering_mode": "bare_metal",
            "capacity_backing": "unbacked",
            "asking_rate": {"amount": amount, "asset": "usd", "period": "hour"},
        },
        accepted_escrows=[],
        settlement_options=[option],
        storefront_url="http://seller",
    )


async def test_a_rateless_introduction_listing_is_found_by_its_asking_rate(
    registry_client,
):
    """Supply that settles by introduction carries no settlement rate, so its
    asking rate is the only price a buyer can compare it on."""
    await registry_client.publish_listing(_introduction_listing("intro-1", "4.00"))

    matched = await _ids(
        registry_client,
        "asking_rate<=5 asking_rate_asset=usd asking_rate_period=hour",
    )
    fetched = await registry_client.get_listing("intro-1")

    assert matched == {"intro-1"}
    (option,) = fetched.settlement_options
    assert option["rates"] == []
    assert fetched.listing_resource["asking_rate"]["amount"] == "4.00"
