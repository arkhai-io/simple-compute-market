import asyncio
import time

import httpx
import pytest
from market_identity import (
    Ed25519Signer,
    ResponseEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_response,
)

from storefront_client.auth import (
    AUTH_HEADERS,
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
)
from storefront_client.client import StorefrontClient, SyncStorefrontClient

_SIGNER = Ed25519Signer(bytes(range(32)))
_RESPONSE = {"status": "closed", "listing_id": "listing-abc"}


def _signed_response(request: httpx.Request) -> httpx.Response:
    authenticated = sign_response(
        signer=_SIGNER,
        envelope=ResponseEnvelope(
            role="seller",
            principal=_SIGNER.identity,
            method="POST",
            operation="close_listing",
            resource="listing-abc",
            request_id=request.headers[REQUEST_ID_HEADER],
            timestamp=int(time.time()),
            status=200,
            body_hash=canonical_body_hash(_RESPONSE),
        ),
    )
    headers = {
        SIGNATURE_VERSION_HEADER: authenticated.protocol,
        IDENTITY_SCHEME_HEADER: authenticated.principal.scheme.value,
        IDENTITY_IDENTIFIER_HEADER: authenticated.principal.identifier,
        ROLE_HEADER: authenticated.role,
        REQUEST_ID_HEADER: authenticated.request_id,
        TIMESTAMP_HEADER: str(authenticated.timestamp),
        SIGNATURE_HEADER: authenticated.proof.value,
    }
    return httpx.Response(200, json=_RESPONSE, headers=headers, request=request)


class _CapturingAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return _signed_response(request)


class _CapturingSyncTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return _signed_response(request)


def test_async_close_listing_posts_empty_body_to_versioned_route():
    async def _run() -> None:
        transport = _CapturingAsyncTransport()
        async with StorefrontClient(
            "http://test",
            signer=_SIGNER,
            caller_role="seller",
            expected_publishers=TrustedIdentitySet(
                identities=(_SIGNER.identity,)
            ),
            transport=transport,
        ) as client:
            resp = await client.close_listing("listing-abc", request_id="request-1")

        assert resp.status == "closed"
        assert resp.listing_id == "listing-abc"
        request = transport.requests[0]
        assert request.method == "POST"
        assert str(request.url) == "http://test/api/v1/listings/listing-abc/close"
        assert request.content == b""
        assert request.headers["X-Market-Role"] == "seller"
        assert request.headers["X-Market-Request-ID"] == "request-1"

    asyncio.run(_run())


def test_sync_close_listing_resigns_semantic_retry(monkeypatch):
    ticks = iter([1_000, 1_000, 1_000, 1_001, 1_001, 1_001])
    monkeypatch.setattr(
        "storefront_client.auth.time.time",
        lambda: next(ticks, 1_001),
    )
    transport = _CapturingSyncTransport()
    with SyncStorefrontClient(
        "http://test",
        signer=_SIGNER,
        caller_role="seller",
        expected_publishers=TrustedIdentitySet(
            identities=(_SIGNER.identity,)
        ),
        transport=transport,
    ) as client:
        resp = client.close_listing("listing-abc", request_id="request-1")
        client.close_listing("listing-abc", request_id="request-1")
        with pytest.raises(ValueError, match="changed request content"):
            client.close_listing("listing-other", request_id="request-1")

    assert resp.status == "closed"
    assert resp.listing_id == "listing-abc"
    first, retry = transport.requests
    assert first.method == "POST"
    assert str(first.url) == "http://test/api/v1/listings/listing-abc/close"
    assert first.content == b""
    assert first.headers["X-Market-Role"] == "seller"
    assert first.headers["X-Market-Request-ID"] == "request-1"
    for name in AUTH_HEADERS - {TIMESTAMP_HEADER, SIGNATURE_HEADER}:
        assert first.headers[name] == retry.headers[name]
    assert first.headers[TIMESTAMP_HEADER] == "1000"
    assert retry.headers[TIMESTAMP_HEADER] == "1001"
    assert first.headers[SIGNATURE_HEADER] != retry.headers[SIGNATURE_HEADER]
