"""VM listing pricing helpers."""

from __future__ import annotations

import json
import re
from fractions import Fraction
from typing import Any

from arkhai_vms_listings.models import Listing


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
    """Return the compute dict from an order's ``listing_resource``."""
    listing_resource = order.get("listing_resource", {})
    if isinstance(listing_resource, str):
        listing_resource = json.loads(listing_resource)
    if not resource_is_compute(listing_resource):
        raise ValueError(
            f"Order listing_resource is not compute: "
            f"listing_id={order.get('listing_id')}"
        )
    return listing_resource


_NO_SELECTION = object()


def extract_initial_price_from_order(
    order: Listing | dict[str, Any],
    *,
    default_min_price: Any = None,
    selected_option: Any = _NO_SELECTION,
) -> int | Fraction:
    """The seller's initial negotiation floor for a VM listing, per hour.

    ``selected_option`` is the accepted escrow or settlement option the buyer's
    proposal selects, or None when it selects none the listing offers. The seller
    negotiates from that option's advertised rate, in its own asset's base units,
    so a hosted selection on a listing that also offers Alkahest is never priced
    against the Alkahest rate. Without a selection to read, as before a buyer has
    proposed, the listing's first accepted escrow stands in.

    When the option advertises no rate the listing is a hidden reserve and the
    floor is the storefront's configured ``default_min_price``, in base units per
    hour, parsed exactly from its decimal text into a ``Fraction``: an amount
    reaching on-chain settlement must never pass through a binary float. See
    openspec/specs/negotiation-protocol/spec.md, "The seller's reference amount is
    the selected option's rate".
    """
    # Read through the Alkahest kit: concept modules may not import core, and
    # this reader handles any option's ``rates`` the same way.
    from market_alkahest.schemas import primary_rate_value

    if isinstance(order, dict):
        order = Listing.model_validate(order)

    if selected_option is _NO_SELECTION:
        selected_option = order.accepted_escrows[0] if order.accepted_escrows else None
    advertised = (
        primary_rate_value(selected_option) if selected_option is not None else None
    )
    if advertised is not None:
        return advertised

    floor = _exact_floor(default_min_price, listing_id=order.listing_id)
    if floor is not None and floor > 0:
        return floor

    raise ValueError(
        f"Listing {order.listing_id} has hidden reserve (the selected settlement "
        "option advertises no rate) and [seller.pricing].default_min_price is not "
        "configured. The seller has no floor to negotiate against; refusing the "
        "negotiation."
    )


_DECIMAL_TEXT = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")


def _exact_floor(value: Any, *, listing_id: str) -> Fraction | None:
    """``default_min_price`` as an exact rational, or None when unset."""
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(
            f"[seller.pricing].default_min_price={value!r} is not a valid number "
            "for an exact floor; state it as decimal text. Hidden-reserve "
            f"listing {listing_id} has no usable floor."
        )
    text = str(value).strip()
    if not text:
        return None
    if not _DECIMAL_TEXT.fullmatch(text):
        raise ValueError(
            f"[seller.pricing].default_min_price={value!r} is not a valid number; "
            f"hidden-reserve listing {listing_id} has no usable floor."
        )
    return Fraction(text)
