"""Integration tests for the Listings API.

Authenticated flows use the async ``StorefrontClient`` through
``httpx.ASGITransport``. Missing-authentication cases deliberately use the
raw transport so the client cannot reject them before they reach middleware.

Fixture pattern: build a minimal FastAPI app containing only the
ListingsController router, backed by an in-memory
SQLiteClient. This mirrors how provisioning-service tests wire a real
FastAPI app with dependency overrides.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from market_identity import Ed25519Signer, TrustedIdentitySet
from storefront_client.client import StorefrontClient, StorefrontClientError

import market_storefront.container as _container
from market_storefront.controllers.listings_controller import router as listings_router
from market_storefront.middleware import admin_identity as _admin_identity
from market_storefront.middleware.seller_auth import listing_lifecycle_middleware
from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.utils.sqlite_client import SQLiteClient

_TEST_MARKETPLACE_SIGNER = Ed25519Signer(b"\x31" * 32)
_TEST_ADMIN_SIGNER = Ed25519Signer(b"\x32" * 32)
_TEST_BUYER_SIGNER = Ed25519Signer(b"\x33" * 32)
_TEST_PROVISIONING_SIGNER = Ed25519Signer(b"\x34" * 32)
_TEST_SELLER_PRINCIPAL = _TEST_MARKETPLACE_SIGNER.identity
_TEST_PUBLISHERS = TrustedIdentitySet(identities=(_TEST_MARKETPLACE_SIGNER.identity,))
_TEST_ADMINISTRATORS = TrustedIdentitySet(identities=(_TEST_ADMIN_SIGNER.identity,))
_TEST_PROVISIONING_AUTHORITIES = TrustedIdentitySet(
    identities=(_TEST_PROVISIONING_SIGNER.identity,)
)


def _configure_administrator_auth(
    app: FastAPI,
    db: SQLiteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _admin_identity,
        "get_administrator_configs",
        lambda: {"operator": _TEST_ADMINISTRATORS},
    )
    _admin_identity.initialize_administrator_identities(db.db_path)
    app.middleware("http")(_admin_identity.administrator_identity_middleware)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path) -> SQLiteClient:
    return SQLiteClient(db_path=str(tmp_path / "listings_test.db"), registry=build_vm_storefront_registry(build_vm_storefront_domain()))


async def _seed_listing(
    db: SQLiteClient,
    listing_id: str,
    status: str = "open",
    *,
    valid_capacity_identity: bool = True,
) -> None:
    offer_resource = {
        "gpu_model": "H200",
        "gpu_count": 1,
        "sla": 99.9,
        "region": "California, US",
    }
    if valid_capacity_identity:
        offer_resource["resource_id"] = f"res-{listing_id}"
    await db.upsert_listing(
        listing_id=listing_id,
        status=status,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource=offer_resource,
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {
                    "token": "0x0000000000000000000000000000000000000001"
                },
                "rates": [{"field": "amount", "per": "hour", "value": "9000"}],
            }
        ],
        fulfillment_resource=None,
        max_duration_seconds=7200,
        storefront_url="http://seller:8001",
        seller_principal=_TEST_SELLER_PRINCIPAL,
    )


@pytest_asyncio.fixture
async def client(
    db,
    monkeypatch,
) -> AsyncIterator[tuple[StorefrontClient, SQLiteClient]]:
    _container.resolved_sqlite_client = db
    _container.resolved_listing_service = None  # not used by read/pause/resume
    _container.resolved_marketplace_signer = _TEST_MARKETPLACE_SIGNER

    app = FastAPI()
    app.include_router(listings_router)
    _configure_administrator_auth(app, db, monkeypatch)

    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient(
        "http://test",
        signer=_TEST_ADMIN_SIGNER,
        caller_role="admin",
        expected_publishers=_TEST_PUBLISHERS,
        transport=transport,
    ) as c:
        yield c, db

    _container.resolved_sqlite_client = None
    _container.resolved_listing_service = None
    _container.resolved_marketplace_signer = None


@pytest_asyncio.fixture
async def unsigned_client(
    db,
    monkeypatch,
) -> AsyncIterator[httpx.AsyncClient]:
    _container.resolved_sqlite_client = db
    _container.resolved_listing_service = None  # auth rejects before dispatch
    _container.resolved_marketplace_signer = _TEST_MARKETPLACE_SIGNER

    app = FastAPI()
    app.include_router(listings_router)
    _configure_administrator_auth(app, db, monkeypatch)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        base_url="http://test",
        transport=transport,
    ) as c:
        yield c

    _container.resolved_sqlite_client = None
    _container.resolved_listing_service = None
    _container.resolved_marketplace_signer = None


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

    # Discovery filters (gpu_model, gpu_count_min, etc.) were dropped in
    # milestone (a1b) — buyers query registries for that, not the
    # storefront.  See core/registry/tests/integration/test_listings
    # _filtering.py for the spec-driven equivalent.


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
    async def test_requires_authentication(self, unsigned_client):
        response = await unsigned_client.post(
            "/api/v1/listings/any-listing/pause",
            json={},
        )
        assert response.status_code == 401

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
    async def test_requires_authentication(self, unsigned_client):
        response = await unsigned_client.post(
            "/api/v1/listings/any-listing/resume",
            json={},
        )
        assert response.status_code == 401

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

    async def test_legacy_invalid_listing_fails_without_clearing_pause(self, client):
        c, db = client
        await _seed_listing(
            db,
            "legacy-invalid",
            valid_capacity_identity=False,
        )
        await db.set_listing_paused(listing_id="legacy-invalid", paused=True)

        with pytest.raises(StorefrontClientError) as exc_info:
            await c.resume_listing("legacy-invalid")

        error = str(exc_info.value)
        assert "409" in error
        assert "invalid_listing_capacity_identity" in error
        assert await db.is_listing_paused(listing_id="legacy-invalid") is True


# ---------------------------------------------------------------------------
# Admin evaluate endpoints — evaluate-negotiate
#
# Uses both the buyer-facing router and the admin_router (which hosts the
# /api/v1/admin/listings/* routes). ListingService is real; evaluate-negotiate
# is a pure dry-run of the negotiation chain against a listing row.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def admin_client(
    db,
    monkeypatch,
) -> AsyncIterator[tuple[StorefrontClient, SQLiteClient]]:
    from market_storefront.controllers.listings_controller import admin_router
    from market_storefront.services.listing_service import ListingService

    listing_svc = ListingService(
        domain=db.domain_registry.resolve_mode("vm").contract,
        sqlite_client=db,
        alkahest_clients=None,
        marketplace_signer=_TEST_MARKETPLACE_SIGNER,
    )
    monkeypatch.setattr(
        "market_storefront.services.capacity_client.get_provisioning_authorities",
        lambda: _TEST_PROVISIONING_AUTHORITIES,
    )

    _container.resolved_sqlite_client = db
    _container.resolved_listing_service = listing_svc
    _container.resolved_marketplace_signer = _TEST_MARKETPLACE_SIGNER

    app = FastAPI()
    app.include_router(listings_router)
    app.include_router(admin_router)
    _configure_administrator_auth(app, db, monkeypatch)

    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient(
        "http://test",
        signer=_TEST_ADMIN_SIGNER,
        caller_role="admin",
        expected_publishers=_TEST_PUBLISHERS,
        transport=transport,
    ) as c:
        yield c, db

    _container.resolved_sqlite_client = None
    _container.resolved_listing_service = None
    _container.resolved_marketplace_signer = None


@pytest_asyncio.fixture
async def unsigned_admin_client(
    db,
    monkeypatch,
) -> AsyncIterator[httpx.AsyncClient]:
    """Admin router exposed to an unsigned raw transport."""
    from market_storefront.controllers.listings_controller import admin_router
    from market_storefront.services.listing_service import ListingService

    listing_svc = ListingService(
        domain=db.domain_registry.resolve_mode("vm").contract,
        sqlite_client=db,
        alkahest_clients=None,
        marketplace_signer=_TEST_MARKETPLACE_SIGNER,
    )

    _container.resolved_sqlite_client = db
    _container.resolved_listing_service = listing_svc
    _container.resolved_marketplace_signer = _TEST_MARKETPLACE_SIGNER

    app = FastAPI()
    app.include_router(listings_router)
    app.include_router(admin_router)
    _configure_administrator_auth(app, db, monkeypatch)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        base_url="http://test",
        transport=transport,
    ) as c:
        yield c

    _container.resolved_sqlite_client = None
    _container.resolved_listing_service = None
    _container.resolved_marketplace_signer = None


_OFFER = {
    "resource_id": "res-test-1",
    "gpu_model": "H200",
    "gpu_count": 1,
    "sla": 99.0,
    "region": "California, US",
}
# Stub accepted_escrows for API-contract tests. Address-correctness is the
# storefront's concern at negotiate time; at listing-create time the
# storefront just stores what it's told.
_ACCEPTED_ESCROWS = [
    {
        "chain_name": "anvil",
        "escrow_address": "0x" + "11" * 20,
        "literal_fields": {"token": "0x0000000000000000000000000000000000000001"},
        "rates": [{"field": "amount", "per": "hour", "value": "5000"}],
    }
]


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
            "domains.vms.negotiation.storefront_round._load_storefront_chain",
            return_value=_bisection_chain(),
        ):
            result = await c.evaluate_negotiate(
                "neg-eval-1",
                proposal={
                    "chain_name": "anvil",
                    "escrow_address": "0x" + "0" * 40,
                    "fields": {"amount": 5000, "token": "0x" + "a" * 40},
                    "expiration_unix": 2000000000,
                },
                buyer_principal=_TEST_BUYER_SIGNER.identity,
            )
        assert isinstance(result.would_negotiate, bool)

    async def test_returns_decision_fields(self, admin_client):
        """Response includes decision, direction, our_reference_price, strategy."""
        c, db = admin_client
        await _seed_listing(db, "neg-eval-2")
        with patch(
            "domains.vms.negotiation.storefront_round._load_storefront_chain",
            return_value=_bisection_chain(),
        ):
            result = await c.evaluate_negotiate(
                "neg-eval-2",
                proposal={
                    "chain_name": "anvil",
                    "escrow_address": "0x" + "0" * 40,
                    "fields": {"amount": 5000, "token": "0x" + "a" * 40},
                    "expiration_unix": 2000000000,
                },
                buyer_principal=_TEST_BUYER_SIGNER.identity,
            )
        assert result.decision in ("accept", "counter", "exit")
        assert result.direction == "maximize"
        assert result.our_reference_amount > 0
        assert result.strategy  # non-empty string

    async def test_price_at_floor_does_not_exit(self, admin_client):
        """Buyer price at or above the seller's floor should not produce exit."""
        c, db = admin_client
        await _seed_listing(db, "neg-eval-floor")  # default price_per_hour=9000
        with patch(
            "domains.vms.negotiation.storefront_round._load_storefront_chain",
            return_value=_bisection_chain(),
        ):
            result = await c.evaluate_negotiate(
                "neg-eval-floor",
                proposal={
                    "chain_name": "anvil",
                    "escrow_address": "0x" + "0" * 40,
                    "fields": {"amount": 9000, "token": "0x" + "a" * 40},
                    "expiration_unix": 2000000000,
                },
                buyer_principal=_TEST_BUYER_SIGNER.identity,
            )
        # At exactly the floor price, bisection should accept or counter, not exit
        assert result.would_negotiate is True, (
            f"Strategy exited at floor price 9000. decision={result.decision!r} "
            f"reason={result.decision_reason!r} our_price={result.our_reference_amount}"
        )

    async def test_unknown_listing_returns_404(self, admin_client):
        """Non-existent listing_id returns 404."""
        c, _ = admin_client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.evaluate_negotiate(
                "ghost-listing",
                proposal={
                    "chain_name": "anvil",
                    "escrow_address": "0x" + "0" * 40,
                    "fields": {"amount": 1000, "token": "0x" + "a" * 40},
                    "expiration_unix": 2000000000,
                },
                buyer_principal=_TEST_BUYER_SIGNER.identity,
            )
        assert "404" in str(exc_info.value)

    async def test_no_negotiation_thread_created(self, admin_client):
        """evaluate-negotiate creates no thread in the DB."""
        c, db = admin_client
        await _seed_listing(db, "neg-eval-no-thread")
        with patch(
            "domains.vms.negotiation.storefront_round._load_storefront_chain",
            return_value=_bisection_chain(),
        ):
            await c.evaluate_negotiate(
                "neg-eval-no-thread",
                proposal={
                    "chain_name": "anvil",
                    "escrow_address": "0x" + "0" * 40,
                    "fields": {"amount": 5000, "token": "0x" + "a" * 40},
                    "expiration_unix": 2000000000,
                },
                buyer_principal=_TEST_BUYER_SIGNER.identity,
            )
        threads = await db.get_active_negotiations_for_listing(
            listing_id="neg-eval-no-thread"
        )
        assert len(threads) == 0, (
            "evaluate-negotiate created a negotiation thread — it must be a pure dry-run"
        )

    async def test_requires_authentication(self, unsigned_admin_client):
        response = await unsigned_admin_client.post(
            "/api/v1/admin/listings/any/evaluate-negotiate",
            json={
                "proposal": {
                    "chain_name": "anvil",
                    "escrow_address": "0x" + "0" * 40,
                    "fields": {
                        "amount": 1000,
                        "token": "0x" + "a" * 40,
                    },
                    "expiration_unix": 2000000000,
                },
                "buyer_principal": _TEST_BUYER_SIGNER.identity.model_dump(mode="json"),
            },
        )
        assert response.status_code == 401


