"""A commit carries the lease's window and the deal to the site.

The commit goes through the real capacity runtime and aggregate client against
the fake site: the window and the escrow reach the site, and the answer the
storefront, only if every layer passes them through.
"""

from __future__ import annotations

import pytest
from market_capacity_publication import PublicationBinding
from market_resource_pools_contracts.backing import BACKED

from tests.fake_site import FakeSite, capacity_runtime_over

_POOL = "pool-window"
_START = "2099-01-01T00:00:00+00:00"
_END = "2099-01-01 01:00"


async def _committed(capacity, fake) -> str:
    binding = PublicationBinding("default", "vm", _POOL, BACKED)
    reserved = await capacity.reserve(binding, claim={"offering_mode": "vm"})
    assert reserved is not None
    reservation_id = str(reserved["capacity_reservation_id"])
    committed = await capacity.commit(
        binding,
        resource_id=None,
        capacity_reservation_id=reservation_id,
        lease_start_utc=_START,
        lease_end_utc=_END,
        deal_ref={"escrow_uid": "0xwindow"},
    )
    assert (committed["lease_start_utc"], committed["lease_end_utc"]) == (_START, _END)
    return reservation_id


@pytest.mark.asyncio
async def test_a_commit_through_the_capacity_runtime_records_the_window_and_escrow():
    fake = FakeSite(deliverable_modes={"vm"})
    fake.add_resource(_POOL, 2, attributes={"vm_host": "kvm1"})

    reservation_id = await _committed(capacity_runtime_over(fake), fake)

    assert fake.reservations[reservation_id]["escrow_uid"] == "0xwindow"
