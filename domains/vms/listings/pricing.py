"""VM listing pricing helpers."""

from __future__ import annotations

import json
from typing import Any

from market_storefront.models.domain_models import Listing


def resource_is_compute(resource: Any) -> bool:
    """True when the resource represents compute rather than tokens."""
    if isinstance(resource, str):
        try:
            resource = json.loads(resource)
        except Exception:
            return False
    if isinstance(resource, dict):
        return "gpu_model" in resource
    return hasattr(resource, "gpu_model")


def extract_compute_from_order(order: dict[str, Any]) -> dict[str, Any]:
    """Return the compute dict from an order's ``offer_resource``."""
    offer_resource = order.get("offer_resource", {})
    if isinstance(offer_resource, str):
        offer_resource = json.loads(offer_resource)
    if not resource_is_compute(offer_resource):
        raise ValueError(
            f"Order offer_resource is not compute: "
            f"listing_id={order.get('listing_id')}"
        )
    return offer_resource


def extract_initial_price_from_order(
    order: Listing | dict[str, Any],
    *,
    default_min_price: Any = None,
) -> int | float:
    """Extract the seller's initial negotiation floor from a VM listing."""
    from service.schemas import primary_rate_value

    if isinstance(order, dict):
        order = Listing.model_validate(order)

    advertised: int | None = None
    if order.accepted_escrows:
        advertised = primary_rate_value(order.accepted_escrows[0])

    if advertised is not None:
        return advertised

    if default_min_price is not None and str(default_min_price).strip():
        try:
            parsed = float(default_min_price)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"[seller.pricing].default_min_price={default_min_price!r} "
                "is not a valid number; hidden-reserve listing "
                f"{order.listing_id} has no usable floor."
            ) from exc
        if parsed > 0:
            return parsed

    raise ValueError(
        f"Listing {order.listing_id} has hidden reserve "
        "(accepted_escrows[0].rates is empty) and "
        "[seller.pricing].default_min_price is not configured. The seller "
        "has no floor to negotiate against; refusing the negotiation."
    )
