"""Listing discovery and principal-owned mutation integration tests."""

from __future__ import annotations

import httpx
import pytest
from market_identity import TrustedIdentitySet

from registry_client import RegistryClient, RegistryClientError
from registry_client.models import (
    ListingListResponse,
    ListingRequest,
    ListingSummary,
    UpdateListingRequest,
)
from src.main import app


def _listing_request(listing_id: str | None = None, **offer_extras) -> ListingRequest:
    kwargs = {} if listing_id is None else {"listing_id": listing_id}
    return ListingRequest(
        offer={"gpu_model": "A100", "region": "us-west", **offer_extras},
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "USDC"},
                "rates": [{"field": "amount", "per": "hour", "value": "100"}],
            }
        ],
        max_duration_seconds=3600,
        storefront_url="http://localhost:8001/",
        **kwargs,
    )


class TestListOrders:
    async def test_empty_db_returns_empty_list(self, registry_client):
        result = await registry_client.list_listings(status=None)
        assert isinstance(result, ListingListResponse)
        assert result.listings == []

    async def test_open_order_appears_in_default_listing(
        self,
        registry_client,
        open_order,
    ):
        result = await registry_client.list_listings()
        assert open_order.listing_id in [str(item.id) for item in result.listings]

    async def test_summary_carries_stable_publisher_and_principal(
        self,
        registry_client,
        open_order,
        maker_signer,
    ):
        result = await registry_client.list_listings()
        listing = next(
            item for item in result.listings if str(item.id) == open_order.listing_id
        )
        assert listing.status == "open"
        assert listing.publisher_id == open_order.publisher_id
        assert listing.publisher_principals == TrustedIdentitySet(
            identities=(maker_signer.identity,)
        )
        assert listing.storefront_url == "http://localhost:8001/"


class TestGetOrder:
    async def test_returns_typed_order_summary(self, registry_client, open_order):
        listing = await registry_client.get_listing(open_order.listing_id)
        assert isinstance(listing, ListingSummary)
        assert str(listing.id) == open_order.listing_id

    async def test_404_raises_registry_client_error(self, registry_client):
        with pytest.raises(RegistryClientError) as exc_info:
            await registry_client.get_listing("nonexistent-order-id")
        assert exc_info.value.status_code == 404


class TestPublishOrder:
    async def test_publish_lazily_creates_publisher(
        self,
        registry_client,
        maker_signer,
    ):
        result = await registry_client.publish_listing(_listing_request("pub-1"))
        publishers = await registry_client.list_publishers(
            principal=maker_signer.identity
        )
        assert result["listing_id"] == "pub-1"
        assert publishers.publishers[0].publisher_id == result["publisher_id"]

    async def test_hosted_settlement_options_round_trip(self, registry_client):
        option = {
            "option_id": "a" * 64,
            "mechanism": "fiat.stripe.v1",
            "asset": "usd",
            "rates": [{"field": "amount", "per": "hour", "value": "125"}],
            "params": {"account_ref": "acct-seller"},
        }
        request = ListingRequest(
            listing_id="pub-hosted",
            offer={"gpu_model": "A100", "region": "us-west"},
            accepted_escrows=[],
            settlement_options=[option],
            storefront_url="http://localhost:8001/",
        )
        await registry_client.publish_listing(request)
        listing = await registry_client.get_listing("pub-hosted")
        assert listing.accepted_escrows == []
        assert listing.settlement_options == [option]

    async def test_republish_reuses_stable_publisher(self, registry_client):
        first = await registry_client.publish_listing(_listing_request("pub-a"))
        second = await registry_client.publish_listing(_listing_request("pub-b"))
        assert first["publisher_id"] == second["publisher_id"]

    async def test_unsigned_legacy_wire_is_rejected(self, registry_client):
        async with httpx.AsyncClient(
            base_url="http://test",
            transport=httpx.ASGITransport(app=app),
        ) as raw:
            response = await raw.post(
                "/listings",
                json={
                    **_listing_request("pub-unsigned").to_dict(),
                    "scheme": "eip191",
                    "identifier": "0x" + "11" * 20,
                    "signature": "0x" + "00" * 65,
                    "timestamp": 1,
                },
                headers={"X-Test-Unsigned": "1"},
            )
        assert response.status_code == 401


