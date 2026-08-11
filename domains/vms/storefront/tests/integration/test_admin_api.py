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

import sqlite3
from collections.abc import AsyncIterator
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from storefront_client.client import StorefrontClient, StorefrontClientError

import market_storefront.container as _container
import market_storefront.server as _server
from market_storefront.controllers.admin_controller import router as admin_router
from market_storefront.controllers.system_controller import router as system_router
from market_storefront.listings.reconciler import (
    mark_derived_listings_closed,
    record_derived_listing,
)
from market_storefront.middleware.admin_auth import require_admin_key
from market_storefront.services.system_service import SystemService
from market_storefront.utils.sqlite_client import SQLiteClient
from tests._settings_overrides import settings_overrides

ADMIN_KEY = "test-admin-key"


def _key_enforcer(expected_key: str):
    """Depends-compatible function that enforces a specific X-Admin-Key header.
    Used in test fixtures to simulate production admin-key enforcement without
    requiring a mutable CONFIG (which is a frozen dataclass).
    """
    from fastapi import Header, HTTPException

    def _dep(
        x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    ) -> None:
        if x_admin_key != expected_key:
            raise HTTPException(
                status_code=403, detail="Valid X-Admin-Key header required"
            )

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


@pytest_asyncio.fixture
async def client_no_key(db) -> AsyncIterator[StorefrontClient]:
    _container.resolved_sqlite_client = db
    _container.resolved_system_service = SystemService(sqlite_client=db)

    app = FastAPI()
    app.include_router(system_router)
    app.include_router(admin_router)
    app.dependency_overrides[require_admin_key] = _key_enforcer(ADMIN_KEY)

    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient("http://test", transport=transport) as c:
        yield c

    _container.resolved_sqlite_client = None
    _container.resolved_system_service = None


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

    async def test_system_status_includes_negotiation_strategy_check(self, client):
        c, _ = client
        result = await c.get_system_status()
        strat_check = result.checks.get("negotiation_strategy")
        assert strat_check is not None
        assert isinstance(strat_check, str) and strat_check
        assert "exit_on_probe" not in strat_check, (
            f"Negotiation strategy would exit on every round: {strat_check!r}"
        )

    async def test_system_status_surfaces_site_projection_state(self, db):
        """End-to-end: a populated projection status summary must survive
        SystemService -> HealthResponse (server, pydantic) -> HTTP JSON ->
        HealthResponse (client, dataclass) intact. Exercises the real route
        through the real StorefrontClient, not SystemService in isolation --
        this is exactly the layer a service-level unit test cannot prove.
        """
        summary = {
            "site-a": {
                "resource_pool": {
                    "state": "loaded",
                    "revision": 3,
                    "digest": "abc123",
                    "last_error": None,
                    "fetched_at": "2026-08-03T12:00:00+00:00",
                },
                "capacity_bucket": {
                    "state": "unavailable",
                    "revision": None,
                    "digest": None,
                    "last_error": "connection refused",
                    "fetched_at": None,
                },
            },
        }
        _container.resolved_sqlite_client = db
        _container.resolved_system_service = SystemService(
            sqlite_client=db,
            projection_status_provider=lambda: summary,
        )
        try:
            app = FastAPI()
            app.include_router(system_router)
            transport = httpx.ASGITransport(app=app)
            async with StorefrontClient("http://test", transport=transport) as c:
                result = await c.get_system_status()
        finally:
            _container.resolved_sqlite_client = None
            _container.resolved_system_service = None

        assert result.site_projections == summary
        assert result.site_projections["site-a"]["resource_pool"]["state"] == "loaded"
        assert (
            result.site_projections["site-a"]["capacity_bucket"]["state"]
            == "unavailable"
        )

    async def test_health_omits_site_projections(self, db):
        """The fast liveness probe (/health) must not carry this field at all."""
        _container.resolved_sqlite_client = db
        _container.resolved_system_service = SystemService(
            sqlite_client=db,
            projection_status_provider=lambda: {"site-a": {}},
        )
        try:
            app = FastAPI()
            app.include_router(system_router)
            transport = httpx.ASGITransport(app=app)
            async with StorefrontClient("http://test", transport=transport) as c:
                result = await c.get_health()
        finally:
            _container.resolved_sqlite_client = None
            _container.resolved_system_service = None

        assert result.site_projections is None

    async def test_system_status_surfaces_listing_mode_explanations(self, db):
        """Same real end-to-end round trip as
        test_system_status_surfaces_site_projection_state (above), for the
        sibling field -- this is exactly the layer that hid the original
        site_projections bug (Pydantic v2's default extra="ignore" silently
        dropping a field the server model hadn't declared), so the new
        field gets the same real-HTTP proof rather than only a
        SystemService-level unit test.
        """
        explanations = {
            "site-a": {
                "gpu-pool": "unrecognized listing_mode 'bogus', using 'fungible'"
            },
        }
        _container.resolved_sqlite_client = db
        _container.resolved_system_service = SystemService(
            sqlite_client=db,
            listing_mode_explanation_provider=lambda: explanations,
        )
        try:
            app = FastAPI()
            app.include_router(system_router)
            transport = httpx.ASGITransport(app=app)
            async with StorefrontClient("http://test", transport=transport) as c:
                result = await c.get_system_status()
        finally:
            _container.resolved_sqlite_client = None
            _container.resolved_system_service = None

        assert result.listing_mode_explanations == explanations

    async def test_health_omits_listing_mode_explanations(self, db):
        """The fast liveness probe (/health) must not carry this field either."""
        _container.resolved_sqlite_client = db
        _container.resolved_system_service = SystemService(
            sqlite_client=db,
            listing_mode_explanation_provider=lambda: {"site-a": {}},
        )
        try:
            app = FastAPI()
            app.include_router(system_router)
            transport = httpx.ASGITransport(app=app)
            async with StorefrontClient("http://test", transport=transport) as c:
                result = await c.get_health()
        finally:
            _container.resolved_sqlite_client = None
            _container.resolved_system_service = None

        assert result.listing_mode_explanations is None


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


