"""Bind VM multiplier negotiation to core's schema-opaque amount codec."""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from decimal import Decimal
from fractions import Fraction
from typing import Any

from arkhai_vms import normalize_vm_provision_terms, vm_listing_resource_shape
from arkhai_vms.capability_shapes import canonical_vm_shape, flatten_vm_shape
from arkhai_vms_listings import extract_compute_from_order
from arkhai_vms_negotiation.amounts import (
    BASIS_POINTS, has_rate_structure, quote_from_multiplier, shape_hourly_amount,
)
from arkhai_vms_negotiation.policies import proposal_uses_scalar_amount
from core_buyer.negotiation_client import NegotiationAmountCodec
from market_core.schemas import settlement_option_schema


def _exact_price(price: Any) -> Fraction:
    value = Fraction(Decimal(str(price)))
    if value < 0:
        raise RuntimeError("buyer price must be non-negative")
    return value


def priced_at_opening_shape(
    listing: Mapping[str, Any],
    requested_shape: Mapping[str, int] | None,
) -> dict[str, Any]:
    """A pricing copy of a candidate whose option advertises its opening shape's rate.

    ``listing`` carries its selected settlement option alone. Generic price
    derivation reads that option's advertised per-hour rate, which prices the
    whole advertised shape; the amount codec anchors the buyer's bounds to the
    shape it opens with, so a smaller ``requested_shape`` would turn derived
    defaults into a multiplier above 1.0x of what the buyer asks for. The
    copy's rate is the advertised one scaled by the composed-price ratio of
    the opening shape, omitted quantities the listing's, rounded up to a whole
    base unit so a derived ceiling never converts below 1.0x. With no
    requested shape, or a candidate without family rates, without exactly one
    option, or whose option advertises no rate, the candidate is returned as
    it is. A shape the selected asset cannot price raises ``ValueError``.
    """
    record = dict(listing)
    options = record.get("settlement_options") or []
    if requested_shape is None or not has_rate_structure(record) or len(options) != 1:
        return record
    option = copy.deepcopy(dict(options[0]))
    rates = (option.get("price") or {}).get("rates") or []
    if not rates:
        return record
    proposal = {"settlement_selection": {
        "option_id": option.get("option_id"),
        "settlement": {"schema": settlement_option_schema(option)},
    }}
    requested = {**extract_compute_from_order(record), **requested_shape}
    hourly = shape_hourly_amount(record, proposal, vm_listing_resource_shape(requested))
    rates[0]["value"] = str(math.ceil(hourly))
    record["settlement_options"] = [option]
    # Derivation reads accepted escrows before options; the option's rate is
    # the only one this copy states.
    record["accepted_escrows"] = []
    return record


def amount_codec(
    listing: Any,
    proposal: Any,
    *,
    opening_terms: Any = None,
    max_price: Any = None,
) -> NegotiationAmountCodec | None:
    """Use the seller-authenticated registry listing, never a storefront read.

    ``listing`` is the buyer's domain listing record, its family rates in
    ``rate_structure``. Public per-hour buyer bounds are anchored once to the
    shape the buyer opens with: ``opening_terms``' ``compute_resource``, its
    omitted dimensions filled from the listing as the seller fills them, or
    the advertised shape when the buyer states none. Shape revisions affect
    the payment, not the scalar ceiling or concessions.

    With ``max_price``, the per-hour ceiling, an acceptance whose derived
    payment exceeds that ceiling over the accepted duration is refused: the
    scalar bound alone does not cap the payment once the accepted shape can
    price above the opening one.
    """
    if listing is None or not has_rate_structure(listing):
        return None
    if hasattr(proposal, "model_dump"):
        proposal = proposal.model_dump(mode="json")
    if "option_id" in proposal:
        proposal = {"settlement_selection": proposal}
    if not proposal_uses_scalar_amount(listing, proposal):
        return None

    def effective(terms: Any, revision: Any):
        if hasattr(terms, "model_dump"):
            terms = terms.model_dump(mode="json")
        terms = normalize_vm_provision_terms(terms)
        payload = dict(terms.payload)
        if revision is not None:
            shape = canonical_vm_shape(revision["payload"])
            flat = flatten_vm_shape(shape)
            payload["compute_resource"] = {**flat.quantities, **flat.attributes}
        elif terms.compute_resource:
            requested = {**extract_compute_from_order(listing), **terms.compute_resource}
            flat = flatten_vm_shape(vm_listing_resource_shape(requested))
            payload["compute_resource"] = {
                **flat.quantities, **flat.attributes,
                **({"region": requested["region"]} if requested.get("region") else {}),
            }
        return normalize_vm_provision_terms(payload)

    opening_shape = None
    if opening_terms is not None:
        opening = effective(opening_terms, None)
        if opening.compute_resource:
            opening_shape = vm_listing_resource_shape(opening.compute_resource)
    hourly = shape_hourly_amount(listing, proposal, opening_shape)
    ceiling = _exact_price(max_price) if max_price is not None else None

    def scalar(price: Any) -> int:
        # A rounded-up scalar could buy more than the caller's monetary ceiling.
        return math.floor(_exact_price(price) * BASIS_POINTS / hourly)

    def payment(value: int, terms: Any) -> int:
        if hasattr(terms, "model_dump"):
            terms = terms.model_dump(mode="json")
        terms = normalize_vm_provision_terms(terms)
        shape = (
            vm_listing_resource_shape(terms.compute_resource)
            if terms.compute_resource is not None else None
        )
        duration = int(terms.duration_seconds)
        amount = quote_from_multiplier(listing, proposal, value, duration, shape)
        if ceiling is not None:
            # The quote rounds up once to a whole base unit, so the ceiling
            # admits that one rounding: a quote at the buyer's own scalar
            # ceiling for its opening shape never exceeds it.
            limit = math.ceil(ceiling * duration / 3600)
            if amount > limit:
                raise RuntimeError(
                    f"accepted payment {amount} exceeds the buyer's ceiling of "
                    f"{limit} ({max_price} per hour for {duration}s)"
                )
        return amount

    return NegotiationAmountCodec(
        scalar_from_price=scalar, payment_from_scalar=payment, effective_terms=effective,
    )
