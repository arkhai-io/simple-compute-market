"""Opaque reservation boundary over the authenticated capacity client."""

from __future__ import annotations

import pytest
from market_identity import Ed25519Signer, TrustedIdentitySet

from fake_site import FakeSite
from market_site_client import SiteCapacityClient


@pytest.mark.asyncio
async def test_reserve_commit_send_no_placement_fields() -> None:
    caller = Ed25519Signer(b"\x66" * 32)
    authority = Ed25519Signer(b"\x77" * 32)
    site = FakeSite(
        caller=caller,
        authority=authority,
        deliverable_modes={"vm"},
    )
    site.add_resource("host-private", 4, attributes={"vm_host": "kvm-private"})
    capacity = SiteCapacityClient(
        "http://capacity.test",
        caller,
        TrustedIdentitySet(identities=(authority.identity,)),
        transport=site.transport(),
    )

    reservation = await capacity.reserve(
        claim={
            "executor_kind": "vm",
            "pool_id": "host-private",
            "gpu_count": 1,
        },
        request_id="opaque-reserve",
    )
    assert reservation is not None
    assert "resource_id" not in reservation
    assert "vm_host" not in reservation

    await capacity.commit(
        capacity_reservation_id=reservation["capacity_reservation_id"],
        idempotency_ref="agreement-mock-boundary",
        request_id="opaque-commit",
    )

    reserve_request, commit_request = site.seen_requests
    assert "resource_id" not in reserve_request["body"]
    assert "resource_id" not in commit_request["body"]
