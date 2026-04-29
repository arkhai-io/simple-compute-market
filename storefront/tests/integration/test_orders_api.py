"""Integration tests for the Orders API.

Uses the async ``StorefrontClient`` via ``httpx.ASGITransport`` —
the same pattern as the provisioning-service integration tests.
All assertions go through the canonical client; no raw HTTP calls.
"""

from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from starlette.applications import Starlette

from market_storefront.controllers.orders_controller import OrdersController
from market_storefront.middleware.admin_auth import AdminAuthMiddleware
from market_storefront.utils.sqlite_client import SQLiteClient
from storefront_client.client import StorefrontClient, StorefrontClientError

ADMIN_KEY = "test-admin-key"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db(tmp_path) -> SQLiteClient:
    return SQLiteClient(db_path=str(tmp_path / "orders_test.db"))


async def _seed_order(db: SQLiteClient, order_id: str, status: str = "open") -> None:
    await db.upsert_order(
        order_id=order_id,
        status=status,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource={"gpu_model": "H200", "quantity": 1, "sla": 99.9, "region": "California, US"},
        demand_resource={"token": {"symbol": "MOCK", "contract_address": "0x0000000000000000000000000000000000000001", "decimals": 18}, "amount": 9000},
        fulfillment_resource=None,
        duration_hours=2,
        order_maker="http://seller:8001",
    )


@pytest_asyncio.fixture
async def client(db) -> AsyncIterator[tuple[StorefrontClient, SQLiteClient]]:
    ctrl = OrdersController(sqlite_client=db)
    app = Starlette(routes=ctrl.routes())
    app.add_middleware(AdminAuthMiddleware, admin_api_key=ADMIN_KEY)
    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient(
        "http://test",
        transport=transport,
        admin_key=ADMIN_KEY,
    ) as c:
        yield c, db


@pytest_asyncio.fixture
async def client_no_key(db) -> AsyncIterator[StorefrontClient]:
    """Client without admin key — for testing 403 responses."""
    ctrl = OrdersController(sqlite_client=db)
    app = Starlette(routes=ctrl.routes())
    app.add_middleware(AdminAuthMiddleware, admin_api_key=ADMIN_KEY)
    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient("http://test", transport=transport) as c:
        yield c


# ---------------------------------------------------------------------------
# GET /api/v1/orders
# ---------------------------------------------------------------------------

class TestListOrders:
    async def test_empty_list(self, client):
        c, _ = client
        result = await c.list_orders()
        assert result.count == 0
        assert result.orders == []

    async def test_returns_seeded_orders(self, client):
        c, db = client
        await _seed_order(db, "o1")
        await _seed_order(db, "o2")
        result = await c.list_orders()
        ids = {o.order_id for o in result.orders}
        assert {"o1", "o2"} == ids

    async def test_status_filter(self, client):
        c, db = client
        await _seed_order(db, "open1", status="open")
        await _seed_order(db, "closed1", status="closed")
        result = await c.list_orders(status="open")
        ids = {o.order_id for o in result.orders}
        assert "open1" in ids
        assert "closed1" not in ids

    async def test_paused_filter(self, client):
        c, db = client
        await _seed_order(db, "paused1")
        await _seed_order(db, "active1")
        await db.set_order_paused(order_id="paused1", paused=True)
        paused_result = await c.list_orders(paused=True)
        active_result = await c.list_orders(paused=False)
        paused_ids = {o.order_id for o in paused_result.orders}
        active_ids = {o.order_id for o in active_result.orders}
        assert "paused1" in paused_ids
        assert "paused1" not in active_ids
        assert "active1" in active_ids

    async def test_pagination_limit(self, client):
        c, db = client
        for i in range(5):
            await _seed_order(db, f"ord-{i}")
        result = await c.list_orders(limit=2)
        assert len(result.orders) == 2
        assert result.limit == 2

    async def test_paused_field_false_by_default(self, client):
        c, db = client
        await _seed_order(db, "check-paused")
        result = await c.list_orders()
        order = next(o for o in result.orders if o.order_id == "check-paused")
        assert order.paused is False


# ---------------------------------------------------------------------------
# GET /api/v1/orders/{order_id}
# ---------------------------------------------------------------------------

class TestGetOrder:
    async def test_returns_order(self, client):
        c, db = client
        await _seed_order(db, "detail-1")
        order = await c.get_order("detail-1")
        assert order.order_id == "detail-1"
        assert order.paused is False

    async def test_404_unknown_order_raises(self, client):
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.get_order("does-not-exist")
        assert "404" in str(exc_info.value)


# ---------------------------------------------------------------------------
# POST /api/v1/orders/{order_id}/pause
# ---------------------------------------------------------------------------

class TestPauseOrder:
    async def test_requires_admin_key(self, client_no_key):
        with pytest.raises(StorefrontClientError) as exc_info:
            await client_no_key.pause_order("any-order")
        assert "403" in str(exc_info.value)

    async def test_pause_sets_flag(self, client):
        c, db = client
        await _seed_order(db, "pausable")
        result = await c.pause_order("pausable")
        assert result.paused is True
        assert await db.is_order_paused(order_id="pausable") is True

    async def test_pause_unknown_order_raises(self, client):
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.pause_order("ghost")
        assert "404" in str(exc_info.value)


# ---------------------------------------------------------------------------
# POST /api/v1/orders/{order_id}/resume
# ---------------------------------------------------------------------------

class TestResumeOrder:
    async def test_requires_admin_key(self, client_no_key):
        with pytest.raises(StorefrontClientError) as exc_info:
            await client_no_key.resume_order("any-order")
        assert "403" in str(exc_info.value)

    async def test_resume_clears_flag(self, client):
        c, db = client
        await _seed_order(db, "resumable")
        await db.set_order_paused(order_id="resumable", paused=True)
        result = await c.resume_order("resumable")
        assert result.paused is False
        assert await db.is_order_paused(order_id="resumable") is False

    async def test_resume_unknown_order_raises(self, client):
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.resume_order("ghost")
        assert "404" in str(exc_info.value)
