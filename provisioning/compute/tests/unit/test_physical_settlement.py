"""Unit tests for PhysicalSettlementRequest/SettlementResource shapes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from compute_provisioning import PhysicalSettlementRequest, SettlementResource


def test_minimal_request_defaults_to_any_eligible_pool():
    request = PhysicalSettlementRequest(
        allocation_id="alloc-1", agreement_id="agree-1", market="vms",
    )
    assert request.pool_id is None
    assert request.resource_id is None
    assert request.terms == {}


def test_request_accepts_pool_id_alone():
    request = PhysicalSettlementRequest(
        allocation_id="alloc-1", agreement_id="agree-1", market="vms",
        pool_id="hetzner-eu",
    )
    assert request.pool_id == "hetzner-eu"


def test_request_accepts_resource_id_alone():
    request = PhysicalSettlementRequest(
        allocation_id="alloc-1", agreement_id="agree-1", market="vms",
        resource_id="kvm1",
    )
    assert request.resource_id == "kvm1"


def test_pool_id_and_resource_id_are_mutually_exclusive():
    with pytest.raises(ValidationError, match="mutually exclusive"):
        PhysicalSettlementRequest(
            allocation_id="alloc-1", agreement_id="agree-1", market="vms",
            pool_id="hetzner-eu", resource_id="kvm1",
        )


def test_settlement_resource_defaults_empty_attributes():
    resource = SettlementResource(
        settlement_resource_id="kvm1",
        pool_id="default",
        resource_kind="compute.gpu",
        provider="ansible",
    )
    assert resource.attributes == {}
