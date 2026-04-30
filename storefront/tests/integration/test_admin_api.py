"""Integration tests for the Admin API.

Uses the async ``StorefrontClient`` via ``httpx.ASGITransport``,
matching the provisioning-service integration test pattern.
All assertions go through the canonical client.
"""

from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from starlette.applications import Starlette

from market_storefront.controllers.admin_controller import AdminController
from market_storefront.controllers.system_controller import SystemController
from market_storefront.middleware.admin_auth import AdminAuthMiddleware
from market_storefront.utils.sqlite_client import SQLiteClient
from storefront_client.client import StorefrontClient, StorefrontClientError

ADMIN_KEY = "test-admin-key"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db(tmp_path) -> SQLiteClient:
    return SQLiteClient(db_path=str(tmp_path / "admin_test.db"))


def _make_app(db: SQLiteClient, *, admin_key: str | None = ADMIN_KEY):
    """Build a minimal Starlette app with system + admin controllers.

    Returns (app, paused_ref) where paused_ref is a mutable list[bool]
    the test can inspect directly to verify the flag was toggled.
    """
    _paused = [False]

    def _get() -> bool:
        return _paused[0]

    def _set(v: bool) -> None:
        _paused[0] = v

    system_ctrl = SystemController(sqlite_client=db, globally_paused_fn=_get)
    admin_ctrl = AdminController(
        sqlite_client=db, get_paused_fn=_get, set_paused_fn=_set
    )
    routes = system_ctrl.routes() + admin_ctrl.routes()
    app = Starlette(routes=routes)
    app.add_middleware(AdminAuthMiddleware, admin_api_key=admin_key)
    return app, _paused


@pytest_asyncio.fixture
async def client(db) -> AsyncIterator[tuple[StorefrontClient, SQLiteClient, list]]:
    app, paused_ref = _make_app(db)
    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient(
        "http://test", transport=transport, admin_key=ADMIN_KEY
    ) as c:
        yield c, db, paused_ref


@pytest_asyncio.fixture
async def client_no_key(db) -> AsyncIterator[StorefrontClient]:
    app, _ = _make_app(db)
    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient("http://test", transport=transport) as c:
        yield c


# ---------------------------------------------------------------------------
# GET /health  (get_health)
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    async def test_health_returns_ok(self, client):
        c, _, _ = client
        result = await c.get_health()
        assert result.status == "ok"
        assert result.checks.get("database") == "ok"

    async def test_system_status_includes_paused(self, client):
        c, _, _ = client
        result = await c.get_system_status()
        assert result.status == "ok"
        assert result.paused is False


# ---------------------------------------------------------------------------
# POST /admin/pause
# ---------------------------------------------------------------------------

class TestAdminPause:
    async def test_requires_admin_key(self, client_no_key):
        with pytest.raises(StorefrontClientError) as exc_info:
            await client_no_key.admin_pause()
        assert "403" in str(exc_info.value)

    async def test_pause_sets_flag(self, client):
        c, _, paused_ref = client
        result = await c.admin_pause()
        assert result.paused is True
        assert paused_ref[0] is True

    async def test_pause_reflected_in_system_status(self, client):
        c, _, _ = client
        await c.admin_pause()
        status = await c.get_system_status()
        assert status.paused is True


# ---------------------------------------------------------------------------
# POST /admin/resume
# ---------------------------------------------------------------------------

class TestAdminResume:
    async def test_requires_admin_key(self, client_no_key):
        with pytest.raises(StorefrontClientError) as exc_info:
            await client_no_key.admin_resume()
        assert "403" in str(exc_info.value)

    async def test_resume_clears_flag(self, client):
        c, _, paused_ref = client
        await c.admin_pause()
        assert paused_ref[0] is True
        result = await c.admin_resume()
        assert result.paused is False
        assert paused_ref[0] is False

    async def test_resume_reflected_in_system_status(self, client):
        c, _, _ = client
        await c.admin_pause()
        await c.admin_resume()
        status = await c.get_system_status()
        assert status.paused is False


# ---------------------------------------------------------------------------
# GET /admin/status
# ---------------------------------------------------------------------------

class TestAdminStatus:
    async def test_requires_admin_key(self, client_no_key):
        with pytest.raises(StorefrontClientError) as exc_info:
            await client_no_key.admin_status()
        assert "403" in str(exc_info.value)

    async def test_status_counts_when_empty(self, client):
        c, _, _ = client
        result = await c.admin_status()
        assert result.paused is False
        assert result.active_negotiations == 0
        assert result.open_listings == 0
        assert result.paused_listings == 0

    async def test_status_counts_open_orders(self, client):
        c, db, _ = client
        now = datetime.now().isoformat()
        await db.upsert_listing(
            listing_id="count-1",
            status="open",
            created_at=now,
            updated_at=now,
            offer_resource={},
            demand_resource={},
            fulfillment_resource=None,
            duration_hours=1,
            seller="http://seller:8001",
        )
        result = await c.admin_status()
        assert result.open_listings == 1

    async def test_status_counts_paused_orders(self, client):
        c, db, _ = client
        now = datetime.now().isoformat()
        await db.upsert_listing(
            listing_id="pause-count",
            status="open",
            created_at=now,
            updated_at=now,
            offer_resource={},
            demand_resource={},
            fulfillment_resource=None,
            duration_hours=1,
            seller="http://seller:8001",
        )
        await db.set_listing_paused(listing_id="pause-count", paused=True)
        result = await c.admin_status()
        # Paused order is excluded from open_orders count
        assert result.open_listings == 0
        assert result.paused_listings == 1
