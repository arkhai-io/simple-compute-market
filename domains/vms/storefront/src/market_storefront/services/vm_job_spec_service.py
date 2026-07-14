"""VM provisioning job-spec construction for storefront fulfillment."""

from __future__ import annotations

import uuid
from typing import Any, Callable

from domains.vms.listings import extract_compute_from_order


_REQUIRED_COMPUTE_KEYS = (
    "pool_id",
    "resource_id",
    "region",
    "gpu_model",
    "gpu_count",
)


def compute_capacity_claim_from_order(order_dict: dict[str, Any] | None) -> dict[str, Any]:
    """Extract inventory-matching attributes from a VM listing/order.

    ``offer_resource`` may arrive as a JSON string, a plain dict, or a
    ``ComputeResource`` model instance — ``Listing.model_validate`` mutates
    rows it validates, replacing the dict in place, and several callers (the
    negotiation accept paths) run after such validation. Silently returning
    ``{}`` for the model shape un-pins the claim and makes capacity
    reservations grab the wrong resource.
    """
    required_attributes: dict[str, Any] = {}
    if not order_dict:
        return required_attributes
    compute_resource = extract_compute_from_order(order_dict)
    if hasattr(compute_resource, "model_dump"):
        compute_resource = compute_resource.model_dump()
    if isinstance(compute_resource, dict):
        for key in _REQUIRED_COMPUTE_KEYS:
            if compute_resource.get(key) is not None:
                required_attributes[key] = compute_resource[key]
    return required_attributes


async def build_provisioning_job_spec(
    *,
    order_dict: dict[str, Any] | None,
    ssh_public_key: str,
    duration_seconds: int,
    capacity: Any,
    vm_target_factory: Callable[[], str] | None = None,
) -> dict[str, Any] | None:
    """Probe the capacity ledger (read-only) and build a VM job spec."""
    required_attributes = compute_capacity_claim_from_order(order_dict)
    selected = await capacity.probe(claim=required_attributes or None)
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
