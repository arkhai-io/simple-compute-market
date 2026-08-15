"""Integration tests for AdminSettleController.

Tests for POST /api/v1/admin/settle/{escrow_uid}/verify
and  POST /api/v1/admin/settle/{escrow_uid}/evaluate.

Both endpoints are dry-run (no DB writes, no chain reads in the unit path).
The verify endpoint requires a real chain — in integration tests we confirm
the error shape on a non-existent escrow. The evaluate endpoint only needs
SQLite (inventory lookup) and is testable fully in-process.

Test structure mirrors test_listings_api.py — FastAPI in-process transport,
real SQLiteClient (tmp_path), real AdminSettleController wired via container.
"""
from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from market_identity import Ed25519Signer, Identity, TrustedIdentitySet

import market_storefront.container as _container
from market_storefront.controllers.settle_controller import admin_settle_router
from market_storefront.middleware.admin_identity import (
    administrator_identity_middleware,
    initialize_administrator_identities,
)
from market_storefront.utils.sqlite_client import SQLiteClient
from storefront_client.client import StorefrontClient, StorefrontClientError

_TEST_SELLER_PRINCIPAL = Identity(
    scheme="eip191",
    identifier="0x2222222222222222222222222222222222222222",
)

ADMIN_SIGNER = Ed25519Signer(b"\x51" * 32)
STOREFRONT_SIGNER = Ed25519Signer(b"\x52" * 32)
PROVISIONING_SIGNER = Ed25519Signer(b"\x53" * 32)
ADMINISTRATORS = TrustedIdentitySet(identities=(ADMIN_SIGNER.identity,))
STOREFRONT_AUTHORITIES = TrustedIdentitySet(
    identities=(STOREFRONT_SIGNER.identity,)
)
PROVISIONING_AUTHORITIES = TrustedIdentitySet(
    identities=(PROVISIONING_SIGNER.identity,)
)


@pytest_asyncio.fixture
async def db(tmp_path):
    db_path = tmp_path / "settle_test.db"
    return SQLiteClient(db_path=str(db_path))


async def _seed_listing(
    db: SQLiteClient,
    listing_id: str,
    *,
    resource_id: str | None = None,
) -> None:
    """Seed a minimal compute listing into SQLite for evaluate tests."""
    now = datetime.now().isoformat()
    await db.upsert_listing(
        listing_id=listing_id,
        status="open",
        created_at=now,
        updated_at=now,
        paused=False,
        offer_resource={
            "resource_id": resource_id or f"res-{listing_id}",
            "gpu_model": "H200", "gpu_count": 1, "sla": 99.0,
            "region": "California, US",
        },
        accepted_escrows=[{
            "chain_name": "anvil",
            "escrow_address": "0x" + "11" * 20,
            "literal_fields": {"token": "0x0000000000000000000000000000000000000001"},
            "rates": [{"field": "amount", "per": "hour", "value": "5000"}],
        }],
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url="http://seller:8001",
        seller_principal=_TEST_SELLER_PRINCIPAL,
    )


@pytest_asyncio.fixture
async def admin_client(
    db,
    monkeypatch,
) -> AsyncIterator[tuple[StorefrontClient, SQLiteClient]]:
    """Admin settle controller wired with real v2 identity authentication."""
    monkeypatch.setattr(
        "market_storefront.middleware.admin_identity.get_administrator_configs",
        lambda: {"integration-admin": ADMINISTRATORS},
    )
    initialize_administrator_identities(db.db_path)
    monkeypatch.setattr(
        "market_storefront.services.capacity_client.get_provisioning_authorities",
        lambda: PROVISIONING_AUTHORITIES,
    )
    _container.resolved_sqlite_client = db
    _container.resolved_marketplace_signer = STOREFRONT_SIGNER

    app = FastAPI()
    app.include_router(admin_settle_router)
    app.middleware("http")(administrator_identity_middleware)

    transport = httpx.ASGITransport(app=app)
    async with StorefrontClient(
        "http://test",
        signer=ADMIN_SIGNER,
        caller_role="admin",
        expected_publishers=STOREFRONT_AUTHORITIES,
        transport=transport,
    ) as c:
        yield c, db

    _container.resolved_sqlite_client = None
    _container.resolved_marketplace_signer = None


# ---------------------------------------------------------------------------
# POST /api/v1/admin/settle/{escrow_uid}/verify
# ---------------------------------------------------------------------------


