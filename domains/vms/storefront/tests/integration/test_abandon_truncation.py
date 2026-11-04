"""Abandoned claims end leases: settlement's "deal is over" → capacity.

The single coupling joint between the design doc's two parts: the
settlement lifecycle decides the deal is over, the capacity layer must
learn it to release the reservation.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from market_capacity_publication import PublicationBinding
from market_deal_servicing.journal import stable_ref

from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.settlement_composition import (
    truncate_lease_for_terminal_settlement,
)
from market_storefront.utils.sqlite_client import SQLiteClient
from tests.fake_site import FakeSite, capacity_runtime_over
from tests.fulfillment_fixtures import make_vm_lifecycle_fixture


async def _persist_terminal_negotiation(
    db: SQLiteClient,
    *,
    agreement_ref: str,
    listing_id: str,
    pool_id: str,
) -> PublicationBinding:
    fixture = await make_vm_lifecycle_fixture(
        Path(db.db_path), escrow_uid="settlement:" + agreement_ref,
        negotiation_id=agreement_ref, listing_id=listing_id, pool_id=pool_id, site_id="default",
    )
    await db.update_negotiation_thread_terminal(negotiation_id=agreement_ref, terminal_state="abandoned")
    return fixture.capacity_binding


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


async def _terminal_reservation(db, fake, *, pool_id: str, commit: bool) -> str:
    """A terminal agreement with a bound reservation, committed or still a hold."""
    capacity = capacity_runtime_over(fake)
    agreement_ref = f"negotiation-{pool_id}"
    binding = await _persist_terminal_negotiation(
        db,
        agreement_ref=agreement_ref,
        listing_id=f"listing-{pool_id}",
        pool_id=pool_id,
    )
    reserved = await capacity.reserve(
        binding,
        claim={"offering_mode": "vm"},
        deal_ref={"listing_id": f"listing-{pool_id}", "negotiation_id": agreement_ref},
    )
    assert reserved is not None
    reservation_id = str(reserved["capacity_reservation_id"])
    if commit:
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
        escrow_uid=f"0x{pool_id}",
        capacity_reservation_id=reservation_id,
    )
    return reservation_id


@pytest.mark.asyncio
async def test_an_uncommitted_hold_is_released_not_truncated(db):
    pool_id = "res-hold"
    fake = FakeSite(deliverable_modes={"vm"})
    fake.add_resource(pool_id, 2, attributes={"vm_host": "kvm1"})

    with (
        patch(
            "market_storefront.delivery_lifecycle.build_capacity_runtime",
            return_value=capacity_runtime_over(fake),
        ),
    ):
        reservation_id = await _terminal_reservation(db, fake, pool_id=pool_id, commit=False)
        released = await truncate_lease_for_terminal_settlement(
            sqlite_client=db,
            agreement_ref=f"negotiation-{pool_id}",
            reason="expiration window passed",
        )

    assert released is not None
    row = fake.reservations[reservation_id]
    assert (row["state"], row["failure_reason"]) == (
        "released", stable_ref(f"negotiation-{pool_id}", "terminate", "terminate"),
    )
    assert not any(path.endswith("/truncate-lease") for _, path in fake.requests)


@pytest.mark.asyncio
async def test_truncates_the_ledger_lease_to_now(db):
    """A delivered lease is terminated immediately; truncation is not teardown."""
    pool_id = "res-trunc"
    listing_id = "listing-abandoned"
    fake = FakeSite(deliverable_modes={"vm"})
    fake.add_resource(pool_id, 2, attributes={"vm_host": "kvm1"})
    capacity = capacity_runtime_over(fake)
    remote = SimpleNamespace(terminate_lease=AsyncMock())
    agreement_ref = "negotiation-abandoned"
    escrow_uid = "0xabandoned"

    with (
        patch(
            "market_storefront.delivery_lifecycle.build_capacity_runtime",
            return_value=capacity,
        ),
        patch("market_storefront.delivery_lifecycle.build_fulfillment_client", return_value=remote),
    ):
        binding = await _persist_terminal_negotiation(
            db,
            agreement_ref=agreement_ref,
            listing_id=listing_id,
            pool_id=pool_id,
        )
        reserved = await capacity.reserve(
            binding,
            claim={"offering_mode": "vm"},
            deal_ref={
                "listing_id": listing_id,
                "negotiation_id": agreement_ref,
            },
        )
        assert reserved is not None
        reservation_id = str(reserved["capacity_reservation_id"])
        fake.delivered.add(reservation_id)
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
    assert truncated["progress"] == "tearing_down"
    remote.terminate_lease.assert_awaited_once()
    assert not any(path.endswith("/truncate-lease") for _, path in fake.requests)


@pytest.mark.asyncio
async def test_no_live_reservation_is_a_quiet_noop(db):
    pool_id = "pool-missing"
    fake = FakeSite(deliverable_modes={"vm"})
    capacity = capacity_runtime_over(fake)
    agreement_ref = "negotiation-with-missing-reservation"

    with (
        patch(
            "market_storefront.delivery_lifecycle.build_capacity_runtime",
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
            == {"progress": "released", "done": True}
        )
