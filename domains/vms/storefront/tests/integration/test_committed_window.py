"""The window a lease is registered with is the one the site recorded.

A registered lease keeps its window, and a registration naming another start is
refused, so the storefront registers the window its commit answers with, never
one it computed. These commit through the real capacity runtime and aggregate
client against the fake site, whose commit keeps a registered lease's window as
the site does: the window reaches the storefront only if every layer passes the
site's answer through.
"""

from __future__ import annotations

import pytest
from market_capacity_publication import CapacityBinding

from market_storefront.services.fulfillment_resume_runtime import _refresh_capacity_lease
from market_storefront.services.vm_fulfillment_service import committed_lease_window
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
    )
    assert committed_lease_window(committed) == (_START, _END)
    return reservation_id


@pytest.mark.asyncio
async def test_a_commit_through_the_capacity_runtime_answers_with_the_recorded_window():
    fake = FakeSite(deliverable_modes={"vm"})
    fake.add_resource(_POOL, 2, attributes={"vm_host": "kvm1"})

    await _committed(capacity_runtime_over(fake), fake)


@pytest.mark.asyncio
async def test_a_resume_pass_registers_the_recorded_window_not_its_own():
    """After registration the site keeps the lease's window, so the resume
    pass, which recomputes a window from the current time when the deal records
    no start, still registers the window the site holds."""
    fake = FakeSite(deliverable_modes={"vm"})
    fake.add_resource(_POOL, 2, attributes={"vm_host": "kvm1"})
    capacity = capacity_runtime_over(fake)
    reservation_id = await _committed(capacity, fake)
    fake.registered.add(reservation_id)

    window = await _refresh_capacity_lease(
        escrow_uid="0xwindow",
        reservation_id=reservation_id,
        resource_id="resource-window",
        lease_start_utc="2099-03-01T00:00:00+00:00",
        lease_end_utc="2099-03-01 01:00",
        capacity_client=capacity.client(),
        site_id="default",
    )

    assert window == (_START, _END)
