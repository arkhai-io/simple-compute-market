"""Unit tests for executor-neutral fulfillment contracts.

Replaces ``provisioning/compute/tests/unit/test_physical_settlement.py``
(tombstoned): that file predated pass-1 multidimensional capacity and
asserted a ``units``/``available_units`` shape these models no longer
have, and it exercised ``agreement_id``/``CapacitySettlementAssignment``,
both removed from the moved contracts (tasks.md 1.5; settlement_types.py
module docstring).
"""

from decimal import Decimal

import pytest

from market_fulfillment import (
    PhysicalSettlementRequest,
    SettlementCandidate,
    SettlementRequirement,
    SettlementResource,
)


def test_request_carries_capacity_reservation_id_not_allocation_or_agreement():
    request = PhysicalSettlementRequest(
        capacity_reservation_id="reservation-1",
        market="vms",
        resource_id="node-7",
    )
    assert request.capacity_reservation_id == "reservation-1"
    assert request.resource_id == "node-7"
    assert request.requirements == {}
    assert not hasattr(request, "allocation_id")
    assert not hasattr(request, "agreement_id")


def test_generic_requirement_and_candidate_are_market_neutral():
    requirement = SettlementRequirement(
        resource_kind="bare-metal-node",
        dimensions={"units": Decimal(1)},
        attributes={"architecture": "amd64"},
    )
    candidate = SettlementCandidate(
        resource_id="node-7",
        pool_id="pool-a",
        resource_kind="bare-metal-node",
        available={"units": Decimal(1)},
        provider="redfish",
        attributes={"architecture": "amd64"},
    )
    assert candidate.resource_kind == requirement.resource_kind


def test_settlement_resource_identifies_the_selected_physical_resource():
    resource = SettlementResource(
        settlement_resource_id="node-7",
        pool_id="pool-a",
        resource_kind="bare-metal-node",
        provider="redfish",
    )
    assert resource.settlement_resource_id == "node-7"
    assert resource.pool_id == "pool-a"


def test_dimensions_must_be_nonempty():
    with pytest.raises(ValueError):
        SettlementRequirement(resource_kind="compute.gpu", dimensions={})


def test_dimensions_must_be_positive():
    with pytest.raises(ValueError):
        SettlementRequirement(
            resource_kind="compute.gpu", dimensions={"gpu_count": Decimal(0)}
        )
