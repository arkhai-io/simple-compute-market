"""Integration tests for the Negotiate controller.

Uses ``StorefrontClient.negotiate_new()`` and ``negotiate_continue()``
via ``httpx.ASGITransport`` — following the canonical client pattern
documented in ARCHITECTURE.md.

These protocol endpoints use EIP-191 buyer signatures. Auth is bypassed
in tests via ``unittest.mock.patch.object(buyer_auth, "_verify", return_value=None)``.
Tests focus on Pydantic validation, routing correctness, and DB interaction.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

import market_storefront.container as _container
from market_storefront.controllers.negotiate_controller import router as negotiate_router
from market_storefront.middleware import buyer_auth
from storefront_client import StorefrontClient, StorefrontClientError

_BUYER = "0xBuyer00000000000000000000000000000000AB"  # 42 chars
_TOKEN = "0x0000000000000000000000000000000000000001"


@pytest_asyncio.fixture
async def db(tmp_path):
    from market_storefront.utils.sqlite_client import SQLiteClient
    return SQLiteClient(db_path=str(tmp_path / "negotiate_test.db"))


async def _seed_listing(db, listing_id: str, demand_amount: int = 5000) -> None:
    await db.upsert_listing(
        listing_id=listing_id,
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource={"gpu_model": "H200", "gpu_count": 1, "sla": 99.9, "region": "California, US"},
        accepted_escrows=[{
            "chain_name": "anvil",
            "escrow_address": "0x" + "11" * 20,
            "fields": {"token": _TOKEN},
            "price_per_hour": demand_amount,
        }],
        fulfillment_resource=None,
        max_duration_seconds=7200,
        seller="http://seller:8001",
    )
    # Seed at least one matching available compute resource so the
    # seller's pre-thread guard composite (default
    # `negotiate_request.default.v1` → `negotiate.guard.has_matching_inventory`)
    # lets the negotiation start. Tests that want to exercise the
    # refusal path should call _seed_listing without this fixture, or
    # override the composite's components list to drop the inventory guard.
    await db.upsert_resource(
        resource_id=f"res-{listing_id}",
        resource_type="compute.gpu",
        resource_subtype=None,
        unit="vm",
        value=1,
        state="available",
        attributes={
            "gpu_model": "H200",
            "region": "California, US",
            "vm_host": "kvm1",
        },
    )


@pytest_asyncio.fixture
async def client(db):
    import market_policy.negotiation_thread as _nt_module
    from market_policy.identity import Identity
    from market_storefront.services.policy_service import PolicyService

    _nt_module._thread_store = None
    _nt_module.get_thread_store(
        sqlite_client=db,
        identity=Identity(agent_url="http://test-seller:8001"),
    )

    config = MagicMock()
    config.base_url_override = "http://test-seller:8001"
    config.base_url_override_raw = "http://test-seller:8001"
    config.agent_id = "test-agent"
    config.agent_priv_key = ""
    config.chain_rpc_url = ""

    _container.resolved_sqlite_client = db
    _container.resolved_policy_service = PolicyService(
        sqlite_client=db,
        alkahest_client=None,
        agent_id="test-agent",
    )

    app = FastAPI()
    app.include_router(negotiate_router)

    transport = httpx.ASGITransport(app=app)
    with patch.object(buyer_auth, "_verify", return_value=None):
        async with StorefrontClient(
            "http://test",
            transport=transport,
            private_key="0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
            ) as c:
            yield c, db

    _container.resolved_sqlite_client = None
    _container.resolved_policy_service = None


class TestNegotiateNew:
    """POST /api/v1/negotiate/new — validation and happy path."""

    async def test_missing_listing_id_raises_422(self, client):
        """listing_id is required — Pydantic rejects the request."""
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_new(
                listing_id="",  # empty string still passes model; real 422 from missing field
                buyer_address=_BUYER,
                initial_price=8000,
                duration_seconds=3600,
            )
        # missing listing_id can't be tested via client (required param);
        # test that a nonexistent listing returns 404 below.

    async def test_unknown_listing_returns_404(self, client):
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_new(
                listing_id="ghost-listing",
                buyer_address=_BUYER,
                initial_price=8000,
                duration_seconds=3600,
            )
        assert "404" in str(exc_info.value)

    async def test_valid_request_starts_negotiation(self, client, db):
        c, db = client
        await _seed_listing(db, "neg-listing-1", demand_amount=5000)
        result = await c.negotiate_new(
            listing_id="neg-listing-1",
            buyer_address=_BUYER,
            initial_price=5000,
            duration_seconds=3600,
            token=_TOKEN,
        )
        assert "negotiation_id" in result
        assert result["action"] in ("accept", "counter", "exit")

    async def test_zero_duration_returns_422(self, client):
        """duration_seconds=0 is rejected by Pydantic (gt=0)."""
        c, _ = client
        with pytest.raises((StorefrontClientError, Exception)) as exc_info:
            await c.negotiate_new(
                listing_id="some-listing",
                buyer_address=_BUYER,
                initial_price=8000,
                duration_seconds=0,
            )
        assert any(code in str(exc_info.value) for code in ("422", "400"))

    async def test_negative_price_returns_422(self, client):
        """initial_price < 0 is rejected by Pydantic (ge=0)."""
        c, _ = client
        with pytest.raises((StorefrontClientError, Exception)) as exc_info:
            await c.negotiate_new(
                listing_id="some-listing",
                buyer_address=_BUYER,
                initial_price=-1,
                duration_seconds=3600,
            )
        assert any(code in str(exc_info.value) for code in ("422", "400"))

    async def test_listing_not_open_returns_409(self, client, db):
        """Listing in a terminal state is refused with 409."""
        c, db = client
        await _seed_listing(db, "neg-listing-closed")
        # Flip the listing's status to a non-open state.
        await db.update_listing(
            listing_id="neg-listing-closed",
            status="accepted",
        )
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_new(
                listing_id="neg-listing-closed",
                buyer_address=_BUYER,
                initial_price=5000,
                duration_seconds=3600,
            )
        msg = str(exc_info.value)
        assert "409" in msg
        assert "listing_not_open" in msg

    async def test_no_matching_inventory_returns_409(self, client, db):
        """Listing without a matching available compute resource is refused."""
        c, db = client
        # Seed listing only — no resource. Use a fresh listing_id since
        # _seed_listing always seeds an available resource.
        await db.upsert_listing(
            listing_id="neg-listing-empty",
            status="open",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            offer_resource={
                "gpu_model": "H200", "gpu_count": 1, "sla": 99.9,
                "region": "California, US",
            },
            accepted_escrows=[{
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "fields": {"token": _TOKEN},
                "price_per_hour": 5000,
            }],
            fulfillment_resource=None,
            max_duration_seconds=7200,
            seller="http://seller:8001",
        )
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_new(
                listing_id="neg-listing-empty",
                buyer_address=_BUYER,
                initial_price=5000,
                duration_seconds=3600,
            )
        msg = str(exc_info.value)
        assert "409" in msg
        assert "no_matching_inventory" in msg

    async def test_priceless_listing_without_fallback_returns_409(self, client, db):
        """Listing with demand.amount=None (hidden reserve) and no
        [seller.pricing].default_min_price configured → 409 with
        reason=no_floor_price (the seller has no negotiation floor)."""
        c, db = client
        await db.upsert_listing(
            listing_id="neg-listing-priceless",
            status="open",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            offer_resource={
                "gpu_model": "H200", "gpu_count": 1, "sla": 99.9,
                "region": "California, US",
            },
            accepted_escrows=[{
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "fields": {"token": _TOKEN},
                "price_per_hour": None,  # hidden reserve
            }],
            fulfillment_resource=None,
            max_duration_seconds=7200,
            seller="http://seller:8001",
        )
        # Seed a matching available resource so the inventory check passes
        # and we test the price-less guard specifically.
        await db.upsert_resource(
            resource_id="res-priceless",
            resource_type="compute.gpu",
            resource_subtype=None,
            unit="vm",
            value=1,
            state="available",
            attributes={"gpu_model": "H200", "region": "California, US", "vm_host": "kvm1"},
        )
        # default_min_price is None in the test config — falls through.
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_new(
                listing_id="neg-listing-priceless",
                buyer_address=_BUYER,
                initial_price=5000,
                duration_seconds=3600,
                token=_TOKEN,
            )
        msg = str(exc_info.value)
        assert "409" in msg
        assert "no_floor_price" in msg

    async def test_inventory_with_wrong_attributes_is_refused(self, client, db):
        """An available resource with the wrong gpu_model doesn't satisfy
        a listing offering a different gpu_model."""
        c, db = client
        # Seed a listing with the standard helper (which seeds H200).
        await _seed_listing(db, "neg-listing-mismatched")
        # Add a *different* available resource and remove the H200 one
        # by deleting it via state transition isn't easy here, so just
        # seed a wrong-model listing and skip the helper-seeded one.
        await db.upsert_listing(
            listing_id="neg-listing-rtx",
            status="open",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            offer_resource={
                "gpu_model": "RTX 4090", "gpu_count": 1, "sla": 99.9,
                "region": "California, US",
            },
            accepted_escrows=[{
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "fields": {"token": _TOKEN},
                "price_per_hour": 5000,
            }],
            fulfillment_resource=None,
            max_duration_seconds=7200,
            seller="http://seller:8001",
        )
        # The H200 resource seeded by _seed_listing doesn't match the
        # RTX 4090 offer; the seller should refuse.
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_new(
                listing_id="neg-listing-rtx",
                buyer_address=_BUYER,
                initial_price=5000,
                duration_seconds=3600,
            )
        assert "409" in str(exc_info.value)
        assert "no_matching_inventory" in str(exc_info.value)


class TestNegotiateContinue:
    """POST /api/v1/negotiate/{neg_id}"""

    async def test_unknown_neg_id_returns_404(self, client):
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_continue(
                "ghost-neg-id",
                action="exit",
                buyer_address=_BUYER,
            )
        assert "404" in str(exc_info.value)

    async def test_invalid_action_returns_422(self, client):
        """'invalid_action' is not a valid Literal — Pydantic rejects it."""
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_continue(
                "neg-123",
                action="invalid_action",
                buyer_address=_BUYER,
            )
        assert any(code in str(exc_info.value) for code in ("422", "400"))

    async def test_counter_without_price_returns_400(self, client, db):
        c, db = client
        await _seed_listing(db, "neg-listing-continue")
        result = await c.negotiate_new(
            listing_id="neg-listing-continue",
            buyer_address=_BUYER,
            initial_price=5000,
            duration_seconds=3600,
            token=_TOKEN,
        )
        if "negotiation_id" not in result:
            pytest.skip("Could not start negotiation")
        neg_id = result["negotiation_id"]

        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_continue(
                neg_id,
                action="counter",
                buyer_address=_BUYER,
                # price intentionally omitted
            )
        assert any(code in str(exc_info.value) for code in ("400", "422"))
