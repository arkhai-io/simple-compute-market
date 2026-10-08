"""A lease's window is its first commit's, and the commit carries the deal.

A lease begins at commit: the first commit records the window and a repeat
answers with it unchanged, so a resumed deal never moves its lease. The commit
also carries the deal's escrow, which a hold placed at negotiation lacks. These
commit through the real capacity runtime and aggregate client against the fake
site, whose commit is write-once as the site's is: the window and the escrow
reach the site, and the answer the storefront, only if every layer passes them
through.
"""

from __future__ import annotations

import pytest
from market_capacity_publication import CapacityBinding

from market_storefront.services.fulfillment_resume_runtime import (
    _commit_recovered_reservation,
)
from tests.fake_site import FakeSite, capacity_runtime_over

_POOL = "pool-window"
_START = "2099-01-01T00:00:00+00:00"
_END = "2099-01-01 01:00"


async def _committed(capacity, fake) -> str:
    binding = CapacityBinding("default", "vm", _POOL)
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


@pytest.mark.asyncio
async def test_a_resumed_deal_never_moves_its_lease():
    """The resume pass commits before beginning a recovered deal's
    fulfillment, computing a window from the current time when the deal
    records no start; a reservation committed earlier keeps its first window."""
    fake = FakeSite(deliverable_modes={"vm"})
    fake.add_resource(_POOL, 2, attributes={"vm_host": "kvm1"})
    capacity = capacity_runtime_over(fake)
    reservation_id = await _committed(capacity, fake)

    await _commit_recovered_reservation(
        escrow_uid="0xwindow",
        reservation_id=reservation_id,
        context={"duration_seconds": 3600},
        capacity_client=capacity.client(),
        site_id="default",
    )

    recorded = fake.reservations[reservation_id]
    assert (recorded["lease_start_utc"], recorded["lease_end_utc"]) == (_START, _END)
