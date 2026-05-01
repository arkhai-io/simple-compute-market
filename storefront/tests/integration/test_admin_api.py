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
from storefront_client.models import StageEventListResponse

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
        # /health must NOT include a registry check (keeps liveness probes fast)
        assert "registry" not in result.checks

    async def test_system_status_includes_paused(self, client):
        """GET /api/v1/system/status includes paused flag regardless of registry state."""
        c, _, _ = client
        result = await c.get_system_status()
        assert result.paused is False

    async def test_system_status_includes_registry_check(self, client):
        """GET /api/v1/system/status must include checks.registry.

        In the integration test environment the registry URL is unconfigured,
        so the value will be 'unconfigured'. What matters is the key is present
        and is a non-empty string.
        """
        c, _, _ = client
        result = await c.get_system_status()
        registry_check = result.checks.get("registry")
        assert registry_check is not None, (
            "checks.registry absent from /api/v1/system/status. "
            "SystemController._health_impl must be called with include_registry=True "
            "from system_status."
        )
        assert isinstance(registry_check, str) and registry_check

    async def test_system_status_includes_registry_auth_check(self, client):
        """GET /api/v1/system/status must include checks.registry_auth.

        Guards against the silent-401 failure mode where the agent's wallet
        doesn't own the pinned onchain_agent_id. In integration tests the
        registry URL is unconfigured so the value will be 'unconfigured'.
        """
        c, _, _ = client
        result = await c.get_system_status()
        auth_check = result.checks.get("registry_auth")
        assert auth_check is not None, (
            "checks.registry_auth absent from /api/v1/system/status. "
            "SystemController._health_impl must call _registry_auth_check()."
        )
        assert isinstance(auth_check, str) and auth_check

    async def test_system_status_includes_negotiation_strategy_check(self, client):
        """GET /api/v1/system/status must include checks.negotiation_strategy.

        The value identifies which strategy is loaded and whether it is viable.
        An exit_on_probe value means every /negotiate/new call will produce a
        terminal failure before any meaningful negotiation — must be caught at
        smoke-test time, not discovered at stage 10 of the e2e test.
        """
        c, _, _ = client
        result = await c.get_system_status()
        strat_check = result.checks.get("negotiation_strategy")
        assert strat_check is not None, (
            "checks.negotiation_strategy absent from /api/v1/system/status. "
            "SystemController._negotiation_strategy_check() must be wired into "
            "_health_impl(include_registry=True)."
        )
        assert isinstance(strat_check, str) and strat_check
        # In integration tests the strategy is always bisection (no torch required).
        assert "exit_on_probe" not in strat_check, (
            f"Negotiation strategy would exit on every round: {strat_check!r}. "
            "Set policy_mode = 'bisection' in config.toml or install torch."
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
            max_duration_seconds=3600,
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
            max_duration_seconds=3600,
            seller="http://seller:8001",
        )
        await db.set_listing_paused(listing_id="pause-count", paused=True)
        result = await c.admin_status()
        # Paused order is excluded from open_orders count
        assert result.open_listings == 0
        assert result.paused_listings == 1


# ---------------------------------------------------------------------------
# Policy seed, status, and evaluate
# ---------------------------------------------------------------------------

class TestPolicySeed:
    async def test_seed_returns_structured_response(self, client):
        c, _, _ = client
        result = await c.policy_seed()
        # Response must have these keys regardless of whether callables loaded
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
        c, _, _ = client
        result = await c.policy_seed()
        seeded = result.get("seeded_policies", [])
        assert any("order_create" in p for p in seeded), (
            f"order_create policy not seeded. Got: {seeded}"
        )

    async def test_seed_idempotent(self, client):
        """Calling seed twice should not fail or duplicate policies."""
        c, _, _ = client
        r1 = await c.policy_seed()
        r2 = await c.policy_seed()
        assert r1["seeded_policies"] == r2["seeded_policies"]


class TestPolicyStatus:
    async def test_policy_status_returns_structured_response(self, client):
        c, _, _ = client
        # Seed first so there is something to read
        await c.policy_seed()
        result = await c.policy_status()
        assert "callable_count" in result
        assert "callable_registry" in result
        assert "seeded_policies" in result
        assert isinstance(result["seeded_policies"], list)

    async def test_policy_status_lists_seeded_policies(self, client):
        c, _, _ = client
        await c.policy_seed()
        result = await c.policy_status()
        names = [p["policy_name"] for p in result["seeded_policies"]]
        assert any("order_create" in n for n in names), (
            f"order_create policy not in status. Got: {names}"
        )

    async def test_policy_status_includes_resolvable_flag(self, client):
        c, _, _ = client
        await c.policy_seed()
        result = await c.policy_status()
        for policy in result["seeded_policies"]:
            assert "components_resolvable" in policy, (
                f"Missing components_resolvable in {policy}"
            )


class TestPolicyEvaluate:
    async def test_evaluate_returns_structured_response(self, client):
        c, _, _ = client
        await c.policy_seed()
        result = await c.policy_evaluate(
            offer={"gpu_model": "H200", "gpu_count": 1, "sla": 99.0, "region": "California, US"},
            demand={"token": {"symbol": "MOCK", "contract_address": "0x0000000000000000000000000000000000000001", "decimals": 18}, "amount": 10000},
        )
        assert "action" in result
        assert "policy_used" in result
        assert "resolvable" in result
        assert "reason" in result

    async def test_evaluate_no_policies_returns_no_action(self, client):
        """Fresh DB with no seeded policies → no_action with clear reason."""
        c, _, _ = client
        # Don't seed — fresh DB has no policies
        result = await c.policy_evaluate(
            offer={"gpu_model": "H200", "gpu_count": 1, "sla": 99.0, "region": "California, US"},
            demand={"token": {"symbol": "MOCK", "contract_address": "0x0000000000000000000000000000000000000001", "decimals": 18}, "amount": 10000},
        )
        # With no policies seeded, must return no_action and a reason
        assert result["action"] == "no_action"
        assert result["reason"] is not None

    async def test_evaluate_rejects_bad_event_type(self, client):
        c, _, _ = client
        resp = await c._client.post(
            "/api/v1/system/policy/evaluate",
            json={"event_type": "totally_unknown", "offer": {}, "demand": {}},
        )
        assert resp.status_code == 400

    async def test_evaluate_rejects_missing_offer(self, client):
        c, _, _ = client
        resp = await c._client.post(
            "/api/v1/system/policy/evaluate",
            json={"event_type": "order_create", "demand": {}},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/v1/system/events
# ---------------------------------------------------------------------------

class TestStreamEvents:
    async def test_requires_admin_key(self, client_no_key):
        resp = await client_no_key._client.get("/api/v1/system/events")
        assert resp.status_code == 403

    async def test_returns_empty_list_on_fresh_db(self, client):
        c, _, _ = client
        result = await c.get_events()
        assert result.count == 0
        assert result.events == []

    async def test_returns_seeded_events(self, client):
        """Events written via stage_log.stage_event() appear in get_events()."""
        c, db, _ = client
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
        """since_id filters to only rows with id > since_id."""
        c, db, _ = client
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
        """stage= query param restricts results to that stage."""
        c, db, _ = client
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
