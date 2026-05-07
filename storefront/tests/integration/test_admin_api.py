"""Integration tests for the Admin API.

Uses the async ``StorefrontClient`` via ``httpx.ASGITransport``,
matching the provisioning-service integration test pattern.
All assertions go through the canonical client.

Key fixture change from Starlette → FastAPI: the AdminController and
SystemController now import the global pause functions from server.py via
their defaults. For testing we need to control the pause state, so the
fixture wires the container and uses the module-level flag in server.py
directly (same as production).
"""
from __future__ import annotations

from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

import market_storefront.container as _container
from market_storefront.middleware.admin_auth import require_admin_key
import market_storefront.server as _server
from market_storefront.controllers.admin_controller import router as admin_router
from market_storefront.controllers.system_controller import router as system_router
from market_storefront.utils.sqlite_client import SQLiteClient
from market_storefront.services.system_service import SystemService
from storefront_client.client import StorefrontClient, StorefrontClientError

ADMIN_KEY = "test-admin-key"

def _key_enforcer(expected_key: str):
    """Depends-compatible function that enforces a specific X-Admin-Key header.
    Used in test fixtures to simulate production admin-key enforcement without
    requiring a mutable CONFIG (which is a frozen dataclass).
    """
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
    return SQLiteClient(db_path=str(tmp_path / "admin_test.db"))


@pytest_asyncio.fixture(autouse=True)
def reset_pause_state():
    """Ensure global pause flag is reset between tests."""
    _server._GLOBALLY_PAUSED = False
    yield
    _server._GLOBALLY_PAUSED = False


@pytest_asyncio.fixture
async def client(db) -> AsyncIterator[tuple[StorefrontClient, SQLiteClient]]:
    _container.resolved_sqlite_client = db
    _container.resolved_system_service = SystemService(sqlite_client=db)
    _container.resolved_policy_service = None  # not needed for most admin tests

    app = FastAPI()
    app.include_router(system_router)
    app.include_router(admin_router)
    app.dependency_overrides[require_admin_key] = _key_enforcer(ADMIN_KEY)

    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient(
        "http://test", transport=transport, admin_key=ADMIN_KEY
    ) as c:
        yield c, db

    _container.resolved_sqlite_client = None
    _container.resolved_system_service = None
    _container.resolved_policy_service = None


@pytest_asyncio.fixture
async def client_no_key(db) -> AsyncIterator[StorefrontClient]:
    _container.resolved_sqlite_client = db
    _container.resolved_system_service = SystemService(sqlite_client=db)
    _container.resolved_policy_service = None

    app = FastAPI()
    app.include_router(system_router)
    app.include_router(admin_router)
    app.dependency_overrides[require_admin_key] = _key_enforcer(ADMIN_KEY)

    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient("http://test", transport=transport) as c:
        yield c

    _container.resolved_sqlite_client = None
    _container.resolved_system_service = None
    _container.resolved_policy_service = None


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    async def test_health_returns_ok(self, client):
        c, _ = client
        result = await c.get_health()
        assert result.status == "ok"
        assert result.checks.get("database") == "ok"
        assert "registry" not in result.checks

    async def test_system_status_includes_paused(self, client):
        c, _ = client
        result = await c.get_system_status()
        assert result.paused is False

    async def test_system_status_includes_registry_check(self, client):
        c, _ = client
        result = await c.get_system_status()
        registry_check = result.checks.get("registry")
        assert registry_check is not None
        assert isinstance(registry_check, str) and registry_check

    async def test_system_status_includes_registry_auth_check(self, client):
        c, _ = client
        result = await c.get_system_status()
        auth_check = result.checks.get("registry_auth")
        assert auth_check is not None
        assert isinstance(auth_check, str) and auth_check

    async def test_system_status_includes_negotiation_strategy_check(self, client):
        c, _ = client
        result = await c.get_system_status()
        strat_check = result.checks.get("negotiation_strategy")
        assert strat_check is not None
        assert isinstance(strat_check, str) and strat_check
        assert "exit_on_probe" not in strat_check, (
            f"Negotiation strategy would exit on every round: {strat_check!r}"
        )


