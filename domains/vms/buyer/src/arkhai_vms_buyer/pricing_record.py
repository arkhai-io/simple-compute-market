"""Acceptance-bound pricing inputs and their seller publication proof."""

import base64
import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from arkhai_vms import normalize_vm_provision_terms, vm_listing_resource_shape
from arkhai_vms_listings.models import registry_rate_structure
from arkhai_vms_negotiation.amounts import (
    quote_from_multiplier, rate_structure_digest, selected_billing_basis,
)
from market_core.schemas import Agreement, BillingProjection, agreed_price
from market_policy.scalar_policies import parse_wire_amount
from market_identity import (
    AuthenticatedRequest, AuthenticatedResponse, Identity, TrustedIdentitySet,
    verify_request, verify_response,
)

from .registry_listing import domain_listing_record


def retained_pricing_record(listing: Mapping[str, Any]) -> dict[str, Any]:
    """Keep pricing inputs and seller proof together for accepted recovery.

    This is retention, not verification. The raw publication preserves signed
    bytes and request context that a reconstructed listing subset cannot prove.
    Copy nested values so later selection or listing edits cannot rewrite them.
    """
    return deepcopy({key: listing[key] for key in (
        "listing_id", "storefront_url", "seller_principal", "listing_resource",
        "rate_structure", "settlement_options",
        "accepted_escrows", "publisher_publication", "publisher_updates",
        "publisher_principals", "publisher_id", "source_registry_url",
        "source_registry_authority",
    ) if key in listing})


def verified_pricing_publication(record: Mapping[str, Any]) -> dict[str, Any]:
    """Verify retained publication context at its own signed timestamp.

    Historical evidence is not a live request and has no transport-freshness
    window. Accepted trust and signed bytes must remain together; a current
    registry listing cannot replace either the publication or its pricing.

    The signed body is the publication as the registry accepted it, its family
    rates in ``pricing.rate_structure``; the retained record is the buyer's
    domain record, which holds the same rates in ``rate_structure``.
    """
    try:
        proof = record["publisher_publication"]
        body = json.loads(base64.b64decode(proof["body_base64"], validate=True))
        request = AuthenticatedRequest.model_validate(proof["request"])
        trust = TrustedIdentitySet.model_validate(record["publisher_principals"])
        checked = verify_request(
            request, body=body, now=request.timestamp, max_skew=0,
            expected_principals=trust, expected_role="seller", expected_method="POST",
            expected_operation="listing.publish", expected_resource="listings",
        )
        if not checked.verified:
            raise ValueError(f"seller publication verification failed: {checked.code.value}")
        # A registry refuses a publication carrying family rates beside its
        # pricing object, so one that does was never served by a registry.
        if "rate_structure" in body:
            raise ValueError(
                "seller publication carries a top-level rate_structure; "
                "family rates are published as pricing.rate_structure"
            )
        for key in ("listing_id", "storefront_url", "listing_resource", "settlement_options"):
            if key not in body or body[key] != record.get(key):
                raise ValueError(f"retained pricing differs from seller publication: {key}")
        published = registry_rate_structure(body)
        if published is None or published != record.get("rate_structure"):
            raise ValueError(
                "retained pricing differs from seller publication: pricing.rate_structure"
            )
        return body
    except (KeyError, TypeError) as exc:
        raise ValueError("accepted pricing requires retained seller publication proof and trust") from exc


def verify_pricing_reply(record: Mapping[str, Any], reply: Mapping[str, Any]) -> None:
    if reply.get("action") not in {"counter", "accept"}:
        return
    publication = verified_pricing_publication(record)
    digest = rate_structure_digest(domain_listing_record(publication))
    if digest is None or reply.get("rate_structure_digest") != digest:
        raise ValueError("seller round changed the published rate-structure identity")


