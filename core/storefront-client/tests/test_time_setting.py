"""The canonical client's time setting: what it signs and what it reads back."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
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
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
)
from storefront_client.client import StorefrontClient, StorefrontClientError

_ADMIN = Ed25519Signer(bytes(range(32)))
_STOREFRONT = Ed25519Signer(bytes(range(1, 33)))
_T = 1000
_LATER = 1794823200


def _storefront(status: int, body: dict, seen: list[AuthenticatedRequest]):
    """A storefront answering every request with ``status`` and ``body``,
    signed at the instant the body names, after recording what was signed."""

    def handler(request: httpx.Request) -> httpx.Response:
        principal = Identity(
            scheme=request.headers[IDENTITY_SCHEME_HEADER],
            identifier=request.headers[IDENTITY_IDENTIFIER_HEADER],
        )
        signed = AuthenticatedRequest(
            protocol=request.headers[SIGNATURE_VERSION_HEADER],
            role=request.headers[ROLE_HEADER],
            principal=principal,
            method=request.method,
            operation="admin_time",
            resource="time",
            request_id=request.headers[REQUEST_ID_HEADER],
            timestamp=int(request.headers[TIMESTAMP_HEADER]),
            body_hash=canonical_body_hash(json.loads(request.content)),
            proof=SignatureProof(
                scheme=principal.scheme, value=request.headers[SIGNATURE_HEADER]
            ),
        )
        seen.append(signed)
        response = sign_response(
            signer=_STOREFRONT,
            envelope=ResponseEnvelope(
                role="seller",
                principal=_STOREFRONT.identity,
                method=request.method,
                operation="admin_time",
                resource="time",
                request_id=signed.request_id,
                timestamp=int(body.get("now", signed.timestamp)),
                status=status,
                body_hash=canonical_body_hash(body),
            ),
        )
        return httpx.Response(
            status,
            json=body,
            headers={
                SIGNATURE_VERSION_HEADER: response.protocol,
                IDENTITY_SCHEME_HEADER: response.principal.scheme.value,
                IDENTITY_IDENTIFIER_HEADER: response.principal.identifier,
                ROLE_HEADER: response.role,
                REQUEST_ID_HEADER: response.request_id,
                TIMESTAMP_HEADER: str(response.timestamp),
                SIGNATURE_HEADER: response.proof.value,
            },
        )

    return httpx.MockTransport(handler)


def _client(transport) -> StorefrontClient:
    return StorefrontClient(
        "http://seller",
        signer=_ADMIN,
        caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(_STOREFRONT.identity,)),
        transport=transport,
    )


def test_set_time_signs_admin_time_over_the_instant_and_reads_the_answer(held_time):
    seen: list[AuthenticatedRequest] = []
    held_time.set(_LATER)
    transport = _storefront(200, {"source": "injected", "now": _LATER}, seen)

    async def run():
        async with _client(transport) as client:
            return await client.set_time(_LATER)

    answer = asyncio.run(run())

    assert (answer.source, answer.now) == ("injected", _LATER)
    (signed,) = seen
    assert (signed.role, signed.timestamp) == ("admin", _LATER)
    assert verify_request(
        signed,
        body={"now": _LATER},
        now=_LATER,
        max_skew=0,
        expected_role="admin",
        expected_method="POST",
        expected_operation="admin_time",
        expected_resource="time",
        expected_principals=TrustedIdentitySet(identities=(_ADMIN.identity,)),
    ).verified


@pytest.mark.parametrize(
    ("status", "code"), ((409, "time_moves_forward"), (422, "invalid_time"))
)
def test_a_refused_setting_raises_with_the_storefront_s_status(held_time, status, code):
    transport = _storefront(status, {"code": code, "detail": "refused"}, [])

    async def run():
        async with _client(transport) as client:
            await client.set_time(_T)

    with pytest.raises(StorefrontClientError) as refused:
        asyncio.run(run())

    assert refused.value.status_code == status
