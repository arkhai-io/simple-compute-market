"""Exact VM quote derivation from advertised rates and a negotiated multiplier."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from fractions import Fraction
from typing import Any

from arkhai_vms import price_vm_shape, vm_family_rate, vm_listing_resource_shape
from arkhai_vms_listings import extract_compute_from_order
from market_core.schemas import primary_rate_value, settlement_option_asset
from market_identity import canonical_json
from market_policy.scalar_policies import selected_settlement_artifact

BASIS_POINTS = 10_000
UINT256_MAX = 2**256 - 1


def listing_record(listing: Any) -> dict[str, Any]:
    return listing.model_dump(mode="json") if hasattr(listing, "model_dump") else dict(listing)


def _rate_structure(listing: Any) -> Any:
    structure = listing_record(listing).get("rate_structure")
    if isinstance(structure, str):
        structure = json.loads(structure)
    return structure


def has_rate_structure(listing: Any) -> bool:
    return bool(_rate_structure(listing))


def rate_structure_digest(listing: Any) -> str | None:
    """The SHA-256 of the listing's rate structure as canonical JSON, or None.

    Covers the family rates alone, so a negotiation pinned to it is refused
    once any rate changes, and only then. None for a listing that is not
    shape-priced.
    """
    structure = _rate_structure(listing)
    if not structure:
        return None
    return hashlib.sha256(canonical_json(structure)).hexdigest()


def multiplier_floor(config: Any = None) -> int:
    """The seller's lowest acceptable multiplier, in basis points.

    At most :data:`BASIS_POINTS`, so the advertised rates are always a price
    the seller accepts and a buyer never has to bargain up to them.
    """
    value = (
        config.get("multiplier_floor_bps", BASIS_POINTS)
        if isinstance(config, Mapping)
        else getattr(config, "multiplier_floor_bps", BASIS_POINTS)
    )
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= BASIS_POINTS
    ):
        raise ValueError(
            f"multiplier_floor_bps must be an integer from 0 to {BASIS_POINTS}"
        )
    return value


def shape_hourly_amount(
    listing: Any,
    proposal: Mapping[str, Any],
    requested_shape: Mapping[str, Mapping[str, Any]] | None = None,
) -> Fraction:
    """Price a shape in the selected option's materialized base-unit scale.

    The rational ratio preserves fractional base units until the final quote;
    rounding either shape or the duration first would make the two sides disagree.

    ``listing`` may be a registry's discovery record, which carries the publisher's
    principals rather than a storefront ``Listing``'s ``seller_principal``, so only
    the fields the quote reads are read and the record is never validated whole.
    """
    record = listing_record(listing)
    selected = selected_settlement_artifact(record, proposal)
    if selected is None:
        raise ValueError("shape_price_unavailable: selected option is not advertised")
    advertised_rate = primary_rate_value(selected)
    if advertised_rate is None:
        raise ValueError("shape_price_unavailable: selected option advertises no rate")
    per_hour = Fraction(advertised_rate)
    structure = record.get("rate_structure")
    if isinstance(structure, str):
        structure = json.loads(structure)
    if not structure:
        raise ValueError("shape_price_unavailable: listing has no rate structure")
    asset = settlement_option_asset(selected)
    if asset is None:
        literals = selected.get("literal_fields") or {}
        asset = literals.get("token") or literals.get("asset") or selected.get("asset") or "native"
    rates = {
        family: vm_family_rate(entry["rate"], entry["per"])
        for family, entries in structure.items()
        for entry in entries
        if entry.get("asset") == asset
    }
    advertised = vm_listing_resource_shape(extract_compute_from_order(record))
    base = price_vm_shape(advertised, rates)
    requested = price_vm_shape(requested_shape if requested_shape is not None else advertised, rates)
    if base.is_zero or requested.is_zero:
        raise ValueError(f"shape_price_unavailable: no positive price in asset {asset!r}")
    return per_hour * Fraction(requested.amount) / Fraction(base.amount)


def quote_from_multiplier(
    listing: Any,
    proposal: Mapping[str, Any],
    multiplier_bps: int,
    duration_seconds: int,
    requested_shape: Mapping[str, Mapping[str, Any]] | None = None,
) -> int:
    """Round a complete exact quote upward once and refuse asset overflow."""
    if isinstance(multiplier_bps, bool) or not isinstance(multiplier_bps, int) or multiplier_bps < 0:
        raise ValueError("multiplier_bps must be a non-negative integer")
    if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, int) or duration_seconds <= 0:
        raise ValueError("duration_seconds must be a positive integer")
    amount = math.ceil(
        shape_hourly_amount(listing, proposal, requested_shape)
        * duration_seconds * multiplier_bps / (3600 * BASIS_POINTS)
    )
    if amount > UINT256_MAX:
        raise ValueError("shape_price_overflow: quote exceeds uint256")
    return amount
