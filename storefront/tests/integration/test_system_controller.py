"""Integration tests for SystemController.wait_for_registry_agent.

Covers the GET /api/v1/system/wait-for-registry-agent endpoint end-to-end
through the canonical ``StorefrontClient`` (async) via ``httpx.ASGITransport``.

The two cases that exercise the service's branching logic are:
  1. ``_registry_auth_per_chain`` returns a definitive dict immediately
     → ``ready=True``, ``registry_auth`` carries the aggregate.
  2. ``_registry_auth_per_chain`` always returns the transient
     ``{"<chain>": "agent_not_found"}`` → request times out → ``ready=False``.

``SystemService._registry_auth_per_chain`` is patched at the class level so the
controller's ``self._svc`` instance sees the mock without requiring the test
to reach the real registry service over the network.
"""
from __future__ import annotations

from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

import market_storefront.container as _container
from market_storefront.controllers.system_controller import router as system_router
from market_storefront.middleware.admin_auth import require_admin_key
from market_storefront.services.system_service import SystemService
from market_storefront.utils.sqlite_client import SQLiteClient
from storefront_client.client import StorefrontClient

ADMIN_KEY = "test-admin-key"


def _key_enforcer(expected_key: str):
    from fastapi import Header, HTTPException
    def _dep(x_admin_key: str | None = Header(default=None, alias="X-Admin-Key")) -> None:
        if x_admin_key != expected_key:
            raise HTTPException(status_code=403, detail="Valid X-Admin-Key header required")
    return _dep


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db(tmp_path) -> SQLiteClient:
    return SQLiteClient(db_path=str(tmp_path / "system_controller_test.db"))


@pytest_asyncio.fixture
async def client(db) -> AsyncIterator[StorefrontClient]:
    """StorefrontClient (async) wired to an in-process FastAPI app."""
    _container.resolved_sqlite_client = db
    _container.resolved_system_service = SystemService(sqlite_client=db)

    app = FastAPI()
    app.include_router(system_router)
    app.dependency_overrides[require_admin_key] = _key_enforcer(ADMIN_KEY)

    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient(
        "http://test", transport=transport, admin_key=ADMIN_KEY
    ) as c:
        yield c

    _container.resolved_sqlite_client = None
    _container.resolved_system_service = None


# ---------------------------------------------------------------------------
# GET /api/v1/system/wait-for-registry-agent
# ---------------------------------------------------------------------------

class TestWaitForRegistryAgent:
    async def test_ready_when_auth_check_returns_ok(self, client):
        """Returns ready=True immediately when every chain reports 'ok'."""
        with patch.object(
            SystemService,
            "_registry_auth_per_chain",
            new=AsyncMock(return_value={"anvil": "ok"}),
        ):
            result = await client.wait_for_registry_agent_ready(timeout=5.0)

        assert result.ready is True
        assert result.registry_auth == "ok"
        assert result.auth_per_chain == {"anvil": "ok"}
        assert result.elapsed_ms >= 0

    async def test_ready_when_auth_check_returns_definitive_non_ok(self, client):
        """Returns ready=True for any definitive result, not only 'ok'.

        'owner_mismatch' is definitive — the agent is indexed but ownership
        verification failed. The controller returns ready=True so callers can
        inspect registry_auth and surface the specific problem. The aggregate
        is chain-prefixed so operators know which chain misconfigured.
        """
        with patch.object(
            SystemService,
            "_registry_auth_per_chain",
            new=AsyncMock(return_value={"anvil": "owner_mismatch"}),
        ):
            result = await client.wait_for_registry_agent_ready(timeout=5.0)

        assert result.ready is True
        assert result.registry_auth == "anvil:owner_mismatch"
        assert result.auth_per_chain == {"anvil": "owner_mismatch"}

    async def test_not_ready_on_timeout(self, client):
        """Returns ready=False when agent_not_found persists past timeout."""
        with patch.object(
            SystemService,
            "_registry_auth_per_chain",
            new=AsyncMock(return_value={"anvil": "agent_not_found"}),
        ):
            # Use a short timeout so the test completes quickly.
            result = await client.wait_for_registry_agent_ready(timeout=1.0)

        assert result.ready is False
        assert result.registry_auth == "anvil:agent_not_found"
        # Elapsed should be at least the timeout (in ms), with some tolerance.
        assert result.elapsed_ms >= 900

    async def test_requires_admin_key(self, db):
        """Endpoint returns 403 when X-Admin-Key is absent or wrong."""
        _container.resolved_sqlite_client = db
        _container.resolved_system_service = SystemService(sqlite_client=db)

        app = FastAPI()
        app.include_router(system_router)
        app.dependency_overrides[require_admin_key] = _key_enforcer(ADMIN_KEY)

        transport = httpx.ASGITransport(app=app)
        async with StorefrontClient("http://test", transport=transport) as c:
            # No admin_key supplied → 403
            resp = await c._client.get(
                "/api/v1/system/wait-for-registry-agent",
                params={"timeout": 1.0},
                timeout=5.0,
            )
            assert resp.status_code == 403

        _container.resolved_sqlite_client = None
        _container.resolved_system_service = None


# ---------------------------------------------------------------------------
# GET /api/v1/system/status — agent_id and chain_id top-level fields
# ---------------------------------------------------------------------------

class TestSystemStatusAgentFields:
    async def test_system_status_exposes_agent_id_and_chain_id(self, client):
        """GET /api/v1/system/status exposes agent_id and chain_id at the top level.

        In the test environment agent_id may be None (no on-chain identity wired
        up), and chain_id may be None (RPC fallback not available in-process).
        The important contract is that the fields are present in the response
        and the client model deserialises them without error.
        """
        result = await client.get_system_status()
        assert hasattr(result, "agent_id"), "agent_id field missing from HealthResponse"
        assert hasattr(result, "chain_id"), "chain_id field missing from HealthResponse"
        assert result.agent_id is None or isinstance(result.agent_id, str)
        assert result.chain_id is None or isinstance(result.chain_id, int)
        assert "agent_id" not in result.checks
        assert "chain_id" not in result.checks

    async def test_system_status_exposes_resource_count(self, client):
        """GET /api/v1/system/status exposes resource_count at the top level.

        In the test environment the resources table is empty (no CSV import),
        so resource_count == 0.  The field must be present and not conflated
        into checks.  A non-None value confirms the DB query succeeded.
        """
        result = await client.get_system_status()
        assert hasattr(result, "resource_count"), "resource_count missing from HealthResponse"
        assert result.resource_count is not None, (
            "resource_count is None — list_resources() raised unexpectedly in test environment"
        )
        assert isinstance(result.resource_count, int)
        assert "resource_count" not in result.checks
