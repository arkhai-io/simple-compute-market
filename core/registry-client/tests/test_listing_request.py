"""Listing publication request wire compatibility."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

from market_identity import Ed25519Signer, TrustedIdentitySet
from registry_client import ListingRequest, RegistryClient, SyncRegistryClient


def _client_kwargs() -> dict:
    signer = Ed25519Signer(bytes(range(32)))
    return {
        "signer": signer,
        "caller_role": "seller",
        "expected_registries": TrustedIdentitySet(identities=(signer.identity,)),
        "registry_authority": "registry-test",
    }


def test_optional_status_preserves_the_existing_positional_wire_shape() -> None:
    request = ListingRequest(
        {"gpu_model": "A100", "region": "dev-west"},
        [{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20}],
        [{"option_id": "option-one", "mechanism": "alkahest.ethereum.v1"}],
        [{"field": "region", "value": "dev-west"}],
        3600,
        "listing-one",
        "http://storefront.test/",
        status=None,
    )

    assert request.to_dict() == {
        "listing_id": "listing-one",
        "offer_resource": {"gpu_model": "A100", "region": "dev-west"},
        "accepted_escrows": [
            {"chain_name": "anvil", "escrow_address": "0x" + "11" * 20}
        ],
        "settlement_options": [
            {"option_id": "option-one", "mechanism": "alkahest.ethereum.v1"}
        ],
        "demands": [{"field": "region", "value": "dev-west"}],
        "max_duration_seconds": 3600,
        "storefront_url": "http://storefront.test/",
    }


def test_explicit_open_status_is_serialized() -> None:
    request = ListingRequest(
        offer={"gpu_model": "A100"},
        accepted_escrows=[],
        listing_id="listing-open",
        storefront_url="http://storefront.test/",
        status="open",
    )

    assert request.to_dict()["status"] == "open"


def test_async_client_publishes_the_real_optional_status_body() -> None:
    async def run() -> None:
        client = RegistryClient("http://registry.test", **_client_kwargs())
        send = AsyncMock(return_value={"listing_id": "listing-async"})
        client._request = send
        try:
            result = await client.publish_listing(
                ListingRequest(
                    offer={"gpu_model": "A100"},
                    accepted_escrows=[],
                    listing_id="listing-async",
                    storefront_url="http://storefront.test/",
                    status="open",
                ),
                request_id="request-async",
                timestamp=123,
            )
        finally:
            await client.close()

        assert result == {"listing_id": "listing-async"}
        assert send.await_args.kwargs["json"]["status"] == "open"
        assert send.await_args.kwargs["json"]["listing_id"] == "listing-async"

    asyncio.run(run())


def test_sync_client_omits_unset_status_from_the_real_publish_body() -> None:
    client = SyncRegistryClient("http://registry.test", **_client_kwargs())
    send = Mock(return_value={"listing_id": "listing-sync"})
    client._request = send
    try:
        result = client.publish_listing(
            ListingRequest(
                offer={"gpu_model": "A100"},
                accepted_escrows=[],
                listing_id="listing-sync",
                storefront_url="http://storefront.test/",
            ),
            request_id="request-sync",
            timestamp=123,
        )
    finally:
        client.close()

    assert result == {"listing_id": "listing-sync"}
    assert send.call_args.kwargs["json"] == {
        "listing_id": "listing-sync",
        "offer_resource": {"gpu_model": "A100"},
        "accepted_escrows": [],
        "settlement_options": [],
        "demands": [],
        "max_duration_seconds": None,
        "storefront_url": "http://storefront.test/",
    }
