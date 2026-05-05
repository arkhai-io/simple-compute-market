"""Integration tests for the Listings API.

Uses the async ``StorefrontClient`` via ``httpx.ASGITransport`` —
matching the provisioning-service integration test pattern.
All assertions go through the canonical client; no raw HTTP calls.

Fixture pattern: build a minimal FastAPI app containing only the
ListingsController router, backed by an in-memory
SQLiteClient. This mirrors how provisioning-service tests wire a real
FastAPI app with dependency overrides.
"""
from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

import market_storefront.container as _container
from market_storefront.middleware.admin_auth import require_admin_key
from market_storefront.controllers.listings_controller import router as listings_router
from market_storefront.utils.sqlite_client import SQLiteClient
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
    return SQLiteClient(db_path=str(tmp_path / "listings_test.db"))


async def _seed_listing(db: SQLiteClient, listing_id: str, status: str = "open") -> None:
    await db.upsert_listing(
        listing_id=listing_id,
        status=status,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource={"gpu_model": "H200", "gpu_count": 1, "sla": 99.9, "region": "California, US"},
        demand_resource={"token": {"symbol": "MOCK", "contract_address": "0x0000000000000000000000000000000000000001", "decimals": 18}, "amount": 9000},
        fulfillment_resource=None,
        max_duration_seconds=7200,
        seller="http://seller:8001",
    )


@pytest_asyncio.fixture
async def client(db) -> AsyncIterator[tuple[StorefrontClient, SQLiteClient]]:
    _container.resolved_sqlite_client = db
    _container.resolved_listing_service = None  # not used by read/pause/resume
    _container.resolved_policy_service = None  # not used by read/pause/resume

    app = FastAPI()
    app.include_router(listings_router)
    app.dependency_overrides[require_admin_key] = _key_enforcer(ADMIN_KEY)

    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient(
        "http://test",
        transport=transport,
        admin_key=ADMIN_KEY,
    ) as c:
        yield c, db

    _container.resolved_sqlite_client = None
    _container.resolved_listing_service = None
    _container.resolved_policy_service = None


@pytest_asyncio.fixture
async def client_no_key(db) -> AsyncIterator[StorefrontClient]:
    _container.resolved_sqlite_client = db
    _container.resolved_listing_service = None  # not used by read/pause/resume
    _container.resolved_policy_service = None  # not used by read/pause/resume

    app = FastAPI()
    app.include_router(listings_router)
    app.dependency_overrides[require_admin_key] = _key_enforcer(ADMIN_KEY)

    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient("http://test", transport=transport) as c:
        yield c

    _container.resolved_sqlite_client = None


# ---------------------------------------------------------------------------
# GET /api/v1/listings
# ---------------------------------------------------------------------------