# ---------------------------------------------------------------------------
# POST /admin/pause
# ---------------------------------------------------------------------------

class TestAdminPause:
    async def test_requires_admin_key(self, client_no_key):
        with pytest.raises(StorefrontClientError) as exc_info:
            await client_no_key.admin_pause()
        assert "403" in str(exc_info.value)

    async def test_pause_sets_flag(self, client):
        c, _ = client
        result = await c.admin_pause()
        assert result.paused is True
        assert _server._GLOBALLY_PAUSED is True

    async def test_pause_reflected_in_system_status(self, client):
        c, _ = client
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
        c, _ = client
        await c.admin_pause()
        assert _server._GLOBALLY_PAUSED is True
        result = await c.admin_resume()
        assert result.paused is False
        assert _server._GLOBALLY_PAUSED is False

    async def test_resume_reflected_in_system_status(self, client):
        c, _ = client
        await c.admin_pause()
        await c.admin_resume()
        status = await c.get_system_status()
        assert status.paused is False

# ---------------------------------------------------------------------------
# Policy seed, status, and evaluate
# ---------------------------------------------------------------------------

class TestPolicySeed:
    async def test_seed_returns_structured_response(self, client):
        c, _ = client
        result = await c.policy_seed()
        assert "callable_registry_count" in result
        assert "callables" in result
        assert "seeded_policies" in result
        assert "import_errors" in result
        assert isinstance(result["callables"], list)
        assert isinstance(result["import_errors"], list)

    async def test_seed_requires_admin_key(self, client_no_key):
        with pytest.raises(StorefrontClientError) as exc_info:
            await client_no_key.policy_seed()
        assert "403" in str(exc_info.value)

    async def test_seed_seeds_order_create_policy(self, client):
        c, _ = client
        result = await c.policy_seed()
        seeded = result.get("seeded_policies", [])
        assert any("order_create" in p for p in seeded)

    async def test_seed_idempotent(self, client):
        c, _ = client
        r1 = await c.policy_seed()
        r2 = await c.policy_seed()
        assert r1["seeded_policies"] == r2["seeded_policies"]


class TestPolicyStatus:
    async def test_policy_status_returns_structured_response(self, client):
        c, _ = client
        await c.policy_seed()
        result = await c.policy_status()
        assert "callable_count" in result
        assert "callable_registry" in result
        assert "seeded_policies" in result
        assert isinstance(result["seeded_policies"], list)

    async def test_policy_status_lists_seeded_policies(self, client):
        c, _ = client
        await c.policy_seed()
        result = await c.policy_status()
        names = [p["policy_name"] for p in result["seeded_policies"]]
        assert any("order_create" in n for n in names)

    async def test_policy_status_includes_resolvable_flag(self, client):
        c, _ = client
        await c.policy_seed()
        result = await c.policy_status()
        for policy in result["seeded_policies"]:
            assert "components_resolvable" in policy


