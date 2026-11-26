"""Deployed reservation-boundary proof for pool-declared offering modes."""

from __future__ import annotations

import pytest
from market_site_client import SiteCapacityClientError


pytestmark = [
    # Listed first, so the holds are taken before, and released after, the
    # lane's cleanup. The module reserves nothing; it holds the timers as every
    # VM-lane module does, so no cycle it did not ask for runs while it
    # observes the stack.
    pytest.mark.usefixtures(
        "storefront_loops_held", "alice_loops_held",
        "fulfillment_convergence_held", "lease_watchdog_held",
        "ensure_storefront_resumed", "reap_buyer_settle_subprocess", "release_reserved_resources",
    ),
    pytest.mark.e2e_pool_declared_modes,
]


def test_undeclared_mode_is_refused_before_a_reservation_exists(site_capacity) -> None:
    # The claim asks for one unit, so the resource must have one free: a
    # resource that cannot meet the claim's dimensions is passed over before
    # its pool's modes are read, and the reserve would find nothing rather
    # than refuse the mode.
    resources = [
        resource
        for resource in site_capacity.snapshot()
        if (resource.get("available_units") or 0) >= 1
    ]
    assert resources, "the lane's site offers no resource with a free unit"

    resource = resources[0]
    resource_id = str(resource["resource_id"])
    escrow_uid = f"e2e-undeclared-mode-{resource_id}"
    assert site_capacity.list_reservations(escrow_uid=escrow_uid) == []

    with pytest.raises(SiteCapacityClientError) as exc_info:
        site_capacity.reserve(
            claim={
                "offering_mode": "e2e_unsupported_mode",
                "resource_id": resource_id,
                "units": 1,
            },
            deal_ref={"escrow_uid": escrow_uid},
        )

    assert exc_info.value.status_code == 409
    assert "e2e_unsupported_mode" in str(exc_info.value)
    assert site_capacity.list_reservations(escrow_uid=escrow_uid) == []
