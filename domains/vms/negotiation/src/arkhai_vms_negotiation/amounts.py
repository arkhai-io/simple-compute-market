"""Exact VM quote derivation from advertised rates and a negotiated multiplier."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from fractions import Fraction
from typing import Any

from arkhai_vms import price_vm_shape, vm_family_rate, vm_listing_resource_shape
from arkhai_vms_listings import extract_compute_from_order, extract_initial_price_from_order
from market_core.schemas import (
    BillingProjection, PriceBasis, SettlementOption, settlement_option_asset,
)
from market_policy.scalar_policies import selected_settlement_artifact

BASIS_POINTS = 10_000
UINT256_MAX = 2**256 - 1


def listing_record(listing: Any) -> dict[str, Any]:
    return listing.model_dump(mode="json") if hasattr(listing, "model_dump") else dict(listing)


def rate_structure_digest(listing: Any) -> str | None:
    """One identity for as-published rates at opening, rounds and acceptance."""
    structure = listing_record(listing).get("rate_structure")
    if structure is None:
        return None
    encoded = json.dumps(
        structure, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def has_rate_structure(listing: Any) -> bool:
    structure = listing_record(listing).get("rate_structure")
    if isinstance(structure, str):
        structure = json.loads(structure)
    return bool(structure)


def multiplier_floor(config: Any = None) -> int:
    value = (
        config.get("multiplier_floor_bps", BASIS_POINTS)
        if isinstance(config, Mapping)
        else getattr(config, "multiplier_floor_bps", BASIS_POINTS)
    )
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("multiplier_floor_bps must be a non-negative integer")
    return value


def shape_hourly_amount(
    listing: Any,
    proposal: Mapping[str, Any],
    requested_shape: Mapping[str, Mapping[str, Any]] | None = None,
) -> Fraction:
    """Price a shape in the selected option's materialized base-unit scale.

    The rational ratio preserves fractional base units until the final quote;
    rounding either shape or the duration first would make the two sides disagree.
    """
    record = listing_record(listing)
    selected = selected_settlement_artifact(record, proposal)
    if selected is None:
        raise ValueError("shape_price_unavailable: selected option is not advertised")
    per_hour = Fraction(extract_initial_price_from_order(record, selected_option=selected))
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


def selected_billing_basis(
    listing: Any, proposal: Mapping[str, Any], project_billing: BillingProjection,
) -> PriceBasis:
    """Resolve canonical options through their installed mechanism's projection.

    The legacy raw escrow proposal has no selected option; its payment is an
    absolute whole-term total. No mechanism schema is interpreted here.
    """
    selected = selected_settlement_artifact(listing_record(listing), proposal)
    if selected is None:
        raise ValueError("shape_price_unavailable: selected option is not advertised")
    if "option_id" not in selected:
        return PriceBasis(unit="total")
    return PriceBasis.model_validate(project_billing(SettlementOption.model_validate(selected)))


def quote_from_multiplier(
    listing: Any,
    proposal: Mapping[str, Any],
    multiplier_bps: int,
    duration_seconds: int | None,
    requested_shape: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    price_basis: PriceBasis = PriceBasis(unit="total"),
) -> int:
    """Round one complete quote, over the term or one projected billing period.

    Callers pricing a selected option supply its mechanism-owned basis. The
    absolute helper default preserves whole-term arithmetic for raw quotes.
    """
    if isinstance(multiplier_bps, bool) or not isinstance(multiplier_bps, int) or multiplier_bps < 0:
        raise ValueError("multiplier_bps must be a non-negative integer")
    seconds = price_basis.period_seconds if price_basis.unit == "per_period" else duration_seconds
    if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
        raise ValueError("duration_seconds must be a positive integer for a whole-term quote")
    assert seconds is not None
    amount = math.ceil(
        shape_hourly_amount(listing, proposal, requested_shape)
        * seconds * multiplier_bps / (3600 * BASIS_POINTS)
    )
    if amount > UINT256_MAX:
        raise ValueError("shape_price_overflow: quote exceeds uint256")
    return amount
