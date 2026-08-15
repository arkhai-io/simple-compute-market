"""Contract tests — RegistryClient ↔ registry-service API.

These tests verify that the ``registry_client`` wheel installed in the
storefront's venv is compatible with the registry-service it will talk to at
runtime.

Why this file exists
--------------------
The storefront's unit tests patch ``_make_registry_client`` before
``ListingRequest.__init__`` is ever reached, so interface mismatches between
the client model and the service are invisible to those tests.  This file
closes that gap.

What we test and why
--------------------
The storefront's only interaction with the registry is through the
``registry_client`` wheel — there is no reason to boot the actual registry
FastAPI app here.  The contract questions we need to answer are all answerable
from the wheel alone:

1. Does ``ListingRequest.__init__`` accept the kwargs that
   ``publish_order_to_registry`` passes?  (catches constructor renames)
2. Does ``ListingRequest.to_dict()`` emit the field names the registry wire
   format expects?  (catches field renames)
3. Does ``RegistryClient.publish_listing()`` call the right URL with the
   right body shape?  (catches method signature / URL path renames)

For (3) we use ``httpx.MockTransport`` — a real ``RegistryClient`` instance
makes a real HTTP call through the full client code path (auth header
construction, JSON serialisation, URL building) against a fake transport that
captures the request and returns a canned 201.  If ``publish_listing``'s
method signature, URL, or body shape changes incompatibly the test fails
immediately without needing a live service.

This is entirely in-process and installs no extra dependencies beyond what
the storefront already requires.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
import pytest_asyncio
from market_identity import (
    AuthenticatedRequest,
    Ed25519Signer,
    Identity,
    ResponseEnvelope,
    SignatureProof,
    TrustedIdentitySet,
    VerificationCode,
    canonical_body_hash,
    sign_response,
    verify_request,
)

from registry_client import RegistryClient
from registry_client.models import ListingRequest

# ---------------------------------------------------------------------------
# Canonical identity-v2 fixtures
# ---------------------------------------------------------------------------

SELLER_SIGNER = Ed25519Signer(bytes.fromhex("21" * 32))
REGISTRY_SIGNER = Ed25519Signer(bytes.fromhex("42" * 32))
REGISTRY_TRUST = TrustedIdentitySet(identities=(REGISTRY_SIGNER.identity,))
REGISTRY_AUTHORITY = "registry.test"

SIGNATURE_VERSION_HEADER = "X-Market-Signature-Version"
IDENTITY_SCHEME_HEADER = "X-Market-Identity-Scheme"
IDENTITY_IDENTIFIER_HEADER = "X-Market-Identity-Identifier"
ROLE_HEADER = "X-Market-Role"
REQUEST_ID_HEADER = "X-Market-Request-ID"
TIMESTAMP_HEADER = "X-Market-Timestamp"
SIGNATURE_HEADER = "X-Market-Signature"


# ---------------------------------------------------------------------------
# MockTransport helpers
# ---------------------------------------------------------------------------

def _signed_response(
    request: httpx.Request,
    *,
    signer: Ed25519Signer,
    status_code: int,
    body: dict[str, Any],
) -> httpx.Response:
    authenticated = sign_response(
        signer=signer,
        envelope=ResponseEnvelope(
            role="registry",
            principal=signer.identity,
            method=request.method,
            operation="listing.publish",
            resource="listings",
            request_id=request.headers[REQUEST_ID_HEADER],
            timestamp=int(request.headers[TIMESTAMP_HEADER]),
            status=status_code,
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
    return httpx.Response(
        status_code,
        json=body,
        headers=headers,
        request=request,
    )


def _request_envelope(
    request: httpx.Request,
    body: dict[str, Any],
) -> AuthenticatedRequest:
    scheme = request.headers[IDENTITY_SCHEME_HEADER]
    return AuthenticatedRequest(
        protocol=request.headers[SIGNATURE_VERSION_HEADER],
        role=request.headers[ROLE_HEADER],
        principal=Identity(
            scheme=scheme,
            identifier=request.headers[IDENTITY_IDENTIFIER_HEADER],
        ),
        method=request.method,
        operation="listing.publish",
        resource="listings",
        request_id=request.headers[REQUEST_ID_HEADER],
        timestamp=int(request.headers[TIMESTAMP_HEADER]),
        body_hash=canonical_body_hash(body),
        proof=SignatureProof(
            scheme=scheme,
            value=request.headers[SIGNATURE_HEADER],
        ),
    )


class _CapturingTransport(httpx.AsyncBaseTransport):
    """Records the signed request and response."""

    def __init__(
        self,
        *,
        response_signer: Ed25519Signer,
        status_code: int = 201,
        body: dict[str, Any] | None = None,
    ) -> None:
        self.last_request: httpx.Request | None = None
        self.last_response: httpx.Response | None = None
        self._response_signer = response_signer
        self._status_code = status_code
        self._body = {} if body is None else body

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.last_request = request
        self.last_response = _signed_response(
            request,
            signer=self._response_signer,
            status_code=self._status_code,
            body=self._body,
        )
        return self.last_response

    @property
    def last_request_body(self) -> dict[str, Any]:
        assert self.last_request is not None, "No request was made"
        return json.loads(self.last_request.content)

    @property
    def last_request_path(self) -> str:
        assert self.last_request is not None, "No request was made"
        return self.last_request.url.path


@pytest_asyncio.fixture
async def capturing_client():
    """Yield a RegistryClient and transport with both v2 directions signed."""
    transport = _CapturingTransport(
        response_signer=REGISTRY_SIGNER,
        status_code=201,
        body={"listing_id": "captured"},
    )
    async with RegistryClient(
        "http://test",
        signer=SELLER_SIGNER,
        caller_role="seller",
        expected_registries=REGISTRY_TRUST,
        registry_authority=REGISTRY_AUTHORITY,
        transport=transport,
    ) as client:
        yield client, transport


# ---------------------------------------------------------------------------
# TestListingRequestConstructor — import-time contract guard
# ---------------------------------------------------------------------------

class TestListingRequestConstructor:
    """Verify ListingRequest accepts the kwargs that publish_order_to_registry passes.

    These tests fail at *construction time* if the installed registry_client
    wheel's ListingRequest model has been modified incompatibly — no HTTP call
    needed.  A TypeError from a bad kwarg is caught immediately on the line
    where ListingRequest(...) is called.

    This is the compile-time guard the patched unit tests were missing.
    """

    def test_accepts_max_duration_seconds(self):
        """ListingRequest must accept max_duration_seconds keyword argument.

        publish_order_to_registry passes this kwarg directly:
            ListingRequest(
                listing_id=order_id,
                offer=...,
                accepted_escrows=...,
                max_duration_seconds=order_dict.get("max_duration_seconds"),
            )
        If this raises TypeError the installed registry_client wheel is stale.
        Run: make dist-registry-client && make reinit (in domains/vms/storefront/)
        """
        req = ListingRequest(
            listing_id=uuid.uuid4().hex,
            offer={"gpu_model": "H200", "gpu_count": 1, "sla": 99.0, "region": "CA"},
            accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20, "literal_fields": {"token": "0x" + "22" * 20}, "rates": [{"field": "amount", "per": "hour", "value": "10000"}]}],
            max_duration_seconds=3600,
        )
        assert req.max_duration_seconds == 3600

    def test_accepts_none_max_duration_seconds(self):
        """max_duration_seconds=None must be accepted (unlimited lease)."""
        req = ListingRequest(
            listing_id=uuid.uuid4().hex,
            offer={"gpu_model": "H200"},
            accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20}],
            max_duration_seconds=None,
        )
        assert req.max_duration_seconds is None

    def test_listing_id_is_optional(self):
        """listing_id has a default — publish_order_to_registry always provides it."""
        req = ListingRequest(offer={}, accepted_escrows=[])
        assert req.listing_id  # auto-generated uuid

    def test_to_dict_emits_max_duration_seconds(self):
        """to_dict() must emit max_duration_seconds for the registry wire format.

        The registry handler reads this field from the POST body.  If it is
        absent from to_dict() the field is silently dropped and the registry
        will not store the lease duration.
        """
        req = ListingRequest(
            listing_id="test-lid",
            offer={"gpu_model": "A100"},
            accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20}],
            max_duration_seconds=7200,
        )
        d = req.to_dict()
        assert "max_duration_seconds" in d, (
            "ListingRequest.to_dict() does not emit 'max_duration_seconds'. "
            "The registry handler reads this field from the request body."
        )
        assert d["max_duration_seconds"] == 7200

    def test_to_dict_emits_listing_id(self):
        """to_dict() must include listing_id — the registry requires it."""
        req = ListingRequest(offer={}, accepted_escrows=[], listing_id="specific-id")
        assert req.to_dict()["listing_id"] == "specific-id"

    def test_to_dict_emits_offer_resource_key(self):
        """to_dict() must use 'offer_resource' not 'offer' as the wire key."""
        req = ListingRequest(offer={"gpu_model": "H200"}, accepted_escrows=[])
        d = req.to_dict()
        assert "offer_resource" in d, (
            "to_dict() must emit 'offer_resource', not 'offer'. "
            "The registry listing_routes.py reads body.get('offer_resource')."
        )

    def test_to_dict_emits_accepted_escrows_key(self):
        """to_dict() must use 'accepted_escrows' as the wire key."""
        entries = [{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20}]
        req = ListingRequest(offer={}, accepted_escrows=entries)
        d = req.to_dict()
        assert "accepted_escrows" in d, (
            "to_dict() must emit 'accepted_escrows'. "
            "The registry listing_routes.py reads body.get('accepted_escrows')."
        )
        assert d["accepted_escrows"] == entries


# ---------------------------------------------------------------------------
# TestPublishListingWireFormat — full client call path via MockTransport
# ---------------------------------------------------------------------------

class TestPublishListingWireFormat:
    """Verify publish_listing sends the correct request through the full client path.

    Uses a real RegistryClient instance against a _CapturingTransport.  The
    entire client code path runs — URL construction, auth header building,
    ListingRequest.to_dict() serialisation — but against a fake transport that
    captures the outgoing request instead of opening a network socket.

    This catches:
    - URL path renames (e.g. /agents/{id}/listings → /agents/{id}/orders)
    - Method signature changes (e.g. publish_listing argument reordering)
    - Auth mechanism changes (v2 envelope absent / wrong header or body binding)
    - Body field renames that survive ListingRequest construction but fail at
      the wire layer
    """

    async def test_posts_to_correct_url(self, capturing_client):
        """publish_listing must POST to /listings."""
        client, transport = capturing_client
        req = ListingRequest(
            listing_id=uuid.uuid4().hex,
            offer={"gpu_model": "H200", "gpu_count": 1, "sla": 99.0, "region": "CA"},
            accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20, "literal_fields": {"token": "0x" + "22" * 20}, "rates": [{"field": "amount", "per": "hour", "value": "10000"}]}],
            max_duration_seconds=3600,
        )
        await client.publish_listing(req)

        assert transport.last_request_path == "/listings", (
            f"publish_listing posted to {transport.last_request_path!r}, "
            "expected '/listings'. "
            "URL path has changed — update the registry-client wheel or storefront."
        )

    async def test_headers_identify_canonical_ed25519_signer(self, capturing_client):
        """Authentication headers must carry the seller's canonical identity."""
        client, transport = capturing_client
        req = ListingRequest(listing_id=uuid.uuid4().hex, offer={}, accepted_escrows=[])
        await client.publish_listing(req)

        assert transport.last_request is not None
        headers = transport.last_request.headers
        assert headers[IDENTITY_SCHEME_HEADER] == "ed25519"
        assert headers[IDENTITY_SCHEME_HEADER] == SELLER_SIGNER.identity.scheme.value
        assert headers[IDENTITY_IDENTIFIER_HEADER] == SELLER_SIGNER.identity.identifier
        assert headers[ROLE_HEADER] == "seller"

    async def test_body_contains_listing_id(self, capturing_client):
        """Request body must include listing_id."""
        client, transport = capturing_client
        listing_id = uuid.uuid4().hex
        req = ListingRequest(listing_id=listing_id, offer={}, accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20}])
        await client.publish_listing(req)
        assert transport.last_request_body.get("listing_id") == listing_id

    async def test_body_contains_offer_resource(self, capturing_client):
        """Request body must include offer_resource with the offer dict."""
        client, transport = capturing_client
        offer = {"gpu_model": "RTX4090", "gpu_count": 2, "sla": 95.0, "region": "NY"}
        req = ListingRequest(listing_id=uuid.uuid4().hex, offer=offer, accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20}])
        await client.publish_listing(req)
        body = transport.last_request_body
        assert "offer_resource" in body, (
            f"'offer_resource' absent from request body. Keys present: {list(body)}"
        )
        assert body["offer_resource"] == offer

    async def test_body_contains_accepted_escrows(self, capturing_client):
        """Request body must include accepted_escrows with the entries list."""
        client, transport = capturing_client
        entries = [{
            "chain_name": "anvil",
            "escrow_address": "0x" + "11" * 20,
            "literal_fields": {"token": "0x" + "22" * 20},
            "rates": [{"field": "amount", "per": "hour", "value": "8000"}],
        }]
        req = ListingRequest(listing_id=uuid.uuid4().hex, offer={}, accepted_escrows=entries)
        await client.publish_listing(req)
        body = transport.last_request_body
        assert "accepted_escrows" in body, (
            f"'accepted_escrows' absent from request body. Keys present: {list(body)}"
        )
        assert body["accepted_escrows"] == entries

    async def test_body_contains_max_duration_seconds(self, capturing_client):
        """Request body must include max_duration_seconds."""
        client, transport = capturing_client
        req = ListingRequest(
            listing_id=uuid.uuid4().hex,
            offer={"gpu_model": "H200"},
            accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20}],
            max_duration_seconds=7200,
        )
        await client.publish_listing(req)
        body = transport.last_request_body
        assert "max_duration_seconds" in body, (
            f"'max_duration_seconds' absent from request body. Keys present: {list(body)}"
        )
        assert body["max_duration_seconds"] == 7200

    async def test_v2_authentication_envelope_binds_exact_body(self, capturing_client):
        """Request headers carry a verifiable v2 envelope bound to the exact body."""
        client, transport = capturing_client
        req = ListingRequest(listing_id=uuid.uuid4().hex, offer={}, accepted_escrows=[])
        await client.publish_listing(req, request_id="request-one")

        assert transport.last_request is not None
        assert transport.last_response is not None
        body = transport.last_request_body
        headers = transport.last_request.headers
        assert headers[SIGNATURE_VERSION_HEADER] == (
            "arkhai.market-request-signature.v2"
        )
        assert headers[REQUEST_ID_HEADER] == "request-one"
        assert headers[TIMESTAMP_HEADER].isdigit()
        assert headers[SIGNATURE_HEADER]
        assert {"scheme", "identifier", "signature", "timestamp"}.isdisjoint(body)

        envelope = _request_envelope(transport.last_request, body)
        trusted_seller = TrustedIdentitySet(identities=(SELLER_SIGNER.identity,))
        verified = verify_request(
            envelope,
            body=body,
            now=envelope.timestamp,
            max_skew=300,
            expected_role="seller",
            expected_method="POST",
            expected_operation="listing.publish",
            expected_resource="listings",
            expected_principals=trusted_seller,
        )
        assert verified.code == VerificationCode.VERIFIED

        tampered = verify_request(
            envelope,
            body={**body, "listing_id": "tampered"},
            now=envelope.timestamp,
            max_skew=300,
            expected_role="seller",
            expected_method="POST",
            expected_operation="listing.publish",
            expected_resource="listings",
            expected_principals=trusted_seller,
        )
        assert tampered.code == VerificationCode.BODY_HASH_MISMATCH

        response_headers = transport.last_response.headers
        assert response_headers[SIGNATURE_VERSION_HEADER] == (
            "arkhai.market-response-signature.v2"
        )
        assert response_headers[IDENTITY_SCHEME_HEADER] == (
            REGISTRY_SIGNER.identity.scheme.value
        )
        assert response_headers[IDENTITY_IDENTIFIER_HEADER] == (
            REGISTRY_SIGNER.identity.identifier
        )
        assert response_headers[ROLE_HEADER] == "registry"
