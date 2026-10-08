"""Deployed reservation-boundary proof for pool-declared offering modes."""

from __future__ import annotations

import pytest
from market_site_client import SiteCapacityClientError


pytestmark = pytest.mark.e2e_pool_declared_modes


def test_undeclared_mode_is_refused_before_a_reservation_exists(site_capacity) -> None:
    resources = site_capacity.snapshot()
    if not resources:
        pytest.skip("provisioning site has no capacity resource")

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
