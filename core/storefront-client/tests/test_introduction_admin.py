"""The operator's introduction-payload deletion, in both client variants."""

from __future__ import annotations

import asyncio
import inspect

import httpx
import pytest
from market_identity import (
    EMPTY_BODY,
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

from storefront_client import StorefrontClientError
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

_ADMIN = Ed25519Signer(bytes(range(32)))
_PUBLISHER = Ed25519Signer(bytes(range(1, 33)))
_REF = "ab" * 32
_RESULT = {
    "obligation_ref": _REF,
    "redacted": True,
    "payloads_deleted_at": "2026-10-01T12:00:00Z",
}
_PUBLISHERS = TrustedIdentitySet(identities=(_PUBLISHER.identity,))


def _respond(request: httpx.Request, status: int = 200, body=None) -> httpx.Response:
    payload = _RESULT if body is None else body
    signed = sign_response(
        signer=_PUBLISHER,
        envelope=ResponseEnvelope(
            role="seller",
            principal=_PUBLISHER.identity,
            method="DELETE",
            operation="admin_delete_introduction_payloads",
            resource=_REF,
            request_id=request.headers[REQUEST_ID_HEADER],
            timestamp=int(request.headers[TIMESTAMP_HEADER]),
            status=status,
            body_hash=canonical_body_hash(payload),
        ),
    )
    headers = {
        SIGNATURE_VERSION_HEADER: signed.protocol,
        IDENTITY_SCHEME_HEADER: signed.principal.scheme.value,
        IDENTITY_IDENTIFIER_HEADER: signed.principal.identifier,
        ROLE_HEADER: signed.role,
        REQUEST_ID_HEADER: signed.request_id,
        TIMESTAMP_HEADER: str(signed.timestamp),
        SIGNATURE_HEADER: signed.proof.value,
    }
    return httpx.Response(status, json=payload, headers=headers, request=request)


class _Async(httpx.AsyncBaseTransport):
    def __init__(self, status: int = 200, body=None) -> None:
        self.requests: list[httpx.Request] = []
        self._status, self._body = status, body

    async def handle_async_request(self, request):
        self.requests.append(request)
        return _respond(request, self._status, self._body)


class _Sync(httpx.BaseTransport):
    def __init__(self, status: int = 200, body=None) -> None:
        self.requests: list[httpx.Request] = []
        self._status, self._body = status, body

    def handle_request(self, request):
        self.requests.append(request)
        return _respond(request, self._status, self._body)


def _async_delete(transport: _Async) -> dict:
    async def run() -> dict:
        async with StorefrontClient(
            "http://test",
            signer=_ADMIN,
            caller_role="admin",
            expected_publishers=_PUBLISHERS,
            transport=transport,
        ) as client:
            return await client.admin_delete_introduction_payloads(
                _REF, request_id="delete-1"
            )

    return asyncio.run(run())


def _sync_delete(transport: _Sync) -> dict:
    with SyncStorefrontClient(
        "http://test",
        signer=_ADMIN,
        caller_role="admin",
        expected_publishers=_PUBLISHERS,
        transport=transport,
    ) as client:
        return client.admin_delete_introduction_payloads(_REF, request_id="delete-1")


def test_both_variants_sign_the_same_bodiless_delete(monkeypatch) -> None:
    monkeypatch.setattr("storefront_client.auth.time.time", lambda: 1_000)
    async_transport, sync_transport = _Async(), _Sync()
    assert _async_delete(async_transport) == _RESULT
    assert _sync_delete(sync_transport) == _RESULT

    async_request = async_transport.requests[0]
    sync_request = sync_transport.requests[0]
    assert async_request.method == sync_request.method == "DELETE"
    assert async_request.url.path == f"/api/v1/admin/introductions/{_REF}/payloads"
    assert async_request.content == sync_request.content == b""
    for name in AUTH_HEADERS:
        assert async_request.headers[name] == sync_request.headers[name]

    scheme = async_request.headers[IDENTITY_SCHEME_HEADER]
    verified = verify_request(
        AuthenticatedRequest(
            protocol=async_request.headers[SIGNATURE_VERSION_HEADER],
            role=async_request.headers[ROLE_HEADER],
            principal=Identity(
                scheme=scheme,
                identifier=async_request.headers[IDENTITY_IDENTIFIER_HEADER],
            ),
            method="DELETE",
            operation="admin_delete_introduction_payloads",
            resource=_REF,
            request_id=async_request.headers[REQUEST_ID_HEADER],
            timestamp=int(async_request.headers[TIMESTAMP_HEADER]),
            body_hash=canonical_body_hash(EMPTY_BODY),
            proof=SignatureProof(
                scheme=scheme, value=async_request.headers[SIGNATURE_HEADER]
            ),
        ),
        body=EMPTY_BODY,
        now=1_000,
        max_skew=0,
        expected_role="admin",
        expected_method="DELETE",
        expected_operation="admin_delete_introduction_payloads",
        expected_resource=_REF,
        expected_principals=TrustedIdentitySet(identities=(_ADMIN.identity,)),
    )
    assert verified.verified


def test_a_refused_delete_raises_with_its_status() -> None:
    refusal = {"detail": "contact exchange is disabled"}
    with pytest.raises(StorefrontClientError) as raised:
        _async_delete(_Async(status=404, body=refusal))
    assert raised.value.status_code == 404
    with pytest.raises(StorefrontClientError) as raised:
        _sync_delete(_Sync(status=404, body=refusal))
    assert raised.value.status_code == 404


def test_the_method_has_one_signature_in_both_variants() -> None:
    assert inspect.signature(
        StorefrontClient.admin_delete_introduction_payloads
    ) == inspect.signature(SyncStorefrontClient.admin_delete_introduction_payloads)
