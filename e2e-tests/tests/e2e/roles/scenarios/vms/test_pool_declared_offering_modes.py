"""Deployed reservation-boundary proof for pool-declared offering modes."""

from __future__ import annotations

import pytest

from vm_provisioning_operator import ProvisioningError


pytestmark = pytest.mark.e2e_pool_declared_modes


def test_undeclared_mode_is_refused_before_a_reservation_exists(
    provisioning_client,
) -> None:
    snapshot = provisioning_client._get("/api/v1/capacity/snapshot")
    resources = snapshot.get("resources") or []
    if not resources:
        pytest.skip("provisioning site has no capacity resource")

    resource = resources[0]
    resource_id = str(resource["resource_id"])
    escrow_uid = f"e2e-undeclared-mode-{resource_id}"
    before = provisioning_client.list_capacity_reservations(escrow_uid=escrow_uid)
    assert before.get("reservations") == []

    with pytest.raises(ProvisioningError) as exc_info:
        provisioning_client._post(
            "/api/v1/capacity/reservations",
            {
                "claim": {
                    "executor_kind": "e2e_unsupported_mode",
                    "resource_id": resource_id,
                    "units": 1,
                },
                "deal_ref": {"escrow_uid": escrow_uid},
            },
        )

    assert exc_info.value.status_code == 409
    assert "e2e_unsupported_mode" in str(exc_info.value)
    after = provisioning_client.list_capacity_reservations(escrow_uid=escrow_uid)
    assert after.get("reservations") == []