class TestVerifySettle:
    """POST /api/v1/admin/settle/{escrow_uid}/verify — escrow chain read dry-run."""

    async def test_unknown_listing_returns_404(self, admin_client):
        """Listing not in DB → 404 before chain read attempt."""
        c, _ = admin_client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.verify_settle(
                "some-escrow-uid",
                seller_wallet="0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
                agreed_price=5000,
                agreed_duration_seconds=3600,
                listing_id="does-not-exist",
            )
        assert "404" in str(exc_info.value)

    async def test_known_listing_attempts_chain_read(self, admin_client):
        """Known listing → proceeds to chain read; returns valid=False with reason (no real chain)."""
        c, db = admin_client
        await _seed_listing(db, "settle-verify-1")
        # Chain RPC is not configured in the in-process test — verify_escrow_for_settlement
        # will raise EscrowVerificationError("chain.rpc_url is not configured")
        # which the controller maps to valid=False (not 500).
        result = await c.verify_settle(
            "fake-escrow-uid",
            seller_wallet="0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
            agreed_price=5000,
            agreed_duration_seconds=3600,
            listing_id="settle-verify-1",
        )
        assert isinstance(result, dict)
        assert result.get("valid") is False
        assert result.get("escrow_uid") == "fake-escrow-uid"
        assert result.get("reason")  # non-empty reason explaining failure

    async def test_response_always_contains_escrow_uid(self, admin_client):
        """escrow_uid is always echoed back in the response."""
        c, db = admin_client
        await _seed_listing(db, "settle-verify-uid")
        result = await c.verify_settle(
            "echo-this-uid",
            seller_wallet="0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
            agreed_price=1000,
            agreed_duration_seconds=3600,
            listing_id="settle-verify-uid",
        )
        assert result.get("escrow_uid") == "echo-this-uid"

    async def test_no_db_writes_on_verify(self, admin_client):
        """verify_settle must not create any settlement_jobs rows."""
        c, db = admin_client
        await _seed_listing(db, "settle-verify-nowrite")
        await c.verify_settle(
            "no-write-uid",
            seller_wallet="0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
            agreed_price=1000,
            agreed_duration_seconds=3600,
            listing_id="settle-verify-nowrite",
        )
        job = await db.load_escrow(escrow_uid="no-write-uid")
        assert job is None, (
            "verify_settle must not write settlement_jobs rows — it is a dry-run endpoint."
        )


# ---------------------------------------------------------------------------
# POST /api/v1/admin/settle/{escrow_uid}/evaluate
# ---------------------------------------------------------------------------


class TestEvaluateSettle:
    """POST /api/v1/admin/settle/{escrow_uid}/evaluate — provisioning job spec dry-run."""

    async def test_unknown_listing_returns_404(self, admin_client):
        """Listing not in DB → 404."""
        c, _ = admin_client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.evaluate_settle(
                "some-escrow-uid",
                listing_id="does-not-exist",
                ssh_public_key="",
                duration_seconds=3600,
            )
        assert "404" in str(exc_info.value)

    async def test_known_listing_no_inventory_returns_would_submit_false(self, admin_client):
        """Known listing but empty inventory → would_submit=False with reason."""
        c, db = admin_client
        await _seed_listing(db, "settle-eval-no-inv")
        from tests.fake_site import FakeSite, site_capacity

        with site_capacity(FakeSite(deliverable_modes={"vm"})):
            result = await c.evaluate_settle(
                "eval-escrow-1",
                listing_id="settle-eval-no-inv",
                ssh_public_key="",
                duration_seconds=3600,
            )
        assert isinstance(result, dict)
        # No inventory registered → no host matches
        assert result.get("would_submit") is False
        assert result.get("escrow_uid") == "eval-escrow-1"
        assert result.get("reason")  # explains no matching host

    async def test_response_contains_escrow_uid(self, admin_client):
        """escrow_uid is always echoed back."""
        c, db = admin_client
        await _seed_listing(db, "settle-eval-echo")
        result = await c.evaluate_settle(
            "echo-escrow-uid",
            listing_id="settle-eval-echo",
        )
        assert result.get("escrow_uid") == "echo-escrow-uid"

    async def test_no_db_writes_on_evaluate(self, admin_client):
        """evaluate_settle must not create settlement_jobs rows or reserve inventory."""
        c, db = admin_client
        await _seed_listing(db, "settle-eval-nowrite")

        # Seed a resource so the select could potentially reserve it
        await db.upsert_resource(
            resource_id="r-eval-1",
            resource_type="compute.gpu",
            resource_subtype="H200",
            unit="gpu",
            state="available",
            value=1,
            attributes={"gpu_model": "H200", "region": "California, US", "vm_host": "host1"},
        )

        await c.evaluate_settle(
            "no-write-eval-uid",
            listing_id="settle-eval-nowrite",
            duration_seconds=3600,
        )

        # Settlement job must not be created
        job = await db.load_escrow(escrow_uid="no-write-eval-uid")
        assert job is None, "evaluate_settle must not write settlement_jobs rows"

        # Resource must still be available (not reserved)
        resource = await db.get_resource(resource_id="r-eval-1")
        assert resource is not None
        assert resource.get("state") == "available", (
            f"evaluate_settle reserved a resource (state={resource.get('state')!r}) "
            "— it must use reserve=False (read-only inventory selection)."
        )

    async def test_with_matching_inventory_returns_would_submit_true(self, admin_client):
        """Listing + matching inventory resource → would_submit=True with vm_host."""
        c, db = admin_client
        await _seed_listing(
            db,
            "settle-eval-match",
            resource_id="r-eval-match",
        )
        await db.upsert_resource(
            resource_id="r-eval-match",
            resource_type="compute.gpu",
            resource_subtype="H200",
            unit="gpu",
            state="available",
            value=1,
            attributes={"gpu_model": "H200", "region": "California, US", "vm_host": "host-match"},
        )

        from tests.fake_site import FakeSite, site_capacity

        fake = FakeSite(deliverable_modes={"vm"})
        fake.add_resource(
            "r-eval-match", 1,
            attributes={
                "gpu_model": "H200", "region": "California, US",
                "vm_host": "host-match",
            },
        )
        with site_capacity(fake):
            result = await c.evaluate_settle(
                "match-escrow-uid",
                listing_id="settle-eval-match",
                ssh_public_key="ssh-ed25519 AAAAC3 test@test",
                duration_seconds=3600,
            )

        assert result.get("would_submit") is True, (
            f"Expected would_submit=True with matching inventory. reason={result.get('reason')!r}"
        )
        assert result.get("vm_host") == "host-match"
        assert result.get("vm_target")  # non-empty generated target name
