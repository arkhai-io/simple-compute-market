"""Bidirectional listing matching logic.

Pure Python — no HTTP, no database. Given a local listing and a list
of candidate listings fetched from the registry, returns the subset
whose offer/demand resources are complementary.

Accepts either ``ListingSummary`` instances (from the canonical
registry client) or plain dicts (for backward compatibility with
legacy callers).
"""

from __future__ import annotations

from typing import Any


def _get_offer(order: Any) -> dict[str, Any]:
    if isinstance(order, dict):
        return order.get("offer_resource") or order.get("offer") or {}
    return getattr(order, "offer", {}) or {}


def _get_demand(order: Any) -> dict[str, Any]:
    if isinstance(order, dict):
        return order.get("demand_resource") or order.get("demand") or {}
    return getattr(order, "demand", {}) or {}


def _resource_type(resource: dict[str, Any]) -> str:
    """Return 'compute', 'token', or 'unknown' for a resource dict."""
    if "token" in resource:
        return "token"
    if "gpu_model" in resource:
        return "compute"
    return "unknown"


def match_orders(
    our_order: Any,
    candidates: list[Any],
    *,
    bidirectional: bool = True,
) -> list[Any]:
    """Return the subset of *candidates* whose resources complement *our_order*.

    Accepts ``OrderSummary`` instances or plain dicts.  Returns the same type
    as was passed in — callers receive back whatever they provided.

    Bidirectional matching (default):
      - Case A: we offer compute + demand token  ↔  they offer token + demand compute
      - Case B: we offer token + demand compute  ↔  they offer compute + demand token

    When ``bidirectional=False`` only direct complementary matches are returned
    (our offer type == their demand type AND our demand type == their offer type).
    """
    our_offer_type = _resource_type(_get_offer(our_order))
    our_demand_type = _resource_type(_get_demand(our_order))

    matches = []
    for candidate in candidates:
        their_offer_type = _resource_type(_get_offer(candidate))
        their_demand_type = _resource_type(_get_demand(candidate))

        if bidirectional:
            case_a = (
                our_offer_type == "compute" and their_demand_type == "compute"
                and our_demand_type == "token" and their_offer_type == "token"
            )
            case_b = (
                our_offer_type == "token" and their_demand_type == "token"
                and our_demand_type == "compute" and their_offer_type == "compute"
            )
            if case_a or case_b:
                matches.append(candidate)
        else:
            if our_offer_type == their_demand_type and our_demand_type == their_offer_type:
                matches.append(candidate)

    return matches
