"""VM provisioning job-spec construction for storefront fulfillment."""

from __future__ import annotations

import uuid
from typing import Any, Callable

from domains.vms.listings import extract_compute_from_order
from domains.vms.listings.models import Listing


_REQUIRED_COMPUTE_KEYS = (
    "pool_id",
    "resource_id",
    "region",
    "gpu_model",
)

# checked against a resource's multidimensional capacity with full
# held/available accounting, forwarded only when the listing declares
# them so older listings without a shape keep working unchanged.
_DIMENSION_COMPUTE_KEYS = ("gpu_count", "vcpu_count", "ram_gb", "disk_gb")


def compute_capacity_claim_from_order(order_dict: dict[str, Any] | None) -> dict[str, Any]:
    """Extract inventory-matching attributes from a VM listing/order.

    ``offer_resource`` may arrive as a JSON string, a plain dict, or a
    ``ComputeResource`` model instance — ``Listing.model_validate`` mutates
    rows it validates, replacing the dict in place, and several callers (the
    negotiation accept paths) run after such validation. Silently returning
    ``{}`` for the model shape un-pins the claim and makes capacity
    reservations grab the wrong resource.

    A listing carrying both ``pool_id`` and ``resource_id`` is treated as an
    intentionally specific-resource listing: ``pool_id`` is dropped from the
    claim so matching pins to the named resource rather than requiring both
    to match (POOLS-4 design review, 2026-07-16).

    The returned claim also carries a ``dimensions`` map (POOLS-6 pass 1)
    built from ``gpu_count``/``vcpu_count``/``ram_gb``/``disk_gb`` — the
    listing's fixed, seller-declared shape — so admission actually checks
    memory/disk/vCPU fit a physical host, not just GPU count. This is the
    concrete gap POOLS-6 pass 1 closes: previously nothing forwarded these
    already-existing ``ComputeResource`` fields past this point.

    Raises ``ValueError`` if the order is missing or yields neither ``pool_id``
    nor ``resource_id`` — an under-specified claim would otherwise silently
    match on shape attributes (region/gpu_model/gpu_count) alone, which is
    exactly the "grabs whatever resource is first in line" bug class this
    function exists to prevent. Listing creation is expected to already
    reject this shape (``ListingService._parse_offer_and_escrows``); this is
    a backstop for any listing that reaches claim-building anyway.
    """
    if not order_dict:
        raise ValueError("Cannot build a capacity claim without a settlement order.")
    required_attributes: dict[str, Any] = {}
    dimensions: dict[str, Any] = {}
    compute_resource = extract_compute_from_order(order_dict)
    if hasattr(compute_resource, "model_dump"):
        compute_resource = compute_resource.model_dump()
    if isinstance(compute_resource, dict):
        for key in _REQUIRED_COMPUTE_KEYS:
            if compute_resource.get(key) is not None:
                required_attributes[key] = compute_resource[key]
        for key in _DIMENSION_COMPUTE_KEYS:
            if compute_resource.get(key) is not None:
                dimensions[key] = compute_resource[key]
    for identity_key in ("pool_id", "resource_id"):
        if identity_key in required_attributes:
            required_attributes[identity_key] = Listing.normalize_capacity_identifier(
                required_attributes[identity_key], field_name=identity_key
            )
    if required_attributes.get("resource_id") is not None:
        required_attributes.pop("pool_id", None)
    if not required_attributes.get("pool_id") and not required_attributes.get("resource_id"):
        order_id = order_dict.get("listing_id") or order_dict.get("order_id")
        raise ValueError(
            f"Cannot build a capacity claim for order {order_id!r}: neither "
            "pool_id nor resource_id is present on its offer_resource."
        )
    if dimensions:
        required_attributes["dimensions"] = dimensions
    return required_attributes


async def build_provisioning_job_spec(
    *,
    order_dict: dict[str, Any],
    ssh_public_key: str,
    duration_seconds: int,
    capacity: Any,
    vm_target_factory: Callable[[], str] | None = None,
) -> dict[str, Any] | None:
    """Probe the capacity ledger (read-only) and build a VM job spec."""
    required_attributes = compute_capacity_claim_from_order(order_dict)
    selected = await capacity.probe(claim=required_attributes)
    if not selected:
        return None

    make_vm_target = vm_target_factory or (lambda: f"tenant-{uuid.uuid4().hex[:4]}")
    return {
        "resource_id": str(selected["resource_id"]),
        "vm_host": selected["vm_host"],
        "vm_target": make_vm_target(),
        "required_attributes": required_attributes,
        "ssh_public_key": ssh_public_key,
        "duration_seconds": duration_seconds,
    }
