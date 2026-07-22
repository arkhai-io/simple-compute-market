"""Unit tests for the shared reservation/scheduling feasibility predicate.

resource_satisfies_requirement is the single implementation of "does this
shape fit this resource" used by both reservation-time admission
(CapacityLedgerService._find_candidate, exercised indirectly through
test_ledger.py's reserve()/probe() tests) and scheduling-time eligibility
(market_fulfillment's scheduler, exercised in its own test suite). This
file tests the predicate directly, at the lowest level that can prove its
behavior, rather than only indirectly through either caller.
"""

from decimal import Decimal

from market_site import resource_satisfies_requirement


def test_matching_kind_and_sufficient_dimensions_is_satisfied():
    assert resource_satisfies_requirement(
        resource_kind="compute.gpu",
        available={"gpu_count": Decimal(4)},
        attributes={},
        required_resource_kind="compute.gpu",
        required_dimensions={"gpu_count": Decimal(2)},
    )


def test_mismatched_resource_kind_is_not_satisfied():
    assert not resource_satisfies_requirement(
        resource_kind="compute.gpu",
        available={"gpu_count": Decimal(4)},
        attributes={},
        required_resource_kind="bare-metal-node",
        required_dimensions={"gpu_count": Decimal(2)},
    )


def test_none_required_resource_kind_accepts_any_kind():
    """Reservation-time admission's claim may omit a resource-kind
    constraint entirely; scheduling always supplies one."""
    assert resource_satisfies_requirement(
        resource_kind="compute.gpu",
        available={"gpu_count": Decimal(4)},
        attributes={},
        required_resource_kind=None,
        required_dimensions={"gpu_count": Decimal(2)},
    )


def test_insufficient_dimension_is_not_satisfied():
    assert not resource_satisfies_requirement(
        resource_kind="compute.gpu",
        available={"gpu_count": Decimal(1)},
        attributes={},
        required_resource_kind="compute.gpu",
        required_dimensions={"gpu_count": Decimal(2)},
    )


def test_dimension_absent_from_available_is_treated_as_zero():
    assert not resource_satisfies_requirement(
        resource_kind="compute.gpu",
        available={"gpu_count": Decimal(8)},
        attributes={},
        required_resource_kind="compute.gpu",
        required_dimensions={"ram_gb": Decimal(1)},
    )


def test_passing_one_dimension_does_not_compensate_for_another():
    assert not resource_satisfies_requirement(
        resource_kind="compute.gpu",
        available={"gpu_count": Decimal(8), "ram_gb": Decimal(16)},
        attributes={},
        required_resource_kind="compute.gpu",
        required_dimensions={"gpu_count": Decimal(1), "ram_gb": Decimal(64)},
    )


def test_matching_required_attributes_is_satisfied():
    assert resource_satisfies_requirement(
        resource_kind="compute.gpu",
        available={"gpu_count": Decimal(1)},
        attributes={"region": "us-east"},
        required_resource_kind="compute.gpu",
        required_dimensions={"gpu_count": Decimal(1)},
        required_attributes={"region": "us-east"},
    )


def test_mismatched_required_attribute_is_not_satisfied():
    assert not resource_satisfies_requirement(
        resource_kind="compute.gpu",
        available={"gpu_count": Decimal(1)},
        attributes={"region": "us-west"},
        required_resource_kind="compute.gpu",
        required_dimensions={"gpu_count": Decimal(1)},
        required_attributes={"region": "us-east"},
    )


def test_no_required_attributes_means_any_attributes_pass():
    assert resource_satisfies_requirement(
        resource_kind="compute.gpu",
        available={"gpu_count": Decimal(1)},
        attributes={"anything": "goes"},
        required_resource_kind="compute.gpu",
        required_dimensions={"gpu_count": Decimal(1)},
    )


def test_canonical_view_exposes_authoritative_top_level_facts():
    from market_site import resource_feasibility_view

    view = resource_feasibility_view(
        resource_id="resource-1",
        pool_id="pool-authoritative",
        resource_kind="compute.gpu",
        resource_subtype="h200",
        value=8,
        units=8,
        available={"gpu_count": Decimal(8)},
        attributes={"pool_id": "stale-pool"},
    )

    assert resource_satisfies_requirement(
        resource=view,
        required_resource_kind="compute.gpu",
        required_dimensions={"gpu_count": Decimal(1)},
        required_attributes={
            "resource_id": "resource-1",
            "pool_id": "pool-authoritative",
            "resource_subtype": "h200",
        },
    )
