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
from market_storefront.services.compute_listing_reconciler import record_derived_listing
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

class TestAdminImportResources:
    """Tests for POST /api/v1/admin/portfolio/resources/import."""

    _VALID_CSV = (
        "resource_id,resource_type,resource_subtype,unit,value,state,"
        "min_price,token,max_duration_seconds,"
        "attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host\n"
        'compute-import-001,compute.gpu,rtx5080,count,1,available,'
        '150,0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0,,'
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
            "resource_id,resource_type,resource_subtype,unit,value,state,"
            "min_price,token,max_duration_seconds,"
            "attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host\n"
            'compute-good-001,compute.gpu,rtx5080,count,1,available,'
            '150,0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0,,'
            'RTX 5080,90.0,"California, US",kvm1\n'
            # Row with missing resource_id will fail.
            ',compute.gpu,rtx5080,count,1,available,150,0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0,,RTX 5080,90.0,"California, US",kvm1\n'
        ).encode()
        result = await c.admin_import_resources(mixed_csv)
        assert result.total_rows == 2
        # The good row should import even if one fails.
        assert result.imported_count >= 1


async def _seed_dynamic_listing_pool_rows(db: SQLiteClient) -> None:
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
            accepted_escrows=[{
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "22" * 20},
                "rates": [{"field": "amount", "per": "hour", "value": "100"}],
            }],
            demands=[],
            fulfillment_resource=None,
            max_duration_seconds=3600,
            seller="http://seller",
        )
        record_derived_listing(
            db.db_path,
            listing_id=listing_id,
            resource_id="pool-h200-1",
            gpu_count=gpu_count,
        )


async def _seed_dynamic_listing_pool(db: SQLiteClient) -> str:
    await _seed_dynamic_listing_pool_rows(db)
    reserved = await db.reserve_available_compute_vm(
        required_attributes={"resource_id": "pool-h200-1", "gpu_count": 2},
        listing_id="listing-2x",
        escrow_uid="escrow-2x",
    )
    assert reserved is not None
    return str(reserved["allocation_id"])


class TestFulfillmentEvents:
    async def test_admin_reserve_capacity_closes_oversized_listings(self, client):
        c, db = client
        await _seed_dynamic_listing_pool_rows(db)

        response = await c._post(
            "/api/v1/admin/portfolio/reservations",
            {
                "required_attributes": {
                    "resource_id": "pool-h200-1",
                    "gpu_count": 2,
                },
                "listing_id": "listing-2x-manual",
                "escrow_uid": "manual-escrow-2x",
            },
            extra_headers=c._admin_headers(),
        )

        assert response["allocation_id"]
        assert response["resource_id"] == "pool-h200-1"
        assert response["gpu_count"] == 2
        assert response["resource_state"] == "available"
        assert sorted(response["closed_listing_ids"]) == ["listing-3x", "listing-4x"]
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

    async def test_admin_reserve_capacity_returns_409_when_no_capacity(self, client):
        c, db = client
        await _seed_dynamic_listing_pool(db)

        with pytest.raises(StorefrontClientError) as exc_info:
            await c._post(
                "/api/v1/admin/portfolio/reservations",
                {
                    "required_attributes": {
                        "resource_id": "pool-h200-1",
                        "gpu_count": 3,
                    },
                    "listing_id": "listing-3x-manual",
                    "escrow_uid": "manual-escrow-3x",
                },
                extra_headers=c._admin_headers(),
            )

        assert "409" in str(exc_info.value)

    async def test_usage_started_marks_leased_and_closes_oversized_listings(self, client):
        c, db = client
        allocation_id = await _seed_dynamic_listing_pool(db)

        response = await c._post(
            "/api/v1/admin/fulfillment/events/usage-started",
            {
                "allocation_id": allocation_id,
                "escrow_uid": "escrow-2x",
                "provider_id": "provider-a",
                "provider_lease_id": "lease-2x",
                "resource_id": "provider-resource-2x",
                "vm_host": "kvm1",
                "vm_target": "tenant-2x",
                "lease_end_utc": "2026-01-01T00:00:00Z",
            },
            extra_headers=c._admin_headers(),
        )

        assert response["allocation_id"] == allocation_id
        assert response["state"] == "leased"
        assert sorted(response["closed_listing_ids"]) == ["listing-3x", "listing-4x"]
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
        conn = sqlite3.connect(db.db_path)
        try:
            row = conn.execute(
                """
                SELECT provider_id, provider_lease_id, provider_resource_id,
                       vm_host, vm_target, lease_end_utc
                FROM compute_allocations
                WHERE allocation_id = ?
                """,
                (allocation_id,),
            ).fetchone()
        finally:
            conn.close()
        assert row == (
            "provider-a",
            "lease-2x",
            "provider-resource-2x",
            "kvm1",
            "tenant-2x",
            "2026-01-01T00:00:00Z",
        )

    async def test_capacity_released_marks_allocation_released(self, client):
        c, db = client
        allocation_id = await _seed_dynamic_listing_pool(db)
        conn = sqlite3.connect(db.db_path)
        try:
            conn.execute("DELETE FROM derived_compute_listings")
            conn.commit()
        finally:
            conn.close()
        await c._post(
            "/api/v1/admin/fulfillment/events/usage-started",
            {"allocation_id": allocation_id, "escrow_uid": "escrow-2x"},
            extra_headers=c._admin_headers(),
        )

        response = await c._post(
            "/api/v1/admin/fulfillment/events/capacity-released",
            {"allocation_id": allocation_id},
            extra_headers=c._admin_headers(),
        )

        assert response["allocation_id"] == allocation_id
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
        selected = await db.select_available_compute_vm(
            required_attributes={"resource_id": "pool-h200-1", "gpu_count": 4},
        )
        assert selected is not None

    async def test_fulfillment_failed_persists_failure_metadata(self, client):
        c, db = client
        allocation_id = await _seed_dynamic_listing_pool(db)

        response = await c._post(
            "/api/v1/admin/fulfillment/events/failed",
            {
                "allocation_id": allocation_id,
                "provider_id": "provider-a",
                "provider_job_id": "job-create-1",
                "resource_id": "provider-resource-2x",
                "reason": "provisioning_error",
                "message": "host rejected request",
                "logs_ref": "s3://logs/job-create-1",
            },
            extra_headers=c._admin_headers(),
        )

        assert response["allocation_id"] == allocation_id
        assert response["state"] == "released"
        conn = sqlite3.connect(db.db_path)
        try:
            row = conn.execute(
                """
                SELECT provider_id, provider_job_id, provider_resource_id,
                       failure_reason, failure_message, logs_ref
                FROM compute_allocations
                WHERE allocation_id = ?
                """,
                (allocation_id,),
            ).fetchone()
        finally:
            conn.close()
        assert row == (
            "provider-a",
            "job-create-1",
            "provider-resource-2x",
            "provisioning_error",
            "host rejected request",
            "s3://logs/job-create-1",
        )

    async def test_fulfillment_event_unknown_allocation_returns_404(self, client):
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c._post(
                "/api/v1/admin/fulfillment/events/usage-started",
                {"allocation_id": "missing"},
                extra_headers=c._admin_headers(),
            )
        assert "404" in str(exc_info.value)


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



class TestPatchResource:
    """Tests for PATCH /api/v1/admin/portfolio/resources/{resource_id}."""

    async def _seed_leased_resource(self, db: SQLiteClient, resource_id: str = "compute-patch-001") -> None:
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
