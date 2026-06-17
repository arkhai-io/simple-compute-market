"""VM fulfillment planning from a listing/order payload."""

from __future__ import annotations

import json
from typing import Any

from domains.vms.listings import extract_compute_from_order
from domains.vms.settlement import (
    encode_compute_lease,
    token_resource_from_accepted_escrow,
)
from market_storefront.models.vm_fulfillment_models import VmFulfillmentPlan
from market_storefront.services.vm_job_spec_service import compute_capacity_claim_from_order


def build_vm_fulfillment_plan(
    *,
    order: str | dict[str, Any] | None,
    duration_seconds: int,
    chain_configs: dict[str, Any] | None = None,
) -> VmFulfillmentPlan:
    """Materialize VM fulfillment inputs from a settlement order payload."""
    order_dict: dict[str, Any] | None = None
    order_bytes = b""

    if order:
        if isinstance(order, str):
            try:
                parsed = json.loads(order)
            except json.JSONDecodeError:
                parsed = None
            order_dict = parsed if isinstance(parsed, dict) else None
            order_bytes = order.encode("utf-8")
        elif isinstance(order, dict):
            order_dict = order

    if not order_dict:
        return VmFulfillmentPlan(
            order_dict=None,
            order_id=None,
            order_bytes=order_bytes,
            required_attributes={},
        )

    order_id = order_dict.get("listing_id") or order_dict.get("order_id")
    compute_resource = extract_compute_from_order(order_dict)
    required_attributes = compute_capacity_claim_from_order(order_dict)
    accepted_escrows = order_dict.get("accepted_escrows") or []
    first_escrow = accepted_escrows[0] if accepted_escrows else None
    token_resource = token_resource_from_accepted_escrow(
        first_escrow,
        chain_configs=chain_configs,
    )
    if token_resource is None:
        raise ValueError(
            f"Cannot encode compute lease for listing {order_id!r}: "
            "accepted_escrows[0] is neither token-backed nor native-token"
        )
    order_bytes = encode_compute_lease(
        compute_resource=compute_resource,
        token_resource=token_resource,
        duration_seconds=duration_seconds,
    )

    return VmFulfillmentPlan(
        order_dict=order_dict,
        order_id=order_id,
        order_bytes=order_bytes,
        required_attributes=required_attributes,
    )
