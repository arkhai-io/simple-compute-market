"""API-tokens listing pricing helpers.

Listings are unit-priced: ``accepted_escrows[*].rates`` carries
``{"field": "amount", "per": "token", "value": <base units>}`` and the
negotiated scalar amount is ``quantity × unit rate``. The
per-unit→absolute translation happens where the seller's reference
amount is computed (the round hook) and, buyer-side, in the policy
surface (work item 5).
"""

from __future__ import annotations

import json
from typing import Any

from domains.apitokens.listings.models import resource_is_api_tokens


def _accepted_escrows(order: dict[str, Any]) -> list[dict[str, Any]]:
    raw = order.get("accepted_escrows")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    return [entry for entry in (raw or []) if isinstance(entry, dict)]


def extract_unit_price_from_order(
    order: dict[str, Any],
    *,
    default_min_price: Any = None,
) -> int | float:
    """The seller's per-token floor from an API-tokens listing.

    Mirrors the VM domain's ``extract_initial_price_from_order``: the
    advertised primary rate wins; a hidden-reserve listing falls back to
    ``[seller.pricing].default_min_price``; with neither there is no
    floor to negotiate against and the negotiation is refused.
    """
    from market_alkahest.schemas import primary_rate_value

    accepted = _accepted_escrows(order)
    advertised = primary_rate_value(accepted[0]) if accepted else None
    if advertised is not None:
        return advertised

    if default_min_price is not None and str(default_min_price).strip():
        try:
            parsed = float(default_min_price)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"[seller.pricing].default_min_price={default_min_price!r} "
                "is not a valid number; hidden-reserve listing "
                f"{order.get('listing_id')} has no usable floor."
            ) from exc
        if parsed > 0:
            return parsed

    raise ValueError(
        f"Listing {order.get('listing_id')} has hidden reserve "
        "(accepted_escrows[0].rates is empty) and "
        "[seller.pricing].default_min_price is not configured. The seller "
        "has no floor to negotiate against; refusing the negotiation."
    )


def determine_strategy_from_order(order: dict[str, Any] | None) -> str | None:
    """Sellers of prepaid credits always maximize the scalar amount."""
    if not order:
        return None
    if resource_is_api_tokens(order.get("offer_resource")):
        return "maximize"
    return None