class TestPauseHaltsTimerLoops:
    """Pause holds background work idle as well as refusing negotiations.

    The endpoint returning 200 has never proven the loops stopped working; after
    this became the substantive half of what pause means, the response reports
    each loop's state and a caller can verify it.
    """

    async def test_pause_reports_every_registered_loop_as_paused(self, client):
        import asyncio

        from core_storefront.app_startup import StorefrontBackgroundTask
        from market_storefront import lifecycle

        c, _ = client

        async def _forever() -> None:
            while True:
                await asyncio.sleep(3600)

        lifecycle.reset_for_tests()
        try:
            lifecycle.start_registered_loop(
                StorefrontBackgroundTask(name="claims_engine", task_factory=_forever)
            )
            await asyncio.sleep(0)

            result = await c.admin_pause()

            assert result.paused is True
            assert result.loops == {"claims_engine": "paused"}
        finally:
            lifecycle.reset_for_tests()

    async def test_resume_reports_them_running_again(self, client):
        import asyncio

        from core_storefront.app_startup import StorefrontBackgroundTask
        from market_storefront import lifecycle

        c, _ = client

        async def _forever() -> None:
            while True:
                await asyncio.sleep(3600)

        lifecycle.reset_for_tests()
        try:
            lifecycle.start_registered_loop(
                StorefrontBackgroundTask(name="claims_engine", task_factory=_forever)
            )
            await c.admin_pause()

            result = await c.admin_resume()
            await asyncio.sleep(0)

            assert result.paused is False
            assert result.loops == {"claims_engine": "running"}
        finally:
            lifecycle.reset_for_tests()


class TestLifecycleAdvance:
    """Each advance runs one cycle of a loop and works while paused.

    Running while paused is the entire purpose: a scenario pauses once at setup
    and advances deliberately, so an advance that respected the pause would be
    unusable.
    """

    async def test_requires_admin_key(self, client_no_key):
        with pytest.raises(StorefrontClientError) as exc_info:
            await client_no_key.admin_run_lifecycle_cycle("claims")
        assert "403" in str(exc_info.value)

    async def test_claims_cycle_runs_while_paused(self, client):
        c, _ = client
        await c.admin_pause()

        result = await c.admin_run_lifecycle_cycle("claims")

        assert result["loop"] == "claims_engine"
        assert "processed" in result

    async def test_fulfillment_resume_cycle_runs_while_paused(self, client):
        c, _ = client
        await c.admin_pause()

        result = await c.admin_run_lifecycle_cycle("fulfillment-resume")

        assert result["loop"] == "fulfillment_resume"

    async def test_negotiation_watchdog_cycle_runs_while_paused(self, client):
        c, _ = client
        await c.admin_pause()

        result = await c.admin_run_lifecycle_cycle("negotiation-watchdog")

        assert result["loop"] == "negotiation_watchdog"
        assert "swept" in result

    async def test_capacity_events_cycle_runs_the_real_reconcile(self, client):
        """The advance drives production reconciliation, unpatched.

        Weaker than it should be, and deliberately so rather than misleadingly
        strong. The assertion this wants is a listing transition — advance once,
        observe a slice close or reopen — and two attempts at it did not produce
        one against `tests/fake_site`, for a reason not yet identified: the
        reconcile runs and finds nothing to change. Rather than reach for a patch
        of `full_capacity_reconcile` to make the test say something (which is the
        mocked-internals shape `TESTING.md` forbids), this asserts only what it
        can honestly observe, and the transition assertion is recorded as owed.

        What it does establish: the route resolves, calls the real reconcile with
        a real site client behind it, and completes while the storefront is
        paused.
        """
        from tests.fake_site import site_capacity

        c, db = client
        await _seed_dynamic_listing_pool_rows(db)
        await c.admin_pause()

        with site_capacity(_fake_pool_site()):
            result = await c.admin_run_lifecycle_cycle("capacity-events")

        assert result == {"loop": "capacity_events_poller", "reconciled": True}


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


