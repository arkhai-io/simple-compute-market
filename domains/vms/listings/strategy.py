"""VM listing negotiation strategy helpers."""

from __future__ import annotations

from domains.vms.listings.models import (
    ComputeDomainResource,
    ComputeResource,
    Listing,
)


def determine_strategy_from_resources(
    offer_resource: ComputeDomainResource | None,
) -> str | None:
    """Determine negotiation strategy from the listing's offered resource."""
    if not offer_resource:
        return None
    if isinstance(offer_resource, ComputeResource):
        return "maximize"
    return None


def determine_strategy_from_order(order: Listing | None) -> str | None:
    """Determine negotiation strategy from a VM Listing."""
    if not order:
        return None
    return determine_strategy_from_resources(order.offer_resource)
