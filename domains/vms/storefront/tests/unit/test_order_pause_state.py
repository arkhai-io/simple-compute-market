"""Unit tests for order pause state.

Tests:
- ``set_order_paused`` / ``is_order_paused`` SQLiteClient helpers
- ``StorefrontPausedError`` is raised by the shared negotiation runtime when
  the storefront is globally paused or the order is individually paused
"""

from __future__ import annotations


import pytest
import pytest_asyncio

from core_storefront.aggregation import fill_first
from core_storefront.domain_registry import (
    StorefrontListingBinding,
    build_storefront_derivation_key,
)
from market_capacity_publication import CapacityBinding, CapacityRuntime, CapacitySite
from market_core.schemas import EscrowProposal
from market_identity import TrustedIdentitySet, create_signer

from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.utils.sqlite_client import SQLiteClient
from market_negotiation_runtime import (
    OfferUnfulfillableError,
    StorefrontPausedError,
)
from market_storefront.negotiation_runtime import build_vm_negotiation_runtime


_BUYER_SIGNER = create_signer("ed25519", b"\x41" * 32)
_SELLER_SIGNER = create_signer("ed25519", b"\x42" * 32)
_BUYER_PRINCIPAL = _BUYER_SIGNER.identity
_SELLER_PRINCIPAL = _SELLER_SIGNER.identity
_PROVISIONING_AUTHORITIES = TrustedIdentitySet(
    identities=(
        create_signer("ed25519", b"\x43" * 32).identity,
        create_signer("ed25519", b"\x44" * 32).identity,
    )
)


async def _noop_reconcile(_context) -> None:
    return None


def _capacity_runtime() -> CapacityRuntime:
    return CapacityRuntime(
        sites=(
            CapacitySite(
                "site-test",
                "http://capacity.test",
                _PROVISIONING_AUTHORITIES,
            ),
        ),
        signer=_SELLER_SIGNER,
        placement=fill_first,
        reconcile=_noop_reconcile,
        site_client_factory=lambda _site, _signer: object(),
    )


async def _start(
    *,
    sqlite_client,
    our_listing_id,
    buyer_principal,
    seller_principal,
    proposal,
    our_base_url,
    their_agent_url,
    provision_terms=None,
):
    registration = sqlite_client.domain_registry.resolve_mode("vm")
    runtime = build_vm_negotiation_runtime(
        registration.contract,
        registry=sqlite_client.domain_registry,
        binding=registration.binding,
        capacity_runtime=_capacity_runtime(),
    )
    return await runtime.start(
        repository=sqlite_client,
        listing_id=our_listing_id,
        buyer_principal=buyer_principal,
        seller_principal=seller_principal,
        actor_principal=buyer_principal,
        proposal=proposal.model_dump(mode="json"),
        terms=provision_terms,
        seller_agent_url=our_base_url,
        buyer_agent_url=their_agent_url,
    )

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db(tmp_path) -> SQLiteClient:
    from datetime import datetime

    domain = build_vm_storefront_domain()
    registry = build_vm_storefront_registry(domain)
    registration = registry.resolve_mode("vm")
    client = SQLiteClient(
        db_path=str(tmp_path / "test.db"),
        registry=registry,
    )
    listing_binding = StorefrontListingBinding.from_source_envelope(
        listing_id="order-001",
        site_id="site-test",
        pool_id="pool-order-001",
        binding=registration.binding,
        derivation_key=build_storefront_derivation_key(
            site_id="site-test",
            offering_mode=registration.offering_mode,
            binding=registration.binding,
            source_identity={"pool_id": "pool-order-001"},
        ),
        source_envelope={
            "kind": "vm.test-listing-source.v1",
            "schema_version": 1,
            "payload": {"pool_id": "pool-order-001"},
        },
        last_reconciled_at=datetime.now().isoformat(),
    )
    await client.upsert_listing_with_binding(
        binding=listing_binding,
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource={
            "gpu_model": "H200",
            "gpu_count": 1,
            "sla": 99.9,
            "region": "California, US",
            "resource_id": "resource-order-001",
            "virtualization_type": "vm",
        },
        accepted_escrows=[{
            "chain_name": "test",
            "escrow_address": "0x000000000000000000000000000000000000abcd",
            "literal_fields": {
                "token": "0x0000000000000000000000000000000000000001",
            },
            "rates": [{"field": "amount", "per": "hour", "value": "1000"}],
        }],
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url="http://seller:8001",
        seller_principal=_SELLER_PRINCIPAL,
    )
    assert await client.load_listing_binding(listing_id="order-001") == listing_binding
    return client


@pytest.fixture
def marketplace_signer(monkeypatch):
    from market_storefront import container
    from market_storefront.services import capacity_client

    monkeypatch.setattr(
        container,
        "resolved_marketplace_signer",
        _SELLER_SIGNER,
    )
    monkeypatch.setattr(
        capacity_client,
        "get_provisioning_authorities",
        lambda: _PROVISIONING_AUTHORITIES,
    )
    return _SELLER_SIGNER

