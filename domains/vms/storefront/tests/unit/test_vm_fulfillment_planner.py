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


def test_hosted_fulfillment_plan_does_not_require_alkahest_token_terms():
    plan = build_vm_fulfillment_plan(
        order={
            "listing_id": "listing-hosted",
            "offer_resource": {
                "resource_id": "hosted-resource",
                "gpu_model": "H100",
                "gpu_count": 1,
                "region": "local",
                "sla": 99.9,
            },
            "settlement_options": [
                {"mechanism": "fiat.stripe.v1", "asset": "usd"}
            ],
        },
        duration_seconds=3600,
        settlement_mechanism="fiat.stripe.v1",
    )

    assert plan.order_id == "listing-hosted"
    assert plan.required_attributes["gpu_model"] == "H100"


def test_fulfillment_plan_rejects_unknown_settlement_mechanism():
    with pytest.raises(ValueError, match="Unsupported settlement mechanism"):
        build_vm_fulfillment_plan(
            order={
                "listing_id": "listing-unknown",
                "offer_resource": {
                    "resource_id": "unknown-resource",
                    "gpu_model": "H100",
                    "gpu_count": 1,
                },
            },
            duration_seconds=3600,
            settlement_mechanism="unknown.v1",
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
