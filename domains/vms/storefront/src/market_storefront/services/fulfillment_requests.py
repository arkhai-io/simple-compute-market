"""Canonical VM scheduling and fulfillment requests from accepted listings."""

from __future__ import annotations

import uuid
from typing import Any

from compute_provisioning import (
    FulfillmentBeginRequest,
    FulfillmentRequestEnvelope,
    FulfillmentScheduleRequest,
)
from domains.vms.listings import extract_compute_from_order

from market_storefront.services.vm_job_spec_service import (
    compute_capacity_claim_from_order,
)


def build_vm_fulfillment_requests(
    *,
    capacity_reservation_id: str,
    order: dict[str, Any],
    ssh_public_key: str,
    vm_target: str | None = None,
) -> tuple[FulfillmentScheduleRequest, FulfillmentBeginRequest]:
    """Translate one accepted VM listing into strict versioned requests."""
    claim = compute_capacity_claim_from_order(order)
    dimensions = dict(claim.pop("dimensions", {}) or {})
    resource_id = claim.pop("resource_id", None)
    claim.pop("pool_id", None)
    schedule = FulfillmentScheduleRequest(
        capacity_reservation_id=capacity_reservation_id,
        market="vms",
        resource_id=str(resource_id) if resource_id is not None else None,
        requirements={
            "resource_kind": "compute.gpu",
            "dimensions": dimensions,
            "attributes": claim,
        },
    )

    compute = extract_compute_from_order(order)
    if hasattr(compute, "model_dump"):
        compute = compute.model_dump()
    if not isinstance(compute, dict):
        raise ValueError("VM fulfillment requires a compute resource object")
    missing = [
        key for key in ("ram_gb", "vcpu_count", "disk_gb") if compute.get(key) is None
    ]
    if missing:
        raise ValueError(
            "VM fulfillment listing is missing required dimensions: "
            + ", ".join(missing)
        )
    payload: dict[str, Any] = {
        "vm_target": vm_target or f"tenant-{uuid.uuid4().hex[:8]}",
        "image_setup_type": "scratch",
        "vm_ram": int(compute["ram_gb"]) * 1024,
        "vm_vcpus": int(compute["vcpu_count"]),
        "vm_disk_size": f"{int(compute['disk_gb'])}G",
        "ssh_pubkey": ssh_public_key,
    }
    gpu_count = compute.get("gpu_count")
    if gpu_count is not None:
        payload["gpu_provisioned"] = int(gpu_count) > 0
        payload["vm_gpu_count"] = int(gpu_count)
    begin = FulfillmentBeginRequest(
        capacity_reservation_id=capacity_reservation_id,
        market="vms",
        fulfillment_request=FulfillmentRequestEnvelope(
            kind="vms.fulfillment",
            schema_version=1,
            payload=payload,
        ),
    )
    return schedule, begin