class TestListListings:
    async def test_empty_list(self, client):
        c, _ = client
        result = await c.list_listings()
        assert result.count == 0
        assert result.listings == []

    async def test_returns_seeded_listings(self, client):
        c, db = client
        await _seed_listing(db, "o1")
        await _seed_listing(db, "o2")
        result = await c.list_listings()
        ids = {o.listing_id for o in result.listings}
        assert {"o1", "o2"} == ids

    async def test_status_filter(self, client):
        c, db = client
        await _seed_listing(db, "open1", status="open")
        await _seed_listing(db, "closed1", status="closed")
        result = await c.list_listings(status="open")
        ids = {o.listing_id for o in result.listings}
        assert "open1" in ids
        assert "closed1" not in ids

    async def test_paused_filter(self, client):
        c, db = client
        await _seed_listing(db, "paused1")
        await _seed_listing(db, "active1")
        await db.set_listing_paused(listing_id="paused1", paused=True)
        paused_result = await c.list_listings(paused=True)
        active_result = await c.list_listings(paused=False)
        paused_ids = {o.listing_id for o in paused_result.listings}
        active_ids = {o.listing_id for o in active_result.listings}
        assert "paused1" in paused_ids
        assert "paused1" not in active_ids
        assert "active1" in active_ids

    async def test_pagination_limit(self, client):
        c, db = client
        for i in range(5):
            await _seed_listing(db, f"ord-{i}")
        result = await c.list_listings(limit=2)
        assert len(result.listings) == 2
        assert result.limit == 2

    async def test_paused_field_false_by_default(self, client):
        c, db = client
        await _seed_listing(db, "check-paused")
        result = await c.list_listings()
        listing = next(o for o in result.listings if o.listing_id == "check-paused")
        assert listing.paused is False

    async def test_spec_filter_gpu_count_min(self, client):
        c, db = client
        for lid, gpu_count in (("small", 1), ("big", 8)):
            await db.upsert_listing(
                listing_id=lid, status="open",
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                offer_resource={
                    "gpu_model": "H200", "gpu_count": gpu_count,
                    "sla": 99.9, "region": "California, US",
                },
                demand_resource={"token": {"symbol": "MOCK", "contract_address": "0x" + "0" * 40, "decimals": 18}, "amount": 100},
                fulfillment_resource=None,
                max_duration_seconds=7200, seller="http://seller:8001",
            )
        result = await c.list_listings(gpu_count_min=4)
        ids = {o.listing_id for o in result.listings}
        assert ids == {"big"}

    async def test_spec_filter_gpu_model_equality(self, client):
        c, db = client
        for lid, model in (("h200", "H200"), ("rtx4090", "RTX 4090")):
            await db.upsert_listing(
                listing_id=lid, status="open",
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                offer_resource={"gpu_model": model, "gpu_count": 1, "sla": 99.0, "region": "California, US"},
                demand_resource={"token": {"symbol": "MOCK", "contract_address": "0x" + "0" * 40, "decimals": 18}, "amount": 100},
                fulfillment_resource=None,
                max_duration_seconds=3600, seller="http://seller:8001",
            )
        result = await c.list_listings(gpu_model="H200")
        ids = {o.listing_id for o in result.listings}
        assert ids == {"h200"}

    async def test_spec_filter_combines_multiple_constraints(self, client):
        c, db = client
        await db.upsert_listing(
            listing_id="dream", status="open",
            created_at=datetime.now().isoformat(), updated_at=datetime.now().isoformat(),
            offer_resource={
                "gpu_model": "H200", "gpu_count": 8, "sla": 99.9, "region": "California, US",
                "vcpu_count": 192, "ram_gb": 2048, "disk_gb": 20000,
                "gpu_interconnect": "nvswitch", "datacenter_grade": True,
            },
            demand_resource={"token": {"symbol": "MOCK", "contract_address": "0x" + "0" * 40, "decimals": 18}, "amount": 1000},
            fulfillment_resource=None,
            max_duration_seconds=86400, seller="http://seller:8001",
        )
        await db.upsert_listing(
            listing_id="basic", status="open",
            created_at=datetime.now().isoformat(), updated_at=datetime.now().isoformat(),
            offer_resource={
                "gpu_model": "RTX 5080", "gpu_count": 1, "sla": 90.0, "region": "California, US",
                "vcpu_count": 16, "ram_gb": 64, "disk_gb": 2000,
                "gpu_interconnect": "pcie_only", "datacenter_grade": False,
            },
            demand_resource={"token": {"symbol": "MOCK", "contract_address": "0x" + "0" * 40, "decimals": 18}, "amount": 100},
            fulfillment_resource=None,
            max_duration_seconds=3600, seller="http://seller:8001",
        )
        result = await c.list_listings(
            gpu_count_min=4, vcpu_count_min=64, gpu_interconnect="nvswitch", datacenter_grade=True,
        )
        ids = {o.listing_id for o in result.listings}
        assert ids == {"dream"}

    async def test_spec_filter_with_no_matches_returns_empty(self, client):
        c, db = client
        await _seed_listing(db, "exists")
        result = await c.list_listings(gpu_model="NONEXISTENT_GPU")
        assert result.count == 0
        raw = await c._get("/api/v1/listings", params={"gpu_model": "NONEXISTENT_GPU"})
        assert raw.get("total_after_filter") == 0


# ---------------------------------------------------------------------------
# GET /api/v1/listings/{listing_id}
# ---------------------------------------------------------------------------

class TestGetListing:
    async def test_returns_listing(self, client):
        c, db = client
        await _seed_listing(db, "detail-1")
        listing = await c.get_listing("detail-1")
        assert listing.listing_id == "detail-1"
        assert listing.paused is False

    async def test_404_unknown_listing_raises(self, client):
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.get_listing("does-not-exist")
        assert "404" in str(exc_info.value)


# ---------------------------------------------------------------------------
# POST /api/v1/listings/{listing_id}/pause
# ---------------------------------------------------------------------------

class TestPauseListing:
    async def test_requires_admin_key(self, client_no_key):
        with pytest.raises(StorefrontClientError) as exc_info:
            await client_no_key.pause_listing("any-listing")
        assert "403" in str(exc_info.value)

    async def test_pause_sets_flag(self, client):
        c, db = client
        await _seed_listing(db, "pausable")
        result = await c.pause_listing("pausable")
        assert result.paused is True
        assert await db.is_listing_paused(listing_id="pausable") is True

    async def test_pause_unknown_listing_raises(self, client):
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.pause_listing("ghost")
        assert "404" in str(exc_info.value)


# ---------------------------------------------------------------------------
# POST /api/v1/listings/{listing_id}/resume
# ---------------------------------------------------------------------------

class TestResumeListing:
    async def test_requires_admin_key(self, client_no_key):
        with pytest.raises(StorefrontClientError) as exc_info:
            await client_no_key.resume_listing("any-listing")
        assert "403" in str(exc_info.value)

    async def test_resume_clears_flag(self, client):
        c, db = client
        await _seed_listing(db, "resumable")
        await db.set_listing_paused(listing_id="resumable", paused=True)
        result = await c.resume_listing("resumable")
        assert result.paused is False
        assert await db.is_listing_paused(listing_id="resumable") is False

    async def test_resume_returns_registry_status(self, client):
        c, db = client
        await _seed_listing(db, "resume-registry-check")
        result = await c.resume_listing("resume-registry-check")
        assert hasattr(result, "registry_status")
        assert isinstance(result.registry_status, str)
        assert "registry_status" not in result.extra

    async def test_pause_response_has_no_registry_status(self, client):
        c, db = client
        await _seed_listing(db, "pause-no-registry")
        result = await c.pause_listing("pause-no-registry")
        assert result.registry_status == ""

    async def test_resume_unknown_listing_raises(self, client):
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.resume_listing("ghost")
        assert "404" in str(exc_info.value)
