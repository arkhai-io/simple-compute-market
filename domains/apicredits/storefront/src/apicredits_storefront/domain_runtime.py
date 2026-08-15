"""API-credit market contract and shared-settlement domain injections."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any
from market_identity import Identity

from market_core import (
    DomainCapability,
    ImmutableFulfillmentCapability,
    ImmutablePublicationCapability,
    ImmutableSettlementCapability,
    ImmutableStorefrontCapability,
    MarketDomainContract,
    validate_domain_contract,
)


def _build_market_domain_contract() -> MarketDomainContract:
    """Build and validate the API-credit contract for the storefront role."""
    from apicredits_storefront.services.fulfillment_service import (
        fulfill_credit_obligation,
    )
    from apicredits_storefront.services.publication_service import (
        publish_order_to_registry,
    )
    from apicredits_storefront.negotiation_runtime import (
        build_api_credit_accepted_artifacts,
    )
    from core_storefront.escrow_verification import verify_escrow_for_settlement
    from domains.apicredits.domain_runtime import market_domain
    from domains.apicredits.negotiation.storefront_round import (
        default_seller_round_hook,
    )

    base = market_domain()
    capabilities = {
        DomainCapability.STOREFRONT,
        DomainCapability.PUBLICATION,
        DomainCapability.SETTLEMENT,
        DomainCapability.FULFILLMENT,
    }
    return validate_domain_contract(
        replace(
            base,
            declared_capabilities=base.declared_capabilities | capabilities,
            storefront=ImmutableStorefrontCapability(
                run_negotiation_policy=default_seller_round_hook,
            ),
            publication=ImmutablePublicationCapability(
                publish=publish_order_to_registry,
            ),
            settlement=ImmutableSettlementCapability(
                verify=verify_escrow_for_settlement,
                build_plan=build_api_credit_accepted_artifacts,
            ),
            fulfillment=ImmutableFulfillmentCapability(
                fulfill=fulfill_credit_obligation,
            ),
        )
    )


#: Installed storefront-domain entry points load concrete validated contracts,
#: not factories. Keeping this immutable object module-local also ensures every
#: service in one process consumes the same composed capability set.
APICREDITS_STOREFRONT_DOMAIN = _build_market_domain_contract()


def get_market_domain_contract() -> MarketDomainContract:
    """Return the validated API-credit contract injected into this storefront."""
    return APICREDITS_STOREFRONT_DOMAIN


@dataclass(frozen=True)
class ApiCreditsFulfillmentInput:
    """Private-to-domain inputs retained only by the in-process job."""

    chain_name: str
    order: dict[str, Any]
    quantity: int
    key_mode: str
    key_id: str | None
    buyer_principal: Identity
    listing_id: str | None
    negotiation_id: str


@dataclass(frozen=True)
class ApiCreditsSettlementProjection:
    """Public legacy-row metadata for the accepted settlement."""

    chain_name: str
    escrow_address: str | None


async def prepare_api_credit_settlement(
    *,
    sqlite_client: Any,
    local_principal: Identity,
    escrow_uid: str,
    negotiation_id: str,
    mechanism_client: Any,
    chain_name: str,
    request: Any = None,
) -> Any:
    """Verify and snapshot the exact durationless API-credit obligation."""
    if request is None:
        raise ValueError("settlement request is required")
    from core_storefront.escrow_verification import verify_escrow_for_settlement
    from market_core.schemas import EscrowProposal
    from market_settlement_runtime import PreparedSettlement

    from apicredits_storefront.utils.config import CHAINS, settings

    chain = CHAINS.get(chain_name)
    if chain is None:
        raise ValueError(f"chain {chain_name!r} is not configured on this storefront")

    thread = await sqlite_client.load_negotiation_thread_row(
        negotiation_id=negotiation_id,
    )
    if not thread:
        raise ValueError(f"Unknown negotiation {negotiation_id}")
    if thread.get("terminal_state") != "success":
        raise ValueError(
            f"Negotiation {negotiation_id} is not terminal-success "
            f"(terminal_state={thread.get('terminal_state')!r})"
        )
    if thread.get("agreed_price") is None:
        raise ValueError(f"Negotiation {negotiation_id} has no agreed_price committed")
    buyer_principal = Identity.model_validate(thread.get("buyer_principal"))
    seller_principal = Identity.model_validate(thread.get("seller_principal"))
    if request.buyer_principal != buyer_principal:
        raise ValueError("settlement buyer principal does not match negotiation")
    if seller_principal != local_principal:
        raise ValueError("settlement seller principal does not match local identity")

    listing_id = thread.get("our_listing_id")
    order = (
        await sqlite_client.load_listing(listing_id=listing_id) if listing_id else None
    )
    if not order:
        raise ValueError(
            f"Seller's order {listing_id!r} (from negotiation "
            f"{negotiation_id}) is gone from the local DB"
        )
    terms = await sqlite_client.load_credit_terms(negotiation_id=negotiation_id)
    if not terms:
        raise ValueError(
            f"Negotiation {negotiation_id} has no token terms recorded — "
            "cannot issue without a quantity"
        )

    proposal_raw = thread.get("buyer_escrow_proposal")
    proposal = (
        EscrowProposal.model_validate(proposal_raw)
        if isinstance(proposal_raw, dict)
        else None
    )
    matched_index = await verify_escrow_for_settlement(
        escrow_uid=escrow_uid,
        seller_wallet=settings.wallet.address or "",
        agreed_price=int(thread["agreed_price"]),
        agreed_duration_seconds=0,
        listing=order,
        alkahest_client=mechanism_client,
        chain_name=chain_name,
        alkahest_address_config_path=chain.alkahest_address_config_path,
        escrow_proposal=proposal,
    )

    settlement = get_market_domain_contract().settlement
    assert settlement is not None
    accepted = settlement.build_plan(
        proposal=proposal,
        agreed_amount=int(thread["agreed_price"]),
        buyer_principal=buyer_principal,
        seller_principal=seller_principal,
    )
    plan = accepted.get("settlement_plan")
    obligations_raw = plan.get("obligations") if isinstance(plan, dict) else None
    if not isinstance(obligations_raw, list) or not obligations_raw:
        raise ValueError(
            f"Negotiation {negotiation_id} has no accepted settlement obligations"
        )
    obligations = tuple(dict(obligation) for obligation in obligations_raw)
    expected_payer = buyer_principal.model_dump(mode="json")
    expected_claimant = seller_principal.model_dump(mode="json")
    for obligation in obligations:
        if obligation.get("payer_principal") != expected_payer:
            raise ValueError("settlement obligation payer principal mismatch")
        if obligation.get("claimant_principal") != expected_claimant:
            raise ValueError("settlement obligation claimant principal mismatch")
    if not isinstance(matched_index, int) or not 0 <= matched_index < len(obligations):
        raise ValueError(
            f"Verified obligation index {matched_index!r} is outside the accepted plan"
        )

    proposal_chain = proposal.chain_name if proposal is not None else None
    escrow_address = proposal.escrow_address if proposal is not None else None
    if proposal_chain is None or escrow_address is None:
        accepted_escrows = order.get("accepted_escrows") or []
        if accepted_escrows and isinstance(accepted_escrows[0], dict):
            proposal_chain = proposal_chain or accepted_escrows[0].get("chain_name")
            escrow_address = escrow_address or accepted_escrows[0].get("escrow_address")

    return PreparedSettlement(
        agreement_ref=negotiation_id,
        local_principal=local_principal,
        obligations=obligations,
        selected_obligation_index=matched_index,
        mechanism_ref=escrow_uid,
        mechanism_receipt={"escrow_uid": escrow_uid},
        fulfillment_input=ApiCreditsFulfillmentInput(
            chain_name=proposal_chain or chain_name,
            order=dict(order),
            quantity=int(terms["quantity"]),
            key_mode=str(terms.get("key_mode") or "new"),
            key_id=terms.get("key_id"),
            buyer_principal=buyer_principal,
            listing_id=listing_id,
            negotiation_id=negotiation_id,
        ),
        projection_context=ApiCreditsSettlementProjection(
            chain_name=proposal_chain or chain_name,
            escrow_address=escrow_address,
        ),
    )


async def reserve_api_credit_settlement(
    sqlite_client: Any,
    prepared: Any,
    escrow_uid: str,
    negotiation_id: str,
    *,
    settlement_runtime: Any,
    wake_servicing: Any,
) -> dict[str, Any] | None:
    """Create, bind, and recover the existing public settlement row."""
    from market_settlement_runtime import derive_obligation_ref

    projection = prepared.projection_context
    inserted = await sqlite_client.insert_escrow(
        escrow_uid=escrow_uid,
        negotiation_id=negotiation_id,
        chain_name=projection.chain_name,
        escrow_address=projection.escrow_address,
        is_primary=True,
        status="provisioning",
    )
    obligation_ref = derive_obligation_ref(
        prepared.agreement_ref,
        prepared.selected_obligation_index,
        prepared.obligations[prepared.selected_obligation_index],
    )
    row = await sqlite_client.bind_escrow_obligation(
        escrow_uid=escrow_uid,
        obligation_ref=obligation_ref,
        obligation_index=prepared.selected_obligation_index,
    )
    fulfillment_ref = row.get("fulfillment_uid")
    if (
        not inserted
        and row.get("status") == "ready"
        and isinstance(fulfillment_ref, str)
        and fulfillment_ref
    ):
        await settlement_runtime.bind_fulfillment(
            obligation_ref,
            fulfillment_ref,
            local_principal=prepared.local_principal,
        )
        await wake_servicing(obligation_ref)
    return None if inserted else row


async def fulfill_api_credit_settlement(
    prepared: Any,
    *,
    mechanism_client: Any,
) -> Any:
    """Issue credits and return only the immutable public fulfillment ref."""
    from market_settlement_runtime import FulfillmentOutcome

    fulfillment = get_market_domain_contract().fulfillment
    assert fulfillment is not None
    params = prepared.fulfillment_input
    try:
        result = await fulfillment.fulfill(
            client=mechanism_client,
            escrow_uid=prepared.mechanism_ref,
            order=params.order,
            quantity=params.quantity,
            key_mode=params.key_mode,
            key_id=params.key_id,
            buyer_principal=params.buyer_principal,
            listing_id=params.listing_id,
            negotiation_id=params.negotiation_id,
        )
    except Exception as exc:
        return FulfillmentOutcome(
            status="failed",
            reason=f"issuance_error: {exc}",
        )

    if (result or {}).get("status") != "fulfilled":
        return FulfillmentOutcome(
            status="failed",
            reason=(result or {}).get("message")
            or f"status={(result or {}).get('status')!r}",
        )
    return FulfillmentOutcome(
        status="fulfilled",
        fulfillment_ref=result.get("fulfillment_uid"),
        public_result={
            key: result[key]
            for key in ("connection_details",)
            if result.get(key) is not None
        },
        private_result=result.get("tenant_credentials"),
    )


async def persist_api_credit_settlement_outcome(
    sqlite_client: Any,
    prepared: Any,
    outcome: Any,
) -> None:
    """Project generic completion into the unchanged settle-status row."""
    if outcome.status == "fulfilled":
        await sqlite_client.update_escrow(
            escrow_uid=prepared.mechanism_ref,
            status="ready",
            fulfillment_uid=outcome.fulfillment_ref,
            connection_details=outcome.public_result.get("connection_details"),
            tenant_credentials=(
                json.dumps(outcome.private_result)
                if outcome.private_result is not None
                else None
            ),
        )
        return
    await sqlite_client.update_escrow(
        escrow_uid=prepared.mechanism_ref,
        status="failed",
        reason=outcome.reason or "fulfillment failed",
    )


def serialize_api_credit_settlement_start(
    row: dict[str, Any],
) -> dict[str, Any]:
    """Keep the established initial 202 response free of runtime identity."""
    return {
        "escrow_uid": row.get("escrow_uid"),
        "negotiation_id": row.get("negotiation_id"),
        "status": row.get("status"),
    }


def serialize_api_credit_settlement(row: dict[str, Any]) -> dict[str, Any]:
    """Keep the established API-credit settle/status JSON projection."""
    out: dict[str, Any] = {
        "escrow_uid": row.get("escrow_uid"),
        "negotiation_id": row.get("negotiation_id"),
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    for field in (
        "fulfillment_uid",
        "chain_name",
        "escrow_address",
        "connection_details",
        "reason",
    ):
        value = row.get(field)
        if value is not None:
            out[field] = value
    if row.get("is_primary") is not None:
        out["is_primary"] = bool(row["is_primary"])
    credentials = row.get("tenant_credentials")
    if credentials:
        try:
            out["tenant_credentials"] = json.loads(credentials)
        except (TypeError, ValueError):
            out["tenant_credentials"] = credentials
    return out
