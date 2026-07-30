from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from market_storefront.services.vm_fulfillment_planner import (
    build_vm_fulfillment_plan,
)
from market_storefront.services.vm_job_spec_service import (
    build_provisioning_job_spec,
)


@pytest.mark.parametrize("order", [None, "", "not-json", {}, "{}"] )
def test_fulfillment_plan_rejects_missing_or_malformed_order(order):
    with pytest.raises(ValueError, match="valid, non-empty settlement order"):
        build_vm_fulfillment_plan(order=order, duration_seconds=3600)


@pytest.mark.asyncio
async def test_missing_order_fails_before_capacity_probe():
    capacity = AsyncMock()

    with pytest.raises(ValueError, match="without a settlement order"):
        await build_provisioning_job_spec(
            order_dict=None,  # type: ignore[arg-type]
            ssh_public_key="ssh-ed25519 test",
            duration_seconds=3600,
            capacity=capacity,
        )

    capacity.probe.assert_not_awaited()