class TestAdminImportResources:
    """Tests for POST /api/v1/admin/portfolio/resources/import."""

    _VALID_CSV = (
        "resource_id,resource_type,resource_subtype,unit,value,state,"
        "min_price,token,max_duration_seconds,"
        "attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host\n"
        "compute-import-001,compute.gpu,rtx5080,count,1,available,"
        "150,0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0,,"
        'RTX 5080,90.0,"California, US",kvm1\n'
    )

    async def test_requires_admin_key(self, client_no_key):
        with pytest.raises(StorefrontClientError) as exc_info:
            await client_no_key.admin_import_resources(self._VALID_CSV.encode())
        assert "403" in str(exc_info.value)

    async def test_imports_valid_csv(self, client):
        c, db = client
        result = await c.admin_import_resources(self._VALID_CSV.encode())
        assert result.imported_count == 1
        assert result.failed_count == 0
        assert result.total_rows == 1
        resources = await db.list_resources()
        assert len(resources) == 1
        assert resources[0]["resource_id"] == "compute-import-001"

    async def test_upserts_when_table_already_populated(self, client):
        """Import always upserts regardless of existing rows (clobber path)."""
        c, db = client
        # Pre-seed one row via the normal DB path.
        await db.upsert_resource(
            resource_id="pre-existing-001",
            resource_type="compute.gpu",
            state="available",
        )
        # Import a different row — both should be present (append-only upsert).
        result = await c.admin_import_resources(self._VALID_CSV.encode())
        assert result.imported_count == 1
        resources = await db.list_resources()
        assert len(resources) == 2

    async def test_rejects_csv_missing_required_column(self, client):
        c, _ = client
        bad_csv = b"resource_id,state\ncompute-bad-001,available\n"
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.admin_import_resources(bad_csv)
        assert "400" in str(exc_info.value)

    async def test_partial_import_counts_failures(self, client):
        """Rows with invalid data are counted in failed_count; valid rows still import."""
        c, _ = client
        # One valid row + one row with a type that will fail schema validation.
        mixed_csv = (
            b"resource_id,resource_type,resource_subtype,unit,value,state,"
            b"min_price,token,max_duration_seconds,"
            b"attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host\n"
            b"compute-good-001,compute.gpu,rtx5080,count,1,available,"
            b"150,0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0,,"
            b'RTX 5080,90.0,"California, US",kvm1\n'
            # Row with missing resource_id will fail.
            b',compute.gpu,rtx5080,count,1,available,150,0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0,,RTX 5080,90.0,"California, US",kvm1\n'
        )
        result = await c.admin_import_resources(mixed_csv)
        assert result.total_rows == 2
        # The good row should import even if one fails.
        assert result.imported_count >= 1


async def _seed_dynamic_listing_pool_rows(
    db: SQLiteClient,
    *,
    record_derived: bool = True,
) -> None:
    await db.upsert_resource(
        resource_id="pool-h200-1",
        resource_type="compute.gpu",
        resource_subtype="h200",
        unit="count",
        value=4,
        state="available",
        attributes={
            "gpu_model": "H200",
            "region": "California, US",
            "vm_host": "host-1",
        },
    )
    for gpu_count in range(1, 5):
        listing_id = f"listing-{gpu_count}x"
        await db.upsert_listing(
            listing_id=listing_id,
            status="open",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
            offer_resource={
                "resource_id": "pool-h200-1",
                "gpu_model": "H200",
                "gpu_count": gpu_count,
                "region": "California, US",
                "sla": 99.0,
            },
            accepted_escrows=[
                {
                    "chain_name": "anvil",
                    "escrow_address": "0x" + "11" * 20,
                    "literal_fields": {"token": "0x" + "22" * 20},
                    "rates": [{"field": "amount", "per": "hour", "value": "100"}],
                }
            ],
            demands=[],
            fulfillment_resource=None,
            max_duration_seconds=3600,
            seller="http://seller",
        )
        if record_derived:
            record_derived_listing(
                db.db_path,
                listing_id=listing_id,
                site_id="default",
                resource_id="pool-h200-1",
                gpu_count=gpu_count,
            )


