"""Derive and persist one hosted binding from seller-accepted state."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from arkhai_bare_metal import (
    HOSTED_MECHANISM,
    BareMetalAcceptedHostedBinding,
    BareMetalBuyerDemand,
    BareMetalHostedOption,
    BareMetalTerms,
    CanonicalPrincipal,
    derive_accepted_hosted_binding,
    validate_buyer_selection,
)
from market_core.schemas import (
    SettlementObligation,
    SettlementOption,
    SettlementPlan,
    SettlementSelection,
    compute_rate_total,
)
from market_hosted_settlement import HostedObligationParams
from market_identity import Identity
from market_settlement_runtime import derive_obligation_ref

from .sqlite_client import SQLiteClient


def _canonical(principal: Identity) -> CanonicalPrincipal:
    return CanonicalPrincipal(
        scheme=principal.scheme.value,
        identifier=principal.identifier,
    )


def build_accepted_hosted_obligation(
    *,
    option: BareMetalHostedOption,
    duration_seconds: int,
    expiration_unix: int,
    buyer_principal: Identity,
    seller_principal: Identity,
) -> SettlementObligation:
    """Rebuild the one canonical obligation used by negotiation and servicing."""

    if option.claimant_principal != _canonical(seller_principal):
        raise ValueError("hosted option claimant does not match the listing seller")
    amount = compute_rate_total(option.option.rates[0], duration_seconds)
    if amount <= 0:
        raise ValueError("trusted duration-scaled hosted amount must be positive")
    params = dict(option.option.params)
    params.pop("bare_metal", None)
    if "funding_authorization_ref" in params:
        raise ValueError("listing cannot pre-authorize hosted funding")
    params["payer_principal"] = buyer_principal.model_dump(mode="json")
    params["claimant_principal"] = seller_principal.model_dump(mode="json")
    params = HostedObligationParams.model_validate(
        {**params, "funding_authorization_ref": "accepted-plan-validation"}
    ).model_dump(mode="json", exclude={"funding_authorization_ref"})
    condition = params.get("condition")
    if not isinstance(condition, Mapping):
        raise ValueError("hosted option has no portable condition")
    return SettlementObligation(
        payer="buyer",
        claimant="seller",
        payer_principal=buyer_principal.model_dump(mode="json"),
        claimant_principal=seller_principal.model_dump(mode="json"),
        amount=amount,
        asset=option.option.asset,
        expiration_unix=expiration_unix,
        conditions=[dict(condition)],
        mechanism=HOSTED_MECHANISM,
        params=params,
    )


def build_accepted_hosted_plan(
    *,
    listing_id: str,
    option: BareMetalHostedOption,
    demand: BareMetalBuyerDemand,
    seller_terms: BareMetalTerms,
    buyer_principal: Identity,
    seller_principal: Identity,
) -> SettlementPlan:
    """Derive the exact accepted plan from seller-owned listing artifacts."""

    obligation = build_accepted_hosted_obligation(
        option=option,
        duration_seconds=demand.duration_seconds,
        expiration_unix=demand.settlement.expiration_unix,
        buyer_principal=buyer_principal,
        seller_principal=seller_principal,
    )
    physical_terms = {
        "listing_id": listing_id,
        "option_id": option.option.option_id,
        "option_facts": option.facts.model_dump(mode="json", exclude_none=True),
        "provision_terms": seller_terms.model_dump(mode="json", exclude_none=True),
    }
    return SettlementPlan(
        buyer_principal=buyer_principal.model_dump(mode="json"),
        seller_principal=seller_principal.model_dump(mode="json"),
        service_terms={"bare_metal.v1": physical_terms},
        obligations=[obligation],
    )


def _accepted_selection(thread: Mapping[str, Any]) -> SettlementSelection:
    proposal = thread.get("buyer_escrow_proposal")
    if not isinstance(proposal, Mapping):
        raise ValueError("accepted hosted negotiation has no exact selection")
    raw = proposal.get("settlement_selection")
    try:
        return SettlementSelection.model_validate(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "accepted hosted negotiation has an invalid selection"
        ) from exc


async def ensure_accepted_hosted_binding(
    *,
    db: SQLiteClient,
    negotiation_id: str,
    obligation_ref: str,
) -> BareMetalAcceptedHostedBinding:
    """Rebuild only from the immutable thread/listing/plan and persist once."""

    existing = await db.load_bare_metal_hosted_lifecycle(obligation_ref=obligation_ref)
    if existing is not None:
        return existing.accepted_binding
    thread = await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
    if thread is None or thread.get("terminal_state") != "success":
        raise ValueError("bare-metal negotiation is not accepted")
    plan = SettlementPlan.model_validate(thread.get("settlement_plan"))
    if len(plan.obligations) != 1:
        raise ValueError("bare-metal hosted agreement must contain one obligation")
    obligation = plan.obligations[0]
    if obligation.mechanism != HOSTED_MECHANISM or obligation.amount is None:
        raise ValueError("accepted obligation is not hosted bare-metal settlement")

    listing_id = str(thread.get("our_listing_id") or "")
    listing_row = await db.load_listing(listing_id=listing_id)
    trusted_listing = await db.load_bare_metal_listing_payload(listing_id=listing_id)
    listing_binding = await db.load_listing_binding(listing_id=listing_id)
    if listing_row is None or trusted_listing is None or listing_binding is None:
        raise ValueError("accepted bare-metal listing is unavailable")
    options = [
        SettlementOption.model_validate(value)
        for value in listing_row.get("settlement_options") or []
    ]
    selection = _accepted_selection(thread)
    terms = await db.load_bare_metal_terms(negotiation_id=negotiation_id)
    if terms is None:
        raise ValueError("accepted bare-metal seller terms are unavailable")
    demand = BareMetalBuyerDemand(
        duration_seconds=terms.duration_seconds,
        access_method=terms.access_method,
        ssh_public_key=terms.ssh_public_key or "",
        settlement=selection,
        allow_off_session=next(
            (
                option.params.get("interaction") == "saved_instrument"
                for option in options
                if option.option_id == selection.option_id
            ),
            False,
        ),
    )
    selected = validate_buyer_selection(
        demand=demand,
        advertised_options=options,
    )
    facts = selected.facts
    if (
        facts.site_id != listing_binding.site_id
        or facts.physical_resource_id != listing_binding.physical_resource_id
        or facts.pool_id != listing_binding.pool_id
        or facts.physical_host_id != trusted_listing.physical_host_id
        or terms.machine_id != trusted_listing.machine_id
        or terms.physical_host_id != trusted_listing.physical_host_id
        or terms.listing_ref != listing_id
    ):
        raise ValueError("accepted hosted physical terms changed trusted listing data")
    buyer = Identity.model_validate(thread.get("buyer_principal"))
    seller = Identity.model_validate(thread.get("seller_principal"))
    expected_plan = build_accepted_hosted_plan(
        listing_id=listing_id,
        option=selected,
        demand=demand,
        seller_terms=terms,
        buyer_principal=buyer,
        seller_principal=seller,
    )
    if plan != expected_plan:
        raise ValueError(
            "accepted hosted plan differs from trusted duration-scaled listing terms"
        )
    expected_ref = derive_obligation_ref(
        negotiation_id,
        0,
        obligation.model_dump(mode="json"),
    )
    if expected_ref != obligation_ref:
        raise ValueError("requested obligation does not match the accepted plan")
    claimant_value = obligation.claimant_principal
    if claimant_value is None:
        raise ValueError("accepted hosted obligation has no claimant principal")
    claimant = Identity.model_validate(claimant_value)
    binding = derive_accepted_hosted_binding(
        agreement_ref=negotiation_id,
        negotiation_id=negotiation_id,
        listing_id=listing_id,
        obligation_ref=obligation_ref,
        option=selected,
        demand=demand,
        buyer_principal=_canonical(buyer),
        seller_principal=_canonical(seller),
        claimant_principal=_canonical(claimant),
        signed_listing=listing_row,
        seller_terms=terms.model_dump(mode="json", exclude_none=True),
        accepted_plan=plan.model_dump(mode="json"),
        authorization_expires_at=datetime.fromtimestamp(
            selection.expiration_unix,
            tz=timezone.utc,
        ),
    )
    await db.save_bare_metal_hosted_binding(binding)
    return binding


__all__ = [
    "build_accepted_hosted_obligation",
    "build_accepted_hosted_plan",
    "ensure_accepted_hosted_binding",
]
