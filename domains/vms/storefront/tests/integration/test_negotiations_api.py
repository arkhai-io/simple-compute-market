"""Integration tests for the Negotiations API.

Uses the async ``StorefrontClient`` via ``httpx.ASGITransport`` —
matching the provisioning-service integration test pattern. Authenticated
paths use the canonical client; raw transport is reserved for unsigned rejection.

``_seed_thread`` writes directly to SQLite because negotiation threads
are created by the negotiation engine, not through a public API.
Direct DB writes are the accepted exception when state is not
expressible through any API endpoint.
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from market_capacity_publication import CapacityBinding, CapacityRuntime, CapacitySite
from market_identity import Ed25519Signer, TrustedIdentitySet

import market_storefront.container as _container
import market_storefront.middleware.admin_identity as _admin_identity
from market_storefront.controllers.negotiations_controller import router as negotiations_router
from core_storefront.aggregation import fill_first
from core_storefront.domain_registry import (
    StorefrontListingBinding,
    build_storefront_derivation_key,
)
from core_storefront.services.negotiation_service import NegotiationService
from core_storefront.stage_log import stage_event

from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.utils.sqlite_client import SQLiteClient
from market_storefront.negotiation_runtime import build_vm_negotiation_runtime
from storefront_client.client import StorefrontClient, StorefrontClientError


_ADMIN_SIGNER = Ed25519Signer(b"\x31" * 32)
_BUYER_SIGNER = Ed25519Signer(b"\x32" * 32)
_SELLER_SIGNER = Ed25519Signer(b"\x33" * 32)
_SELLER_TRUST = TrustedIdentitySet(identities=(_SELLER_SIGNER.identity,))
_ADMIN_TRUST = TrustedIdentitySet(identities=(_ADMIN_SIGNER.identity,))

async def _noop_reconcile(_context) -> None:
    return None


def _capacity_runtime() -> CapacityRuntime:
    return CapacityRuntime(
        sites=(
            CapacitySite(
                "site-test",
                "http://capacity.test",
                _SELLER_TRUST,
            ),
        ),
        signer=_SELLER_SIGNER,
        placement=fill_first,
        reconcile=_noop_reconcile,
        site_client_factory=lambda _site, _signer: object(),
    )



# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db(tmp_path) -> SQLiteClient:
    domain = build_vm_storefront_domain()
    registry = build_vm_storefront_registry(domain)
    return SQLiteClient(
        db_path=str(tmp_path / "neg_test.db"),
        registry=registry,
    )


async def _seed_order(db: SQLiteClient, order_id: str) -> None:
    registration = db.domain_registry.resolve_mode("vm")
    listing_binding = StorefrontListingBinding.from_source_envelope(
        listing_id=order_id,
        site_id="site-test",
        pool_id=f"pool-{order_id}",
        binding=registration.binding,
        derivation_key=build_storefront_derivation_key(
            site_id="site-test",
            offering_mode=registration.offering_mode,
            binding=registration.binding,
            source_identity={"pool_id": f"pool-{order_id}"},
        ),
        source_envelope={
            "kind": "vm.test-listing-source.v1",
            "schema_version": 1,
            "payload": {"pool_id": f"pool-{order_id}"},
        },
        last_reconciled_at=datetime.now().isoformat(),
    )
    await db.upsert_listing_with_binding(
        binding=listing_binding,
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource={
            "resource_id": f"res-{order_id}",
            "gpu_model": "H200",
            "gpu_count": 1,
            "sla": 99.9,
            "region": "California, US",
            "virtualization_type": "vm",
        },
        accepted_escrows=[{
            "chain_name": "anvil",
            "escrow_address": "0x" + "11" * 20,
            "literal_fields": {
                "token": "0x0000000000000000000000000000000000000001",
            },
            "rates": [{"field": "amount", "per": "hour", "value": "9000"}],
        }],
        fulfillment_resource=None,
        max_duration_seconds=7200,
        storefront_url="http://seller:8001",
        seller_principal=_SELLER_SIGNER.identity,
    )


async def _seed_thread(
    db: SQLiteClient,
    neg_id: str,
    order_id: str,
    *,
    terminal_state: str | None = None,
    agreed_price: float | None = None,
) -> None:
    """Insert a minimal negotiation thread and two messages directly into SQLite."""
    now = datetime.now().isoformat()

    def _insert() -> None:
        conn = sqlite3.connect(db.db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO negotiation_threads
                  (negotiation_id, our_listing_id, their_listing_id,
                   buyer_scheme, buyer_identifier,
                   seller_scheme, seller_identifier,
                   terminal_state, agreed_price, agreed_duration_seconds,
                   agreed_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    neg_id,
                    order_id,
                    "",
                    _BUYER_SIGNER.identity.scheme.value,
                    _BUYER_SIGNER.identity.identifier,
                    _SELLER_SIGNER.identity.scheme.value,
                    _SELLER_SIGNER.identity.identifier,
                    terminal_state,
                    agreed_price,
                    7200 if agreed_price else None,
                    now if agreed_price else None,
                    now,
                    now,
                ),
            )
            messages = (
                (_BUYER_SIGNER.identity, "buyer", "make_offer", 7000),
                (_SELLER_SIGNER.identity, "seller", "counter_offer", 9500),
            )
            for round_num, (sender, sender_role, action, price) in enumerate(messages):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO negotiation_messages
                      (negotiation_id, round, sender_role,
                       sender_scheme, sender_identifier,
                       our_price, their_price, proposed_price,
                       action_taken, message_type, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        neg_id,
                        round_num,
                        sender_role,
                        sender.scheme.value,
                        sender.identifier,
                        9000,
                        price,
                        price,
                        action,
                        "offer" if round_num == 0 else "counter_proposal",
                        now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    await asyncio.to_thread(_insert)
    thread_binding = await db.copy_listing_binding_to_thread(
        negotiation_id=neg_id,
        listing_id=order_id,
    )
    listing_binding = await db.load_listing_binding(listing_id=order_id)
    assert listing_binding is not None
    assert thread_binding.binding == listing_binding.binding
    assert thread_binding.site_id == listing_binding.site_id


def _make_negotiation_service(db: SQLiteClient) -> NegotiationService:
    registration = db.domain_registry.resolve_mode("vm")
    runtime = build_vm_negotiation_runtime(
        registration.contract,
        registry=db.domain_registry,
        binding=registration.binding,
        capacity_runtime=_capacity_runtime(),
    )
    return NegotiationService(
        sqlite_client=db,
        continue_negotiation=runtime.continue_negotiation,
        stage_event=stage_event,
    )


@pytest_asyncio.fixture
async def api(db, monkeypatch) -> AsyncIterator[tuple[FastAPI, SQLiteClient]]:
    import market_policy.negotiation_thread as _nt_module
    from market_policy.identity import Identity as PolicyIdentity

    async def capacity_binding_for_listing(_repository, listing_id):
        assert _repository is db
        listing_binding = await db.load_listing_binding(listing_id=listing_id)
        assert listing_binding is not None
        return CapacityBinding(
            listing_binding.site_id,
            listing_binding.binding.offering_mode,
            str(listing_binding.pool_id),
        )

    monkeypatch.setattr(
        "market_storefront.negotiation_runtime.capacity_binding_for_listing",
        capacity_binding_for_listing,
    )

    _nt_module._thread_store = None
    _nt_module.get_thread_store(
        sqlite_client=db,
        identity=PolicyIdentity(agent_url="http://test-seller:8001"),
    )

    _container.resolved_sqlite_client = db
    _container.resolved_negotiation_service = _make_negotiation_service(db)
    _container.resolved_marketplace_signer = _SELLER_SIGNER
    monkeypatch.setattr(
        _admin_identity,
        "get_administrator_configs",
        lambda: {"operator": _ADMIN_TRUST},
    )
    _admin_identity.initialize_administrator_identities(db.db_path)

    app = FastAPI()
    app.middleware("http")(_admin_identity.administrator_identity_middleware)
    app.include_router(negotiations_router)
    yield app, db

    _nt_module._thread_store = None
    _container.resolved_sqlite_client = None
    _container.resolved_negotiation_service = None
    _container.resolved_marketplace_signer = None


@pytest_asyncio.fixture
async def client(api) -> AsyncIterator[tuple[StorefrontClient, SQLiteClient]]:
    app, db = api
    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient(
        "http://test",
        signer=_ADMIN_SIGNER,
        caller_role="admin",
        expected_publishers=_SELLER_TRUST,
        transport=transport,
    ) as c:
        yield c, db


@pytest_asyncio.fixture
async def unsigned_client(api) -> AsyncIterator[httpx.AsyncClient]:
    app, _ = api
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        base_url="http://test",
        transport=transport,
    ) as c:
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
        assert all(
            negotiation.buyer_principal == _BUYER_SIGNER.identity
            and negotiation.seller_principal == _SELLER_SIGNER.identity
            for negotiation in result.negotiations
        )

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
        assert detail.buyer_principal == _BUYER_SIGNER.identity
        assert detail.seller_principal == _SELLER_SIGNER.identity
        assert len(detail.messages) == 2
        assert detail.round_count == 2

    async def test_message_log_fields(self, client):
        c, db = client
        await _seed_order(db, "ord-msg")
        await _seed_thread(db, "neg-msg", "ord-msg")
        detail = await c.get_negotiation("ord-msg", "neg-msg")
        assert [msg.sender_role for msg in detail.messages] == ["buyer", "seller"]
        assert [msg.sender_principal for msg in detail.messages] == [
            _BUYER_SIGNER.identity,
            _SELLER_SIGNER.identity,
        ]
        assert all(msg.action_taken for msg in detail.messages)

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

    async def test_surfaces_escrows(self, client):
        c, db = client
        await _seed_order(db, "ord-esc")
        await _seed_thread(db, "neg-esc", "ord-esc")
        await db.insert_escrow(
            escrow_uid="0xPrimary",
            negotiation_id="neg-esc",
            chain_name="anvil",
            escrow_address="0x" + "11" * 20,
            is_primary=True,
            status="provisioning",
        )
        await db.update_escrow(
            escrow_uid="0xPrimary",
            fulfillment_uid="0xFulfillment",
        )
        await db.insert_escrow(
            escrow_uid="0xBond",
            negotiation_id="neg-esc",
            chain_name="anvil",
            escrow_address="0x" + "22" * 20,
            is_primary=False,
            status="provisioning",
        )
        detail = await c.get_negotiation("ord-esc", "neg-esc")
        assert len(detail.escrows) == 2
        # Primary first
        primary, bond = detail.escrows
        assert primary["escrow_uid"] == "0xPrimary"
        assert primary["fulfillment_uid"] == "0xFulfillment"
        assert primary["chain_name"] == "anvil"
        assert primary["is_primary"] is True
        assert primary["status"] == "provisioning"
        assert bond["escrow_uid"] == "0xBond"
        assert bond["is_primary"] is False

    async def test_empty_escrows_when_none_recorded(self, client):
        c, db = client
        await _seed_order(db, "ord-noesc")
        await _seed_thread(db, "neg-noesc", "ord-noesc")
        detail = await c.get_negotiation("ord-noesc", "neg-noesc")
        assert detail.escrows == []


# ---------------------------------------------------------------------------
# POST .../force-accept
# ---------------------------------------------------------------------------

class TestForceAccept:
    async def test_requires_signed_admin_identity(self, unsigned_client):
        response = await unsigned_client.post(
            "/api/v1/listings/ord-fa/negotiations/neg-fa/force-accept",
            json={"amount": 8500},
        )
        assert response.status_code == 401

    async def test_force_accept_commits_terminal_success(self, client):
        c, db = client
        await _seed_order(db, "ord-fa2")
        await _seed_thread(db, "neg-fa2", "ord-fa2")
        result = await c.force_accept_negotiation("ord-fa2", "neg-fa2", amount=8500)
        assert result.action == "accept"
        assert result.amount == 8500
        assert result.source == "admin_force_accept"
        detail = await c.get_negotiation("ord-fa2", "neg-fa2")
        assert detail.terminal_state == "success"
        assert detail.agreed_amount == 8500
        assert detail.messages[-1].sender_role == "admin"
        assert detail.messages[-1].sender_principal == _ADMIN_SIGNER.identity

    async def test_force_accept_missing_price_raises(self, client):
        c, db = client
        await _seed_order(db, "ord-fa3")
        await _seed_thread(db, "neg-fa3", "ord-fa3")
        with pytest.raises(StorefrontClientError) as exc_info:
            await c._authenticated_post(
                "/api/v1/listings/ord-fa3/negotiations/neg-fa3/force-accept",
                {},
                role="admin",
                operation="admin_force_accept_negotiation",
                resource="ord-fa3/neg-fa3",
            )
        assert exc_info.value.status_code == 422

    async def test_force_accept_already_terminal_raises(self, client):
        c, db = client
        await _seed_order(db, "ord-fa4")
        await _seed_thread(db, "neg-fa4", "ord-fa4",
                           terminal_state="success", agreed_price=9000)
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.force_accept_negotiation("ord-fa4", "neg-fa4", amount=8000)
        assert "409" in str(exc_info.value)

    async def test_force_accept_404_unknown_neg_raises(self, client):
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.force_accept_negotiation("ord-fa5", "ghost", amount=8000)
        assert "404" in str(exc_info.value)


# ---------------------------------------------------------------------------
# POST .../advance
# ---------------------------------------------------------------------------

class TestAdvanceNegotiation:
    async def test_requires_signed_admin_identity(self, unsigned_client):
        response = await unsigned_client.post(
            "/api/v1/listings/ord-adv/negotiations/neg-adv/advance",
            json={"action": "exit"},
        )
        assert response.status_code == 401

    async def test_invalid_action_raises(self, client):
        c, db = client
        await _seed_order(db, "ord-adv2")
        await _seed_thread(db, "neg-adv2", "ord-adv2")
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.advance_negotiation("ord-adv2", "neg-adv2", action="invalid")
        assert exc_info.value.status_code == 422

    async def test_counter_missing_price_raises(self, client):
        c, db = client
        await _seed_order(db, "ord-adv3")
        await _seed_thread(db, "neg-adv3", "ord-adv3")
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.advance_negotiation("ord-adv3", "neg-adv3", action="counter")
        assert exc_info.value.status_code == 400

    async def test_exit_marks_thread_terminal(self, client):
        c, db = client
        await _seed_order(db, "ord-adv4")
        await _seed_thread(db, "neg-adv4", "ord-adv4")
        result = await c.advance_negotiation(
            "ord-adv4", "neg-adv4", action="exit", reason="operator_decision"
        )
        assert result.action == "exit"
        detail = await c.get_negotiation("ord-adv4", "neg-adv4")
        assert detail.terminal_state == "failure"

    async def test_404_unknown_neg_raises(self, client):
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.advance_negotiation("ord-adv5", "ghost", action="exit")
        assert "404" in str(exc_info.value)
