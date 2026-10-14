from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from market_storefront.services.vm_fulfillment_planner import (
    build_vm_fulfillment_plan,
)
from market_storefront.settlement_stages import delivery_facts, vm_evidence
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


def test_refund_states_keep_the_verified_facts_for_a_started_delivery():
    for status in ("refunding", "refunded"):
        plan = build_vm_fulfillment_plan(
            evidence=replace(vm_delivery_evidence(), status=status)
        )
        assert plan.order_id == "listing-1"


def test_payment_fulfillment_plan_does_not_require_alkahest_token_terms():
    agreement = {
        "negotiation_id": "neg-payment",
        "listing_id": "listing-payment",
        "duration_seconds": 3600,
        "start_utc": "2026-01-01T00:00:00Z",
        "provision_terms": {
            "kind": "compute.v1",
            "version": 1,
            "payload": {"ssh_public_key": "ssh-ed25519 test", "duration_seconds": 3600},
        },
    }
    order = {
        "listing_id": "listing-payment",
        "listing_resource": {
            "resource_id": "payment-resource",
            "gpu_model": "H100",
            "gpu_count": 1,
            "region": "local",
            "sla": 99.9,
        },
        "settlement_options": [{"mechanism": "arkhai.payments.v1", "asset": "USD/2"}],
    }
    plan = build_vm_fulfillment_plan(
        evidence=vm_evidence(
            raw=json.dumps(agreement).encode(),
            mechanism="arkhai.payments.v1",
            reference="a" * 64,
            source={"mandate": {}},
            facts=delivery_facts(agreement, order),
        )
    )

    assert plan.order_id == "listing-payment"
    assert plan.required_attributes["gpu_model"] == "H100"
    assert plan.order_bytes == b""


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
