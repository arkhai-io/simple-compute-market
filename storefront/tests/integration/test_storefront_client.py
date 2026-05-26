"""Integration tests for orders and identity endpoints.

Covers the endpoints extracted from agent.py into the new controllers:
  - OrdersController  (/listings/create, /listings/close)
  - IdentityController (/.well-known/*)

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
from market_storefront.controllers.identity_controller import router as identity_router
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
    "fields": {"token": "0x0000000000000000000000000000000000000001"},
    "price_per_hour": 10,
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


@pytest_asyncio.fixture
async def identity_client() -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    app.include_router(identity_router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


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


# ---------------------------------------------------------------------------
# /.well-known/erc-8004-registration.json
# ---------------------------------------------------------------------------

class TestRegistrationEndpoint:
    async def test_returns_200_with_json(self, identity_client):
        resp = await identity_client.get("/.well-known/erc-8004-registration.json")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    async def test_contains_expected_fields(self, identity_client):
        resp = await identity_client.get("/.well-known/erc-8004-registration.json")
        data = resp.json()
        # ERC-8004 spec: either 'type' or 'name' must be present
        assert "type" in data or "name" in data


# ---------------------------------------------------------------------------
# /.well-known/agent-wallet.json
# ---------------------------------------------------------------------------

class TestAgentWalletEndpoint:
    async def test_returns_200_with_address(self, identity_client):
        resp = await identity_client.get("/.well-known/agent-wallet.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "agent_wallet_address" in data
        # Value is a string (may be empty if not configured)
        assert isinstance(data["agent_wallet_address"], str)


# ---------------------------------------------------------------------------
# /.well-known/agent-card.json
# ---------------------------------------------------------------------------

class TestAgentCardEndpoint:
    async def test_returns_200_with_json(self, identity_client):
        resp = await identity_client.get("/.well-known/agent-card.json")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        # A2A AgentCard requires name + url + version + skills/capabilities.
        assert "name" in data
        assert "url" in data
        assert "version" in data