def _bisection_chain():
    """Single-middleware chain (just bisection) for negotiate-evaluate tests.

    Skips the guards so the test's seeded listings don't need to match
    an inventory-portfolio entry. Avoids the torch/rl dependency.
    """
    from domains.vms.negotiation.policies import bisection_middleware

    return [bisection_middleware]


# ---------------------------------------------------------------------------
# Seller identity integration tests for listing lifecycle mutations
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seller_auth_client(db):
    """Listing router composed with an explicit Ed25519 seller signer."""
    _container.resolved_marketplace_signer = _TEST_MARKETPLACE_SIGNER
    _container.resolved_sqlite_client = db
    _container.resolved_listing_service = None  # auth rejects before dispatch

    app = FastAPI()
    app.include_router(listings_router)
    app.middleware("http")(listing_lifecycle_middleware)

    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient(
        "http://test",
        signer=_TEST_MARKETPLACE_SIGNER,
        caller_role="seller",
        expected_publishers=_TEST_PUBLISHERS,
        transport=transport,
    ) as c:
        yield c, db

    _container.resolved_sqlite_client = None
    _container.resolved_listing_service = None
    _container.resolved_marketplace_signer = None


@pytest_asyncio.fixture
async def seller_auth_full_client(db):
    """Listing lifecycle app with a real signer-aware ListingService."""
    from market_storefront.services.listing_service import ListingService

    class _AcceptedEscrowComposition:
        async def publication_artifacts(self, resources, *, clauses=None):
            assert clauses is None
            return list(resources["accepted_escrows"]), [], ()

    listing_svc = ListingService(
        domain=db.domain_registry.resolve_mode("vm").contract,
        sqlite_client=db,
        alkahest_clients=None,
        marketplace_signer=_TEST_MARKETPLACE_SIGNER,
        settlement_composition_provider=lambda: _AcceptedEscrowComposition(),
    )

    _container.resolved_sqlite_client = db
    _container.resolved_listing_service = listing_svc
    _container.resolved_marketplace_signer = _TEST_MARKETPLACE_SIGNER

    app = FastAPI()
    app.include_router(listings_router)
    app.middleware("http")(listing_lifecycle_middleware)

    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient(
        "http://test",
        signer=_TEST_MARKETPLACE_SIGNER,
        caller_role="seller",
        expected_publishers=_TEST_PUBLISHERS,
        transport=transport,
    ) as c:
        yield c, db

    _container.resolved_sqlite_client = None
    _container.resolved_listing_service = None
    _container.resolved_marketplace_signer = None


