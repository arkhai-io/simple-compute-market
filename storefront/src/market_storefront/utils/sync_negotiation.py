"""Synchronous request-response negotiation.

Buyer drives every round via `POST /negotiate/{id}` (or `/new`); the
seller's decision is returned in the HTTP response body instead of
being pushed back as a separate message.

Shape:

    POST /negotiate/new
      {seller_order_id, buyer_address, initial_price}
      → {neg_id, action: "counter"|"accept"|"exit"|"reject", price?, reason?}

    POST /negotiate/{neg_id}
      {action: "counter"|"accept"|"exit", price?, reason?, buyer_address}
      → {action, price?, reason?}

`action` in the request is what the buyer is proposing *in this round*.
`action` in the response is the seller's resulting decision.

Negotiation state is persisted in the existing `negotiation_threads` +
`negotiation_messages` tables. The per-round decision lives in
`market_policy.negotiation_strategy` so both buyer and storefront drive
rounds through the same engine.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from market_policy.negotiation_strategy import (
    DEFAULT_STRATEGY,
    NegotiationDecision,
    NegotiationRound,
    NegotiationRoundInput,
    load_strategy,
)

logger = logging.getLogger(__name__)


class StorefrontPausedError(Exception):
    """Raised when a new negotiation is attempted while the storefront (or the
    specific order) is paused.

    The negotiate endpoints convert this to HTTP 503 with a machine-readable
    body so callers can distinguish a pause from a real server error.
    """

    def __init__(self, reason: str = "paused") -> None:
        super().__init__(reason)
        self.reason = reason


def _maybe_register_rl_strategy() -> None:
    """Trigger self-registration of the torch RL strategy.

    The strategy module calls ``register_strategy("rl", ...)`` at import
    time. If torch / pufferlib aren't installed, the import fails — we
    swallow it and let ``load_strategy("rl")`` raise the actionable
    KeyError so callers get a clear "install with [rl] extras" message.
    """
    try:
        import domain.compute.agent.app.policy.torch_arkhai_strategy  # noqa: F401
    except Exception as exc:
        logger.debug("[NEGOTIATION] torch_arkhai_strategy not available: %s", exc)


def _load_storefront_strategy():
    """Resolve the storefront's configured strategy.

    Selected via ``CONFIG.negotiation_policy_mode``; defaults to the
    registered default ("rl") if unset. Triggers the torch strategy's
    self-registration on first call.
    """
    from market_storefront.utils.config import CONFIG
    name = (CONFIG.negotiation_policy_mode or "").strip() or None
    if (name or DEFAULT_STRATEGY) == "rl":
        _maybe_register_rl_strategy()
    return load_strategy(name)


def _direction_from_strategy_label(strategy: str) -> str:
    """Translate the storefront's per-order strategy ('minimize'|'maximize')
    into the symmetric negotiation direction. They happen to match
    today; the indirection makes any future schema drift obvious."""
    if strategy in ("minimize", "maximize"):
        return strategy
    raise ValueError(f"Unknown order strategy {strategy!r}")


def _history_from_messages(messages: list[dict[str, Any]], our_sender: str) -> list[NegotiationRound]:
    """Convert the SQLite-flavored thread messages into the symmetric
    NegotiationRound shape strategies consume."""
    out: list[NegotiationRound] = []
    for i, m in enumerate(messages):
        sender = "us" if m.get("sender") == our_sender else "them"
        action_taken = m.get("action_taken", "")
        if action_taken == "make_offer":
            action = "initial"
        elif action_taken == "counter_offer":
            action = "counter"
        elif action_taken == "accept_offer":
            action = "accept"
        elif action_taken in ("exit_negotiation",):
            action = "exit"
        else:
            action = "counter"
        price = m.get("proposed_price")
        out.append(NegotiationRound(
            round_number=i,
            sender=sender,
            action=action,
            price=int(price) if price is not None else None,
        ))
    return out


# ---------------------------------------------------------------------------
# Stateful wrappers — load/save thread, call the configured strategy.
# ---------------------------------------------------------------------------


async def start_sync_negotiation(
    *,
    sqlite_client: Any,
    our_listing_id: str,
    buyer_address: str,
    their_proposed_price: int,
    our_base_url: str,
    their_agent_url: str,
) -> dict[str, Any]:
    """Create a new negotiation thread and return the seller's first response.

    Generates a fresh ``negotiation_id`` (uuid4) and returns it to the
    buyer in the response. The buyer captures it from the response and
    uses it for all subsequent ``/negotiate/{neg_id}`` rounds — the
    canonical id is server-assigned, not client-derived.

    Raises ``ValueError`` if ``our_listing_id`` isn't in the local DB
    (seller must have published; no ad-hoc negotiations without a
    listing).
    """
    # Imports deferred so unit tests can patch the registry / thread store
    # without paying for the whole import graph.
    from market_policy.negotiation_thread import NegotiationThreadTransaction
    from market_storefront.schema.pydantic_models import Listing
    from market_storefront.utils.action_executor import (
        _extract_initial_price_from_order,
        determine_strategy_from_order,
    )
    from market_storefront.utils.stage_log import stage_event

    # Check global pause flag and per-order pause flag before doing any work.
    from market_storefront.server import is_globally_paused
    if is_globally_paused():
        raise StorefrontPausedError("global")

    if await sqlite_client.is_listing_paused(listing_id=our_listing_id):
        raise StorefrontPausedError(f"order:{our_listing_id}")

    our_order_dict = await sqlite_client.load_listing(listing_id=our_listing_id)
    if not our_order_dict:
        raise ValueError(f"Order {our_listing_id} not found locally; seller has no matching listing")

    our_order = Listing.model_validate(our_order_dict)
    strategy = determine_strategy_from_order(our_order)
    if not strategy:
        raise ValueError(f"Order {our_listing_id} has no usable strategy for negotiation")
    our_price = _extract_initial_price_from_order(our_order)

    neg_id = "neg_" + uuid.uuid4().hex

    async with NegotiationThreadTransaction("SYNC_NEGOTIATE_NEW") as txn:
        await txn.ensure_thread(
            negotiation_id=neg_id,
            our_listing_id=our_listing_id,
            their_listing_id="",  # buyer has no listing; engine column kept for symmetric schema
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

    strategy_obj = _load_storefront_strategy()
    decision = strategy_obj.decide(NegotiationRoundInput(
        direction=_direction_from_strategy_label(strategy),
        our_reference_price=our_price,
        their_proposed_price=their_proposed_price,
        history=[],
    ))
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
    from market_storefront.schema.pydantic_models import Listing
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

    our_listing_id = thread.get("our_listing_id")
    our_order_dict = await sqlite_client.load_listing(listing_id=our_listing_id) if our_listing_id else None
    if not our_order_dict:
        raise ValueError(f"Seller's order {our_listing_id} is gone from local DB")
    our_order = Listing.model_validate(our_order_dict)
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
            agreed_duration_hours=int((our_order_dict.get("max_duration_seconds") or 3600) // 3600),
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

    from market_storefront.utils.config import CONFIG as _CONFIG
    our_sender = _CONFIG.base_url_override or "seller"
    strategy_obj = _load_storefront_strategy()
    decision = strategy_obj.decide(NegotiationRoundInput(
        direction=_direction_from_strategy_label(strategy),
        our_reference_price=our_price,
        their_proposed_price=int(buyer_price),
        history=_history_from_messages(messages, our_sender),
    ))
    await _record_seller_decision(
        neg_id=neg_id, our_price=our_price,
        their_price=int(buyer_price), decision=decision,
    )
    if decision.action == "accept":
        await sqlite_client.commit_agreed_terms(
            negotiation_id=neg_id,
            agreed_price=int(decision.price),
            agreed_duration_hours=int((our_order_dict.get("max_duration_seconds") or 3600) // 3600),
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
    decision: NegotiationDecision,
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
