import asyncio
import json

import httpx
from market_identity import (
    AuthenticatedRequest,
    Ed25519Signer,
    Identity,
    ResponseEnvelope,
    SignatureProof,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_response,
    verify_request,
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
_PUBLISHER = Ed25519Signer(bytes(range(1, 33)))
_RESPONSE = {
    "capacity_reservation_id": "reservation-1",
    "state": "released",
}

def _signed_response(request):
    authenticated = sign_response(
        signer=_PUBLISHER,
        envelope=ResponseEnvelope(
            role="seller",
            principal=_PUBLISHER.identity,
            method="POST",
            operation="fulfillment_capacity_released",
            resource="reservation-1",
            request_id=request.headers[REQUEST_ID_HEADER],
            timestamp=int(request.headers[TIMESTAMP_HEADER]),
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


def _signed_create_response(request):
    body = {"status": "created", "listing_id": "listing-1"}
    authenticated = sign_response(
        signer=_PUBLISHER,
        envelope=ResponseEnvelope(
            role="seller",
            principal=_PUBLISHER.identity,
            method="POST",
            operation="create_listing",
            resource="",
            request_id=request.headers[REQUEST_ID_HEADER],
            timestamp=int(request.headers[TIMESTAMP_HEADER]),
            status=200,
            body_hash=canonical_body_hash(body),
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
    return httpx.Response(200, json=body, headers=headers, request=request)


class _AsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        return _signed_response(request)


class _SyncTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.requests = []

    def handle_request(self, request):
        self.requests.append(request)
        return _signed_response(request)



class _AsyncCreateTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        return _signed_create_response(request)


class _SyncCreateTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.requests = []

    def handle_request(self, request):
        self.requests.append(request)
        return _signed_create_response(request)

def _envelope(request, body):
    scheme = request.headers[IDENTITY_SCHEME_HEADER]
    return AuthenticatedRequest(
        protocol=request.headers[SIGNATURE_VERSION_HEADER],
        role=request.headers[ROLE_HEADER],
        principal=Identity(
            scheme=scheme,
            identifier=request.headers[IDENTITY_IDENTIFIER_HEADER],
        ),
        method=request.method,
        operation="fulfillment_capacity_released",
        resource="reservation-1",
        request_id=request.headers[REQUEST_ID_HEADER],
        timestamp=int(request.headers[TIMESTAMP_HEADER]),
        body_hash=canonical_body_hash(body),
        proof=SignatureProof(
            scheme=scheme,
            value=request.headers[SIGNATURE_HEADER],
        ),
    )


def test_capacity_release_sync_async_contract_is_byte_equivalent(monkeypatch):
    monkeypatch.setattr("storefront_client.auth.time.time", lambda: 1_000)
    async_transport = _AsyncTransport()
    sync_transport = _SyncTransport()
    kwargs = {
        "site_id": "site-1",
        "resource_id": "resource-1",
        "provider_lease_id": None,
        "released_at": "2026-08-11T00:00:00Z",
        "request_id": "callback-1",
    }

    async def _run():
        async with StorefrontClient(
            "http://test",
            signer=_SIGNER,
            caller_role="service",
            expected_publishers=TrustedIdentitySet(
                identities=(_PUBLISHER.identity,)
            ),
            transport=async_transport,
        ) as client:
            await client.notify_capacity_released("reservation-1", **kwargs)

    asyncio.run(_run())
    with SyncStorefrontClient(
        "http://test",
        signer=_SIGNER,
        caller_role="service",
        expected_publishers=TrustedIdentitySet(
            identities=(_PUBLISHER.identity,)
        ),
        transport=sync_transport,
    ) as client:
        client.notify_capacity_released("reservation-1", **kwargs)

    async_request = async_transport.requests[0]
    sync_request = sync_transport.requests[0]
    body = json.loads(async_request.content)
    assert body == {
        "capacity_reservation_id": "reservation-1",
        "site_id": "site-1",
        "released_at": "2026-08-11T00:00:00Z",
        "resource_id": "resource-1",
    }
    assert async_request.content == sync_request.content
    assert async_request.headers[ROLE_HEADER] == "service"
    assert async_request.headers[REQUEST_ID_HEADER] == "callback-1"
    for name in AUTH_HEADERS:
        assert async_request.headers[name] == sync_request.headers[name]

    result = verify_request(
        _envelope(async_request, body),
        body=body,
        now=1_000,
        max_skew=0,
        expected_role="service",
        expected_method="POST",
        expected_operation="fulfillment_capacity_released",
        expected_resource="reservation-1",
        expected_principals=TrustedIdentitySet(
            identities=(_SIGNER.identity,)
        ),
    )
    assert result.verified


def test_create_listing_settlement_config_sync_async_contract_is_byte_equivalent(
    monkeypatch,
):
    monkeypatch.setattr("storefront_client.auth.time.time", lambda: 1_000)
    async_transport = _AsyncCreateTransport()
    sync_transport = _SyncCreateTransport()
    settlement_config = {"mechanism_payload": {"opaque": ["shape"]}}
    kwargs = {
        "offer": {"gpu_model": "H200", "gpu_count": 1},
        "settlement_config": settlement_config,
        "request_id": "create-1",
    }

    async def _run():
        async with StorefrontClient(
            "http://test",
            signer=_SIGNER,
            caller_role="seller",
            expected_publishers=TrustedIdentitySet(
                identities=(_SIGNER.identity, _PUBLISHER.identity)
            ),
            transport=async_transport,
        ) as client:
            await client.create_listing(**kwargs)

    asyncio.run(_run())
    with SyncStorefrontClient(
        "http://test",
        signer=_SIGNER,
        caller_role="seller",
        expected_publishers=TrustedIdentitySet(
            identities=(_SIGNER.identity, _PUBLISHER.identity)
        ),
        transport=sync_transport,
    ) as client:
        client.create_listing(**kwargs)

    async_request = async_transport.requests[0]
    sync_request = sync_transport.requests[0]
    body = json.loads(async_request.content)
    assert body == {
        "accepted_escrows": [],
        "demands": [],
        "max_duration_seconds": None,
        "offer": {"gpu_count": 1, "gpu_model": "H200"},
        "paused": False,
        "settlement_config": settlement_config,
        "settlement_options": [],
    }
    assert async_request.content == sync_request.content
    for name in AUTH_HEADERS:
        assert async_request.headers[name] == sync_request.headers[name]

    envelope = _envelope(async_request, body).model_copy(
        update={"operation": "create_listing", "resource": ""}
    )
    result = verify_request(
        envelope,
        body=body,
        now=1_000,
        max_skew=0,
        expected_role="seller",
        expected_method="POST",
        expected_operation="create_listing",
        expected_resource="",
        expected_principals=TrustedIdentitySet(
            identities=(_SIGNER.identity,)
        ),
    )
    assert result.verified
