import asyncio
import json

import httpx

from storefront_client.client import StorefrontClient, SyncStorefrontClient


class _CapturingAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            200,
            json={"status": "closed", "listing_id": "listing-abc"},
            request=request,
        )


class _CapturingSyncTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            200,
            json={"status": "closed", "listing_id": "listing-abc"},
            request=request,
        )


def test_async_close_listing_posts_to_versioned_path_param_route():
    async def _run() -> None:
        transport = _CapturingAsyncTransport()
        async with StorefrontClient("http://test", transport=transport) as client:
            resp = await client.close_listing("listing-abc")

        assert resp.status == "closed"
        assert resp.listing_id == "listing-abc"
        assert len(transport.requests) == 1
        request = transport.requests[0]
        assert request.method == "POST"
        assert str(request.url) == "http://test/api/v1/listings/listing-abc/close"
        assert json.loads(request.content) == {}

    asyncio.run(_run())


def test_sync_close_listing_posts_to_versioned_path_param_route():
    transport = _CapturingSyncTransport()
    with SyncStorefrontClient("http://test", transport=transport) as client:
        resp = client.close_listing("listing-abc")

    assert resp.status == "closed"
    assert resp.listing_id == "listing-abc"
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.method == "POST"
    assert str(request.url) == "http://test/api/v1/listings/listing-abc/close"
    assert json.loads(request.content) == {}