class TestListPublisherListings:
    async def test_returns_exact_principal_listings(
        self,
        registry_client,
        open_order,
        maker_signer,
    ):
        result = await registry_client.list_listings_for_publisher(
            maker_signer.identity,
            status=None,
        )
        assert open_order.listing_id in [str(item.id) for item in result.listings]

    async def test_different_scheme_principal_does_not_resolve(
        self,
        registry_client,
        ed25519_signer,
    ):
        principal = ed25519_signer.identity
        assert principal.scheme.value == "ed25519"
        result = await registry_client.list_listings_for_publisher(
            principal,
            status=None,
        )
        assert result.listings == []


class TestDeleteOrder:
    async def test_owner_signed_delete(self, registry_client, authenticated_open_order):
        await registry_client.delete_listing(authenticated_open_order.listing_id)
        with pytest.raises(RegistryClientError) as exc_info:
            await registry_client.get_listing(authenticated_open_order.listing_id)
        assert exc_info.value.status_code == 404

    async def test_non_owner_delete_rejected(
        self,
        registry_client,
        authenticated_open_order,
        taker_signer,
        registry_authority,
    ):
        async with RegistryClient(
            "http://test",
            transport=httpx.ASGITransport(app=app),
            signer=taker_signer,
            caller_role="seller",
            expected_registries=TrustedIdentitySet(
                identities=(registry_authority.identity,)
            ),
            registry_authority="test-registry",
        ) as other:
            with pytest.raises(RegistryClientError) as exc_info:
                await other.delete_listing(authenticated_open_order.listing_id)
        assert exc_info.value.status_code == 403

    async def test_nonexistent_raises_404(self, registry_client):
        with pytest.raises(RegistryClientError) as exc_info:
            await registry_client.delete_listing("nope")
        assert exc_info.value.status_code == 404


class TestUpdateOrderAuth:
    async def test_owner_signed_update_closed(
        self,
        registry_client,
        authenticated_open_order,
    ):
        result = await registry_client.update_listing(
            authenticated_open_order.listing_id,
            UpdateListingRequest(updates={"status": "closed"}),
        )
        assert result["status"] == "closed"

    async def test_non_owner_signature_rejected(
        self,
        registry_client,
        authenticated_open_order,
        taker_signer,
        registry_authority,
    ):
        async with RegistryClient(
            "http://test",
            transport=httpx.ASGITransport(app=app),
            signer=taker_signer,
            caller_role="seller",
            expected_registries=TrustedIdentitySet(
                identities=(registry_authority.identity,)
            ),
            registry_authority="test-registry",
        ) as other:
            with pytest.raises(RegistryClientError) as exc_info:
                await other.update_listing(
                    authenticated_open_order.listing_id,
                    UpdateListingRequest(updates={"status": "closed"}),
                )
        assert exc_info.value.status_code == 403


class TestOrderLifecycle:
    async def test_publish_list_get_update_delete(self, registry_client):
        published = await registry_client.publish_listing(_listing_request("life-1"))
        listing_id = published["listing_id"]
        assert any(
            str(item.id) == listing_id
            for item in (await registry_client.list_listings(status=None)).listings
        )
        assert (await registry_client.get_listing(listing_id)).status == "open"
        updated = await registry_client.update_listing(
            listing_id,
            UpdateListingRequest(updates={"status": "closed"}),
        )
        assert updated["status"] == "closed"
        await registry_client.delete_listing(listing_id)
        with pytest.raises(RegistryClientError):
            await registry_client.get_listing(listing_id)
