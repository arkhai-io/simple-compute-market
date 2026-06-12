"""Synchronous request-response negotiation — API-tokens flavor.

Same wire shape as the VM storefront (POST /negotiate/new and
/negotiate/{neg_id}; the seller's decision rides the HTTP response).
The domain differences: ``provision_terms`` carries
``{kind: "api_tokens.v1", payload: {quantity, key}}`` fixed at round 0,
the seller's reference amount is ``quantity × unit rate``, the chain
runs the quota + key-ownership guards, and the agreed terms persist a
``token_deal_terms`` row that settlement reads back for issuance.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from core_storefront.negotiation_sync import (
    LIVE_LISTING_STATUSES,
    OfferUnfulfillableError,
    StorefrontPausedError,
    coerce_pinned_proposal as _coerce_pinned_proposal,
    create_sync_negotiation_thread as _create_sync_negotiation_thread,
    history_from_messages as _history_from_messages,
    record_buyer_accept_message as _record_buyer_accept_message,
    record_buyer_counter_message as _record_buyer_counter_message,
    record_buyer_exit_message as _record_buyer_exit_message,
    record_seller_decision_message as _record_seller_decision_message,
)
from domains.apitokens.listings.models import coerce_resource_dict
from domains.apitokens.listings.pricing import (
    determine_strategy_from_order,
    extract_unit_price_from_order,
)
from domains.apitokens.negotiation.storefront_round import (
    ApiTokensSellerRoundHook,
    default_seller_round_hook,
)
from domains.apitokens.negotiation.terms import (
    provision_key_id,
    provision_key_mode,
    provision_quantity,
)
from market_policy.scalar_policies import _amount_from_proposal
from market_alkahest.proposals import accepted_escrow_artifacts_from_proposal
from market_core.schemas import EscrowProposal
from market_policy.negotiation_middleware import NegotiationRound

logger = logging.getLogger(__name__)

_LIVE_LISTING_STATUSES = LIVE_LISTING_STATUSES

# Credits don't expire; the duration input to plan materialization is
# inert for token deals (the negotiated amount is always concrete).
_NO_LEASE_DURATION_SECONDS = 0


def _negotiation_settings() -> Any:
    from apitokens_storefront.utils.config import settings

    return settings.get("negotiation")


def _chain_settings() -> dict[str, Any]:
    from apitokens_storefront.utils.config import CHAINS

    return dict(CHAINS)


def _default_min_price() -> Any:
    from apitokens_storefront.utils.config import settings

    return settings.get("pricing.default_min_price")


def _default_seller_round_hook(sqlite_client: Any) -> ApiTokensSellerRoundHook:
    from apitokens_storefront.services.capacity_client import build_capacity_client
    from apitokens_storefront.services.keys_lookup import lookup_key_record

    return default_seller_round_hook(
        build_capacity_client(lambda: sqlite_client),
        lookup_key_record,
        negotiation_config=_negotiation_settings(),
        chains=_chain_settings(),
        default_min_price=_default_min_price(),
    )


def _chain_config_paths() -> dict[str, str | None]:
    from apitokens_storefront.utils.config import CHAINS

    return {
        name: chain.alkahest_address_config_path
        for name, chain in CHAINS.items()
    }


def _seller_reference_amount(listing: dict[str, Any], quantity: int | None) -> int:
    unit = Decimal(str(
        extract_unit_price_from_order(
            listing, default_min_price=_default_min_price(),
        )
    ))
    return int(unit * int(quantity if quantity is not None else 1))


def _accepted_escrow_artifacts(
    *,
    proposal: EscrowProposal | dict[str, Any] | None,
    agreed_amount: int,
    uses_scalar_amount: bool = True,
) -> dict[str, Any]:
    artifacts = accepted_escrow_artifacts_from_proposal(
        proposal=proposal,
        agreed_amount=agreed_amount,
        duration_seconds=_NO_LEASE_DURATION_SECONDS,
        uses_scalar_amount=uses_scalar_amount,
        seller_wallet_address=None,
        chain_config_paths=_chain_config_paths(),
        heartbeat_interval_seconds=None,
    )
    error = artifacts.pop("accepted_escrow_terms_error", None)
    if error:
        logger.debug("Could not materialize accepted escrow terms: %s", error)
    return artifacts


async def _place_quota_hold(
    sqlite_client: Any,
    *,
    negotiation_id: str,
    listing_id: str | None,
    order_dict: dict[str, Any] | None,
    quantity: int | None,
) -> None:
    """Two-phase reserve: a TTL'd soft hold on the quota at acceptance.

    Settlement hands the held allocation_id to issuance, which commits
    it open-ended. Best-effort: a hold that can't be placed leaves
    acceptance untouched (issuance then reserves fresh), and a hold
    whose deal never settles auto-lapses at the ledger.
    """
    from core_storefront.stage_log import stage_event

    from apitokens_storefront.utils.config import settings as _settings

    ttl = float(_settings.get("capacity.hold_ttl_seconds", 0) or 0)
    if ttl <= 0 or not quantity:
        return
    try:
        from apitokens_storefront.services.capacity_client import (
            build_capacity_client,
        )

        offer = coerce_resource_dict((order_dict or {}).get("offer_resource"))
        claim: dict[str, Any] = {"units": int(quantity)}
        if offer.get("resource_id"):
            claim["resource_id"] = str(offer["resource_id"])
        capacity = build_capacity_client(lambda: sqlite_client)
        held = await capacity.reserve(
            claim=claim,
            deal_ref={
                "listing_id": listing_id,
                "negotiation_id": negotiation_id,
            },
            ttl_seconds=ttl,
        )
    except Exception as exc:
        logger.warning(
            "[NEGOTIATION] Could not place quota hold for %s: %s",
            negotiation_id, exc,
        )
        return
    if not held:
        stage_event(
            "negotiation", "capacity_hold_unavailable",
            negotiation_id=negotiation_id,
            listing_id=listing_id,
        )
        return
    await sqlite_client.save_capacity_hold(
        negotiation_id=negotiation_id,
        listing_id=listing_id,
        allocation_id=str(held["allocation_id"]),
        payload=held,
        expires_at=held.get("hold_expires_at"),
    )
    stage_event(
        "negotiation", "capacity_hold_placed",
        negotiation_id=negotiation_id,
        listing_id=listing_id,
        allocation_id=held.get("allocation_id"),
        resource_id=held.get("resource_id"),
        site=held.get("site"),
        hold_expires_at=held.get("hold_expires_at"),
    )


async def start_sync_negotiation(
    *,
    sqlite_client: Any,
    our_listing_id: str,
    buyer_address: str,
    proposal: EscrowProposal | None = None,
    provision_terms: Any = None,
    our_base_url: str,
    their_agent_url: str,
    seller_round_hook: ApiTokensSellerRoundHook | None = None,
) -> dict[str, Any]:
    """Create a new negotiation thread and return the seller's first response."""
    from core_storefront.stage_log import stage_event

    from apitokens_storefront.server import is_globally_paused

    if is_globally_paused():
        raise StorefrontPausedError("global")
    if await sqlite_client.is_listing_paused(listing_id=our_listing_id):
        raise StorefrontPausedError(f"order:{our_listing_id}")

    our_order_dict = await sqlite_client.load_listing(listing_id=our_listing_id)
    if not our_order_dict:
        raise ValueError(
            f"Order {our_listing_id} not found locally; seller has no matching listing"
        )
    listing_status = (our_order_dict.get("status") or "").strip()
    if listing_status not in _LIVE_LISTING_STATUSES:
        raise OfferUnfulfillableError(
            f"listing_not_open (status={listing_status!r})",
            listing_id=our_listing_id,
        )

    quantity = provision_quantity(provision_terms)
    key_mode = provision_key_mode(provision_terms)
    key_id = provision_key_id(provision_terms)

    proposal_dict = (
        proposal.model_dump()
        if proposal is not None and hasattr(proposal, "model_dump")
        else proposal
    )
    history = [NegotiationRound(
        round_number=0,
        sender="them",
        action="initial",
        proposal=proposal_dict,
    )]
    try:
        round_hook = seller_round_hook or _default_seller_round_hook(sqlite_client)
        round_result = await round_hook(
            listing=our_order_dict,
            history=history,
            requested_quantity=quantity,
            key_mode=key_mode,
            key_id=key_id,
            buyer_wallet=buyer_address,
        )
    except ValueError as exc:
        if "price-less" in str(exc) or "default_min_price" in str(exc):
            raise OfferUnfulfillableError(
                "no_floor_price", listing_id=our_listing_id,
            ) from exc
        raise
    our_amount = round_result.our_amount
    strategy = round_result.strategy_label
    decision = round_result.decision

    if decision.action == "reject":
        raise OfferUnfulfillableError(
            decision.reason or "rejected",
            listing_id=our_listing_id,
        )

    policy_intermediate = round_result.intermediate or {}
    accepted_proposal_dict = policy_intermediate.get("accepted_escrow_proposal")
    accepted_proposal = (
        EscrowProposal.model_validate(accepted_proposal_dict)
        if isinstance(accepted_proposal_dict, dict)
        else proposal
    )
    uses_scalar_amount = bool(policy_intermediate.get("uses_scalar_amount", True))
    their_amount = _amount_from_proposal(proposal_dict)
    their_amount = int(their_amount) if their_amount is not None else 0

    neg_id = "neg_" + uuid.uuid4().hex

    await _create_sync_negotiation_thread(
        negotiation_id=neg_id,
        our_listing_id=our_listing_id,
        their_listing_id="",
        our_agent_id=our_base_url,
        their_agent_id=their_agent_url,
        our_initial_amount=our_amount,
        our_strategy=strategy,
        requested_duration_seconds=None,
        buyer_escrow_proposal=(
            accepted_proposal.model_dump()
            if accepted_proposal is not None
            else None
        ),
        opening_sender=their_agent_url or buyer_address,
        opening_amount=their_amount,
    )
    # What is being bought — fixed at round 0, read back at settlement.
    if quantity is not None:
        await sqlite_client.save_token_terms(
            negotiation_id=neg_id,
            quantity=int(quantity),
            key_mode=key_mode,
            key_id=key_id,
        )

    await _record_seller_decision(
        neg_id=neg_id,
        our_amount=our_amount,
        their_amount=their_amount,
        decision=decision,
    )
    decision_amount = _amount_from_proposal(decision.proposal)
    if decision.action == "accept":
        agreed_amount = decision_amount if decision_amount is not None else our_amount
        await sqlite_client.commit_agreed_terms(
            negotiation_id=neg_id,
            agreed_price=int(agreed_amount),
            agreed_duration_seconds=0,
        )
        await _place_quota_hold(
            sqlite_client,
            negotiation_id=neg_id,
            listing_id=our_listing_id,
            order_dict=our_order_dict,
            quantity=quantity,
        )
    stage_event(
        "negotiation", "round_decided",
        negotiation_id=neg_id,
        round=0,
        our_amount=our_amount,
        their_amount=their_amount,
        decision=decision.action,
        decision_amount=int(decision_amount) if decision_amount is not None else None,
        decision_reason=decision.reason,
    )
    response: dict[str, Any] = {"negotiation_id": neg_id, **decision.to_dict()}
    if provision_terms is not None:
        response["accepted_provision_terms"] = (
            provision_terms.model_dump()
            if hasattr(provision_terms, "model_dump")
            else dict(provision_terms)
        )
    if accepted_proposal is not None:
        artifacts = _accepted_escrow_artifacts(
            proposal=accepted_proposal,
            agreed_amount=int(
                agreed_amount if decision.action == "accept" else our_amount
            ),
            uses_scalar_amount=uses_scalar_amount,
        )
        if decision.action == "accept":
            response.update(artifacts)
        else:
            response["accepted_escrow_proposal"] = artifacts[
                "accepted_escrow_proposal"
            ]
    return response


