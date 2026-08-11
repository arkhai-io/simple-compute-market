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
from market_storefront.utils.sqlite_client import SQLiteClient
from tests.fake_site import FakeSite, site_capacity


@pytest.fixture
def db(tmp_path):
    return SQLiteClient(db_path=str(tmp_path / "abandon-test.db"))


@pytest.mark.asyncio
async def test_truncates_the_ledger_lease_to_now(db):
    fake = FakeSite()
    fake.add_resource("res-trunc", 2, attributes={"vm_host": "kvm1"})

    with site_capacity(fake) as capacity:
        reserved = await capacity.reserve(
            claim={},
            deal_ref={"escrow_uid": "0xabandoned"},
        )
        await capacity.commit(
            resource_id=reserved["resource_id"],
            capacity_reservation_id=reserved["capacity_reservation_id"],
            lease_start_utc="2099-01-01T00:00:00Z",
            lease_end_utc="2099-01-01 01:00",
        )
        truncated = await truncate_lease_for_terminal_settlement(
            sqlite_client=db,
            escrow_uid="0xabandoned",
            reason="expiration window passed",
        )

    assert truncated is not None
    row = fake.reservations[reserved["capacity_reservation_id"]]
    assert row["state"] == "leased"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert str(row["lease_end_utc"]).startswith(today)


@pytest.mark.asyncio
async def test_no_live_reservation_is_a_quiet_noop(db):
    with site_capacity(FakeSite()):
        assert (
            await truncate_lease_for_terminal_settlement(
                sqlite_client=db,
                escrow_uid="0xunknown",
            )
            is None
        )
