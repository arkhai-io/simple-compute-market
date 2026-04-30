"""Unit tests for AdminAuthMiddleware.

Tests the key-checking logic directly: which paths require auth, which pass
through, and how the middleware responds to missing/wrong/correct keys.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from market_storefront.middleware.admin_auth import AdminAuthMiddleware, _requires_admin


# ---------------------------------------------------------------------------
# Unit tests for _requires_admin path matcher
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path,expected", [
    # Protected prefixes
    ("/admin/pause", True),
    ("/admin/resume", True),
    ("/admin/status", True),
    ("/admin/anything", True),
    # Protected suffixes (per-resource admin actions)
    ("/api/v1/listings/abc/pause", True),
    ("/api/v1/listings/abc/resume", True),
    ("/api/v1/listings/abc/negotiations/neg1/advance", True),
    ("/api/v1/listings/abc/negotiations/neg1/force-accept", True),
    # NOT protected
    ("/health", False),
    ("/api/v1/listings", False),
    ("/api/v1/listings/abc", False),
    ("/api/v1/listings/abc/negotiations", False),
    ("/api/v1/listings/abc/negotiations/neg1", False),
    ("/negotiate/new", False),
    ("/negotiate/neg1", False),
    ("/settle/uid123", False),
    ("/.well-known/agent-wallet.json", False),
])
def test_requires_admin_path_matching(path: str, expected: bool) -> None:
    assert _requires_admin(path) is expected


# ---------------------------------------------------------------------------
# Integration-style tests via a minimal Starlette app
# ---------------------------------------------------------------------------

CORRECT_KEY = "test-secret-key"


async def _echo(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _make_app(key: str | None) -> Starlette:
    app = Starlette(routes=[
        Route("/health", _echo, methods=["GET"]),
        Route("/admin/pause", _echo, methods=["POST"]),
        Route("/api/v1/listings/abc/pause", _echo, methods=["POST"]),
        Route("/api/v1/listings/abc/negotiations/n1/advance", _echo, methods=["POST"]),
        Route("/api/v1/listings/abc/negotiations/n1/force-accept", _echo, methods=["POST"]),
    ])
    app.add_middleware(AdminAuthMiddleware, admin_api_key=key)
    return app


@pytest_asyncio.fixture
async def client_with_key() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=_make_app(CORRECT_KEY)),
        base_url="http://test",
    ) as c:
        yield c


@pytest_asyncio.fixture
async def client_no_key() -> AsyncClient:
    """App with no admin_api_key configured — dev/unprotected mode."""
    async with AsyncClient(
        transport=ASGITransport(app=_make_app(None)),
        base_url="http://test",
    ) as c:
        yield c


class TestAdminAuthMiddlewareWithKey:
    async def test_non_admin_route_passes_without_key(self, client_with_key):
        r = await client_with_key.get("/health")
        assert r.status_code == 200

    async def test_admin_route_blocked_without_key(self, client_with_key):
        r = await client_with_key.post("/admin/pause")
        assert r.status_code == 403
        assert "X-Admin-Key" in r.json()["detail"]

    async def test_admin_route_blocked_wrong_key(self, client_with_key):
        r = await client_with_key.post(
            "/admin/pause", headers={"X-Admin-Key": "wrong-key"}
        )
        assert r.status_code == 403

    async def test_admin_route_allowed_correct_key(self, client_with_key):
        r = await client_with_key.post(
            "/admin/pause", headers={"X-Admin-Key": CORRECT_KEY}
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    async def test_order_pause_blocked_without_key(self, client_with_key):
        r = await client_with_key.post("/api/v1/listings/abc/pause")
        assert r.status_code == 403

    async def test_order_pause_allowed_correct_key(self, client_with_key):
        r = await client_with_key.post(
            "/api/v1/listings/abc/pause",
            headers={"X-Admin-Key": CORRECT_KEY},
        )
        assert r.status_code == 200

    async def test_advance_blocked_without_key(self, client_with_key):
        r = await client_with_key.post(
            "/api/v1/listings/abc/negotiations/n1/advance"
        )
        assert r.status_code == 403

    async def test_force_accept_blocked_without_key(self, client_with_key):
        r = await client_with_key.post(
            "/api/v1/listings/abc/negotiations/n1/force-accept"
        )
        assert r.status_code == 403


class TestAdminAuthMiddlewareNoKey:
    """When no admin_api_key is configured, all routes pass through."""

    async def test_admin_route_passes_without_header(self, client_no_key):
        r = await client_no_key.post("/admin/pause")
        assert r.status_code == 200

    async def test_admin_route_passes_with_any_header(self, client_no_key):
        r = await client_no_key.post(
            "/admin/pause", headers={"X-Admin-Key": "whatever"}
        )
        assert r.status_code == 200
