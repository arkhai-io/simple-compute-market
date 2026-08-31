"""Integration tests for POST /api/v1/listings/validate-publish.

Validation is now schema-driven: the ``listing_shape`` in filter-spec.yaml
defines what a publishable listing looks like.  These tests pin the
behavior at the boundary — happy path, individual structural failures,
and the cosmetic offer_resource_type tag the registry-client still reads.
"""

from __future__ import annotations
import json
import time
import uuid

import httpx
import pytest
from market_identity import (
    Ed25519Signer,
    RequestEnvelope,
    canonical_body_hash,
    sign_request,
)

from src.main import app
from src.api.validate_model import ValidatePublishRequest


class _ValidationAuth(httpx.Auth):
    def __init__(self) -> None:
        self.signer = Ed25519Signer(bytes(range(32)))

    def auth_flow(self, request):
        body = ValidatePublishRequest.model_validate(
            json.loads(request.content)
        ).model_dump(mode="json")
        authenticated = sign_request(
            signer=self.signer,
            envelope=RequestEnvelope(
                role="buyer",
                principal=self.signer.identity,
                method="POST",
                operation="listing.validate",
                resource="listings",
                request_id=uuid.uuid4().hex,
                timestamp=int(time.time()),
                body_hash=canonical_body_hash(body),
            ),
        )
        request.headers.update(
            {
                "X-Market-Signature-Version": authenticated.protocol,
                "X-Market-Identity-Scheme": authenticated.principal.scheme.value,
                "X-Market-Identity-Identifier": authenticated.principal.identifier,
                "X-Market-Role": authenticated.role,
                "X-Market-Request-ID": authenticated.request_id,
                "X-Market-Timestamp": str(authenticated.timestamp),
                "X-Market-Signature": authenticated.proof.value,
            }
        )
        yield request


def _client() -> httpx.AsyncClient:
    """Raw JSON client with canonical buyer authentication."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        auth=_ValidationAuth(),
    )


def _valid_payload(**overrides: object) -> dict:
    base: dict = {
        "listing_id": "test-listing-1",
        "storefront_url": "http://seller.example/",
        "offer_resource": {"gpu_model": "A100", "region": "us-west"},
        "accepted_escrows": [
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "ab" * 20},
            }
        ],
        "max_duration_seconds": 3600,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_valid_listing_passes() -> None:
    async with _client() as c:
        resp = await c.post("/api/v1/listings/validate-publish", json=_valid_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["errors"] == []
    assert body["listing_id"] == "test-listing-1"
    assert body["accepted_escrows_count"] == 1
    assert body["offer_resource_type"] == "compute"


@pytest.mark.asyncio
async def test_hosted_settlement_option_passes_without_alkahest_choice() -> None:
    payload = _valid_payload(
        accepted_escrows=[],
        settlement_options=[
            {
                "option_id": "a" * 64,
                "mechanism": "fiat.stripe.v1",
                "asset": "usd",
                "rates": [{"field": "amount", "per": "hour", "value": "125"}],
                "params": {"account_ref": "acct-seller"},
            }
        ],
    )
    async with _client() as c:
        resp = await c.post("/api/v1/listings/validate-publish", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["accepted_escrows_count"] == 0
    assert body["settlement_options_count"] == 1


@pytest.mark.asyncio
async def test_missing_offer_resource_rejected() -> None:
    payload = _valid_payload()
    del payload["offer_resource"]["gpu_model"]
    del payload["offer_resource"]["region"]
    async with _client() as c:
        resp = await c.post("/api/v1/listings/validate-publish", json=payload)
    body = resp.json()
    assert body["valid"] is False
    # Schema requires gpu_model AND region on offer_resource.
    joined = " ".join(body["errors"])
    assert "gpu_model" in joined
    assert "region" in joined


@pytest.mark.asyncio
async def test_empty_accepted_escrows_rejected() -> None:
    payload = _valid_payload(accepted_escrows=[])
    async with _client() as c:
        resp = await c.post("/api/v1/listings/validate-publish", json=payload)
    body = resp.json()
    assert body["valid"] is False
    assert any("accepted_escrows" in e for e in body["errors"])
    assert body["accepted_escrows_count"] == 0


@pytest.mark.asyncio
async def test_accepted_escrow_missing_required_keys_rejected() -> None:
    payload = _valid_payload(
        accepted_escrows=[
            {"escrow_address": "0x" + "11" * 20}
        ]  # missing chain_name + literal_fields
    )
    async with _client() as c:
        resp = await c.post("/api/v1/listings/validate-publish", json=payload)
    body = resp.json()
    assert body["valid"] is False
    joined = " ".join(body["errors"])
    assert "chain_name" in joined
    assert "literal_fields" in joined


@pytest.mark.asyncio
async def test_blank_listing_id_rejected() -> None:
    payload = _valid_payload(listing_id="")
    async with _client() as c:
        resp = await c.post("/api/v1/listings/validate-publish", json=payload)
    body = resp.json()
    assert body["valid"] is False
    assert any("listing_id" in e for e in body["errors"])


@pytest.mark.asyncio
async def test_invalid_gpu_interconnect_enum_rejected() -> None:
    payload = _valid_payload()
    payload["offer_resource"]["gpu_interconnect"] = "not-a-real-mode"
    async with _client() as c:
        resp = await c.post("/api/v1/listings/validate-publish", json=payload)
    body = resp.json()
    # The interconnect enum is part of the listing_shape — schema-driven
    # validation catches violations that the old hardcoded path missed.
    assert body["valid"] is False
    assert any("gpu_interconnect" in e for e in body["errors"])


@pytest.mark.asyncio
async def test_negative_max_duration_rejected() -> None:
    payload = _valid_payload(max_duration_seconds=-1)
    async with _client() as c:
        resp = await c.post("/api/v1/listings/validate-publish", json=payload)
    body = resp.json()
    assert body["valid"] is False
    assert any("max_duration_seconds" in e for e in body["errors"])


@pytest.mark.asyncio
async def test_null_max_duration_accepted() -> None:
    """``max_duration_seconds: None`` means open-ended; schema allows null."""
    payload = _valid_payload(max_duration_seconds=None)
    async with _client() as c:
        resp = await c.post("/api/v1/listings/validate-publish", json=payload)
    body = resp.json()
    assert body["valid"] is True
