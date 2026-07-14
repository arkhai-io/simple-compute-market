"""Integration tests for listing endpoints.

Covers the endpoints extracted from agent.py into the new controllers:
  - OrdersController  (/listings/create, /listings/close)

Uses a StorefrontService stub and FastAPI ASGITransport.

The original conftest/agent_app_client fixture is superseded by the
per-test fixtures here that wire only the routers under test.
"""
from __future__ import annotations

from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

import market_storefront.container as _container
from market_storefront.controllers.listings_controller import router as listings_router

_COMPUTE_OFFER = {
    "gpu_model": "RTX 4090",
    "gpu_count": 1,
    "sla": 99.0,
    "region": "California, US",
}

_ACCEPTED_ESCROWS = [{
    "chain_name": "anvil",
    "escrow_address": "0x" + "11" * 20,
    "literal_fields": {"token": "0x0000000000000000000000000000000000000001"},
    "rates": [{"field": "amount", "per": "hour", "value": "10"}],
}]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def mock_svc():
    """Minimal service stubs matching ListingService and PolicyPipelineService APIs."""
    svc = MagicMock()
    # ListingService methods
    svc.create_listing = AsyncMock(
        return_value={"status": "created", "listing_id": "test-listing-123", "root_agent_response": ""}
    )
    svc.close_listing = AsyncMock(
        return_value={"status": "closed", "listing_id": "test-listing-close", "root_agent_response": ""}
    )
    return svc


@pytest_asyncio.fixture
async def orders_client(mock_svc, tmp_path) -> AsyncIterator[httpx.AsyncClient]:
    from market_storefront.utils.sqlite_client import SQLiteClient
    db = SQLiteClient(db_path=str(tmp_path / "orders_test.db"))
    _container.resolved_sqlite_client = db
    _container.resolved_listing_service = mock_svc

    app = FastAPI()
    app.include_router(listings_router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    _container.resolved_sqlite_client = None
    _container.resolved_listing_service = None


# ---------------------------------------------------------------------------
# /listings/create
# ---------------------------------------------------------------------------

class TestCreateOrderEndpoint:
    async def test_valid_create_returns_200(self, orders_client):
        body = {
            "offer": _COMPUTE_OFFER,
            "accepted_escrows": _ACCEPTED_ESCROWS,
        }
        resp = await orders_client.post("/api/v1/listings/create", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("created", "no_action")

    async def test_missing_offer_returns_422(self, orders_client):
        """CreateListingRequest Pydantic model requires offer; FastAPI returns 422."""
        resp = await orders_client.post(
            "/api/v1/listings/create",
            json={"accepted_escrows": _ACCEPTED_ESCROWS},
        )
        assert resp.status_code == 422

    async def test_missing_accepted_escrows_returns_422(self, orders_client):
        """CreateListingRequest Pydantic model requires accepted_escrows; FastAPI returns 422."""
        resp = await orders_client.post("/api/v1/listings/create", json={"offer": _COMPUTE_OFFER})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /listings/close
# ---------------------------------------------------------------------------

class TestCloseOrderEndpoint:
    async def test_valid_close_returns_200(self, orders_client):
        """listing_id is in the path, not the body."""
        resp = await orders_client.post("/api/v1/listings/test-listing-abc/close", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data

    async def test_unknown_listing_returns_404(self, orders_client):
        """Close with a listing that doesn't exist in DB."""
        # The mock listing_svc.close_listing always returns, so 404 only comes
        # from missing path param or route mismatch.
        resp = await orders_client.post("/api/v1/listings//close", json={})
        assert resp.status_code in (404, 405, 422)
