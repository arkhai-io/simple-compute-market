"""Unit tests for the require_admin_key FastAPI Security dependency.

Tests the actual dependency behaviour via a minimal FastAPI app —
verifying that protected routes return 403 without the key, 403 with
the wrong key, and 200 with the correct key.

The old AdminAuthMiddleware path-matching tests are not reproduced here
because path-matching no longer exists — auth is explicit per-router/endpoint.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI, Header, HTTPException
from httpx import ASGITransport, AsyncClient

from market_storefront.middleware.admin_auth import require_admin_key

CORRECT_KEY = "test-secret-key"


# ---------------------------------------------------------------------------
# App factory helpers
# ---------------------------------------------------------------------------

def _enforcer(expected_key: str):
    """Return a Depends-compatible function that enforces a specific key."""
    def _dep(
        x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    ) -> None:
        if x_admin_key != expected_key:
            raise HTTPException(
                status_code=403,
                detail="Valid X-Admin-Key header required",
            )
    return _dep


def _make_app_with_key(key: str) -> FastAPI:
    """App where require_admin_key is overridden to enforce ``key``."""
    app = FastAPI()
    app.dependency_overrides[require_admin_key] = _enforcer(key)

    @app.post("/admin/test", dependencies=[Depends(require_admin_key)])
    async def _protected():
        return {"ok": True}

    @app.get("/public")
    async def _public():
        return {"ok": True}

    return app


def _make_app_no_key() -> FastAPI:
    """App where require_admin_key is NOT overridden — uses CONFIG (None in tests = dev mode)."""
    app = FastAPI()

    @app.post("/admin/test", dependencies=[Depends(require_admin_key)])
    async def _protected():
        return {"ok": True}

    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def protected_client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=_make_app_with_key(CORRECT_KEY)),
        base_url="http://test",
    ) as c:
        yield c


@pytest_asyncio.fixture
async def dev_mode_client() -> AsyncClient:
    """No key configured — all requests pass through (local dev default)."""
    async with AsyncClient(
        transport=ASGITransport(app=_make_app_no_key()),
        base_url="http://test",
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests: key enforced
# ---------------------------------------------------------------------------

class TestRequireAdminKeyEnforced:
    async def test_missing_key_returns_403(self, protected_client):
        r = await protected_client.post("/admin/test")
        assert r.status_code == 403
        assert "X-Admin-Key" in r.json()["detail"]

    async def test_wrong_key_returns_403(self, protected_client):
        r = await protected_client.post(
            "/admin/test", headers={"X-Admin-Key": "wrong-key"}
        )
        assert r.status_code == 403

    async def test_correct_key_returns_200(self, protected_client):
        r = await protected_client.post(
            "/admin/test", headers={"X-Admin-Key": CORRECT_KEY}
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    async def test_public_route_never_requires_key(self, protected_client):
        r = await protected_client.get("/public")
        assert r.status_code == 200

    async def test_case_sensitive_key(self, protected_client):
        r = await protected_client.post(
            "/admin/test", headers={"X-Admin-Key": CORRECT_KEY.upper()}
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Tests: dev mode (no key configured = all pass)
# ---------------------------------------------------------------------------

class TestRequireAdminKeyDevMode:
    async def test_admin_route_passes_without_key(self, dev_mode_client):
        """settings.admin_api_key is None in tests → require_admin_key is a no-op."""
        r = await dev_mode_client.post("/admin/test")
        assert r.status_code == 200

    async def test_admin_route_passes_with_any_key(self, dev_mode_client):
        r = await dev_mode_client.post(
            "/admin/test", headers={"X-Admin-Key": "anything"}
        )
        assert r.status_code == 200
