"""Polling-mode settlement for the API-tokens domain.

Same wire shape as the VM storefront (POST /settle/{escrow_uid} kicks
off fulfillment; GET /settle/{escrow_uid}/status polls), same fail-closed
on-chain verification before any side effect. Fulfillment is an
issuance job against the tokens service instead of VM provisioning;
the buyer's credentials ({key_id, secret?, base_url}) ride the
``tenant_credentials`` channel, delivered once.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from core_storefront.escrow_verification import verify_escrow_for_settlement
from domains.apitokens.listings.models import coerce_resource_dict
from market_core.schemas import EscrowProposal

logger = logging.getLogger(__name__)


async def start_settlement_job(
    *,
    escrow_uid: str,
    negotiation_id: str,
    sqlite_client: Any,
    alkahest_client: Any,
    chain_name: str,
) -> dict[str, Any]:
    """Verify the escrow against the negotiated terms and kick off issuance.

    Mirrors the VM ``start_settlement_job``: terminal-success thread with
    agreed terms, fail-closed on-chain verification, idempotent escrows
    row, background fulfillment, claim registration for collection.
    """
    from apitokens_storefront.utils.config import CHAINS

    chain_cfg = CHAINS.get(chain_name)
    if chain_cfg is None:
        raise ValueError(
            f"chain {chain_name!r} is not configured on this storefront"
        )

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

    our_listing_id = thread.get("our_listing_id")
    our_order_dict = (
        await sqlite_client.load_listing(listing_id=our_listing_id)
        if our_listing_id else None
    )
    if not our_order_dict:
        raise ValueError(
            f"Seller's order {our_listing_id!r} (from negotiation "
            f"{negotiation_id}) is gone from the local DB"
        )

    terms = await sqlite_client.load_token_terms(negotiation_id=negotiation_id)
    if not terms:
        raise ValueError(
            f"Negotiation {negotiation_id} has no token terms recorded — "
            "cannot issue without a quantity"
        )

    proposal_raw = thread.get("buyer_escrow_proposal")
    proposal: EscrowProposal | None = None
    if isinstance(proposal_raw, dict):
        proposal = EscrowProposal.model_validate(proposal_raw)

    from apitokens_storefront.utils.config import settings

    await verify_escrow_for_settlement(
        escrow_uid=escrow_uid,
        seller_wallet=settings.wallet.address or "",
        agreed_price=int(thread["agreed_price"]),
        # Credits don't expire; duration is inert for token escrows (the
        # negotiated amount is always concrete).
        agreed_duration_seconds=0,
        listing=our_order_dict,
        alkahest_client=alkahest_client,
        chain_name=chain_name,
        alkahest_address_config_path=chain_cfg.alkahest_address_config_path,
        escrow_proposal=proposal,
    )

    proposal_chain = proposal.chain_name if proposal is not None else None
    escrow_address = proposal.escrow_address if proposal is not None else None
    if proposal_chain is None or escrow_address is None:
        accepted = our_order_dict.get("accepted_escrows") or []
        if accepted and isinstance(accepted[0], dict):
            proposal_chain = proposal_chain or accepted[0].get("chain_name")
            escrow_address = escrow_address or accepted[0].get("escrow_address")

    inserted = await sqlite_client.insert_escrow(
        escrow_uid=escrow_uid,
        negotiation_id=negotiation_id,
        chain_name=proposal_chain or chain_name,
        escrow_address=escrow_address,
        is_primary=True,
        status="provisioning",
    )
    if not inserted:
        existing = await sqlite_client.load_escrow(escrow_uid=escrow_uid)
        logger.info(
            "[SETTLE_JOB] Job already exists for escrow %s: status=%s",
            escrow_uid, (existing or {}).get("status"),
        )
        return existing or {}

    from apitokens_storefront.services.claims_runtime import derive_claim_obligation

    claim_obligation = derive_claim_obligation(
        proposal=proposal,
        agreed_amount=int(thread["agreed_price"]),
    )

    asyncio.create_task(
        _run_settlement_job_bg(
            escrow_uid=escrow_uid,
            terms=terms,
            buyer_wallet=thread.get("buyer") or thread.get("their_agent_id"),
            listing_id=our_listing_id,
            order_dict=our_order_dict,
            sqlite_client=sqlite_client,
            alkahest_client=alkahest_client,
            negotiation_id=negotiation_id,
            claim_obligation=claim_obligation,
            claim_chain_name=proposal_chain or chain_name,
            claim_escrow_address=escrow_address,
        )
    )

    return {
        "escrow_uid": escrow_uid,
        "negotiation_id": negotiation_id,
        "status": "provisioning",
    }


async def _run_settlement_job_bg(
    *,
    escrow_uid: str,
    terms: dict[str, Any],
    buyer_wallet: str | None,
    listing_id: str | None,
    order_dict: dict[str, Any],
    sqlite_client: Any,
    alkahest_client: Any,
    negotiation_id: str | None = None,
    claim_obligation: dict[str, Any] | None = None,
    claim_chain_name: str | None = None,
    claim_escrow_address: str | None = None,
) -> None:
    """Background coroutine: run issuance fulfillment, patch the job row."""
    from apitokens_storefront.services.fulfillment_service import (
        fulfill_token_obligation,
    )

    try:
        result = await fulfill_token_obligation(
            client=alkahest_client,
            escrow_uid=escrow_uid,
            order=order_dict,
            quantity=int(terms["quantity"]),
            key_mode=terms.get("key_mode") or "new",
            key_id=terms.get("key_id"),
            buyer_wallet=buyer_wallet,
            listing_id=listing_id,
            negotiation_id=negotiation_id,
        )
    except Exception as exc:
        logger.exception(
            "[SETTLE_JOB] fulfill_token_obligation raised for %s", escrow_uid,
        )
        await sqlite_client.update_escrow(
            escrow_uid=escrow_uid,
            status="failed",
            reason=f"issuance_error: {exc}",
        )
        return

    status = (result or {}).get("status")
    if status == "fulfilled":
        await sqlite_client.update_escrow(
            escrow_uid=escrow_uid,
            status="ready",
            fulfillment_uid=result.get("fulfillment_uid"),
            connection_details=result.get("connection_details"),
            tenant_credentials=(
                json.dumps(result.get("tenant_credentials"))
                if result.get("tenant_credentials") is not None else None
            ),
        )
        logger.info("[SETTLE_JOB] Escrow %s issuance complete", escrow_uid)
        if alkahest_client is not None:
            from apitokens_storefront.services.claims_runtime import submit_claim

            try:
                await submit_claim(
                    sqlite_client=sqlite_client,
                    escrow_uid=escrow_uid,
                    fulfillment_uid=result.get("fulfillment_uid"),
                    negotiation_id=negotiation_id,
                    listing_id=listing_id,
                    obligation=claim_obligation,
                    chain_name=claim_chain_name,
                    escrow_address=claim_escrow_address,
                )
            except Exception:
                logger.exception(
                    "[SETTLE_JOB] claim submission failed for %s — "
                    "collection will not happen until resubmitted",
                    escrow_uid,
                )
    else:
        reason = (result or {}).get("message") or f"status={status!r}"
        await sqlite_client.update_escrow(
            escrow_uid=escrow_uid,
            status="failed",
            reason=reason,
        )
        logger.warning(
            "[SETTLE_JOB] Escrow %s issuance did not succeed: %s",
            escrow_uid, reason,
        )


def serialize_settlement_job(row: dict[str, Any]) -> dict[str, Any]:
    """Shape a raw escrows row for the HTTP response."""
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
        v = row.get(field)
        if v is not None:
            out[field] = v
    if row.get("is_primary") is not None:
        out["is_primary"] = bool(row["is_primary"])
    tc_raw = row.get("tenant_credentials")
    if tc_raw:
        try:
            out["tenant_credentials"] = json.loads(tc_raw)
        except Exception:
            out["tenant_credentials"] = tc_raw
    return out


def listing_offer_resource(order_dict: dict[str, Any]) -> dict[str, Any]:
    """The listing's offer_resource as a dict (SQLite may store JSON text)."""
    return coerce_resource_dict(order_dict.get("offer_resource"))