class TestPolicyEvaluate:
    """Tests for POST /api/v1/system/policy/evaluate.

    Full policy evaluation requires a real PolicyService which needs the full
    domain package. The validation tests (bad event_type, missing offer) can
    run with policy_svc=None because they fail before reaching the service.
    The evaluation tests that need PolicyService are tested in
    unit/services/test_policy_service.py.
    """

    async def test_evaluate_rejects_bad_event_type(self, client):
        """Empty offer/demand rejected with 400 by the controller."""
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.policy_evaluate(
                offer={}, demand={},
                max_duration_seconds=None,
                policy_components=["oc.action.make_offer_from_order_create"],
            )
        # policy_evaluate hardcodes event_type="order_create" in the client,
        # so we test the missing offer/demand validation instead.
        assert "400" in str(exc_info.value) or "422" in str(exc_info.value)

    async def test_evaluate_rejects_missing_offer(self, client):
        """Empty offer dict is rejected with 400 by the controller."""
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.policy_evaluate(
                offer={}, demand={"token": "MOCK", "amount": 1000},
                policy_components=["oc.action.make_offer_from_order_create"],
            )
        assert any(code in str(exc_info.value) for code in ("400", "422"))

    async def test_evaluate_rejects_missing_demand(self, client):
        """Empty demand dict is rejected with 400 by the controller."""
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.policy_evaluate(
                offer={"gpu_model": "H200", "gpu_count": 1, "sla": 99.0, "region": "California, US"},
                demand={},
                policy_components=["oc.action.make_offer_from_order_create"],
            )
        assert any(code in str(exc_info.value) for code in ("400", "422"))


# ---------------------------------------------------------------------------
# GET /api/v1/system/events
# ---------------------------------------------------------------------------

class TestStreamEvents:
    async def test_requires_admin_key(self, client_no_key):
        """Events endpoint requires admin key; client without key receives 403."""
        with pytest.raises(StorefrontClientError) as exc_info:
            await client_no_key.get_events()
        assert "403" in str(exc_info.value)

    async def test_returns_empty_list_on_fresh_db(self, client):
        c, _ = client
        result = await c.get_events()
        assert result.count == 0
        assert result.events == []

    async def test_returns_seeded_events(self, client):
        c, db = client
        import json as _json
        import sqlite3

        conn = sqlite3.connect(db.db_path)
        try:
            conn.execute(
                "INSERT INTO stage_events (ts, stage, event, listing_id, data) "
                "VALUES (?, ?, ?, ?, ?)",
                ("2025-01-01T00:00:00Z", "discovery", "order_published", "listing-1",
                 _json.dumps({"listing_id": "listing-1"})),
            )
            conn.commit()
        finally:
            conn.close()

        result = await c.get_events()
        assert result.count == 1
        assert result.events[0].stage == "discovery"
        assert result.events[0].event == "order_published"
        assert result.events[0].listing_id == "listing-1"

    async def test_since_id_cursor(self, client):
        c, db = client
        import json as _json
        import sqlite3

        conn = sqlite3.connect(db.db_path)
        try:
            for i in range(3):
                conn.execute(
                    "INSERT INTO stage_events (ts, stage, event, data) VALUES (?, ?, ?, ?)",
                    (f"2025-01-0{i+1}T00:00:00Z", "discovery", f"event_{i}",
                     _json.dumps({"seq": i})),
                )
            conn.commit()
        finally:
            conn.close()

        all_events = await c.get_events()
        assert all_events.count == 3

        first_id = all_events.events[0].id
        tail = await c.get_events(since_id=first_id)
        assert tail.count == 2
        assert all(ev.id > first_id for ev in tail.events)

    async def test_stage_filter(self, client):
        c, db = client
        import json as _json
        import sqlite3

        conn = sqlite3.connect(db.db_path)
        try:
            conn.execute(
                "INSERT INTO stage_events (ts, stage, event, data) VALUES (?, ?, ?, ?)",
                ("2025-01-01T00:00:00Z", "discovery", "published", _json.dumps({})),
            )
            conn.execute(
                "INSERT INTO stage_events (ts, stage, event, data) VALUES (?, ?, ?, ?)",
                ("2025-01-01T00:00:01Z", "negotiation", "started", _json.dumps({})),
            )
            conn.commit()
        finally:
            conn.close()

        disc_events = await c.get_events(stage="discovery")
        assert all(ev.stage == "discovery" for ev in disc_events.events)
        assert disc_events.count == 1

        neg_events = await c.get_events(stage="negotiation")
        assert neg_events.count == 1
        assert neg_events.events[0].stage == "negotiation"
