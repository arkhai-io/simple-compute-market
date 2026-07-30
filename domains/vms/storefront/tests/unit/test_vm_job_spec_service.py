"""compute_capacity_claim_from_order: the resource_type constraint.

Previously untested even before this change -- compute_capacity_claim_from_order
had no dedicated test file at all. Focused here on the one new behavior:
every claim this function builds now names resource_type explicitly, so
an injected exact ClaimMatcher (kit/site's dict_resource_satisfies_claim)
can reject a resource of the wrong kind rather than silently ranking it.
"""

from __future__ import annotations

from market_storefront.services.vm_job_spec_service import (
    _VM_RESOURCE_TYPE,
    compute_capacity_claim_from_order,
)


def _order(**offer_overrides):
    offer_resource = {
        "resource_id": "res-1",
        "pool_id": "pool-1",
        "gpu_model": "H200",
        "gpu_count": 2,
        "region": "California, US",
    }
    offer_resource.update(offer_overrides)
    return {
        "listing_id": "lst-1",
        "status": "open",
        "seller": "http://seller:8001",
        "offer_resource": offer_resource,
        "accepted_escrows": [],
    }


def test_claim_always_names_resource_type():
    claim = compute_capacity_claim_from_order(_order())
    assert claim["resource_type"] == _VM_RESOURCE_TYPE


def test_resource_type_constant_matches_the_actual_registered_gpu_resource_type():
    """Guards against the two sides drifting independently: this
    constant must equal what ComputeGpuResourceAdapter actually
    registers, or the claim would reject every real VM resource that
    exists."""
    from domains.vms.listings.resources import ComputeGpuResourceAdapter

    assert _VM_RESOURCE_TYPE == ComputeGpuResourceAdapter().resource_type


def test_claim_names_resource_type_even_for_a_pinned_resource_id():
    claim = compute_capacity_claim_from_order(_order(pool_id=None))
    assert claim["resource_id"] == "res-1"
    assert "pool_id" not in claim
    assert claim["resource_type"] == _VM_RESOURCE_TYPE