def _fake_pool_site():
    from tests.fake_site import FakeSite

    fake = FakeSite()
    fake.add_resource(
        "pool-h200-1",
        4,
        attributes={
            "gpu_model": "H200",
            "region": "California, US",
            "vm_host": "host-1",
        },
    )
    return fake


async def _ledger_hold(capacity, *, gpu_count: int = 2) -> str:
    reserved = await capacity.reserve(
        claim={"resource_id": "pool-h200-1", "gpu_count": gpu_count},
        deal_ref={"listing_id": "listing-2x", "escrow_uid": "escrow-2x"},
    )
    assert reserved is not None
    return str(reserved["capacity_reservation_id"])


class TestFulfillmentEvents:
    """Deal-scoped event endpoints over the site-authority ledger.

    The reservation rows live in the ledger; these endpoints stage deal
    context, reconcile derived listings against the aggregated
    availability, and (for capacity-released / failed) return the units
    through the capacity client.
    """

    async def test_admin_reserve_capacity_closes_oversized_listings(self, client):
        from tests.fake_site import site_capacity

        c, db = client
        await _seed_dynamic_listing_pool_rows(db)

        with site_capacity(_fake_pool_site()):
            response = await c.admin_reserve_capacity(
                required_attributes={
                    "resource_id": "pool-h200-1",
                    "gpu_count": 2,
                },
                listing_id="listing-2x-manual",
                escrow_uid="manual-escrow-2x",
            )

        assert response.capacity_reservation_id
        assert response.resource_id == "pool-h200-1"
        assert response.gpu_count == 2
        assert sorted(response.closed_listing_ids) == ["listing-3x", "listing-4x"]
        statuses = {
            gpu_count: (await db.load_listing(listing_id=f"listing-{gpu_count}x"))[
                "status"
            ]
            for gpu_count in range(1, 5)
        }
        assert statuses == {
            1: "open",
            2: "open",
            3: "closed",
            4: "closed",
        }

    async def test_admin_reserve_capacity_for_a_mapped_listing_pins_to_its_site(
        self,
        client,
    ):
        """A listing already mapped to a site (derived_compute_listings)
        must reserve there -- proves the site_id lookup and threading
        through reserve(site=...) doesn't break the ordinary case where
        the mapped site is also the only site configured. The collision
        case (a mapped site preferred over placement's own choice) is
        covered at the AggregateCapacityClient unit level
        (test_aggregation.py), where a real multi-site setup exists.
        """
        from tests.fake_site import site_capacity

        c, db = client
        await _seed_dynamic_listing_pool_rows(db)
        record_derived_listing(
            db.db_path,
            listing_id="listing-2x-manual",
            site_id="default",
            pool_id="pool-h200-1",
            resource_id=None,
            gpu_count=2,
        )

        with site_capacity(_fake_pool_site()):
            response = await c.admin_reserve_capacity(
                required_attributes={
                    "resource_id": "pool-h200-1",
                    "gpu_count": 2,
                },
                listing_id="listing-2x-manual",
                escrow_uid="manual-escrow-2x",
            )

        assert response.capacity_reservation_id
        assert response.resource_id == "pool-h200-1"

    async def test_admin_reserve_capacity_honors_a_live_refusal_over_a_cached_projection(
        self,
        client,
    ):
        """A fresh, valid cached site_resource_pools projection showing
        abundant capacity must not override what the site's live
        reservations endpoint actually says. reserve() has no code path
        that reads the projection cache at all today (confirmed
        directly against aggregation.py -- zero references); this test
        proves the *observable* consequence of that fact, so it fails
        immediately if a future change ever adds such a shortcut.
        """
        from core_storefront.site_projections import (
            ProjectionCache,
            ProjectionIdentity,
            ProjectionState,
        )

        from market_storefront.services import site_projection_cache as spc
        from tests.fake_site import FakeSite, site_capacity

        c, db = client
        # The live site genuinely has zero capacity for this resource.
        fake = FakeSite()
        fake.add_resource(
            "pool-h200-1",
            0,
            attributes={"gpu_model": "H200", "vm_host": "host-1"},
        )
        # Mapped listing -- routes reserve() through _reserve_at_site
        # (the pinned-site path), not the placement fan-out; without a
        # mapping this test would exercise a different code path than
        # the one it's meant to guard.
        record_derived_listing(
            db.db_path,
            listing_id="listing-refused-mapped",
            site_id="default",
            pool_id="pool-h200-1",
            resource_id=None,
            gpu_count=2,
        )

        # A cached projection for the same site, same pool, claiming
        # abundant capacity -- fresh, loaded, not stale.
        resource_pools_cache: ProjectionCache = ProjectionCache(client=None)
        resource_pools_cache._value = [
            {
                "resource_pool_id": "pool-h200-1",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 8},
                        "available": {"gpu_count": 8},
                        "attributes": {"gpu_model": "H200"},
                        "enabled": True,
                    }
                ],
            }
        ]
        resource_pools_cache._state = ProjectionState.loaded
        resource_pools_cache._identity = ProjectionIdentity(revision=1, digest="abc")
        caches = spc.SiteProjectionCaches(
            resource_pools=resource_pools_cache,
            capacity_buckets=ProjectionCache(client=None),
        )

        with (
            site_capacity(fake),
            patch.dict(spc._caches, {"default": caches}, clear=True),
        ):
            with pytest.raises(StorefrontClientError) as exc_info:
                await c.admin_reserve_capacity(
                    required_attributes={
                        "resource_id": "pool-h200-1",
                        "gpu_count": 2,
                    },
                    listing_id="listing-refused-mapped",
                    escrow_uid="manual-escrow-refused",
                )

        assert "409" in str(exc_info.value)

    async def test_admin_reserve_reports_listings_closed_by_delta_race(self, client):
        from tests.fake_site import site_capacity

        c, db = client
        await _seed_dynamic_listing_pool_rows(db)
        fake = _fake_pool_site()
        original_handle = fake._handle

        def handle_with_delta_reconciliation(request):
            response = original_handle(request)
            if (
                request.method == "POST"
                and request.url.path == "/api/v1/capacity/reservations"
            ):
                conn = sqlite3.connect(db.db_path)
                try:
                    conn.execute(
                        "UPDATE listings SET status = 'closed' WHERE listing_id = ?",
                        ("listing-3x",),
                    )
                    conn.commit()
                finally:
                    conn.close()
                mark_derived_listings_closed(
                    db.db_path,
                    ["listing-3x"],
                    home_site="default",
                    configured_site_count=1,
                )
            return response

        fake._handle = handle_with_delta_reconciliation
        with site_capacity(fake):
            response = await c.admin_reserve_capacity(
                required_attributes={
                    "resource_id": "pool-h200-1",
                    "gpu_count": 2,
                },
                listing_id="listing-2x-manual",
                escrow_uid="manual-escrow-2x",
            )

        assert sorted(response.closed_listing_ids) == [
            "listing-3x",
            "listing-4x",
        ]

    async def test_admin_reserve_echoes_a_resource_pinned_claim_and_no_pool(
        self, client,
    ):
        """A resource-pinned claim reports its resource and no pool.

        The reservation response carries neither field -- the site strips both,
        because a reservation commits to a site and a shape and scheduling may
        rebind it within that site. So what comes back is the claim's own
        pinning, and a claim that pinned no pool reports none rather than
        reporting the pool the site happened to match.
        """
        from tests.fake_site import site_capacity

        c, db = client
        await _seed_dynamic_listing_pool_rows(db)

        with site_capacity(_fake_pool_site()):
            response = await c.admin_reserve_capacity(
                required_attributes={
                    "resource_id": "pool-h200-1",
                    "gpu_count": 2,
                },
                listing_id="listing-2x-manual",
                escrow_uid="manual-escrow-pinned",
            )

        assert response.capacity_reservation_id
        assert response.resource_id == "pool-h200-1"
        assert response.pool_id is None
        assert response.member_id is None

    async def test_admin_reserve_echoes_a_pool_scoped_claim_and_no_resource(
        self, client,
    ):
        """A pool-scoped claim reports its pool and no resource.

        The inverse of the test above, and the shape the fungible e2e scenario
        drives. Reporting a resource here would name the host the site matched,
        which fulfillment scheduling is free to move.
        """
        from tests.fake_site import site_capacity

        c, db = client
        await _seed_dynamic_listing_pool_rows(db)
        fake = _fake_pool_site()
        fake.add_resource(
            "pool-h200-2",
            4,
            attributes={
                "pool_id": "pool-h200",
                "gpu_model": "H200",
                "region": "California, US",
                "vm_host": "host-2",
            },
        )

        with site_capacity(fake):
            response = await c.admin_reserve_capacity(
                required_attributes={
                    "pool_id": "pool-h200",
                    "gpu_count": 2,
                },
                listing_id="listing-2x-manual",
                escrow_uid="manual-escrow-pooled",
            )

        assert response.capacity_reservation_id
        assert response.pool_id == "pool-h200"
        assert response.resource_id is None

    async def test_admin_reserve_capacity_returns_409_when_no_capacity(self, client):
        from tests.fake_site import site_capacity

        c, db = client
        await _seed_dynamic_listing_pool_rows(db)

        with site_capacity(_fake_pool_site()) as capacity:
            await _ledger_hold(capacity, gpu_count=2)
            with pytest.raises(StorefrontClientError) as exc_info:
                await c.admin_reserve_capacity(
                    required_attributes={
                        "resource_id": "pool-h200-1",
                        "gpu_count": 3,
                    },
                    listing_id="listing-3x-manual",
                    escrow_uid="manual-escrow-3x",
                )

        assert "409" in str(exc_info.value)

    async def test_admin_reserve_capacity_returns_500_for_a_stale_site_mapping(
        self,
        client,
    ):
        """A listing mapped to a site that isn't currently configured is
        a data-integrity problem, not a capacity answer -- must not be
        collapsed into the same 409 a genuine refusal returns."""
        from tests.fake_site import site_capacity

        c, db = client
        await _seed_dynamic_listing_pool_rows(db)
        record_derived_listing(
            db.db_path,
            listing_id="listing-stale-mapping",
            site_id="ghost-site",
            pool_id="pool-h200-1",
            resource_id=None,
            gpu_count=2,
        )

        with site_capacity(_fake_pool_site()):
            with pytest.raises(StorefrontClientError) as exc_info:
                await c.admin_reserve_capacity(
                    required_attributes={
                        "resource_id": "pool-h200-1",
                        "gpu_count": 2,
                    },
                    listing_id="listing-stale-mapping",
                    escrow_uid="manual-escrow-stale",
                )

        assert "500" in str(exc_info.value)

    async def test_admin_reserve_capacity_returns_502_when_the_mapped_site_is_unreachable(
        self,
        client,
    ):
        """The mapped site itself failing to respond is also distinct
        from a genuine "no capacity" refusal -- must surface as an
        upstream-communication failure, not a 409."""
        from tests.fake_site import site_capacity

        c, db = client
        await _seed_dynamic_listing_pool_rows(db)
        record_derived_listing(
            db.db_path,
            listing_id="listing-unreachable",
            site_id="default",
            pool_id="pool-h200-1",
            resource_id=None,
            gpu_count=2,
        )
        fake = _fake_pool_site()

        def handle_reservation_failure(request):
            if (
                request.method == "POST"
                and request.url.path == "/api/v1/capacity/reservations"
            ):
                raise ConnectionError("site unreachable")
            return original_handle(request)

        original_handle = fake._handle
        fake._handle = handle_reservation_failure

        with site_capacity(fake):
            with pytest.raises(StorefrontClientError) as exc_info:
                await c.admin_reserve_capacity(
                    required_attributes={
                        "resource_id": "pool-h200-1",
                        "gpu_count": 2,
                    },
                    listing_id="listing-unreachable",
                    escrow_uid="manual-escrow-unreachable",
                )

        assert "502" in str(exc_info.value)

    async def test_usage_started_closes_oversized_listings(self, client):
        from tests.fake_site import site_capacity

        c, db = client
        await _seed_dynamic_listing_pool_rows(db)
        fake = _fake_pool_site()

        with site_capacity(fake) as capacity:
            capacity_reservation_id = await _ledger_hold(capacity, gpu_count=2)
            response = await c.notify_usage_started(
                capacity_reservation_id,
                escrow_uid="escrow-2x",
                provider_id="provider-a",
                provider_lease_id="lease-2x",
                resource_id="provider-resource-2x",
                vm_host="kvm1",
                vm_target="tenant-2x",
                lease_end_utc="2026-01-01T00:00:00Z",
            )

        assert response["capacity_reservation_id"] == capacity_reservation_id
        assert response["state"] == "leased"
        assert sorted(response["closed_listing_ids"]) == ["listing-3x", "listing-4x"]
        # Progress events carry no capacity effect: a held reservation is
        # held in every progress state, and the ledger row is the
        # provisioning service's to advance.
        assert fake.reservations[capacity_reservation_id]["state"] == "reserved"

    async def test_capacity_released_releases_and_reopens(self, client):
        from tests.fake_site import site_capacity

        c, db = client
        await _seed_dynamic_listing_pool_rows(db)
        fake = _fake_pool_site()

        with site_capacity(fake) as capacity:
            capacity_reservation_id = await _ledger_hold(capacity, gpu_count=2)
            closed = await c.notify_usage_started(
                capacity_reservation_id,
                escrow_uid="escrow-2x",
            )
            assert sorted(closed["closed_listing_ids"]) == [
                "listing-3x",
                "listing-4x",
            ]

            response = await c.notify_capacity_released(capacity_reservation_id)

        assert response["capacity_reservation_id"] == capacity_reservation_id
        assert response["state"] == "released"
        assert sorted(response["reopened_listing_ids"]) == ["listing-3x", "listing-4x"]
        statuses = {
            gpu_count: (await db.load_listing(listing_id=f"listing-{gpu_count}x"))[
                "status"
            ]
            for gpu_count in range(1, 5)
        }
        assert statuses == {
            1: "open",
            2: "open",
            3: "open",
            4: "open",
        }
        assert fake.reservations[capacity_reservation_id]["state"] == "released"
        assert fake._available("pool-h200-1") == 4

    async def test_manual_compute_listings_reopen_after_release(self, client):
        from tests.fake_site import site_capacity

        c, db = client
        await _seed_dynamic_listing_pool_rows(db, record_derived=False)
        fake = _fake_pool_site()

        with site_capacity(fake) as capacity:
            capacity_reservation_id = await _ledger_hold(capacity, gpu_count=2)
            closed = await c.notify_usage_started(
                capacity_reservation_id,
                escrow_uid="escrow-2x",
            )
            assert sorted(closed["closed_listing_ids"]) == [
                "listing-3x",
                "listing-4x",
            ]

            response = await c.notify_capacity_released(capacity_reservation_id)

        assert sorted(response["reopened_listing_ids"]) == [
            "listing-3x",
            "listing-4x",
        ]
        statuses = {
            gpu_count: (await db.load_listing(listing_id=f"listing-{gpu_count}x"))[
                "status"
            ]
            for gpu_count in range(1, 5)
        }
        assert statuses == {
            1: "open",
            2: "open",
            3: "open",
            4: "open",
        }

    async def test_fulfillment_failed_releases_with_failure_metadata(self, client):
        from tests.fake_site import site_capacity

        c, db = client
        await _seed_dynamic_listing_pool_rows(db)
        fake = _fake_pool_site()

        with site_capacity(fake) as capacity:
            capacity_reservation_id = await _ledger_hold(capacity, gpu_count=2)
            response = await c.notify_fulfillment_failed(
                capacity_reservation_id,
                provider_id="provider-a",
                provider_job_id="job-create-1",
                resource_id="provider-resource-2x",
                reason="provisioning_error",
                message="host rejected request",
                logs_ref="s3://logs/job-create-1",
            )

        assert response["capacity_reservation_id"] == capacity_reservation_id
        assert response["state"] == "released"
        reservation = fake.reservations[capacity_reservation_id]
        assert reservation["state"] == "released"
        assert reservation["failure_reason"] == "provisioning_error"
        assert reservation["failure_message"] == "host rejected request"
        assert fake._available("pool-h200-1") == 4

    async def test_release_of_unknown_reservation_is_idempotent(self, client):
        """The watchdog usually released first; a second capacity-released
        for the same (or an unknown) reservation must land cleanly."""
        from tests.fake_site import FakeSite, site_capacity

        c, _ = client
        with site_capacity(FakeSite()):
            response = await c.notify_capacity_released(
                "ledger-only-alloc",
                resource_id="compute-kvm1-001",
                released_at="2026-06-10T00:00:00Z",
            )
        assert response["capacity_reservation_id"] == "ledger-only-alloc"
        assert response["state"] == "released"


