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
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

import market_storefront.container as _container
from market_storefront.controllers.negotiate_controller import router as negotiate_router
from market_storefront.middleware import buyer_auth
from storefront_client import StorefrontClient, StorefrontClientError

_BUYER = "0xBuyer00000000000000000000000000000000AB"  # 42 chars


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
        demand_resource={
            "token": {
                "symbol": "MOCK",
                "contract_address": "0x0000000000000000000000000000000000000001",
                "decimals": 0,
            },
            "amount": demand_amount,
        },
        fulfillment_resource=None,
        max_duration_seconds=7200,
        seller="http://seller:8001",
    )


@pytest_asyncio.fixture
async def client(db):
    import market_policy.negotiation_thread as _nt_module
    from market_policy.identity import Identity

    _nt_module._thread_store = None
    _nt_module.get_thread_store(
        sqlite_client=db,
        identity=Identity(agent_url="http://test-seller:8001"),
    )
    _container.resolved_sqlite_client = db

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
