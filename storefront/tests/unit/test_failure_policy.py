from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from market_storefront.utils.failure_policy import (
    FulfillmentFailureContext,
    apply_fulfillment_failure_policy,
)
from market_storefront.utils.sqlite_client import SQLiteClient


@pytest.mark.asyncio
async def test_failure_policy_releases_capacity_and_runs_webhook(tmp_path, monkeypatch):
    db = SQLiteClient(db_path=str(tmp_path / "failure-policy.db"))
    await db.upsert_resource(
        resource_id="gpu-host-1",
        resource_type="compute.gpu",
        resource_subtype="h200",
        unit="count",
        value=2,
        state="available",
        attributes={"gpu_model": "H200", "region": "California, US", "vm_host": "kvm1"},
    )
    reserved = await db.reserve_available_compute_vm(
        required_attributes={"resource_id": "gpu-host-1", "gpu_count": 1},
        listing_id="listing-1x",
        escrow_uid="escrow-1",
    )
    assert reserved is not None

    async def fake_webhook(payload):
        assert payload["allocation_id"] == reserved["allocation_id"]
        assert payload["reason"] == "provisioning_error"
        assert payload["state"] == "released"
        return {"action": "webhook", "status": "sent", "status_code": 204}

    monkeypatch.setattr(
        "market_storefront.utils.failure_policy.configured_failure_actions",
        lambda: ["release_capacity", "webhook"],
    )
    webhook = AsyncMock(side_effect=fake_webhook)
    monkeypatch.setattr("market_storefront.utils.failure_policy._send_webhook", webhook)

    result = await apply_fulfillment_failure_policy(
        db,
        FulfillmentFailureContext(
            allocation_id=reserved["allocation_id"],
            escrow_uid="escrow-1",
            reason="provisioning_error",
            message="host rejected request",
            source="test",
        ),
    )

    assert result.state == "released"
    assert result.resource_id == "gpu-host-1"
    assert result.actions == [
        {"action": "release_capacity", "status": "ok"},
        {"action": "webhook", "status": "sent", "status_code": 204},
    ]
    webhook.assert_awaited_once()

    allocation = await db.update_compute_allocation_state(
        allocation_id=reserved["allocation_id"],
        state="released",
    )
    assert allocation is not None
    assert allocation["state"] == "released"
