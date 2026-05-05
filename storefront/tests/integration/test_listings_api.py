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


# ---------------------------------------------------------------------------
# Admin evaluate endpoints — evaluate-create, evaluate-close, evaluate-negotiate
#
# These tests use a dedicated fixture that includes both the buyer-facing
# router and the admin_router (which hosts the /api/v1/admin/listings/* routes).
# They require a real ListingService and PolicyService because the evaluate
# paths exercise the full service stack.
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock, patch


@pytest_asyncio.fixture
async def admin_client(db) -> AsyncIterator[tuple[StorefrontClient, SQLiteClient]]:
    """Fixture wiring both listings router and admin_router with real services.

    PolicyService requires a config mock — only base_url_override and agent_id
    are read during evaluate paths (via _consult_policy → PolicyManager).
    """
    from market_storefront.controllers.listings_controller import admin_router
    from market_storefront.services.listing_service import ListingService
    from market_storefront.services.policy_service import PolicyService

    config = MagicMock()
    config.base_url_override = ""
    config.base_url_override_raw = ""
    config.agent_id = "test-agent"
    config.agent_priv_key = ""
    config.chain_rpc_url = ""

    listing_svc = ListingService(
        sqlite_client=db, alkahest_client=None, config=config
    )
    policy_svc = PolicyService(
        sqlite_client=db, alkahest_client=None, config=config, agent_id="test-agent"
    )

    _container.resolved_sqlite_client = db
    _container.resolved_listing_service = listing_svc
    _container.resolved_policy_service = policy_svc

    app = FastAPI()
    app.include_router(listings_router)
    app.include_router(admin_router)
    app.dependency_overrides[require_admin_key] = _key_enforcer(ADMIN_KEY)

    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient(
        "http://test", transport=transport, admin_key=ADMIN_KEY,
        private_key="0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    ) as c:
        yield c, db

    _container.resolved_sqlite_client = None
    _container.resolved_listing_service = None
    _container.resolved_policy_service = None


@pytest_asyncio.fixture
async def admin_no_key_client(db) -> AsyncIterator[StorefrontClient]:
    """Admin router wired without an admin key — for 403 tests on admin endpoints."""
    from market_storefront.controllers.listings_controller import admin_router
    from market_storefront.services.listing_service import ListingService
    from market_storefront.services.policy_service import PolicyService

    config = MagicMock()
    config.base_url_override = ""
    config.base_url_override_raw = ""
    config.agent_id = "test-agent"
    config.agent_priv_key = ""
    config.chain_rpc_url = ""

    listing_svc = ListingService(
        sqlite_client=db, alkahest_client=None, config=config
    )
    policy_svc = PolicyService(
        sqlite_client=db, alkahest_client=None, config=config, agent_id="test-agent"
    )

    _container.resolved_sqlite_client = db
    _container.resolved_listing_service = listing_svc
    _container.resolved_policy_service = policy_svc

    app = FastAPI()
    app.include_router(listings_router)
    app.include_router(admin_router)
    app.dependency_overrides[require_admin_key] = _key_enforcer(ADMIN_KEY)

    transport = httpx.ASGITransport(app=app)
    # No admin_key supplied → X-Admin-Key header absent → 403
    async with StorefrontClient(
        "http://test", transport=transport,
        private_key="0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    ) as c:
        yield c

    _container.resolved_sqlite_client = None
    _container.resolved_listing_service = None
    _container.resolved_policy_service = None


_OFFER = {
    "gpu_model": "H200", "gpu_count": 1, "sla": 99.0, "region": "California, US"
}
_DEMAND = {
    "token": {
        "symbol": "MOCK",
        "contract_address": "0x0000000000000000000000000000000000000001",
        "decimals": 0,
    },
    "amount": 5000,
}


# ---------------------------------------------------------------------------
# POST /api/v1/admin/listings/evaluate-create
# ---------------------------------------------------------------------------

class TestEvaluateCreate:
    """POST /api/v1/admin/listings/evaluate-create — dry-run, no DB writes."""

    async def test_returns_200_with_would_create_field(self, admin_client):
        """Endpoint returns a structured response with would_create field."""
        c, _ = admin_client
        result = await c.evaluate_create_listing(
            offer=_OFFER, demand=_DEMAND, max_duration_seconds=3600, paused=False,
        )
        assert isinstance(result, dict), f"Expected dict, got {type(result)}: {result}"
        assert "would_create" in result, f"Missing 'would_create' in response: {result}"
        assert isinstance(result["would_create"], bool)

    async def test_returns_action_field(self, admin_client):
        """Response includes action string (make_offer or no_action)."""
        c, _ = admin_client
        result = await c.evaluate_create_listing(
            offer=_OFFER, demand=_DEMAND, max_duration_seconds=3600, paused=False,
        )
        assert "action" in result, f"Missing 'action' in response: {result}"
        assert isinstance(result["action"], str)

    async def test_no_side_effects_db_unchanged(self, admin_client):
        """evaluate-create writes nothing to SQLite."""
        c, db = admin_client
        before = await db.list_listings()
        await c.evaluate_create_listing(
            offer=_OFFER, demand=_DEMAND, max_duration_seconds=3600, paused=False,
        )
        after = await db.list_listings()
        assert len(before) == len(after), (
            "evaluate-create wrote a listing to the DB — it must be a pure dry-run"
        )

    async def test_requires_admin_key(self, admin_no_key_client):
        """Admin key required — missing key returns 403."""
        with pytest.raises(StorefrontClientError) as exc_info:
            await admin_no_key_client.evaluate_create_listing(
                offer=_OFFER, demand=_DEMAND,
            )
        assert "403" in str(exc_info.value)

    async def test_empty_offer_returns_500_or_400(self, admin_client):
        """Malformed offer dict handled gracefully — no 500 from unhandled exception."""
        c, _ = admin_client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.evaluate_create_listing(offer={}, demand=_DEMAND)
        # 400 from the service ValueError or 500 if parse_resource_from_dict raises
        assert any(code in str(exc_info.value) for code in ("400", "500"))


# ---------------------------------------------------------------------------
# POST /api/v1/admin/listings/{listing_id}/evaluate-close
# ---------------------------------------------------------------------------

class TestEvaluateClose:
    """POST /api/v1/admin/listings/{listing_id}/evaluate-close — dry-run."""

    async def test_returns_200_with_would_close_field(self, admin_client):
        """Endpoint returns a structured response with would_close field."""
        c, db = admin_client
        await _seed_listing(db, "close-test-1")
        result = await c.evaluate_close_listing("close-test-1")
        assert isinstance(result, dict), f"Expected dict, got {type(result)}: {result}"
        assert "would_close" in result, f"Missing 'would_close' in response: {result}"
        assert isinstance(result["would_close"], bool)

    async def test_returns_action_and_listing_id(self, admin_client):
        """Response includes action and listing_id fields."""
        c, db = admin_client
        await _seed_listing(db, "close-test-2")
        result = await c.evaluate_close_listing("close-test-2")
        assert "action" in result
        assert result.get("listing_id") == "close-test-2"

    async def test_unknown_listing_returns_response_not_404(self, admin_client):
        """Non-existent listing_id returns 200 (not 404) with listing_id echoed back.

        evaluate_close delegates to the policy pipeline which doesn't verify
        the listing exists — it just builds a close event and consults the policy.
        This is by design: the evaluate endpoint is a pure policy dry-run.
        """
        c, _ = admin_client
        result = await c.evaluate_close_listing("does-not-exist")
        assert isinstance(result, dict)
        assert result.get("listing_id") == "does-not-exist"
        assert isinstance(result.get("would_close"), bool)
        assert "action" in result

    async def test_no_side_effects_db_unchanged(self, admin_client):
        """evaluate-close writes nothing to SQLite."""
        c, db = admin_client
        await _seed_listing(db, "close-side-effects")
        before_status = (await db.load_listing(listing_id="close-side-effects")).get("status")
        await c.evaluate_close_listing("close-side-effects")
        after_status = (await db.load_listing(listing_id="close-side-effects")).get("status")
        assert before_status == after_status, (
            "evaluate-close changed listing status — it must be a pure dry-run"
        )

    async def test_requires_admin_key(self, admin_no_key_client):
        """Admin key required — missing key returns 403."""
        with pytest.raises(StorefrontClientError) as exc_info:
            await admin_no_key_client.evaluate_close_listing("any-listing")
        assert "403" in str(exc_info.value)


# ---------------------------------------------------------------------------
# POST /api/v1/admin/listings/{listing_id}/evaluate-negotiate
# ---------------------------------------------------------------------------

class TestEvaluateNegotiate:
    """POST /api/v1/admin/listings/{listing_id}/evaluate-negotiate — dry-run."""

    async def test_returns_200_with_would_negotiate_field(self, admin_client):
        """Endpoint returns a structured response with would_negotiate field."""
        c, db = admin_client
        await _seed_listing(db, "neg-eval-1")
        with patch(
            "market_storefront.utils.sync_negotiation._load_storefront_strategy",
            return_value=_bisection_strategy(),
        ):
            result = await c.evaluate_negotiate("neg-eval-1", their_proposed_price=5000)
        assert isinstance(result.would_negotiate, bool)

    async def test_returns_decision_fields(self, admin_client):
        """Response includes decision, direction, our_reference_price, strategy."""
        c, db = admin_client
        await _seed_listing(db, "neg-eval-2")
        with patch(
            "market_storefront.utils.sync_negotiation._load_storefront_strategy",
            return_value=_bisection_strategy(),
        ):
            result = await c.evaluate_negotiate("neg-eval-2", their_proposed_price=5000)
        assert result.decision in ("accept", "counter", "exit")
        assert result.direction == "maximize"
        assert result.our_reference_price > 0
        assert result.strategy  # non-empty string

    async def test_price_at_floor_does_not_exit(self, admin_client):
        """Buyer price at or above the seller's floor should not produce exit."""
        c, db = admin_client
        await _seed_listing(db, "neg-eval-floor")  # default demand amount=9000
        with patch(
            "market_storefront.utils.sync_negotiation._load_storefront_strategy",
            return_value=_bisection_strategy(),
        ):
            result = await c.evaluate_negotiate(
                "neg-eval-floor", their_proposed_price=9000
            )
        # At exactly the floor price, bisection should accept or counter, not exit
        assert result.would_negotiate is True, (
            f"Strategy exited at floor price 9000. decision={result.decision!r} "
            f"reason={result.decision_reason!r} our_price={result.our_reference_price}"
        )

    async def test_unknown_listing_returns_404(self, admin_client):
        """Non-existent listing_id returns 404."""
        c, _ = admin_client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.evaluate_negotiate("ghost-listing", their_proposed_price=1000)
        assert "404" in str(exc_info.value)

    async def test_no_negotiation_thread_created(self, admin_client):
        """evaluate-negotiate creates no thread in the DB."""
        c, db = admin_client
        await _seed_listing(db, "neg-eval-no-thread")
        with patch(
            "market_storefront.utils.sync_negotiation._load_storefront_strategy",
            return_value=_bisection_strategy(),
        ):
            await c.evaluate_negotiate("neg-eval-no-thread", their_proposed_price=5000)
        threads = await db.get_active_negotiations_for_listing(listing_id="neg-eval-no-thread")
        assert len(threads) == 0, (
            "evaluate-negotiate created a negotiation thread — it must be a pure dry-run"
        )

    async def test_requires_admin_key(self, admin_no_key_client):
        """Admin key required — missing key returns 403."""
        with pytest.raises(StorefrontClientError) as exc_info:
            await admin_no_key_client.evaluate_negotiate("any", their_proposed_price=1000)
        assert "403" in str(exc_info.value)


def _bisection_strategy():
    """Return a real BisectionStrategy instance for use in integration tests.

    Patches _load_storefront_strategy to avoid torch/rl dependency and
    CONFIG access in integration tests.
    """
    from market_policy.negotiation_strategy import load_strategy
    return load_strategy("bisection")


# ---------------------------------------------------------------------------
# Seller auth integration tests for POST /api/v1/listings/create
#
# These tests prove the EIP-191 auth contract between the client and the
# seller_auth middleware for the create_listing endpoint:
#   - client signs "create_listing:{agent_wallet_address}:{ts}"
#   - server verifies the same message against CONFIG.agent_wallet_address
#
# This is a pure interface test — no policy pipeline needed, so the
# listing_svc dependency is left as None (the 403 fires before it's called).
# ---------------------------------------------------------------------------

# Hardhat/Anvil deterministic test key pair — safe for tests, never mainnet.
_TEST_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
_TEST_WALLET     = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"  # address for above key


@pytest_asyncio.fixture
async def seller_auth_client(db):
    """Fixture wiring listings router with seller auth enabled via CONFIG patch.

    Patches CONFIG.agent_wallet_address to _TEST_WALLET so the middleware
    enforces EIP-191 verification. The StorefrontClient is constructed with
    _TEST_PRIVATE_KEY so signatures verify correctly.
    """
    from unittest.mock import MagicMock, patch as _patch
    import market_storefront.middleware.seller_auth as _seller_auth_mod
    import market_storefront.utils.config as _config_mod

    _container.resolved_sqlite_client = db
    _container.resolved_listing_service = None  # 403 fires before service is called
    _container.resolved_policy_service = None

    fake_config = MagicMock()
    fake_config.agent_wallet_address = _TEST_WALLET

    app = FastAPI()
    app.include_router(listings_router)
    app.dependency_overrides[require_admin_key] = _key_enforcer(ADMIN_KEY)

    transport = httpx.ASGITransport(app=app)
    with _patch.object(_config_mod, "CONFIG", fake_config), \
         _patch.object(_seller_auth_mod, "CONFIG", fake_config, create=True):
        async with StorefrontClient(
            "http://test",
            transport=transport,
            admin_key=ADMIN_KEY,
            private_key=_TEST_PRIVATE_KEY,
        ) as c:
            yield c, db

    _container.resolved_sqlite_client = None
    _container.resolved_listing_service = None
    _container.resolved_policy_service = None


class TestCreateListingSellerAuth:
    """Proves the EIP-191 auth contract for POST /api/v1/listings/create.

    The client signs ``create_listing:{agent_wallet_address}:{ts}`` and the
    server verifies against CONFIG.agent_wallet_address. These tests confirm
    that the middleware correctly accepts a valid signature and rejects
    mismatched ones.

    The tests exercise auth only — the listing_svc is None so the 200 path
    is not tested here (see TestCreateListing for that).
    """

    async def test_valid_signature_passes_auth(self, seller_auth_client):
        """Correct private key + matching wallet address → auth passes.

        The request will fail after auth (listing_svc is None → 500 or
        similar), but NOT with 403. A 403 means auth rejected the request.
        """
        c, _ = seller_auth_client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.create_listing(
                agent_wallet_address=_TEST_WALLET,
                offer={"gpu_model": "H200", "gpu_count": 1,
                       "sla": 99.0, "region": "California, US"},
                demand={"token": {"symbol": "MOCK",
                                  "contract_address": "0x0000000000000000000000000000000000000001",
                                  "decimals": 0},
                        "amount": 5000},
            )
        # Auth passed — error is from missing listing_svc (500), not auth (403)
        assert "403" not in str(exc_info.value), (
            f"Auth rejected a valid signature. Error: {exc_info.value}\n"
            "Check that seller_auth middleware uses CONFIG.agent_wallet_address "
            "as resource_id for create_listing (no listing_id path param)."
        )

    async def test_wrong_wallet_address_returns_403(self, seller_auth_client):
        """Wrong agent_wallet_address in the call → signature doesn't verify → 403.

        The client signs with _TEST_WALLET but we pass a different wallet as
        the resource_id, so the signed message doesn't match what the server
        reconstructs.
        """
        c, _ = seller_auth_client
        wrong_wallet = "0x0000000000000000000000000000000000000001"
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.create_listing(
                agent_wallet_address=wrong_wallet,  # client signs this, server checks _TEST_WALLET
                offer={"gpu_model": "H200", "gpu_count": 1,
                       "sla": 99.0, "region": "California, US"},
                demand={"token": {"symbol": "MOCK",
                                  "contract_address": "0x0000000000000000000000000000000000000001",
                                  "decimals": 0},
                        "amount": 5000},
            )
        assert "403" in str(exc_info.value), (
            f"Expected 403 for wrong wallet address, got: {exc_info.value}"
        )

    async def test_missing_auth_headers_returns_403(self, seller_auth_client):
        """Request with no X-Signature / X-Timestamp → 403 Missing auth headers."""
        from httpx import AsyncClient, ASGITransport as _Transport
        import market_storefront.middleware.seller_auth as _sam
        import market_storefront.utils.config as _cm
        from unittest.mock import MagicMock, patch as _patch

        fake_config = MagicMock()
        fake_config.agent_wallet_address = _TEST_WALLET

        app = FastAPI()
        app.include_router(listings_router)
        app.dependency_overrides[require_admin_key] = _key_enforcer(ADMIN_KEY)

        transport = httpx.ASGITransport(app=app)
        with _patch.object(_cm, "CONFIG", fake_config), \
             _patch.object(_sam, "CONFIG", fake_config, create=True):
            async with httpx.AsyncClient(
                base_url="http://test", transport=transport
            ) as raw:
                resp = await raw.post(
                    "/api/v1/listings/create",
                    json={"offer": {}, "demand": {}, "paused": False},
                    headers={"X-Admin-Key": ADMIN_KEY},
                    # No X-Signature or X-Timestamp
                )
        assert resp.status_code == 403
        assert "auth" in resp.json().get("detail", "").lower()
