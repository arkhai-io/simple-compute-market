"""Bind VM multiplier negotiation to core's schema-opaque amount codec."""
from __future__ import annotations

import math
from collections.abc import Mapping
from decimal import Decimal
from fractions import Fraction
from typing import Any

from arkhai_vms import normalize_vm_provision_terms, vm_listing_resource_shape
from arkhai_vms.capability_shapes import canonical_vm_shape, flatten_vm_shape
from arkhai_vms_listings import extract_compute_from_order
from arkhai_vms_negotiation.amounts import (
    BASIS_POINTS, has_rate_structure, quote_from_multiplier, selected_billing_basis,
    shape_hourly_amount,
)
from arkhai_vms_negotiation.policies import proposal_uses_scalar_amount
from core_buyer.negotiation_client import NegotiationAmountCodec
from market_core.schemas import BillingProjection

from .pricing_record import retained_pricing_record, verify_pricing_acceptance, verify_pricing_reply
from .settlement_composition import buyer_settlement_registry


def priced_unit_count(
    listing: Any, proposal: Any, duration_seconds: int | float | None,
    *, project_billing: BillingProjection | None = None,
) -> float:
    """Scale hourly bounds by one billing period, never a recurring horizon."""
    if hasattr(proposal, "model_dump"):
        proposal = proposal.model_dump(mode="json")
    if proposal and "option_id" in proposal:
        proposal = {"settlement_selection": proposal}
    if listing is not None and proposal and "settlement_selection" in proposal:
        basis = selected_billing_basis(
            listing, proposal, project_billing or buyer_settlement_registry().project_billing,
        )
        if basis.unit == "per_period":
            assert basis.period_seconds is not None
            return basis.period_seconds / 3600.0
    if duration_seconds is None or duration_seconds <= 0:
        raise ValueError("reserved selections require an explicit positive duration")
    return float(duration_seconds) / 3600.0


def amount_codec(
    listing: Any, proposal: Any, *, project_billing: BillingProjection | None = None,
) -> NegotiationAmountCodec | None:
    """Use the seller-authenticated registry listing, never a storefront read.

    Public per-hour buyer bounds are anchored to the advertised shape once.
    Shape revisions affect the payment, not the scalar ceiling or concessions.
    """
    if listing is None or not has_rate_structure(listing):
        return None
    if hasattr(proposal, "model_dump"):
        proposal = proposal.model_dump(mode="json")
    if "option_id" in proposal:
        proposal = {"settlement_selection": proposal}
    if not proposal_uses_scalar_amount(listing, proposal):
        return None
    hourly = shape_hourly_amount(listing, proposal)
    project_billing = project_billing or buyer_settlement_registry().project_billing
    basis = selected_billing_basis(listing, proposal, project_billing)
    pricing_record = retained_pricing_record(listing)

    def scalar(price: Any) -> int:
        value = Fraction(Decimal(str(price)))
        if value < 0:
            raise RuntimeError("buyer price must be non-negative")
        # A rounded-up scalar could buy more than the caller's monetary ceiling.
        return math.floor(value * BASIS_POINTS / hourly)

    def payment(value: int, terms: Any) -> int:
        if hasattr(terms, "model_dump"):
            terms = terms.model_dump(mode="json")
        terms = normalize_vm_provision_terms(terms)
        shape = (
            vm_listing_resource_shape(terms.compute_resource)
            if terms.compute_resource is not None else None
        )
        return quote_from_multiplier(
            listing, proposal, value, terms.duration_seconds, shape, price_basis=basis,
        )

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

    def validate_reply(reply):
        try:
            verify_pricing_reply(pricing_record, reply)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

    def validate_accepted(outcome, reply):
        try:
            verify_pricing_acceptance(
                pricing_record, outcome.agreement, reply,
                multiplier=outcome.negotiated_scalar, project_billing=project_billing,
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

    return NegotiationAmountCodec(
        scalar_from_price=scalar, payment_from_scalar=payment, effective_terms=effective,
        validate_reply=validate_reply, validate_accepted=validate_accepted,
    )
