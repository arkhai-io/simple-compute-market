"""Synchronous request-response negotiation.

Buyer drives every round via `POST /negotiate/{id}` (or `/new`); the
seller's decision is returned in the HTTP response body instead of
being pushed back as a separate message.

Shape:

    POST /negotiate/new
      {seller_order_id, buyer_order_id, buyer_address, initial_price}
      → {neg_id, action: "counter"|"accept"|"exit"|"reject", price?, reason?}

    POST /negotiate/{neg_id}
      {action: "counter"|"accept"|"exit", price?, reason?, buyer_address}
      → {action, price?, reason?}

`action` in the request is what the buyer is proposing *in this round*.
`action` in the response is the seller's resulting decision.

Negotiation state is persisted in the existing `negotiation_threads` +
`negotiation_messages` tables. The per-round decision lives in
`market_policy.negotiation_round` so both buyer and storefront drive
rounds through the same engine.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from market_policy.negotiation_round import SellerDecision, decide_response

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stateful wrappers — load/save thread, call decide_response.
# ---------------------------------------------------------------------------


async def start_sync_negotiation(
    *,
    sqlite_client: Any,
    our_order_id: str,
    their_order_id: str,
    buyer_address: str,
    their_proposed_price: int,
    our_base_url: str,
    their_agent_url: str,
) -> dict[str, Any]:
    """Create a new negotiation thread and return the seller's first response.

    - `sqlite_client` must expose upsert_negotiation_thread-like helpers
      via the thread store; we use existing NegotiationThreadTransaction.
    - Raises ValueError if our_order isn't in the local DB (seller must
      have published; no ad-hoc negotiations without a listing).
    """
    # Imports deferred so unit tests can patch the registry / thread store
    # without paying for the whole import graph.
    from market_policy.negotiation_thread import NegotiationThreadTransaction
    from market_policy.action_builders import make_negotiation_id
    from market_storefront.schema.pydantic_models import MarketOrder
    from market_storefront.utils.action_executor import (
        _extract_initial_price_from_order,
        determine_strategy_from_order,
    )
    from market_storefront.utils.stage_log import stage_event

    our_order_dict = await sqlite_client.load_order(order_id=our_order_id)
    if not our_order_dict:
        raise ValueError(f"Order {our_order_id} not found locally; seller has no matching listing")

    our_order = MarketOrder.model_validate(our_order_dict)
    strategy = determine_strategy_from_order(our_order)
    if not strategy:
        raise ValueError(f"Order {our_order_id} has no usable strategy for negotiation")
    our_price = _extract_initial_price_from_order(our_order)

    neg_id = make_negotiation_id(our_order_id, their_order_id)

    async with NegotiationThreadTransaction("SYNC_NEGOTIATE_NEW") as txn:
        await txn.ensure_thread(
            negotiation_id=neg_id,
            our_order_id=our_order_id,
            their_order_id=their_order_id,
            our_agent_id=our_base_url,
            their_agent_id=their_agent_url,
            our_initial_price=our_price,
            our_strategy=strategy,
        )
        # Round-0 record of the buyer's opening proposal.
        await txn.add_message(
            negotiation_id=neg_id,
            sender=their_agent_url or buyer_address,
            our_price=our_price,
            their_price=their_proposed_price,
            proposed_price=their_proposed_price,
            action_taken="make_offer",
            message_type="offer",
        )

    decision = decide_response(
        strategy=strategy,
        our_price=our_price,
        their_proposed_price=their_proposed_price,
        our_previous_counters=[],
    )
    await _record_seller_decision(neg_id=neg_id, our_price=our_price,
                                  their_price=their_proposed_price,
                                  decision=decision)
    stage_event(
        "negotiation", "round_decided",
        negotiation_id=neg_id,
        round=0,
        our_price=our_price,
        their_price=their_proposed_price,
        decision=decision.action,
        decision_price=decision.price,
    )
    return {"negotiation_id": neg_id, **decision.to_dict()}


async def continue_sync_negotiation(
    *,
    sqlite_client: Any,
    neg_id: str,
    buyer_action: str,
    buyer_price: int | None,
    buyer_reason: str | None,
    buyer_address: str,
) -> dict[str, Any]:
    """Drive one further round against an existing thread.

    `buyer_action` is the action the buyer is proposing this round:
      - "counter" with `buyer_price`: the buyer's new price offer.
      - "accept": the buyer accepts the seller's last counter; we
        commit agreed_terms and return action=accept in response.
      - "exit": the buyer is walking away; we mark the thread terminal.
    """
    from market_policy.negotiation_thread import NegotiationThreadTransaction
    from market_storefront.schema.pydantic_models import MarketOrder
    from market_storefront.utils.action_executor import (
        _extract_initial_price_from_order,
        determine_strategy_from_order,
    )
    from market_storefront.utils.stage_log import stage_event

    thread = await sqlite_client.load_negotiation_thread_row(negotiation_id=neg_id)
    if not thread:
        raise ValueError(f"Unknown negotiation {neg_id}")
    if thread.get("terminal_state"):
        raise ValueError(
            f"Negotiation {neg_id} is already in terminal state "
            f"{thread.get('terminal_state')!r}",
        )

    our_order_id = thread.get("our_order_id")
    our_order_dict = await sqlite_client.load_order(order_id=our_order_id) if our_order_id else None
    if not our_order_dict:
        raise ValueError(f"Seller's order {our_order_id} is gone from local DB")
    our_order = MarketOrder.model_validate(our_order_dict)
    strategy = determine_strategy_from_order(our_order)
    our_price = _extract_initial_price_from_order(our_order)

    messages = await sqlite_client.load_negotiation_thread(negotiation_id=neg_id)
    our_previous_counters = [
        int(m["proposed_price"])
        for m in messages
        if m.get("action_taken") == "counter_offer"
        and m.get("proposed_price") is not None
    ]

    # Buyer-declared action short-circuits (accept / exit). No policy call.
    if buyer_action == "accept":
        # The buyer is accepting our last offered price. Commit terms.
        last_seller_price = next(
            (int(m["proposed_price"]) for m in reversed(messages)
             if m.get("action_taken") == "counter_offer" and m.get("sender") != buyer_address),
            our_price,
        )
        async with NegotiationThreadTransaction("SYNC_NEGOTIATE_ACCEPT") as txn:
            await txn.add_message(
                negotiation_id=neg_id,
                sender=buyer_address,
                our_price=our_price,
                their_price=last_seller_price,
                proposed_price=last_seller_price,
                action_taken="accept_offer",
                message_type="accepted",
            )
            await txn.mark_terminal(neg_id, "success")
        await sqlite_client.commit_agreed_terms(
            negotiation_id=neg_id,
            agreed_price=last_seller_price,
            agreed_duration_hours=int(our_order_dict.get("duration_hours") or 1),
        )
        stage_event(
            "negotiation", "accepted",
            negotiation_id=neg_id,
            agreed_price=last_seller_price,
            our_initial_price=our_price,
        )
        return {"action": "accept", "price": last_seller_price}

    if buyer_action == "exit":
        async with NegotiationThreadTransaction("SYNC_NEGOTIATE_EXIT") as txn:
            await txn.add_message(
                negotiation_id=neg_id,
                sender=buyer_address,
                our_price=our_price,
                their_price=None,
                proposed_price=None,
                action_taken="exit_negotiation",
                message_type="exit",
            )
            await txn.mark_terminal(neg_id, "failure")
        stage_event(
            "negotiation", "exited",
            negotiation_id=neg_id,
            reason=buyer_reason or "buyer_exit",
        )
        return {"action": "exit", "reason": "buyer_exit"}

    # Counter: call the policy.
    if buyer_action != "counter":
        raise ValueError(f"Unsupported buyer action {buyer_action!r}")
    if buyer_price is None:
        raise ValueError("counter requires 'price'")

    # Record the buyer's counter before deciding — symmetric with round-0
    # recording in start_sync_negotiation.
    async with NegotiationThreadTransaction("SYNC_NEGOTIATE_BUYER_COUNTER") as txn:
        await txn.add_message(
            negotiation_id=neg_id,
            sender=buyer_address,
            our_price=our_price,
            their_price=int(buyer_price),
            proposed_price=int(buyer_price),
            action_taken="counter_offer",
            message_type="counter_proposal",
        )

    decision = decide_response(
        strategy=strategy,
        our_price=our_price,
        their_proposed_price=int(buyer_price),
        our_previous_counters=our_previous_counters,
    )
    await _record_seller_decision(
        neg_id=neg_id, our_price=our_price,
        their_price=int(buyer_price), decision=decision,
    )
    if decision.action == "accept":
        await sqlite_client.commit_agreed_terms(
            negotiation_id=neg_id,
            agreed_price=int(decision.price),
            agreed_duration_hours=int(our_order_dict.get("duration_hours") or 1),
        )
    stage_event(
        "negotiation", "round_decided",
        negotiation_id=neg_id,
        round=len(our_previous_counters) + 1,
        our_price=our_price,
        their_price=int(buyer_price),
        decision=decision.action,
        decision_price=decision.price,
    )
    return decision.to_dict()


async def _record_seller_decision(
    *,
    neg_id: str,
    our_price: int,
    their_price: int,
    decision: SellerDecision,
) -> None:
    """Persist the seller's decision as a message + terminal state if applicable."""
    from market_policy.negotiation_thread import NegotiationThreadTransaction
    from market_storefront.utils.config import CONFIG

    sender = CONFIG.base_url_override or "seller"
    action_taken_map = {
        "counter": "counter_offer",
        "accept": "accept_offer",
        "exit": "exit_negotiation",
        "reject": "exit_negotiation",  # reject reuses exit terminal state
    }
    action_taken = action_taken_map[decision.action]
    message_type_map = {
        "counter": "counter_proposal",
        "accept": "accepted",
        "exit": "exit",
        "reject": "exit",
    }

    async with NegotiationThreadTransaction("SYNC_NEGOTIATE_SELLER_DECISION") as txn:
        await txn.add_message(
            negotiation_id=neg_id,
            sender=sender,
            our_price=our_price,
            their_price=their_price,
            proposed_price=decision.price if decision.price is not None else their_price,
            action_taken=action_taken,
            message_type=message_type_map[decision.action],
        )
        if decision.action in ("accept",):
            await txn.mark_terminal(neg_id, "success")
        elif decision.action in ("exit", "reject"):
            await txn.mark_terminal(neg_id, "failure")
