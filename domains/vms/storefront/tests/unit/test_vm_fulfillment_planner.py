from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from market_storefront.services.vm_fulfillment_planner import (
    build_vm_fulfillment_plan,
)
from market_storefront.services.vm_job_spec_service import (
    build_provisioning_job_spec,
)
from tests.fulfillment_fixtures import vm_delivery_evidence


@pytest.mark.parametrize("order", [None, "", "not-json", {}, "{}"])
def test_fulfillment_plan_rejects_missing_or_malformed_order(order):
    with pytest.raises(ValueError, match="valid, non-empty settlement order"):
        build_vm_fulfillment_plan(
            evidence=vm_delivery_evidence(order=order if order is not None else {})
        )


def test_fulfillment_plan_rejects_unverified_evidence():
    with pytest.raises(ValueError, match="verified settlement evidence"):
        build_vm_fulfillment_plan(
            evidence=replace(vm_delivery_evidence(), status="pending")
        )


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
