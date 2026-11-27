"""Client-contract tests — what `RegistryClient` sends.

**Test level: unit.** This file exercises the installed ``registry_client``
wheel against ``httpx.MockTransport``. It boots no application, opens no
database, and wires no container, so by
`docs/guidance/engineering/test-levels.md`'s definition it is not an integration
test and does not discharge any interservice requirement. It proves what the
client *sends*; whether a registry *accepts* it is answered by
``core/registry/tests/integration/test_settled_listing_vocabulary.py``.

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
import injected_time
from market_identity import (
    Ed25519Signer,
    RequestBinding,
    TrustedIdentitySet,
    VerificationCode,
    verify_market_request,
)
from market_identity.fixtures.messages import build_signed_response

from registry_client import RegistryClient
from registry_client.models import ListingRequest

# ---------------------------------------------------------------------------
# Canonical identity-v3 fixtures
# ---------------------------------------------------------------------------

SELLER_SIGNER = Ed25519Signer(bytes.fromhex("21" * 32))
REGISTRY_SIGNER = Ed25519Signer(bytes.fromhex("42" * 32))
REGISTRY_TRUST = TrustedIdentitySet(identities=(REGISTRY_SIGNER.identity,))
REGISTRY_AUTHORITY = "registry.test"


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
    """The registry's answer, signed over the request identity the request
    states, as the registry signs every answer naming a request."""
    binding = RequestBinding(
        method=request.method,
        operation=request.headers["Market-Operation"],
        resource=request.headers.get("Market-Resource"),
        request_id=request.headers["Market-Request-ID"],
    )
    signed = build_signed_response(
        signer=signer,
        request=binding,
        status=status_code,
        body=json.dumps(body).encode(),
        created=injected_time.now(),
    )
    return httpx.Response(status_code, content=signed.body, headers=signed.headers, request=request)


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
        await request.aread()
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
    """Yield a RegistryClient and transport with both version 3 directions signed."""
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
                listing_resource=...,
                accepted_escrows=...,
                max_duration_seconds=order_dict.get("max_duration_seconds"),
            )
        If this raises TypeError the installed registry_client wheel is stale.
        Run: make dist-registry-client && make reinit (in domains/vms/storefront/)
        """
        req = ListingRequest(
            listing_id=uuid.uuid4().hex,
            listing_resource={"gpu_model": "H200", "gpu_count": 1, "sla": 99.0, "region": "CA"},
            accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20, "literal_fields": {"token": "0x" + "22" * 20}, "rates": [{"field": "amount", "per": "hour", "value": "10000"}]}],
            max_duration_seconds=3600,
        )
        assert req.max_duration_seconds == 3600

    def test_accepts_none_max_duration_seconds(self):
        """max_duration_seconds=None must be accepted (unlimited lease)."""
        req = ListingRequest(
            listing_id=uuid.uuid4().hex,
            listing_resource={"gpu_model": "H200"},
            accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20}],
            max_duration_seconds=None,
        )
        assert req.max_duration_seconds is None

    def test_listing_id_is_optional(self):
        """listing_id has a default — publish_order_to_registry always provides it."""
        req = ListingRequest(listing_resource={}, accepted_escrows=[])
        assert req.listing_id  # auto-generated uuid

    def test_to_dict_emits_max_duration_seconds(self):
        """to_dict() must emit max_duration_seconds for the registry wire format.

        The registry handler reads this field from the POST body.  If it is
        absent from to_dict() the field is silently dropped and the registry
        will not store the lease duration.
        """
        req = ListingRequest(
            listing_id="test-lid",
            listing_resource={"gpu_model": "A100"},
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
        req = ListingRequest(listing_resource={}, accepted_escrows=[], listing_id="specific-id")
        assert req.to_dict()["listing_id"] == "specific-id"

    def test_to_dict_emits_listing_resource_key(self):
        """to_dict() must use 'listing_resource' not 'listing_resource' as the wire key."""
        req = ListingRequest(listing_resource={"gpu_model": "H200"}, accepted_escrows=[])
        d = req.to_dict()
        assert "listing_resource" in d, (
            "to_dict() must emit 'listing_resource', not 'listing_resource'. "
            "The registry listing_routes.py reads body.get('listing_resource')."
        )

    def test_to_dict_emits_accepted_escrows_key(self):
        """to_dict() must use 'accepted_escrows' as the wire key."""
        entries = [{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20}]
        req = ListingRequest(listing_resource={}, accepted_escrows=entries)
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
    - Auth mechanism changes (version 3 signature absent, or not bound to the body)
    - Body field renames that survive ListingRequest construction but fail at
      the wire layer
    """

    async def test_posts_to_correct_url(self, capturing_client):
        """publish_listing must POST to /listings."""
        client, transport = capturing_client
        req = ListingRequest(
            listing_id=uuid.uuid4().hex,
            listing_resource={"gpu_model": "H200", "gpu_count": 1, "sla": 99.0, "region": "CA"},
            accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20, "literal_fields": {"token": "0x" + "22" * 20}, "rates": [{"field": "amount", "per": "hour", "value": "10000"}]}],
            max_duration_seconds=3600,
        )
        await client.publish_listing(req)

        assert transport.last_request_path == "/listings", (
            f"publish_listing posted to {transport.last_request_path!r}, "
            "expected '/listings'. "
            "URL path has changed — update the registry-client wheel or storefront."
        )

    async def test_headers_identify_the_seller_and_address_the_registry(self, capturing_client):
        """Authentication headers carry the seller's role, an operation with no
        target, and the registry the seller would accept the answer from."""
        client, transport = capturing_client
        req = ListingRequest(listing_id=uuid.uuid4().hex, listing_resource={}, accepted_escrows=[])
        await client.publish_listing(req)

        assert transport.last_request is not None
        headers = transport.last_request.headers
        assert headers["Market-Role"] == "seller"
        assert headers["Market-Operation"] == "listing.publish"
        assert "Market-Resource" not in headers
        assert REGISTRY_SIGNER.identity.identifier in headers["Market-Audience"]
        assert f'keyid="ed25519:{SELLER_SIGNER.identity.identifier}"' in headers["Signature-Input"]

    async def test_body_contains_listing_id(self, capturing_client):
        """Request body must include listing_id."""
        client, transport = capturing_client
        listing_id = uuid.uuid4().hex
        req = ListingRequest(listing_id=listing_id, listing_resource={}, accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20}])
        await client.publish_listing(req)
        assert transport.last_request_body.get("listing_id") == listing_id

    async def test_body_contains_listing_resource(self, capturing_client):
        """Request body must include listing_resource with the listing_resource dict."""
        client, transport = capturing_client
        listing_resource = {"gpu_model": "RTX4090", "gpu_count": 2, "sla": 95.0, "region": "NY"}
        req = ListingRequest(listing_id=uuid.uuid4().hex, listing_resource=listing_resource, accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20}])
        await client.publish_listing(req)
        body = transport.last_request_body
        assert "listing_resource" in body, (
            f"'listing_resource' absent from request body. Keys present: {list(body)}"
        )
        assert body["listing_resource"] == listing_resource

    async def test_body_contains_accepted_escrows(self, capturing_client):
        """Request body must include accepted_escrows with the entries list."""
        client, transport = capturing_client
        entries = [{
            "chain_name": "anvil",
            "escrow_address": "0x" + "11" * 20,
            "literal_fields": {"token": "0x" + "22" * 20},
            "rates": [{"field": "amount", "per": "hour", "value": "8000"}],
        }]
        req = ListingRequest(listing_id=uuid.uuid4().hex, listing_resource={}, accepted_escrows=entries)
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
            listing_resource={"gpu_model": "H200"},
            accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20}],
            max_duration_seconds=7200,
        )
        await client.publish_listing(req)
        body = transport.last_request_body
        assert "max_duration_seconds" in body, (
            f"'max_duration_seconds' absent from request body. Keys present: {list(body)}"
        )
        assert body["max_duration_seconds"] == 7200

    async def test_the_version_3_signature_binds_the_exact_body(self, capturing_client):
        """The request verifies under the version 3 profile over the exact body
        sent, as the seller, and fails over any other body."""
        client, transport = capturing_client
        req = ListingRequest(listing_id=uuid.uuid4().hex, listing_resource={}, accepted_escrows=[])
        await client.publish_listing(req, request_id="request-one")

        assert transport.last_request is not None
        content = transport.last_request.content
        headers = transport.last_request.headers
        assert {"scheme", "identifier", "signature", "timestamp"}.isdisjoint(json.loads(content))

        verified = verify_market_request(method="POST", headers=headers, body=content)
        assert verified.code == VerificationCode.VERIFIED
        assert verified.request is not None
        assert verified.request.principal == SELLER_SIGNER.identity
        assert verified.request.request_id == "request-one"
        assert verified.request.addressed_to(REGISTRY_SIGNER.identity)

        tampered = verify_market_request(
            method="POST", headers=headers, body=content.replace(b"{", b'{"listing_id":"tampered",', 1)
        )
        assert tampered.code != VerificationCode.VERIFIED
