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

from registry_client import RegistryClient
from registry_client.models import ListingRequest

# ---------------------------------------------------------------------------
# Constants — Hardhat/Anvil deterministic key pair (account index 2)
# ---------------------------------------------------------------------------

AGENT_PRIVATE_KEY  = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
AGENT_CANONICAL_ID = "eip155:31337:0x21df544947ba3e8b3c32561399e88b52dc8b2823:2"


# ---------------------------------------------------------------------------
# MockTransport helpers
# ---------------------------------------------------------------------------

class _CapturingTransport(httpx.AsyncBaseTransport):
    """Records the most recent request; returns a configurable canned response."""

    def __init__(self, status_code: int = 201, body: dict | None = None) -> None:
        self.last_request: httpx.Request | None = None
        self._status_code = status_code
        self._body = body or {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.last_request = request
        return httpx.Response(
            self._status_code,
            json=self._body,
            headers={"content-type": "application/json"},
        )

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
    """RegistryClient wired to a capturing MockTransport.

    Yields (client, transport) so tests can inspect what was sent.
    """
    transport = _CapturingTransport(status_code=201, body={"listing_id": "captured"})
    async with RegistryClient("http://test", transport=transport) as client:
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
        Run: make dist-registry-client && make reinit (in storefront/)
        """
        req = ListingRequest(
            listing_id=uuid.uuid4().hex,
            offer={"gpu_model": "H200", "gpu_count": 1, "sla": 99.0, "region": "CA"},
            accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20, "fields": {"payment_token": "0x" + "22" * 20}, "price_per_hour": 10_000}],
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
    - Auth mechanism changes (signature absent / wrong field name in body)
    - Body field renames that survive ListingRequest construction but fail at
      the wire layer
    """

    async def test_posts_to_correct_url(self, capturing_client):
        """publish_listing must POST to /agents/{agent_id}/listings."""
        client, transport = capturing_client
        req = ListingRequest(
            listing_id=uuid.uuid4().hex,
            offer={"gpu_model": "H200", "gpu_count": 1, "sla": 99.0, "region": "CA"},
            accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20, "fields": {"payment_token": "0x" + "22" * 20}, "price_per_hour": 10_000}],
            max_duration_seconds=3600,
        )
        await client.publish_listing(AGENT_CANONICAL_ID, req, private_key=AGENT_PRIVATE_KEY)

        expected_path = f"/agents/{AGENT_CANONICAL_ID}/listings"
        assert transport.last_request_path == expected_path, (
            f"publish_listing posted to {transport.last_request_path!r}, "
            f"expected {expected_path!r}. "
            "URL path has changed — update the registry-client wheel or storefront."
        )

    async def test_body_contains_listing_id(self, capturing_client):
        """Request body must include listing_id."""
        client, transport = capturing_client
        listing_id = uuid.uuid4().hex
        req = ListingRequest(listing_id=listing_id, offer={}, accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20}])
        await client.publish_listing(AGENT_CANONICAL_ID, req, private_key=AGENT_PRIVATE_KEY)
        assert transport.last_request_body.get("listing_id") == listing_id

    async def test_body_contains_offer_resource(self, capturing_client):
        """Request body must include offer_resource with the offer dict."""
        client, transport = capturing_client
        offer = {"gpu_model": "RTX4090", "gpu_count": 2, "sla": 95.0, "region": "NY"}
        req = ListingRequest(listing_id=uuid.uuid4().hex, offer=offer, accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20}])
        await client.publish_listing(AGENT_CANONICAL_ID, req, private_key=AGENT_PRIVATE_KEY)
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
            "fields": {"payment_token": "0x" + "22" * 20},
            "price_per_hour": 8_000,
        }]
        req = ListingRequest(listing_id=uuid.uuid4().hex, offer={}, accepted_escrows=entries)
        await client.publish_listing(AGENT_CANONICAL_ID, req, private_key=AGENT_PRIVATE_KEY)
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
        await client.publish_listing(AGENT_CANONICAL_ID, req, private_key=AGENT_PRIVATE_KEY)
        body = transport.last_request_body
        assert "max_duration_seconds" in body, (
            f"'max_duration_seconds' absent from request body. Keys present: {list(body)}"
        )
        assert body["max_duration_seconds"] == 7200

    async def test_body_contains_eip191_signature(self, capturing_client):
        """Request body must include signature and timestamp for registry auth.

        The registry verifies EIP-191 signatures embedded in the request body
        (not in HTTP headers).  Both fields must be present and non-empty.
        """
        client, transport = capturing_client
        req = ListingRequest(listing_id=uuid.uuid4().hex, offer={}, accepted_escrows=[])
        await client.publish_listing(AGENT_CANONICAL_ID, req, private_key=AGENT_PRIVATE_KEY)
        body = transport.last_request_body
        assert "signature" in body, (
            f"'signature' absent from request body. Keys present: {list(body)}. "
            "The registry verifies EIP-191 signatures from the body, not headers."
        )
        assert "timestamp" in body, (
            f"'timestamp' absent from request body. Keys present: {list(body)}"
        )
        sig = body["signature"]
        # sign_eip191 returns bare hex (no 0x prefix) via bytes.hex()
        assert isinstance(sig, str) and len(sig) >= 130, (
            f"signature looks wrong: {sig!r}. Expected 130+ char hex string."
        )
