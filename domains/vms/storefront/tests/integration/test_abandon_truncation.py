"""Abandoned claims end leases: settlement's "deal is over" → capacity.

The single coupling joint between the design doc's two parts: the
settlement lifecycle decides the deal is over, the capacity layer must
learn it to release the reservation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from core_storefront.domain_registry import StorefrontThreadBinding
from core_storefront.site_projections import (
    ProjectionCache,
    ProjectionIdentity,
    ProjectionState,
)
from market_identity import create_signer
from market_capacity_publication import CapacityBinding

from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.publication_binding import prepare_vm_listing_binding
from market_storefront.services import site_projection_cache
from market_storefront.services.capacity_client import capacity_binding_for_listing
from market_storefront.settlement_composition import (
    truncate_lease_for_terminal_settlement,
)
from market_storefront.utils.sqlite_client import SQLiteClient
from tests.fake_site import (
    FakeSite,
    TEST_MARKETPLACE_SIGNER,
    capacity_runtime_over,
)

_BUYER_SIGNER = create_signer("ed25519", b"\x43" * 32)

def _pool_projection_caches(pool_id: str) -> site_projection_cache.SiteProjectionCaches:
    resource_pools = ProjectionCache(client=None)
    resource_pools._value = [
        {
            "resource_pool_id": pool_id,
            "pool_metadata": {
                "policy_tags": {"deliverable_modes": ["vm"]},
            },
            "resources": [],
        }
    ]
    resource_pools._state = ProjectionState.loaded
    resource_pools._identity = ProjectionIdentity(
        revision=1,
        digest=f"vm-pool:{pool_id}",
    )
    return site_projection_cache.SiteProjectionCaches(
        resource_pools=resource_pools,
        capacity_buckets=ProjectionCache(client=None),
    )


async def _persist_terminal_negotiation(
    db: SQLiteClient,
    *,
    agreement_ref: str,
    listing_id: str,
    pool_id: str,
) -> CapacityBinding:
    now = datetime.now(timezone.utc).isoformat()
    listing_binding = prepare_vm_listing_binding(
        listing_id=listing_id,
        candidate={
            "site_id": "default",
            "pool_id": pool_id,
            "gpu_count": 1,
        },
    )
    await db.upsert_listing_with_binding(
        binding=listing_binding,
        status="closed",
        created_at=now,
        updated_at=now,
        offer_resource={
            "resource_id": pool_id,
            "gpu_model": "H200",
            "gpu_count": 1,
            "sla": 99.9,
            "region": "California, US",
            "virtualization_type": "vm",
        },
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
        max_duration_seconds=3600,
        storefront_url="http://seller:8001",
        seller_principal=TEST_MARKETPLACE_SIGNER.identity,
    )
    await db.create_negotiation_thread(
        negotiation_id=agreement_ref,
        our_listing_id=listing_id,
        their_listing_id=f"demand-{agreement_ref}",
        our_agent_id="http://seller:8001",
        their_agent_id="http://buyer:8000",
        buyer_principal=_BUYER_SIGNER.identity,
        seller_principal=TEST_MARKETPLACE_SIGNER.identity,
        owner_id="seller",
        status="active",
        our_initial_price="9000",
        our_strategy="fixed",
        requested_duration_seconds=3600,
        binding=StorefrontThreadBinding(
            negotiation_id=agreement_ref,
            listing_id=listing_binding.listing_id,
            site_id=listing_binding.site_id,
            binding=listing_binding.binding,
        ),
    )
    await db.update_negotiation_thread_terminal(
        negotiation_id=agreement_ref,
        terminal_state="abandoned",
    )
    return await capacity_binding_for_listing(db, listing_id)


async def _persist_reservation_identity(
    db: SQLiteClient,
    *,
    agreement_ref: str,
    escrow_uid: str,
    capacity_reservation_id: str,
) -> None:
    await db.insert_escrow(
        escrow_uid=escrow_uid,
        negotiation_id=agreement_ref,
        chain_name=None,
        escrow_address=None,
    )
    await db.update_escrow(
        escrow_uid=escrow_uid,
        capacity_reservation_id=capacity_reservation_id,
    )


@pytest.fixture
def db(tmp_path):
    return SQLiteClient(db_path=str(tmp_path / "abandon-test.db"), registry=build_vm_storefront_registry(build_vm_storefront_domain()))


@pytest.mark.asyncio
async def test_truncates_the_ledger_lease_to_now(db):
    pool_id = "res-trunc"
    listing_id = "listing-abandoned"
    fake = FakeSite(deliverable_modes={"vm"})
    fake.add_resource(pool_id, 2, attributes={"vm_host": "kvm1"})
    capacity = capacity_runtime_over(fake)
    agreement_ref = "negotiation-abandoned"
    escrow_uid = "0xabandoned"

    with (
        patch.dict(
            site_projection_cache._caches,
            {"default": _pool_projection_caches(pool_id)},
            clear=True,
        ),
        patch(
            "market_storefront.settlement_composition.build_capacity_runtime",
            return_value=capacity,
        ),
    ):
        binding = await _persist_terminal_negotiation(
            db,
            agreement_ref=agreement_ref,
            listing_id=listing_id,
            pool_id=pool_id,
        )
        reserved = await capacity.reserve(
            binding,
            claim={"executor_kind": "vm"},
            deal_ref={
                "listing_id": listing_id,
                "negotiation_id": agreement_ref,
            },
        )
        assert reserved is not None
        reservation_id = str(reserved["capacity_reservation_id"])
        await capacity.commit(
            binding,
            resource_id=None,
            capacity_reservation_id=reservation_id,
            lease_start_utc="2099-01-01T00:00:00Z",
            lease_end_utc="2099-01-01 01:00",
        )
        await _persist_reservation_identity(
            db,
            agreement_ref=agreement_ref,
            escrow_uid=escrow_uid,
            capacity_reservation_id=reservation_id,
        )
        truncated = await truncate_lease_for_terminal_settlement(
            sqlite_client=db,
            agreement_ref=agreement_ref,
            reason="expiration window passed",
        )

    assert truncated is not None
    row = fake.reservations[reservation_id]
    assert row["state"] == "leased"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert str(row["lease_end_utc"]).startswith(today)


@pytest.mark.asyncio
async def test_no_live_reservation_is_a_quiet_noop(db):
    pool_id = "pool-missing"
    fake = FakeSite(deliverable_modes={"vm"})
    capacity = capacity_runtime_over(fake)
    agreement_ref = "negotiation-with-missing-reservation"

    with (
        patch.dict(
            site_projection_cache._caches,
            {"default": _pool_projection_caches(pool_id)},
            clear=True,
        ),
        patch(
            "market_storefront.settlement_composition.build_capacity_runtime",
            return_value=capacity,
        ),
    ):
        await _persist_terminal_negotiation(
            db,
            agreement_ref=agreement_ref,
            listing_id="listing-with-missing-reservation",
            pool_id=pool_id,
        )
        await _persist_reservation_identity(
            db,
            agreement_ref=agreement_ref,
            escrow_uid="0xmissing",
            capacity_reservation_id="alloc-missing",
        )
        assert (
            await truncate_lease_for_terminal_settlement(
                sqlite_client=db,
                agreement_ref=agreement_ref,
            )
            is None
        )