async def continue_sync_negotiation(
    *,
    sqlite_client: Any,
    neg_id: str,
    buyer_action: str,
    buyer_proposal: dict[str, Any] | None,
    buyer_reason: str | None,
    buyer_address: str,
    seller_round_hook: ApiTokensSellerRoundHook | None = None,
) -> dict[str, Any]:
    """Drive one further round against an existing thread."""
    from core_storefront.stage_log import stage_event

    thread = await sqlite_client.load_negotiation_thread_row(negotiation_id=neg_id)
    if not thread:
        raise ValueError(f"Unknown negotiation {neg_id}")
    if thread.get("terminal_state"):
        raise ValueError(
            f"Negotiation {neg_id} is already in terminal state "
            f"{thread.get('terminal_state')!r}",
        )

    our_listing_id = thread.get("our_listing_id")
    our_order_dict = (
        await sqlite_client.load_listing(listing_id=our_listing_id)
        if our_listing_id else None
    )
    if not our_order_dict:
        raise ValueError(f"Seller's order {our_listing_id} is gone from local DB")
    strategy = determine_strategy_from_order(our_order_dict)

    terms = await sqlite_client.load_token_terms(negotiation_id=neg_id) or {}
    quantity = terms.get("quantity")
    key_mode = terms.get("key_mode") or "new"
    key_id = terms.get("key_id")

    buyer_pinned_proposal = _coerce_pinned_proposal(thread.get("buyer_escrow_proposal"))
    pinned_fields = (
        buyer_pinned_proposal.get("fields")
        if isinstance(buyer_pinned_proposal, dict)
        else None
    )
    uses_scalar_amount = isinstance(pinned_fields, dict) and "amount" in pinned_fields
    our_amount = (
        _seller_reference_amount(our_order_dict, quantity)
        if uses_scalar_amount else 0
    )

    messages = await sqlite_client.load_negotiation_thread(negotiation_id=neg_id)

    if buyer_action == "accept":
        from decimal import Decimal as _Decimal

        last_seller_amount = next(
            (int(_Decimal(str(m["proposed_price"]))) for m in reversed(messages)
             if m.get("action_taken") == "counter_offer"
             and m.get("sender") != buyer_address),
            our_amount,
        )
        await _record_buyer_accept_message(
            negotiation_id=neg_id,
            sender=buyer_address,
            our_amount=our_amount,
            accepted_amount=last_seller_amount,
        )
        await sqlite_client.commit_agreed_terms(
            negotiation_id=neg_id,
            agreed_price=int(last_seller_amount),
            agreed_duration_seconds=0,
        )
        await _place_quota_hold(
            sqlite_client,
            negotiation_id=neg_id,
            listing_id=our_listing_id,
            order_dict=our_order_dict,
            quantity=quantity,
        )
        stage_event(
            "negotiation", "accepted",
            negotiation_id=neg_id,
            agreed_amount=last_seller_amount,
            our_initial_amount=our_amount,
        )
        response: dict[str, Any] = {"action": "accept"}
        response.update(
            _accepted_escrow_artifacts(
                proposal=buyer_pinned_proposal,
                agreed_amount=int(last_seller_amount),
                uses_scalar_amount=uses_scalar_amount,
            )
        )
        return response

    if buyer_action == "exit":
        await _record_buyer_exit_message(
            negotiation_id=neg_id,
            sender=buyer_address,
            our_amount=our_amount,
        )
        stage_event(
            "negotiation", "exited",
            negotiation_id=neg_id,
            reason=buyer_reason or "buyer_exit",
        )
        return {"action": "exit", "reason": "buyer_exit"}

    if buyer_action != "counter":
        raise ValueError(f"Unsupported buyer action {buyer_action!r}")

    from apitokens_storefront.utils.config import BASE_URL_OVERRIDE

    our_sender = BASE_URL_OVERRIDE or "seller"
    history = _history_from_messages(
        messages, our_sender, buyer_pinned_proposal=buyer_pinned_proposal,
    )
    history.append(NegotiationRound(
        round_number=len(history),
        sender="them",
        action="counter",
        proposal=buyer_proposal or buyer_pinned_proposal,
    ))
    round_hook = seller_round_hook or _default_seller_round_hook(sqlite_client)
    round_result = await round_hook(
        listing=our_order_dict,
        history=history,
        requested_quantity=quantity,
        key_mode=key_mode,
        key_id=key_id,
        buyer_wallet=buyer_address,
        strategy_label=strategy,
    )
    policy_intermediate = round_result.intermediate or {}
    uses_scalar_amount = bool(
        policy_intermediate.get("uses_scalar_amount", uses_scalar_amount),
    )
    fallback_buyer_amount = _amount_from_proposal(buyer_proposal)
    buyer_amount = int(
        policy_intermediate.get(
            "buyer_amount",
            fallback_buyer_amount if fallback_buyer_amount is not None else 0,
        ),
    )
    our_amount = round_result.our_amount
    await _record_buyer_counter_message(
        negotiation_id=neg_id,
        sender=buyer_address,
        our_amount=our_amount,
        counter_amount=buyer_amount,
    )
    decision = round_result.decision
    await _record_seller_decision(
        neg_id=neg_id, our_amount=our_amount,
        their_amount=buyer_amount, decision=decision,
    )
    decision_amount = _amount_from_proposal(decision.proposal)
    if decision.action == "accept":
        agreed_amount = decision_amount if decision_amount is not None else our_amount
        await sqlite_client.commit_agreed_terms(
            negotiation_id=neg_id,
            agreed_price=int(agreed_amount),
            agreed_duration_seconds=0,
        )
        await _place_quota_hold(
            sqlite_client,
            negotiation_id=neg_id,
            listing_id=our_listing_id,
            order_dict=our_order_dict,
            quantity=quantity,
        )
    stage_event(
        "negotiation", "round_decided",
        negotiation_id=neg_id,
        round=len(history),
        our_amount=our_amount,
        their_amount=buyer_amount,
        decision=decision.action,
        decision_amount=int(decision_amount) if decision_amount is not None else None,
        decision_reason=decision.reason,
    )
    response = decision.to_dict()
    if decision.action == "accept":
        response.update(
            _accepted_escrow_artifacts(
                proposal=buyer_pinned_proposal,
                agreed_amount=(
                    int(decision_amount)
                    if decision_amount is not None
                    else int(our_amount)
                ),
                uses_scalar_amount=uses_scalar_amount,
            )
        )
    return response


async def _record_seller_decision(
    *,
    neg_id: str,
    our_amount: int,
    their_amount: int,
    decision: Any,
) -> None:
    from apitokens_storefront.utils.config import BASE_URL_OVERRIDE

    sender = BASE_URL_OVERRIDE or "seller"
    decision_amount = _amount_from_proposal(decision.proposal)
    await _record_seller_decision_message(
        negotiation_id=neg_id,
        sender=sender,
        our_amount=our_amount,
        their_amount=their_amount,
        decision=decision,
        decision_amount=(
            int(decision_amount) if decision_amount is not None else None
        ),
    )