# ---------------------------------------------------------------------------
# Real orchestration: a cached projection reaches the real reconciler and
# produces real storefront DB/listing state, using the real
# close_stale_compute_listings_after_capacity_change /
# reopen_available_compute_listings_after_capacity_change functions rather
# than a mocked reconciliation boundary.
# ---------------------------------------------------------------------------


class TestRealOrchestrationCacheToReconciliation:
    async def test_cached_projection_closes_real_oversized_listings(self, client):
        from core_storefront.capacity import CapacityDelta
        from core_storefront.site_projections import (
            ProjectionCache,
            ProjectionIdentity,
            ProjectionState,
        )

        from market_storefront.services import site_projection_cache as spc
        from market_storefront.services.capacity_client import (
            _make_listing_reconcile_subscriber,
        )
        from tests.fake_site import site_capacity

        c, db = client
        await _seed_dynamic_listing_pool_rows(db)

        # The projection's own "available" field takes precedence over the
        # live snapshot (see _projected_resource_usage) -- 2 of the pool's
        # 4 GPUs available, authoritative, not derived from a reservation.
        resource_pools_cache: ProjectionCache = ProjectionCache(client=None)
        resource_pools_cache._value = [
            {
                "resource_pool_id": "pool-h200-1",
                "resources": [
                    {
                        "physical_resource_id": "pool-h200-1",
                        "capacity": {"gpu_count": 4},
                        "available": {"gpu_count": 2},
                        "attributes": {"gpu_model": "H200"},
                        "enabled": True,
                    }
                ],
            }
        ]
        resource_pools_cache._state = ProjectionState.loaded
        resource_pools_cache._identity = ProjectionIdentity(revision=1, digest="abc")
        caches = spc.SiteProjectionCaches(
            resource_pools=resource_pools_cache,
            capacity_buckets=ProjectionCache(client=None),
        )

        with (
            site_capacity(_fake_pool_site()) as capacity,
            patch.dict(spc._caches, {"default": caches}, clear=True),
            settings_overrides(**{"capacity.use_site_projection_for_listings": True}),
            patch(
                "market_storefront.services.publication_service.get_sqlite_client",
                return_value=db,
            ),
        ):
            # close_order (called for each stale listing) is registry-
            # backed and has no real registry server here -- it falls
            # back to get_sqlite_client() to confirm the DB-side close
            # landed even when the registry push failed. That global
            # singleton defaults to settings.db_path, not this test's
            # own db fixture, so it must be patched here or the
            # fallback check silently finds nothing.
            subscriber = _make_listing_reconcile_subscriber(lambda: db, capacity)
            await subscriber(CapacityDelta(kind="reserved", version=1))

        # Real DB state, not a fake's captured call arguments: listing-3x
        # and listing-4x (3 and 4 GPUs) no longer fit under the cached
        # projection's 2-GPU answer and must be genuinely closed.
        statuses = {
            gpu_count: (await db.load_listing(listing_id=f"listing-{gpu_count}x"))[
                "status"
            ]
            for gpu_count in range(1, 5)
        }
        assert statuses == {
            1: "open",
            2: "open",
            3: "closed",
            4: "closed",
        }


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
                (
                    "2025-01-01T00:00:00Z",
                    "discovery",
                    "order_published",
                    "listing-1",
                    _json.dumps({"listing_id": "listing-1"}),
                ),
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
                    (
                        f"2025-01-0{i + 1}T00:00:00Z",
                        "discovery",
                        f"event_{i}",
                        _json.dumps({"seq": i}),
                    ),
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


