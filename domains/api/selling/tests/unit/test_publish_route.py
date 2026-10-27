"""The seller publish-from-quota clients sign the request the route authenticates."""

from __future__ import annotations

import inspect

from market_identity import Ed25519Signer

from arkhai_api_selling.publish_route import (
    PUBLISH_FROM_QUOTA_OPERATION,
    PUBLISH_FROM_QUOTA_PATH,
    ListingClient,
    PublishFromQuotaRequest,
    SyncListingClient,
    seller_resource,
)

# A deterministic development key; never used on any network.
SELLER = Ed25519Signer(b"\x22" * 32).identity
REQUEST = {"resource_id": "quota-a", "product": "Example"}
RESPONSE = {"status": "created", "listing_id": "listing-1"}


class ExampleRequest(PublishFromQuotaRequest):
    product: str


class _Recording:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    def authenticated_request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return RESPONSE


class _AsyncRecording(_Recording):
    async def authenticated_request(self, *args, **kwargs):
        return super().authenticated_request(*args, **kwargs)


def _public_methods(cls) -> dict[str, inspect.Signature]:
    return {
        name: inspect.signature(member)
        for name, member in vars(cls).items()
        if callable(member) and not name.startswith("_")
    }


def test_sync_and_async_clients_offer_the_same_methods():
    assert _public_methods(ListingClient) == _public_methods(SyncListingClient)


async def test_both_clients_sign_as_the_seller_on_its_own_principal():
    sync_transport, async_transport = _Recording(), _AsyncRecording()

    sync_result = SyncListingClient(
        sync_transport, seller=SELLER, request_model=ExampleRequest
    ).publish_from_quota(REQUEST, request_id="r-1")
    async_result = await ListingClient(
        async_transport, seller=SELLER, request_model=ExampleRequest
    ).publish_from_quota(REQUEST, request_id="r-1")

    assert sync_result == async_result
    assert sync_result.listing_id == "listing-1"
    assert sync_transport.calls == async_transport.calls
    ((args, kwargs),) = sync_transport.calls
    assert args == ("POST", PUBLISH_FROM_QUOTA_PATH)
    assert kwargs["role"] == "seller"
    assert kwargs["operation"] == PUBLISH_FROM_QUOTA_OPERATION
    assert kwargs["resource"] == seller_resource(SELLER)
    assert kwargs["body"]["resource_id"] == "quota-a"
    assert kwargs["body"]["product"] == "Example"
    assert kwargs["request_id"] == "r-1"


def test_a_request_hands_the_mapping_only_what_describes_the_listing():
    request = ExampleRequest(resource_id="quota-a", product="Example", paused=True)

    assert request.listing_request() == {"product": "Example"}
