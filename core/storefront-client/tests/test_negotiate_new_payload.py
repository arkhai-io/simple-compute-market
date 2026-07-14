import asyncio
import json

import httpx

from storefront_client.client import StorefrontClient, SyncStorefrontClient

_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"


class _CapturingAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"negotiation_id": "neg-1"}, request=request)


class _CapturingSyncTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"negotiation_id": "neg-1"}, request=request)


def test_async_negotiate_new_preserves_explicit_empty_literal_fields():
    async def _run() -> None:
        transport = _CapturingAsyncTransport()
        async with StorefrontClient(
            "http://test", private_key=_PRIVATE_KEY, transport=transport
        ) as client:
            await client.negotiate_new(
                listing_id="listing-1",
                buyer_address="0xbuyer",
                initial_amount=7,
                duration_seconds=3600,
                escrow_address="0x" + "11" * 20,
                literal_fields={},
            )

        body = json.loads(transport.requests[0].content)
        assert body["proposal"]["literal_fields"] == {}

    asyncio.run(_run())


def test_sync_negotiate_new_preserves_explicit_empty_literal_fields():
    transport = _CapturingSyncTransport()
    with SyncStorefrontClient(
        "http://test", private_key=_PRIVATE_KEY, transport=transport
    ) as client:
        client.negotiate_new(
            listing_id="listing-1",
            buyer_address="0xbuyer",
            initial_amount=7,
            duration_seconds=3600,
            escrow_address="0x" + "11" * 20,
            literal_fields={},
        )

    body = json.loads(transport.requests[0].content)
    assert body["proposal"]["literal_fields"] == {}
