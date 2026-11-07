"""compute_capacity_claim_from_order: the resource_type constraint.

Every claim this function builds names resource_type explicitly, so an
injected exact ClaimMatcher (kit/site's dict_resource_satisfies_claim) can
reject a resource of the wrong kind rather than silently ranking it.
"""

from __future__ import annotations

from arkhai_vms_listings.models import Listing
from arkhai_vms_listings.resources import ComputeGpuResourceAdapter

from market_storefront.services.vm_job_spec_service import (
    _VM_RESOURCE_TYPE,
    compute_capacity_claim_from_order,
)


def _order(**offer_overrides):
    listing_resource = {
        "resource_id": "res-1",
        "pool_id": "pool-1",
        "gpu_model": "H200",
        "gpu_count": 2,
        "region": "California, US",
    }
    listing_resource.update(offer_overrides)
    return {
        "listing_id": "lst-1",
        "status": "open",
        "storefront_url": "http://seller:8001",
        "seller_principal": {
            "scheme": "eip191",
            "identifier": "0x2222222222222222222222222222222222222222",
        },
        "listing_resource": listing_resource,
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
    assert _VM_RESOURCE_TYPE == ComputeGpuResourceAdapter().resource_type


def test_claim_names_resource_type_even_for_a_pinned_resource_id():
    claim = compute_capacity_claim_from_order(_order(pool_id=None))
    assert claim["resource_id"] == "res-1"
    assert "pool_id" not in claim
    assert claim["resource_type"] == _VM_RESOURCE_TYPE


def _gpu_less_order():
    order = _order(resource_id=None, vcpu_count=8, ram_gb=32)
    del order["listing_resource"]["gpu_model"]
    del order["listing_resource"]["gpu_count"]
    return order


def test_a_listing_without_gpus_claims_its_vcpus_and_memory_and_no_gpu():
    claim = compute_capacity_claim_from_order(_gpu_less_order())

    assert claim == {
        "offering_mode": "vm",
        "resource_type": "compute.gpu",
        "pool_id": "pool-1",
        "region": "California, US",
        "dimensions": {"vcpu_count": 8, "ram_gb": 32},
    }


def test_a_listing_without_gpus_claims_alike_from_its_parsed_model():
    order = _gpu_less_order()
    order["listing_resource"]["sla"] = 99.0
    order["listing_resource"] = Listing.model_validate(order).listing_resource

    claim = compute_capacity_claim_from_order(order)

    assert claim == compute_capacity_claim_from_order(_gpu_less_order())
