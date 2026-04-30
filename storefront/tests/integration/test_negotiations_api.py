"""Integration tests for the Negotiations API.

Uses the async ``StorefrontClient`` via ``httpx.ASGITransport`` —
matching the provisioning-service integration test pattern.
All assertions go through the canonical client; no raw HTTP calls.

``_seed_thread`` writes directly to SQLite because negotiation threads
are created by the negotiation engine, not through a public API.
Direct DB writes are the accepted exception when state is not
expressible through any API endpoint.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from starlette.applications import Starlette

from market_storefront.controllers.negotiations_controller import NegotiationsController
from market_storefront.middleware.admin_auth import AdminAuthMiddleware
from market_storefront.utils.sqlite_client import SQLiteClient
from storefront_client.client import StorefrontClient, StorefrontClientError

ADMIN_KEY = "test-admin-key"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db(tmp_path) -> SQLiteClient:
    return SQLiteClient(db_path=str(tmp_path / "neg_test.db"))


async def _seed_order(db: SQLiteClient, order_id: str) -> None:
    await db.upsert_listing(
        listing_id=order_id,
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource={"gpu_model": "H200", "quantity": 1, "sla": 99.9, "region": "California, US"},
        demand_resource={"token": {"symbol": "MOCK", "contract_address": "0x0000000000000000000000000000000000000001", "decimals": 18}, "amount": 9000},
        fulfillment_resource=None,
        duration_hours=2,
        seller="http://seller:8001",
    )


async def _seed_thread(
    db: SQLiteClient,
    neg_id: str,
    order_id: str,
    *,
    terminal_state: str | None = None,
    agreed_price: int | None = None,
) -> None:
    """Insert a minimal negotiation thread and two messages directly into SQLite.

    Uses an explicit named-column INSERT so the VALUES tuple count exactly
    matches the named columns, regardless of how many total columns the
    table has (extras get their DEFAULT values).
    """
    now = datetime.now().isoformat()

    def _insert() -> None:
        conn = sqlite3.connect(db.db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO negotiation_threads
                  (negotiation_id, our_listing_id, their_listing_id,
                   our_agent_id, their_agent_id,
                   terminal_state, agreed_price, agreed_duration_hours,
                   agreed_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    neg_id, order_id, "",
                    "http://seller:8001", "0xBuyer",
                    terminal_state,
                    agreed_price,
                    2 if agreed_price else None,
                    now if agreed_price else None,
                    now, now,
                ),
            )
            for round_num, (sender, action, price) in enumerate([
                ("0xBuyer",            "make_offer",    7000),
                ("http://seller:8001", "counter_offer", 9500),
            ]):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO negotiation_messages
                      (negotiation_id, round, sender,
                       our_price, their_price, proposed_price,
                       action_taken, message_type, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (neg_id, round_num, sender,
                     9000, price, price,
                     action,
                     "offer" if round_num == 0 else "counter_proposal",
                     now),
                )
            conn.commit()
        finally:
            conn.close()

    await asyncio.to_thread(_insert)


@pytest_asyncio.fixture
async def client(db) -> AsyncIterator[tuple[StorefrontClient, SQLiteClient]]:
    ctrl = NegotiationsController(sqlite_client=db)
    app = Starlette(routes=ctrl.routes())
    app.add_middleware(AdminAuthMiddleware, admin_api_key=ADMIN_KEY)
    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient(
        "http://test",
        transport=transport,
        admin_key=ADMIN_KEY,
    ) as c:
        yield c, db


@pytest_asyncio.fixture
async def client_no_key(db) -> AsyncIterator[StorefrontClient]:
    ctrl = NegotiationsController(sqlite_client=db)
    app = Starlette(routes=ctrl.routes())
    app.add_middleware(AdminAuthMiddleware, admin_api_key=ADMIN_KEY)
    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient("http://test", transport=transport) as c:
        yield c


# ---------------------------------------------------------------------------
# GET /api/v1/listings/{order_id}/negotiations
# ---------------------------------------------------------------------------

class TestListNegotiations:
    async def test_404_unknown_order(self, client):
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.list_negotiations("ghost")
        assert "404" in str(exc_info.value)

    async def test_empty_list(self, client):
        c, db = client
        await _seed_order(db, "ord-empty")
        result = await c.list_negotiations("ord-empty")
        assert result.negotiations == []
        assert result.count == 0

    async def test_lists_threads(self, client):
        c, db = client
        await _seed_order(db, "ord-a")
        await _seed_thread(db, "neg-1", "ord-a")
        await _seed_thread(db, "neg-2", "ord-a")
        result = await c.list_negotiations("ord-a")
        ids = {n.negotiation_id for n in result.negotiations}
        assert {"neg-1", "neg-2"} == ids

    async def test_terminal_state_filter(self, client):
        c, db = client
        await _seed_order(db, "ord-b")
        await _seed_thread(db, "neg-active", "ord-b")
        await _seed_thread(db, "neg-success", "ord-b",
                           terminal_state="success", agreed_price=9000)
        result = await c.list_negotiations("ord-b", terminal_state="success")
        ids = {n.negotiation_id for n in result.negotiations}
        assert "neg-success" in ids
        assert "neg-active" not in ids

    async def test_does_not_list_other_orders_threads(self, client):
        c, db = client
        await _seed_order(db, "ord-c")
        await _seed_order(db, "ord-d")
        await _seed_thread(db, "neg-c", "ord-c")
        result = await c.list_negotiations("ord-d")
        assert result.negotiations == []


# ---------------------------------------------------------------------------
# GET /api/v1/listings/{order_id}/negotiations/{neg_id}
# ---------------------------------------------------------------------------

class TestGetNegotiation:
    async def test_returns_detail(self, client):
        c, db = client
        await _seed_order(db, "ord-detail")
        await _seed_thread(db, "neg-detail", "ord-detail")
        detail = await c.get_negotiation("ord-detail", "neg-detail")
        assert detail.negotiation_id == "neg-detail"
        assert detail.our_listing_id == "ord-detail"
        assert len(detail.messages) == 2
        assert detail.round_count == 2

    async def test_message_log_fields(self, client):
        c, db = client
        await _seed_order(db, "ord-msg")
        await _seed_thread(db, "neg-msg", "ord-msg")
        detail = await c.get_negotiation("ord-msg", "neg-msg")
        for msg in detail.messages:
            assert msg.action_taken != ""
            assert msg.sender != ""

    async def test_404_unknown_neg(self, client):
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.get_negotiation("some-order", "does-not-exist")
        assert "404" in str(exc_info.value)

    async def test_404_neg_wrong_order(self, client):
        c, db = client
        await _seed_order(db, "ord-x")
        await _seed_order(db, "ord-y")
        await _seed_thread(db, "neg-x", "ord-x")
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.get_negotiation("ord-y", "neg-x")
        assert "404" in str(exc_info.value)


# ---------------------------------------------------------------------------
# POST .../force-accept
# ---------------------------------------------------------------------------

class TestForceAccept:
    async def test_requires_admin_key(self, client_no_key):
        with pytest.raises(StorefrontClientError) as exc_info:
            await client_no_key.force_accept_negotiation("ord-fa", "neg-fa", price=8500)
        assert "403" in str(exc_info.value)

    async def test_force_accept_commits_terminal_success(self, client):
        c, db = client
        await _seed_order(db, "ord-fa2")
        await _seed_thread(db, "neg-fa2", "ord-fa2")
        result = await c.force_accept_negotiation("ord-fa2", "neg-fa2", price=8500)
        assert result.action == "accept"
        assert result.price == 8500
        assert result.source == "admin_force_accept"
        # Verify through the read API — client contract test
        detail = await c.get_negotiation("ord-fa2", "neg-fa2")
        assert detail.terminal_state == "success"
        assert detail.agreed_price == 8500

    async def test_force_accept_missing_price_raises(self, client):
        c, db = client
        await _seed_order(db, "ord-fa3")
        await _seed_thread(db, "neg-fa3", "ord-fa3")
        # Bypass the typed client to test the API's own 400 handling
        resp = await c._client.post(
            "/api/v1/listings/ord-fa3/negotiations/neg-fa3/force-accept",
            json={},
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert resp.status_code == 400

    async def test_force_accept_already_terminal_raises(self, client):
        c, db = client
        await _seed_order(db, "ord-fa4")
        await _seed_thread(db, "neg-fa4", "ord-fa4",
                           terminal_state="success", agreed_price=9000)
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.force_accept_negotiation("ord-fa4", "neg-fa4", price=8000)
        assert "409" in str(exc_info.value)

    async def test_force_accept_404_unknown_neg_raises(self, client):
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.force_accept_negotiation("ord-fa5", "ghost", price=8000)
        assert "404" in str(exc_info.value)


# ---------------------------------------------------------------------------
# POST .../advance
# ---------------------------------------------------------------------------

class TestAdvanceNegotiation:
    async def test_requires_admin_key(self, client_no_key):
        with pytest.raises(StorefrontClientError) as exc_info:
            await client_no_key.advance_negotiation("ord-adv", "neg-adv", action="exit")
        assert "403" in str(exc_info.value)

    async def test_invalid_action_raises(self, client):
        c, db = client
        await _seed_order(db, "ord-adv2")
        await _seed_thread(db, "neg-adv2", "ord-adv2")
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.advance_negotiation("ord-adv2", "neg-adv2", action="invalid")
        assert "400" in str(exc_info.value)

    async def test_counter_missing_price_raises(self, client):
        c, db = client
        await _seed_order(db, "ord-adv3")
        await _seed_thread(db, "neg-adv3", "ord-adv3")
        with pytest.raises(StorefrontClientError) as exc_info:
            # price=None (default) with action=counter should be rejected by service
            await c.advance_negotiation("ord-adv3", "neg-adv3", action="counter")
        assert "400" in str(exc_info.value)

    async def test_exit_marks_thread_terminal(self, client):
        c, db = client
        await _seed_order(db, "ord-adv4")
        await _seed_thread(db, "neg-adv4", "ord-adv4")
        result = await c.advance_negotiation(
            "ord-adv4", "neg-adv4", action="exit", reason="operator_decision"
        )
        assert result.action == "exit"
        # Verify through the read API
        detail = await c.get_negotiation("ord-adv4", "neg-adv4")
        assert detail.terminal_state == "failure"

    async def test_404_unknown_neg_raises(self, client):
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.advance_negotiation("ord-adv5", "ghost", action="exit")
        assert "404" in str(exc_info.value)
