"""Integration tests for the Negotiate controller.

Auth is bypassed by monkeypatching ``buyer_auth._verify`` to a no-op.
This is the correct seam: the controller calls ``buyer_auth._verify``
directly to avoid fastapi_utils @cbv + method-level Depends interactions.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

import market_storefront.container as _container
from market_storefront.controllers.negotiate_controller import router as negotiate_router
from market_storefront.middleware import buyer_auth


@pytest_asyncio.fixture
async def db(tmp_path):
    from market_storefront.utils.sqlite_client import SQLiteClient
    return SQLiteClient(db_path=str(tmp_path / "negotiate_test.db"))


async def _seed_listing(db, listing_id: str, demand_amount: int = 5000) -> None:
    await db.upsert_listing(
        listing_id=listing_id,
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource={"gpu_model": "H200", "gpu_count": 1, "sla": 99.9, "region": "California, US"},
        demand_resource={
            "token": {
                "symbol": "MOCK",
                "contract_address": "0x0000000000000000000000000000000000000001",
                "decimals": 0,
            },
            "amount": demand_amount,
        },
        fulfillment_resource=None,
        max_duration_seconds=7200,
        seller="http://seller:8001",
    )


@pytest_asyncio.fixture
async def http_client(db):
    import market_policy.negotiation_thread as _nt_module
    from market_policy.identity import Identity
    _nt_module._thread_store = None
    _nt_module.get_thread_store(
        sqlite_client=db,
        identity=Identity(agent_url="http://test-seller:8001"),
    )
    _container.resolved_sqlite_client = db

    app = FastAPI()
    app.include_router(negotiate_router)

    transport = httpx.ASGITransport(app=app)
    # Bypass buyer auth by patching _verify to a no-op
    with patch.object(buyer_auth, "_verify", return_value=None):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    _container.resolved_sqlite_client = None


_BUYER = "0xBuyer00000000000000000000000000000000AB"  # 42 chars


class TestNegotiateNew:
    async def test_missing_listing_id_returns_422(self, http_client):
        resp = await http_client.post("/negotiate/new", json={
            "buyer_address": _BUYER,
            "initial_price": 8000,
            "duration_seconds": 3600,
        })
        assert resp.status_code == 422

    async def test_missing_buyer_address_returns_422(self, http_client):
        resp = await http_client.post("/negotiate/new", json={
            "listing_id": "some-listing",
            "initial_price": 8000,
            "duration_seconds": 3600,
        })
        assert resp.status_code == 422

    async def test_zero_duration_returns_422(self, http_client):
        resp = await http_client.post("/negotiate/new", json={
            "listing_id": "some-listing",
            "buyer_address": _BUYER,
            "initial_price": 8000,
            "duration_seconds": 0,
        })
        assert resp.status_code == 422

    async def test_negative_price_returns_422(self, http_client):
        resp = await http_client.post("/negotiate/new", json={
            "listing_id": "some-listing",
            "buyer_address": _BUYER,
            "initial_price": -1,
            "duration_seconds": 3600,
        })
        assert resp.status_code == 422

    async def test_unknown_listing_returns_404(self, http_client):
        resp = await http_client.post("/negotiate/new", json={
            "listing_id": "ghost-listing",
            "buyer_address": _BUYER,
            "initial_price": 8000,
            "duration_seconds": 3600,
        })
        assert resp.status_code == 404

    async def test_valid_request_starts_negotiation(self, http_client, db):
        await _seed_listing(db, "neg-listing-1", demand_amount=5000)
        resp = await http_client.post("/negotiate/new", json={
            "listing_id": "neg-listing-1",
            "buyer_address": _BUYER,
            "initial_price": 5000,
            "duration_seconds": 3600,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "negotiation_id" in body
        assert body["action"] in ("accept", "counter", "exit")


class TestNegotiateContinue:
    async def test_invalid_action_returns_422(self, http_client):
        resp = await http_client.post("/negotiate/neg-123", json={
            "action": "invalid_action",
            "buyer_address": _BUYER,
        })
        assert resp.status_code == 422

    async def test_missing_buyer_address_returns_422(self, http_client):
        resp = await http_client.post("/negotiate/neg-123", json={"action": "exit"})
        assert resp.status_code == 422

    async def test_unknown_neg_id_returns_404(self, http_client):
        resp = await http_client.post("/negotiate/ghost-neg-id", json={
            "action": "exit",
            "buyer_address": _BUYER,
        })
        assert resp.status_code == 404

    async def test_counter_without_price_returns_400(self, http_client, db):
        await _seed_listing(db, "neg-listing-continue")
        start = await http_client.post("/negotiate/new", json={
            "listing_id": "neg-listing-continue",
            "buyer_address": _BUYER,
            "initial_price": 5000,
            "duration_seconds": 3600,
        })
        if start.status_code != 200:
            pytest.skip("Could not start negotiation")
        neg_id = start.json().get("negotiation_id")

        resp = await http_client.post(f"/negotiate/{neg_id}", json={
            "action": "counter",
            "buyer_address": _BUYER,
            # price intentionally omitted
        })
        assert resp.status_code in (400, 422)
