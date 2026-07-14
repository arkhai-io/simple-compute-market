"""Unit tests for executor-neutral physical-settlement contracts."""

from compute_provisioning import (
    CapacitySettlementAssignment,
    PhysicalSettlementRequest,
    SettlementCandidate,
    SettlementRequirement,
    SettlementResource,
)


def test_request_keeps_optional_explicit_resource_constraint():
    request = PhysicalSettlementRequest(
        allocation_id="alloc-1",
        agreement_id="agree-1",
        market="vms",
        resource_id="node-7",
    )
    assert request.resource_id == "node-7"
    assert request.terms == {}


def test_generic_requirement_and_candidate_are_market_neutral():
    requirement = SettlementRequirement(
        resource_kind="bare-metal-node",
        units=1,
        attributes={"architecture": "amd64"},
    )
    candidate = SettlementCandidate(
        resource_id="node-7",
        pool_id="pool-a",
        resource_kind="bare-metal-node",
        available_units=1,
        provider="redfish",
        attributes={"architecture": "amd64"},
    )
    assert candidate.resource_kind == requirement.resource_kind


def test_capacity_settlement_assignment_wraps_selected_resource():
    resource = SettlementResource(
        settlement_resource_id="node-7",
        pool_id="pool-a",
        resource_kind="bare-metal-node",
        provider="redfish",
    )
    assignment = CapacitySettlementAssignment(
        allocation_id="alloc-1",
        agreement_id="agree-1",
        resource=resource,
    )
    assert assignment.resource == resource
