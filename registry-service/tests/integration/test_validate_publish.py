"""Integration tests for POST /api/v1/listings/validate-publish.

Validation is now schema-driven: the ``listing_shape`` in filter-spec.yaml
defines what a publishable listing looks like.  These tests pin the
behavior at the boundary — happy path, individual structural failures,
and the cosmetic offer_resource_type tag the registry-client still reads.
"""

from __future__ import annotations

import httpx
import pytest

from src.main import app


def _client() -> httpx.AsyncClient:
    """Plain httpx.AsyncClient over the FastAPI app — no auth, no DB needed."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def _valid_payload(**overrides: object) -> dict:
    base: dict = {
        "listing_id": "test-listing-1",
        "seller": "http://seller.example/",
        "offer_resource": {"gpu_model": "A100", "region": "us-west"},
        "accepted_escrows": [
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "fields": {"token": "0x" + "ab" * 20},
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
        accepted_escrows=[{"escrow_address": "0x" + "11" * 20}]  # missing chain_name + fields
    )
    async with _client() as c:
        resp = await c.post("/api/v1/listings/validate-publish", json=payload)
    body = resp.json()
    assert body["valid"] is False
    joined = " ".join(body["errors"])
    assert "chain_name" in joined
    assert "fields" in joined


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