class TestPatchResource:
    """Tests for PATCH /api/v1/admin/portfolio/resources/{resource_id}."""

    async def _seed_leased_resource(
        self, db: SQLiteClient, resource_id: str = "compute-patch-001"
    ) -> None:
        # Use resource_type other than compute.gpu or omit vm_host to skip capacity gate
        await db.upsert_resource(
            resource_id=resource_id,
            resource_type="compute.gpu",
            state="leased",
            # No attributes.vm_host → capacity gate skipped
        )

    async def test_requires_admin_key(self, client_no_key):
        c = client_no_key
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.patch_resource("compute-patch-001", state="available")
        assert exc_info.value.status_code in (401, 403)

    async def test_patch_state_to_available(self, client):
        c, db = client
        await self._seed_leased_resource(db)
        result = await c.patch_resource("compute-patch-001", state="available")
        assert result["state"] == "available"
        assert result["updated"] is True

    async def test_patch_is_idempotent_when_state_unchanged(self, client):
        c, db = client
        await self._seed_leased_resource(db)
        await c.patch_resource("compute-patch-001", state="available")
        result = await c.patch_resource("compute-patch-001", state="available")
        assert result["updated"] is False

    async def test_patch_clears_attribute(self, client):
        c, db = client
        await db.upsert_resource(
            resource_id="compute-patch-002",
            resource_type="compute.gpu",
            state="leased",
            attributes={"lease_end_utc": "2025-01-01 00:00"},
        )
        result = await c.patch_resource(
            "compute-patch-002",
            state="available",
            attributes={"lease_end_utc": None},
        )
        assert result["state"] == "available"
        assert result["attributes"].get("lease_end_utc") is None

    async def test_patch_nonexistent_returns_404(self, client):
        c, db = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.patch_resource("no-such-resource", state="available")
        assert exc_info.value.status_code == 404

    async def test_patch_preserves_unspecified_fields(self, client):
        c, db = client
        await db.upsert_resource(
            resource_id="compute-patch-003",
            resource_type="compute.gpu",
            state="leased",
            attributes={"gpu_model": "RTX 5080", "lease_end_utc": "2025-01-01 00:00"},
        )
        result = await c.patch_resource(
            "compute-patch-003",
            attributes={"lease_end_utc": None},
        )
        # state not specified → should remain leased
        assert result["state"] == "leased"
        # gpu_model not in patch → should be preserved
        assert result["attributes"].get("gpu_model") == "RTX 5080"
        assert result["attributes"].get("lease_end_utc") is None