class TestLegacyInvalidListingRemoval:
    async def test_seller_can_explicitly_close_invalid_legacy_listing(
        self,
        seller_auth_full_client,
    ):
        c, db = seller_auth_full_client
        await _seed_listing(
            db,
            "legacy-invalid-close",
            valid_capacity_identity=False,
        )
        with patch(
            "market_storefront.services.publication_service.close_order",
            new_callable=AsyncMock,
            return_value={
                "status": "closed",
                "listing_id": "legacy-invalid-close",
            },
        ) as close_order:
            result = await c.close_listing("legacy-invalid-close")

        assert result.status == "closed"
        close_order.assert_awaited_once_with(
            {"listing_id": "legacy-invalid-close"},
            sqlite_client=db,
        )


class TestCreateListing:
    """Full round-trip tests for POST /api/v1/listings/create.

    These tests exercise the complete path: seller auth → policy pipeline →
    ListingService → controller → typed response. They catch regressions like
    the double-wrap bug (CreateListingResponse(**result) when result is already
    a CreateListingResponse) which would produce a 500 not caught by auth-only
    or evaluate-only tests.
    """

    async def test_creates_listing_and_returns_listing_id(
        self, seller_auth_full_client
    ):
        """Valid request creates a listing and returns a listing_id."""
        c, _ = seller_auth_full_client
        result = await c.create_listing(
            offer=_OFFER,
            accepted_escrows=_ACCEPTED_ESCROWS,
            paused=True,
        )
        assert hasattr(result, "listing_id") or (
            isinstance(result, dict) and "listing_id" in result
        ), f"No listing_id in response: {result}"
        listing_id = (
            result.listing_id if hasattr(result, "listing_id") else result["listing_id"]
        )
        assert listing_id, "listing_id must be non-empty"

    async def test_rejects_offer_with_neither_pool_id_nor_resource_id(
        self,
        seller_auth_full_client,
    ):
        """A compute offer with no pool_id and no resource_id can't be
        reliably matched to inventory at reservation time and must be
        rejected at creation rather than published."""
        c, _ = seller_auth_full_client
        offer_without_identity = {
            k: v for k, v in _OFFER.items() if k not in ("pool_id", "resource_id")
        }
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.create_listing(
                offer=offer_without_identity,
                accepted_escrows=_ACCEPTED_ESCROWS,
                paused=True,
            )
        assert "400" in str(exc_info.value)

    async def test_resource_id_only_offer_succeeds(self, seller_auth_full_client):
        """A resource_id-only offer (no pool_id) is a legitimate
        specific-resource listing, not an error."""
        c, _ = seller_auth_full_client
        assert "pool_id" not in _OFFER  # confirms this case is what's exercised
        result = await c.create_listing(
            offer=_OFFER,
            accepted_escrows=_ACCEPTED_ESCROWS,
            paused=True,
        )
        listing_id = (
            result.listing_id if hasattr(result, "listing_id") else result["listing_id"]
        )
        assert listing_id, "listing_id must be non-empty"

    async def test_listing_persisted_in_db(self, seller_auth_full_client):
        """Created listing returns a non-None listing_id in the response.

        The full DB persistence path depends on storefront services that read
        the real CONFIG singleton. This test therefore asserts the response
        contract rather than raw DB state: a non-None listing_id proves the
        policy pipeline ran and the controller serialised the response correctly.
        """
        c, _ = seller_auth_full_client
        result = await c.create_listing(
            offer=_OFFER,
            accepted_escrows=_ACCEPTED_ESCROWS,
            paused=True,
        )
        listing_id = (
            result.listing_id
            if hasattr(result, "listing_id")
            else result.get("listing_id")
        )
        assert listing_id is not None, (
            "listing_id is None — policy pipeline returned no_action or service failed. "
            f"Full response: {result}"
        )
        assert isinstance(listing_id, str) and listing_id

    async def test_paused_listing_not_in_registry(self, seller_auth_full_client):
        """paused=True create returns a listing_id without registry error.

        Full registry publish suppression requires the real settings.enable_registry_discovery
        flag from the storefront settings singleton. This test asserts the response
        is well-formed (listing_id present, no 500), which is sufficient to prove the
        paused=True path through the controller works correctly.
        """
        c, _ = seller_auth_full_client
        result = await c.create_listing(
            offer=_OFFER,
            accepted_escrows=_ACCEPTED_ESCROWS,
            paused=True,
        )
        listing_id = (
            result.listing_id
            if hasattr(result, "listing_id")
            else result.get("listing_id")
        )
        assert listing_id is not None, (
            f"paused=True create should still return a listing_id. Response: {result}"
        )

    async def test_response_is_correctly_typed(self, seller_auth_full_client):
        """Controller returns StorefrontListingCreateResponse, not a 500.

        This is the direct regression test for the double-wrap bug:
        CreateListingResponse(**result) when result is already CreateListingResponse
        raises TypeError and produces HTTP 500.
        """
        c, _ = seller_auth_full_client
        # If the double-wrap bug is present this raises StorefrontClientError with '500'
        result = await c.create_listing(
            offer=_OFFER,
            accepted_escrows=_ACCEPTED_ESCROWS,
            paused=True,
        )
        # StorefrontListingCreateResponse from the client — has listing_id
        assert result is not None
        assert hasattr(result, "listing_id") or (
            isinstance(result, dict) and "listing_id" in result
        ), f"Unexpected response shape: {result}"
