import asyncio
import json

import httpx
import pytest

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


def test_async_negotiate_new_round_trips_schema_opaque_envelope():
    async def _run() -> None:
        transport = _CapturingAsyncTransport()
        envelope = {
            "kind": "api_credits.v1",
            "version": 1,
            "payload": {"quantity": 9, "key": {"mode": "new"}},
        }
        async with StorefrontClient(
            "http://test", private_key=_PRIVATE_KEY, transport=transport
        ) as client:
            await client.negotiate_new(
                listing_id="listing-1",
                buyer_address="0xbuyer",
                initial_amount=7,
                provision_terms=envelope,
                escrow_address="0x" + "11" * 20,
                literal_fields={},
            )

        body = json.loads(transport.requests[0].content)
        assert body["provision_terms"] == envelope
        assert body["proposal"]["literal_fields"] == {}

    asyncio.run(_run())


def test_sync_negotiate_new_round_trips_vm_envelope():
    transport = _CapturingSyncTransport()
    envelope = {
        "kind": "compute.v1",
        "version": 1,
        "payload": {"duration_seconds": 3600, "ssh_public_key": "ssh-ed25519 x"},
    }
    with SyncStorefrontClient(
        "http://test", private_key=_PRIVATE_KEY, transport=transport
    ) as client:
        client.negotiate_new(
            listing_id="listing-1",
            buyer_address="0xbuyer",
            initial_amount=7,
            provision_terms=envelope,
            escrow_address="0x" + "11" * 20,
            literal_fields={},
        )

    body = json.loads(transport.requests[0].content)
    assert body["provision_terms"] == envelope
    assert body["proposal"]["literal_fields"] == {}


@pytest.mark.parametrize(
    "legacy",
    [
        {"duration_seconds": 60, "ssh_public_key": ""},
        {"kind": "compute.v1", "payload": {"duration_seconds": 60}},
        {"kind": "compute.v1", "version": 0, "payload": {}},
    ],
)
def test_sync_client_rejects_legacy_or_incompatible_envelope_before_http(legacy):
    transport = _CapturingSyncTransport()
    with SyncStorefrontClient(
        "http://test", private_key=_PRIVATE_KEY, transport=transport
    ) as client:
        with pytest.raises(ValueError):
            client.negotiate_new(
                listing_id="listing-1",
                buyer_address="0xbuyer",
                initial_amount=7,
                provision_terms=legacy,
            )
    assert transport.requests == []
