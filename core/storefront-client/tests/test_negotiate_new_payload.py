import asyncio
import json

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
_PUBLISHER = Ed25519Signer(bytes(range(1, 33)))
_RESPONSE = {"negotiation_id": "neg-1"}


def _signed_response(request: httpx.Request) -> httpx.Response:
    authenticated = sign_response(
        signer=_PUBLISHER,
        envelope=ResponseEnvelope(
            role="seller",
            principal=_PUBLISHER.identity,
            method="POST",
            operation="negotiate_new",
            resource="listing-1",
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


def _negotiate_kwargs(envelope):
    return {
        "listing_id": "listing-1",
        "initial_amount": 7,
        "provision_terms": envelope,
        "escrow_address": "0x" + "11" * 20,
        "literal_fields": {},
        "request_id": "request-1",
    }


def test_async_and_sync_negotiate_new_are_byte_equivalent(monkeypatch):
    monkeypatch.setattr("storefront_client.auth.time.time", lambda: 1_000)
    monkeypatch.setattr("storefront_client.client.time.time", lambda: 1_000)
    envelope = {
        "kind": "compute.v1",
        "version": 1,
        "payload": {"duration_seconds": 3600, "ssh_public_key": "ssh-ed25519 x"},
    }
    async_transport = _CapturingAsyncTransport()
    sync_transport = _CapturingSyncTransport()

    async def _run() -> None:
        async with StorefrontClient(
            "http://test",
            signer=_SIGNER,
            caller_role="buyer",
            expected_publishers=TrustedIdentitySet(
                identities=(_PUBLISHER.identity,)
            ),
            transport=async_transport,
        ) as client:
            await client.negotiate_new(**_negotiate_kwargs(envelope))

    asyncio.run(_run())
    with SyncStorefrontClient(
        "http://test",
        signer=_SIGNER,
        caller_role="buyer",
        expected_publishers=TrustedIdentitySet(
            identities=(_PUBLISHER.identity,)
        ),
        transport=sync_transport,
    ) as client:
        client.negotiate_new(**_negotiate_kwargs(envelope))

    async_request = async_transport.requests[0]
    sync_request = sync_transport.requests[0]
    assert async_request.content == sync_request.content
    assert async_request.content == json.dumps(
        json.loads(async_request.content),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    for name in AUTH_HEADERS:
        assert async_request.headers[name] == sync_request.headers[name]
    body = json.loads(async_request.content)
    assert body["provision_terms"] == envelope
    assert body["proposal"]["literal_fields"] == {}
    assert body["buyer_principal"] == _SIGNER.identity.model_dump(mode="json")
    assert "buyer_address" not in body


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
        "http://test",
        signer=_SIGNER,
        caller_role="buyer",
        expected_publishers=TrustedIdentitySet(
            identities=(_PUBLISHER.identity,)
        ),
        transport=transport,
    ) as client:
        with pytest.raises(ValueError):
            client.negotiate_new(
                listing_id="listing-1",
                initial_amount=7,
                provision_terms=legacy,
            )
    assert transport.requests == []


_SELECTION = {"mechanism": "fiat.stripe.v1", "option_id": "a" * 64, "expiration_unix": 2_000}


def _selection_kwargs(envelope, **overrides):
    return {
        "listing_id": "listing-1",
        "initial_amount": None,
        "provision_terms": envelope,
        "proposal_fields": {"amount": "180"},
        "settlement_selection": _SELECTION,
        "selection_only": True,
        "request_id": "request-1",
        **overrides,
    }


_ENVELOPE = {
    "kind": "bare_metal.v2",
    "version": 1,
    "payload": {"duration_seconds": 3600, "ssh_public_key": "ssh-ed25519 x"},
}


def test_a_selection_only_opening_carries_no_escrow_and_is_identical_in_both_clients(
    monkeypatch,
):
    monkeypatch.setattr("storefront_client.auth.time.time", lambda: 1_000)
    async_transport = _CapturingAsyncTransport()
    sync_transport = _CapturingSyncTransport()
    publishers = TrustedIdentitySet(identities=(_PUBLISHER.identity,))

    async def _run() -> None:
        async with StorefrontClient(
            "http://test", signer=_SIGNER, caller_role="buyer",
            expected_publishers=publishers, transport=async_transport,
        ) as client:
            await client.negotiate_new(**_selection_kwargs(_ENVELOPE))

    asyncio.run(_run())
    with SyncStorefrontClient(
        "http://test", signer=_SIGNER, caller_role="buyer",
        expected_publishers=publishers, transport=sync_transport,
    ) as client:
        client.negotiate_new(**_selection_kwargs(_ENVELOPE))

    assert async_transport.requests[0].content == sync_transport.requests[0].content
    body = json.loads(async_transport.requests[0].content)
    assert body["proposal"] == {"fields": {"amount": "180"}}
    assert body["settlement_selection"] == _SELECTION


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"settlement_selection": None}, id="no selection"),
        pytest.param({"chain_name": "anvil"}, id="chain"),
        pytest.param({"escrow_address": "0x" + "11" * 20}, id="escrow address"),
        pytest.param({"token": "0x" + "22" * 20}, id="token"),
        pytest.param({"literal_fields": {}}, id="literal fields"),
        pytest.param({"rates": []}, id="rates"),
    ],
)
def test_a_selection_only_opening_refuses_an_escrow_parameter(overrides):
    transport = _CapturingSyncTransport()
    with SyncStorefrontClient(
        "http://test", signer=_SIGNER, caller_role="buyer",
        expected_publishers=TrustedIdentitySet(identities=(_PUBLISHER.identity,)),
        transport=transport,
    ) as client:
        with pytest.raises(ValueError):
            client.negotiate_new(**_selection_kwargs(_ENVELOPE, **overrides))

    assert transport.requests == []


def test_an_escrow_opening_with_a_selection_is_unchanged():
    """Without ``selection_only``, a selection still rides beside the escrow
    carrier, so existing callers send what they sent before."""
    transport = _CapturingSyncTransport()
    with SyncStorefrontClient(
        "http://test", signer=_SIGNER, caller_role="buyer",
        expected_publishers=TrustedIdentitySet(identities=(_PUBLISHER.identity,)),
        transport=transport,
    ) as client:
        client.negotiate_new(
            **_selection_kwargs(_ENVELOPE, selection_only=False, chain_name="", literal_fields={})
        )

    body = json.loads(transport.requests[0].content)
    assert body["proposal"]["chain_name"] == "anvil"
    assert body["settlement_selection"] == _SELECTION
