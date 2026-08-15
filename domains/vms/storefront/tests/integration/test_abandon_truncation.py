"""Abandoned claims end leases: settlement's "deal is over" → capacity.

The single coupling joint between the design doc's two parts: the
settlement lifecycle decides the deal is over, the capacity layer must
learn it to release the reservation.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from market_storefront.settlement_composition import (
    truncate_lease_for_terminal_settlement,
)
from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.utils.sqlite_client import SQLiteClient
from tests.fake_site import FakeSite, site_capacity


@pytest.fixture
def db(tmp_path):
    return SQLiteClient(db_path=str(tmp_path / "abandon-test.db"), registry=build_vm_storefront_registry(build_vm_storefront_domain()))


@pytest.mark.asyncio
async def test_truncates_the_ledger_lease_to_now(db):
    fake = FakeSite(deliverable_modes={"vm"})
    fake.add_resource("res-trunc", 2, attributes={"vm_host": "kvm1"})
    agreement_ref = "negotiation-abandoned"
    escrow_uid = "0xabandoned"
    await db.insert_escrow(
        escrow_uid=escrow_uid,
        negotiation_id=agreement_ref,
        chain_name=None,
        escrow_address=None,
    )

    with site_capacity(fake) as capacity:
        reserved = await capacity.reserve(
            claim={"executor_kind": "vm"},
            deal_ref={
                "listing_id": "listing-abandoned",
                "negotiation_id": agreement_ref,
            },
        )
        await capacity.commit(
            capacity_reservation_id=reserved["capacity_reservation_id"],
            lease_start_utc="2099-01-01T00:00:00Z",
            lease_end_utc="2099-01-01 01:00",
        )
        await db.update_escrow(
            escrow_uid=escrow_uid,
            capacity_reservation_id=reserved["capacity_reservation_id"],
        )
        truncated = await truncate_lease_for_terminal_settlement(
            sqlite_client=db,
            agreement_ref=agreement_ref,
            reason="expiration window passed",
        )

    assert truncated is not None
    row = fake.reservations[reserved["capacity_reservation_id"]]
    assert row["state"] == "leased"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert str(row["lease_end_utc"]).startswith(today)


@pytest.mark.asyncio
async def test_no_live_reservation_is_a_quiet_noop(db):
    agreement_ref = "negotiation-with-missing-reservation"
    escrow_uid = "0xmissing"
    await db.insert_escrow(
        escrow_uid=escrow_uid,
        negotiation_id=agreement_ref,
        chain_name=None,
        escrow_address=None,
    )
    await db.update_escrow(
        escrow_uid=escrow_uid,
        capacity_reservation_id="alloc-missing",
    )
    with site_capacity(FakeSite(deliverable_modes={"vm"})):
        assert (
            await truncate_lease_for_terminal_settlement(
                sqlite_client=db,
                agreement_ref=agreement_ref,
            )
            is None
        )
