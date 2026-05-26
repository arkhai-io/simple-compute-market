"""Unit tests for order pause state.

Tests:
- ``set_order_paused`` / ``is_order_paused`` SQLiteClient helpers
- ``StorefrontPausedError`` is raised by ``start_sync_negotiation`` when
  the storefront is globally paused or the order is individually paused
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from service.schemas import EscrowProposal

from market_storefront.utils.sqlite_client import SQLiteClient
from market_storefront.utils.sync_negotiation import (
    OfferUnfulfillableError,
    StorefrontPausedError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db(tmp_path) -> SQLiteClient:
    client = SQLiteClient(db_path=str(tmp_path / "test.db"))
    # Seed a minimal order row to test pause helpers against
    from datetime import datetime
    await client.upsert_listing(
        listing_id="order-001",
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource={"gpu_model": "H200", "gpu_count": 1, "sla": 99.9, "region": "California, US"},
        accepted_escrows=[{
            "chain_name": "test",
            "escrow_address": "0x000000000000000000000000000000000000abcd",
            "fields": {"token": "0x0000000000000000000000000000000000000001"},
            "price_per_hour": 1000,
        }],
        fulfillment_resource=None,
        max_duration_seconds=3600,
        seller="http://seller:8001",
    )
    return client


# ---------------------------------------------------------------------------
# set_order_paused / is_order_paused
# ---------------------------------------------------------------------------

class TestOrderPauseHelpers:
    async def test_new_order_not_paused_by_default(self, db):
        assert await db.is_listing_paused(listing_id="order-001") is False

    async def test_set_paused_true(self, db):
        await db.set_listing_paused(listing_id="order-001", paused=True)
        assert await db.is_listing_paused(listing_id="order-001") is True

    async def test_set_paused_false_after_true(self, db):
        await db.set_listing_paused(listing_id="order-001", paused=True)
        await db.set_listing_paused(listing_id="order-001", paused=False)
        assert await db.is_listing_paused(listing_id="order-001") is False

    async def test_unknown_order_not_paused(self, db):
        assert await db.is_listing_paused(listing_id="does-not-exist") is False

    async def test_load_listing_returns_paused_flag(self, db):
        """load_listing must surface the paused column.

        Regression guard: load_listing previously omitted 'paused' from its
        SELECT, so the controller always fell back to paused=False regardless
        of what set_listing_paused had written.
        """
        # Default: paused should be False
        row = await db.load_listing(listing_id="order-001")
        assert row is not None
        assert row.get("paused") is False, (
            f"Expected paused=False on a freshly created listing, got {row.get('paused')!r}"
        )

        # After set_listing_paused: load_listing must reflect the change
        await db.set_listing_paused(listing_id="order-001", paused=True)
        row = await db.load_listing(listing_id="order-001")
        assert row is not None
        assert row.get("paused") is True, (
            f"Expected paused=True after set_listing_paused, got {row.get('paused')!r}. "
            f"'paused' key present: {'paused' in row}"
        )

        # And it round-trips back to False
        await db.set_listing_paused(listing_id="order-001", paused=False)
        row = await db.load_listing(listing_id="order-001")
        assert row["paused"] is False

    async def test_upsert_listing_round_trips_paused_flag(self, db):
        from datetime import datetime

        now = datetime.now().isoformat()
        await db.upsert_listing(
            listing_id="order-paused-at-create",
            status="open",
            created_at=now,
            updated_at=now,
            offer_resource={},
            
            fulfillment_resource=None,
            max_duration_seconds=3600,
            seller="http://seller:8001",
            paused=True,
        )

        row = await db.load_listing(listing_id="order-paused-at-create")
        assert row is not None
        assert row["paused"] is True

        paused_orders = await db.list_listings(paused=True)
        assert "order-paused-at-create" in {
            order["listing_id"] for order in paused_orders
        }

    async def test_list_orders_paused_filter(self, db):
        # Add a second order (not paused)
        from datetime import datetime
        await db.upsert_listing(
            listing_id="order-002",
            status="open",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            offer_resource={},
            
            fulfillment_resource=None,
            max_duration_seconds=3600,
            seller="http://seller:8001",
        )
        await db.set_listing_paused(listing_id="order-001", paused=True)

        paused_orders = await db.list_listings(paused=True)
        unpaused_orders = await db.list_listings(paused=False)

        paused_ids = {o["listing_id"] for o in paused_orders}
        unpaused_ids = {o["listing_id"] for o in unpaused_orders}

        assert "order-001" in paused_ids
        assert "order-002" not in paused_ids
        assert "order-002" in unpaused_ids
        assert "order-001" not in unpaused_ids


# ---------------------------------------------------------------------------
# StorefrontPausedError
# ---------------------------------------------------------------------------

class TestStorefrontPausedError:
    def test_default_reason(self):
        exc = StorefrontPausedError()
        assert exc.reason == "paused"
        assert "paused" in str(exc)

    def test_custom_reason(self):
        exc = StorefrontPausedError("global")
        assert exc.reason == "global"

    def test_order_reason(self):
        exc = StorefrontPausedError("order:abc123")
        assert exc.reason == "order:abc123"

    def test_is_exception_subclass(self):
        assert isinstance(StorefrontPausedError(), Exception)


# ---------------------------------------------------------------------------
# start_sync_negotiation raises StorefrontPausedError when paused
# ---------------------------------------------------------------------------

class TestStartSyncNegotiationPauseGuard:
    """Test that pause checks fire before any DB work in start_sync_negotiation."""

    async def test_global_pause_raises(self, db, monkeypatch):
        # Patch is_globally_paused to return True
        import market_storefront.server as server_mod
        monkeypatch.setattr(server_mod, "_GLOBALLY_PAUSED", True)

        from market_storefront.utils.sync_negotiation import start_sync_negotiation
        with pytest.raises(StorefrontPausedError) as exc_info:
            await start_sync_negotiation(
                sqlite_client=db,
                our_listing_id="order-001",
                buyer_address="0xBuyer",
                proposal=EscrowProposal(chain_name="anvil", escrow_address="0x"+"0"*40, fields={"amount": 5000, "token": "0x"+"a"*40}, expiration_unix=2000000000),
                our_base_url="http://seller:8001",
                their_agent_url="0xBuyer",
            )
        assert exc_info.value.reason == "global"

    async def test_order_pause_raises(self, db, monkeypatch):
        import market_storefront.server as server_mod
        monkeypatch.setattr(server_mod, "_GLOBALLY_PAUSED", False)

        await db.set_listing_paused(listing_id="order-001", paused=True)

        from market_storefront.utils.sync_negotiation import start_sync_negotiation
        with pytest.raises(StorefrontPausedError) as exc_info:
            await start_sync_negotiation(
                sqlite_client=db,
                our_listing_id="order-001",
                buyer_address="0xBuyer",
                proposal=EscrowProposal(chain_name="anvil", escrow_address="0x"+"0"*40, fields={"amount": 5000, "token": "0x"+"a"*40}, expiration_unix=2000000000),
                our_base_url="http://seller:8001",
                their_agent_url="0xBuyer",
            )
        assert "order-001" in exc_info.value.reason

    async def test_no_pause_proceeds_normally(self, db, monkeypatch):
        """When not paused, the function proceeds to normal validation
        (raises ValueError for missing strategy, not StorefrontPausedError)."""
        import market_storefront.server as server_mod
        monkeypatch.setattr(server_mod, "_GLOBALLY_PAUSED", False)

        from market_storefront.utils.sync_negotiation import start_sync_negotiation
        # order-001 has no strategy set, so we expect ValueError not paused
        with pytest.raises((ValueError, Exception)) as exc_info:
            await start_sync_negotiation(
                sqlite_client=db,
                our_listing_id="order-001",
                buyer_address="0xBuyer",
                proposal=EscrowProposal(chain_name="anvil", escrow_address="0x"+"0"*40, fields={"amount": 5000, "token": "0x"+"a"*40}, expiration_unix=2000000000),
                our_base_url="http://seller:8001",
                their_agent_url="0xBuyer",
            )
        assert not isinstance(exc_info.value, StorefrontPausedError)

    async def test_pre_negotiation_guard_rejection_raises_offer_unfulfillable(
        self, db, monkeypatch
    ):
        """Round-0 guard veto (no matching inventory) raises OfferUnfulfillableError.

        The fixture's listing offers ``gpu_model=H200, region=California, US``;
        the test DB has no portfolio resources at all, so the
        ``has_matching_inventory_guard`` middleware vetoes with
        ``no_matching_inventory``, which maps to 409.
        """
        import market_storefront.server as server_mod
        monkeypatch.setattr(server_mod, "_GLOBALLY_PAUSED", False)

        from market_storefront.utils.sync_negotiation import start_sync_negotiation
        from service.schemas import EscrowProposal, ProvisionTerms
        with pytest.raises(OfferUnfulfillableError) as exc_info:
            await start_sync_negotiation(
                sqlite_client=db,
                our_listing_id="order-001",
                buyer_address="0xBuyer",
                proposal=EscrowProposal(chain_name="anvil", escrow_address="0x"+"0"*40, fields={"amount": 5000, "token": "0x"+"a"*40}, expiration_unix=2000000000),
                provision_terms=ProvisionTerms(
                    duration_seconds=1800, ssh_public_key="ssh-rsa AAAA",
                ),
                our_base_url="http://seller:8001",
                their_agent_url="0xBuyer",
            )

        assert exc_info.value.reason == "no_matching_inventory"
        assert exc_info.value.listing_id == "order-001"