def verify_pricing_acceptance(
    record: Mapping[str, Any], agreement: Agreement, reply: Mapping[str, Any], *,
    multiplier: int | None, project_billing: BillingProjection,
) -> None:
    """Bind published rates, transcript scalar and exact accepted monetary terms."""
    verify_pricing_reply(record, reply)
    pin = reply.get("pricing_pin")
    if not isinstance(pin, Mapping) or pin.get("rate_structure_digest") != rate_structure_digest(record):
        raise ValueError("accepted pricing requires a matching signed pricing pin")
    raw = pin.get("multiplier")
    if not isinstance(raw, str) or not raw.isascii() or not raw.isdecimal() or str(int(raw)) != raw:
        raise ValueError("signed pricing pin has an invalid multiplier")
    if multiplier is None or int(raw) != multiplier:
        raise ValueError("signed pricing multiplier differs from transcript")
    trust = TrustedIdentitySet.model_validate(record["publisher_principals"])
    if Identity.model_validate(agreement.seller) not in trust:
        raise ValueError("accepted seller differs from retained publisher trust")
    if agreement.settlement is None:
        raise ValueError("accepted pricing requires the exact published settlement option")
    price = agreed_price(agreement, record, project_billing=project_billing)
    terms = normalize_vm_provision_terms(agreement.provision_terms)
    if terms.duration_seconds != agreement.duration_seconds:
        raise ValueError("Agreement duration differs from accepted provision terms")
    proposal = {"settlement_selection": {
        "option_id": agreement.settlement.option_id,
        "settlement": {"schema": agreement.settlement.settlement_schema},
    }}
    expected = quote_from_multiplier(
        record, proposal, multiplier, agreement.duration_seconds,
        vm_listing_resource_shape(terms.compute_resource) if terms.compute_resource is not None else None,
        price_basis=selected_billing_basis(record, proposal, project_billing),
    )
    if price.amount != expected:
        raise ValueError("accepted monetary amount differs from authenticated pricing")


def verify_recovered_pricing(
    record: Mapping[str, Any], agreement: Agreement, agreement_bytes: str,
    evidence: Any, *, project_billing: BillingProjection,
) -> None:
    """Require the archived seller acceptance, not an unsigned reconstructed pin."""
    seller = Identity.model_validate(agreement.seller)
    buyer = Identity.model_validate(agreement.buyer)
    previous_counter = None
    for item in evidence.items:
        if item.kind != "signed_response":
            continue
        reply = json.loads(item.body)
        context = {key: value for key, value in item.context.items() if key in AuthenticatedResponse.model_fields}
        response = AuthenticatedResponse.model_validate(context)
        operation = response.operation
        if operation not in {"negotiate_new", "negotiate_continue"}:
            continue
        if (operation == "negotiate_new" and reply.get("negotiation_id") != agreement.negotiation_id or
                operation == "negotiate_continue" and response.resource != agreement.negotiation_id):
            continue
        resource = agreement.listing_id if operation == "negotiate_new" else agreement.negotiation_id
        checked = verify_response(
            response, body=reply, now=response.timestamp, max_skew=0,
            expected_role="seller", expected_principals=TrustedIdentitySet(identities=(seller,)),
            expected_method="POST", expected_operation=operation, expected_resource=resource,
            expected_request_id=response.request_id,
        )
        if not checked.verified or not 200 <= response.status < 300:
            raise ValueError("retained pricing response signature/context is invalid")
        verify_pricing_reply(record, reply)
        scalar = parse_wire_amount(((reply.get("proposal") or {}).get("fields") or {}).get("amount"))
        if reply.get("action") == "counter":
            previous_counter = scalar
            continue
        if reply.get("action") != "accept" or reply.get("agreement_bytes") != agreement_bytes:
            continue
        if (Agreement.model_validate(reply.get("agreement")) != agreement or
                reply.get("buyer_principal") != agreement.buyer or reply.get("seller_principal") != agreement.seller):
            raise ValueError("retained pricing acceptance differs from accepted Agreement")
        for request_item in evidence.items:
            if request_item.kind != "signed_request" or request_item.context.get("request_id") != response.request_id:
                continue
            context = {key: value for key, value in request_item.context.items() if key in AuthenticatedRequest.model_fields}
            request = AuthenticatedRequest.model_validate(context)
            request_body = json.loads(request_item.body)
            checked = verify_request(
                request, body=request_body, now=request.timestamp, max_skew=0,
                expected_role="buyer", expected_principals=TrustedIdentitySet(identities=(buyer,)),
                expected_method="POST", expected_operation=operation, expected_resource=resource,
            )
            if not checked.verified or request_body.get("buyer_principal") != agreement.buyer:
                raise ValueError("retained pricing request signature/context is invalid")
            if scalar is None:
                scalar = previous_counter if request_body.get("action") == "accept" else parse_wire_amount(
                    ((request_body.get("proposal") or {}).get("fields") or {}).get("amount"),
                )
            verify_pricing_acceptance(record, agreement, reply, multiplier=scalar, project_billing=project_billing)
            return
        raise ValueError("retained pricing acceptance has no matching signed buyer request")
    raise ValueError("accepted pricing requires retained signed acceptance evidence")