@pytest.fixture(autouse=True)
def exact_capacity_binding(monkeypatch):
    async def resolve(repository, listing_id):
        binding = await repository.load_listing_binding(listing_id=listing_id)
        assert binding is not None
        return CapacityBinding(
            binding.site_id,
            binding.binding.offering_mode,
            str(binding.pool_id),
        )

    monkeypatch.setattr(
        "market_storefront.negotiation_runtime.capacity_binding_for_listing",
        resolve,
    )


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
            storefront_url="http://seller:8001",
            seller_principal=_SELLER_PRINCIPAL,
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
            storefront_url="http://seller:8001",
            seller_principal=_SELLER_PRINCIPAL,
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
# Shared runtime pause guards
# ---------------------------------------------------------------------------

class TestNegotiationRuntimePauseGuard:
    """Pause checks fire before negotiation policy or persistence."""

    async def test_global_pause_raises(self, db, monkeypatch):
        # Patch is_globally_paused to return True
        import market_storefront.server as server_mod
        monkeypatch.setattr(server_mod, "_GLOBALLY_PAUSED", True)

        with pytest.raises(StorefrontPausedError) as exc_info:
            await _start(sqlite_client=db,
            our_listing_id="order-001", buyer_principal=_BUYER_PRINCIPAL, seller_principal=_SELLER_PRINCIPAL, proposal=EscrowProposal(chain_name="anvil", escrow_address="0x"+"0"*40, fields={"amount": 5000, "token": "0x"+"a"*40}, expiration_unix=2000000000),
            our_base_url="http://seller:8001",
            their_agent_url="0xBuyer",)
        assert exc_info.value.reason == "global"

    async def test_order_pause_raises(self, db, monkeypatch):
        import market_storefront.server as server_mod
        monkeypatch.setattr(server_mod, "_GLOBALLY_PAUSED", False)

        await db.set_listing_paused(listing_id="order-001", paused=True)

        with pytest.raises(StorefrontPausedError) as exc_info:
            await _start(sqlite_client=db,
            our_listing_id="order-001", buyer_principal=_BUYER_PRINCIPAL, seller_principal=_SELLER_PRINCIPAL, proposal=EscrowProposal(chain_name="anvil", escrow_address="0x"+"0"*40, fields={"amount": 5000, "token": "0x"+"a"*40}, expiration_unix=2000000000),
            our_base_url="http://seller:8001",
            their_agent_url="0xBuyer",)
        assert "order-001" in exc_info.value.reason

    async def test_no_pause_proceeds_normally(self, db, monkeypatch):
        """When not paused, the function proceeds to normal validation
        (raises ValueError for missing strategy, not StorefrontPausedError)."""
        import market_storefront.server as server_mod
        monkeypatch.setattr(server_mod, "_GLOBALLY_PAUSED", False)

        # order-001 has no strategy set, so we expect ValueError not paused
        with pytest.raises((ValueError, Exception)) as exc_info:
            await _start(sqlite_client=db,
            our_listing_id="order-001", buyer_principal=_BUYER_PRINCIPAL, seller_principal=_SELLER_PRINCIPAL, proposal=EscrowProposal(chain_name="anvil", escrow_address="0x"+"0"*40, fields={"amount": 5000, "token": "0x"+"a"*40}, expiration_unix=2000000000),
            our_base_url="http://seller:8001",
            their_agent_url="0xBuyer",)
        assert not isinstance(exc_info.value, StorefrontPausedError)

    async def test_pre_negotiation_guard_rejection_raises_offer_unfulfillable(
        self, db, monkeypatch, marketplace_signer
    ):
        """Round-0 guard veto (no matching inventory) raises OfferUnfulfillableError.

        The fixture's listing offers ``gpu_model=H200, region=California, US``;
        the test DB has no portfolio resources at all, so the
        ``has_matching_inventory_guard`` middleware vetoes with
        ``no_matching_inventory``, which maps to 409.
        """
        import market_storefront.server as server_mod
        monkeypatch.setattr(server_mod, "_GLOBALLY_PAUSED", False)

        from market_core.schemas import EscrowProposal, ProvisionTerms
        with pytest.raises(OfferUnfulfillableError) as exc_info:
            await _start(sqlite_client=db,
            our_listing_id="order-001", buyer_principal=_BUYER_PRINCIPAL, seller_principal=_SELLER_PRINCIPAL, proposal=EscrowProposal(chain_name="anvil", escrow_address="0x"+"0"*40, fields={"amount": 5000, "token": "0x"+"a"*40}, expiration_unix=2000000000),
            provision_terms=ProvisionTerms(
                kind="compute.v1",
                version=1,
                payload={
                    "duration_seconds": 1800,
                    "ssh_public_key": "ssh-rsa AAAA",
                },
            ),
            our_base_url="http://seller:8001",
            their_agent_url="0xBuyer",)

        assert exc_info.value.reason == "no_matching_inventory"
        assert exc_info.value.listing_id == "order-001"
