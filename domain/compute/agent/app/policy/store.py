from __future__ import annotations

import logging
from typing import Any

from core.agent.app.schema.pydantic_models import (
    Action as DomainAction,
    ActionType as DomainActionType,
    AcceptOfferEvent,
    ReceiveComputeObligationFulfillmentEvent,
    ArbitrationCompleteEvent,
    DecisionContext,
    MakeOfferEvent,
    MarketOrder,
    NegotiationEvent,
    ComputeResource,
    TokenResource,
    ComputeResourcePortfolio,
)
from core.agent.app.policy.registry import policy_callable
from core.agent.app.policy.action_builders import NegotiationActionBuilder, make_negotiation_id
from core.agent.app.policy.negotiation_thread import get_thread_store, NegotiationThreadTransaction
from core.agent.app.utils.validation import (
    extract_resources_from_make_offer_event,
    determine_strategy_from_order,
)
from service.clients.indexer import get_registry_client
from core.agent.app.utils.action_executor import _extract_initial_price_from_order

logger = logging.getLogger(__name__)


def get_compute_resource_portfolio(
    context: DecisionContext,
) -> ComputeResourcePortfolio | None:
    """Build a compute-only portfolio view from generic available resources."""
    available_resources = context.available_resources
    if not isinstance(available_resources, dict):
        return None

    raw_resources = available_resources.get("resources")
    if not isinstance(raw_resources, list):
        return None

    compute_resources: list[dict[str, Any]] = []
    for resource in raw_resources:
        if isinstance(resource, ComputeResource):
            compute_resources.append(resource.model_dump(mode="json"))
            continue
        if not isinstance(resource, dict):
            continue
        if "gpu_model" not in resource:
            continue
        compute_resources.append(resource)

    if not compute_resources:
        return None

    try:
        return ComputeResourcePortfolio.model_validate({"resources": compute_resources})
    except Exception as exc:
        logger.warning("[COMPUTE POLICY] Failed to validate compute portfolio: %s", exc)
        return None


# ----- Named guard/action callables for versioned composites -----

@policy_callable("ri.guard.trigger_is_resource_imbalance")
def ri_guard_trigger_is_resource_imbalance(context: DecisionContext) -> DomainAction | None:
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "resource_imbalance":
        return None
    return None


@policy_callable("ri.guard.resource_present")
def ri_guard_resource_present(context: DecisionContext) -> DomainAction | None:
    res = getattr(context.event, "resource", None)
    if not res:
        return None
    return None


@policy_callable("oc.action.make_offer_from_order_create")
def oc_action_make_offer_from_order_create(context: DecisionContext) -> DomainAction | None:
    from core.agent.app.schema.pydantic_models import ActionType, OrderCreateEvent

    if not isinstance(context.event, OrderCreateEvent):
        return None

    offer = context.event.offer
    demand = context.event.demand
    duration_hours = context.event.duration_hours

    # Enrich a bare ComputeResource offer (no resource_id) with the actual registered
    # portfolio resource so that resource_id and vm_host are populated in the outgoing order.
    if isinstance(offer, ComputeResource) and offer.resource_id is None:
        portfolio = get_compute_resource_portfolio(context)
        if portfolio:
            for resource in portfolio.resources:
                if (
                    resource.gpu_model == offer.gpu_model
                    and resource.region == offer.region
                    and resource.sla >= offer.sla
                    and resource.quantity >= offer.quantity
                ):
                    offer = resource
                    break

    offer_payload = offer.model_dump(mode="json") if hasattr(offer, "model_dump") else offer
    demand_payload = demand.model_dump(mode="json") if hasattr(demand, "model_dump") else demand

    return DomainAction(
        action_type=ActionType.MAKE_OFFER,
        parameters={
            "offer": offer_payload,
            "demand": demand_payload,
            "duration_hours": duration_hours,
        },
    )

@policy_callable("oc.action.close_order")
def oc_action_close_order(context: DecisionContext) -> DomainAction | None:
    from core.agent.app.schema.pydantic_models import ActionType, OrderCloseEvent

    if not isinstance(context.event, OrderCloseEvent):
        return None

    return DomainAction(
        action_type=ActionType.CLOSE_ORDER,
        parameters={
            "order_id": context.event.order_id,
        },
    )

@policy_callable("ri.action.make_offer_from_resource")
def ri_action_make_offer_from_resource(context: DecisionContext) -> DomainAction | None:
    from core.agent.app.schema.pydantic_models import ActionType

    res = getattr(context.event, "resource", None)
    if not res:
        return None
    return DomainAction(
        action_type=ActionType.MAKE_OFFER,
        parameters={
            "gpu_model": res.gpu_model,
            "sla": res.sla,
            "region": res.region,
            "imbalance_type": getattr(context.event, "imbalance_type", "surplus"),
        },
    )

# Accept-offer -> fulfill flow
@policy_callable("ao.action.fulfill_after_accept")
def ao_action_fulfill_after_accept(context: DecisionContext) -> DomainAction | None:
    if not isinstance(context.event, AcceptOfferEvent):
        return None

    from core.agent.app.utils.config import CONFIG

    order = context.event.order
    escrow_uid = context.event.escrow_uid
    ssh_key = context.event.ssh_public_key
    matched_order_id = context.event.matched_order_id
    sender_url = context.event.source

    maker_offers_compute = isinstance(order.offer_resource, ComputeResource)
    our_url = (CONFIG.base_url_override or "").rstrip("/")
    maker_url = (order.order_maker or "").rstrip("/")
    we_are_maker = bool(our_url and maker_url and our_url == maker_url)

    compute_buyer = (maker_offers_compute and not we_are_maker) or (not maker_offers_compute and we_are_maker)

    if compute_buyer:
        if escrow_uid:
            return None
        neg_id = make_negotiation_id(order.order_id, matched_order_id) if matched_order_id else None
        our_initial_price = _extract_initial_price_from_order(order)
        # buyer_order_id is set by the seller so the buyer can link escrow_uid to their local
        # order record. Fall back to order.order_id for backwards-compat (older seller agents).
        our_order_id = getattr(context.event, "buyer_order_id", None) or order.order_id
        return DomainAction(
            action_type=DomainActionType.ACCEPT_OFFER,
            parameters={
                "order": order.model_dump(mode="json"),
                "order_id": order.order_id,
                "our_order_id": our_order_id,
                "their_order_id": matched_order_id,
                "counterparty_url": sender_url,
                "matched_order_id": matched_order_id,
                "negotiation_id": neg_id,
                "our_initial_price": our_initial_price,
                "our_price": our_initial_price,
                "their_price": our_initial_price,
                # compute_buyer = True means we minimize (token payer wants lowest price)
                "our_strategy": "minimize",
            },
        )

    if not escrow_uid or not ssh_key:
        return None
    return DomainAction(
        action_type=DomainActionType.FULFILL_COMPUTE_OBLIGATION,
        parameters={
            "order": order.model_dump(mode="json"),
            "escrow_uid": escrow_uid,
            "ssh_public_key": ssh_key,
            "oracle_address": order.oracle_address,
            "counterparty_url": sender_url,
            "matched_order_id": matched_order_id,
            # buyer_order_id is echoed by the buyer in their AcceptOfferEvent so the seller
            # can reconstruct make_negotiation_id(seller_order, buyer_order) regardless of
            # who initiated the MakeOfferEvent.
            # Case A (buyer initiates): offer field = buyer's order → order.order_id = buyer's ✓
            # Case B (seller initiates): offer field = seller's order → need the echo ✓
            "buyer_order_id": getattr(context.event, "buyer_order_id", None) or order.order_id,
        },
    )

# Receive fulfillment -> trust arbitration path
@policy_callable("rcf.action.trust_fulfillment")
def rcf_action_trust_fulfillment(context: DecisionContext) -> DomainAction | None:
    """When we receive compute fulfillment, trust it and move to arbitration."""
    if not isinstance(context.event, ReceiveComputeObligationFulfillmentEvent):
        return None
    return DomainAction(
        action_type=DomainActionType.TRUST_COMPUTE_OBLIGATION_FULFILLMENT,
        parameters={
            "escrow_uid": context.event.escrow_uid,
            "fulfillment_uid": context.event.fulfillment_uid,
            "connection_details": context.event.connection_details,
            "counterparty_url": context.event.fulfilling_party_url,
            "tenant_credentials": context.event.tenant_credentials,
        },
    )

# Arbitration complete -> collect escrow
@policy_callable("arb.action.collect_escrow_after_arbitration")
def arb_action_collect_escrow_after_arbitration(context: DecisionContext) -> DomainAction | None:
    """After arbitration completes, collect escrow for the fulfillment."""
    event = context.event
    if not (
        isinstance(event, ArbitrationCompleteEvent)
    ):
        return None

    data = getattr(event, "data", {}) or {}
    escrow_uid = getattr(event, "escrow_uid", None) or data.get("escrow_uid")
    fulfillment_uid = getattr(event, "fulfillment_uid", None) or data.get("fulfillment_uid")

    if not escrow_uid or not fulfillment_uid:
        return None

    return DomainAction(
        action_type=DomainActionType.COLLECT_ESCROW,
        parameters={
            "escrow_uid": escrow_uid,
            "fulfillment_uid": fulfillment_uid,
            "decisions": getattr(event, "decisions", None) or data.get("decisions"),
            "oracle_address": getattr(event, "oracle_address", None) or data.get("oracle_address"),
            "status": getattr(event, "status", None) or data.get("status"),
        },
    )


@policy_callable("mo.guard.trigger_is_make_offer")
def mo_guard_trigger_is_make_offer(context: DecisionContext) -> DomainAction | None:
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "make_offer":
        return None
    return None


# ===== Negotiation Policies (Strategic Interaction Pattern) =====

@policy_callable("negotiation.guard.always_negotiate_on_price_diff")
def negotiation_guard_always_negotiate_on_price_diff(context: DecisionContext) -> DomainAction | None:
    """Admission policy: Always negotiate when prices differ, accept when equal.

    CGT role: Implements the "Entry Decision → Negotiation Game" handoff from
    Reactive Decision Pattern to Strategic Interaction Pattern.

    Returns:
        None to pass to next policy (continue negotiation), or
        ACCEPT_OFFER if prices are equal (skip negotiation)
    """
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None

    # Check if this is a negotiation event with price data
    if not isinstance(context.event, NegotiationEvent):
        return None

    data = context.event.data or {}

    their_price = data.get("proposed_price")

    thread_info = context.market_state.get("thread_info", {})
    negotiation_history = context.negotiation_history or []

    # Use our last counter as the comparison point, not the initial price
    last_our_proposal = thread_info.get("our_initial_price")
    if negotiation_history:
        for msg in reversed(negotiation_history):
            if msg.get("sender") == context.agent_id and msg.get("proposed_price"):
                last_our_proposal = msg.get("proposed_price")
                break

    if last_our_proposal is not None and their_price is not None and last_our_proposal == their_price:
        logger.info(f"[NEGOTIATION] Prices equal ({last_our_proposal}), accepting directly")
        data = {
            **data,
            "counterparty_url": thread_info.get("their_agent_id"),
            "our_price": thread_info.get("our_initial_price"),
            "their_price": their_price,
            "our_strategy": thread_info.get("our_strategy"),
        }
        actions = NegotiationActionBuilder(data)
        return actions.accept("price_equal")

    return None


@policy_callable("negotiation.action.price_interval_concession")
def negotiation_action_price_interval_concession(context: DecisionContext) -> DomainAction | None:
    """Strategy-aware price-based counter-offer policy using minimizer/maximizer model.

    - their_price: Derived from event's proposed_price (what they're offering)
    - our_price: Retrieved from local thread state (our_initial_price)
    - strategy: Retrieved from local thread state (our_strategy)

    Strategy types (inferred from our own order resource types):
    - Minimizer: demanding ComputeResource (wants lowest rate, our_price = ceiling)
    - Maximizer: offering ComputeResource (wants highest rate, our_price = floor)

    Strategy logic:
    - Minimizer: accept if their_price <= our_price, counter if <= 1.5x, else exit
    - Maximizer: accept if their_price >= our_price, counter if >= 0.67x, else exit

    CGT role: Implements the per-round "Strategic Decision" in the bilateral
    negotiation game, using thread state and resource-aware thresholds.

    Returns:
        ACCEPT_OFFER if their price is favorable,
        COUNTER_OFFER with proposed price if reasonable but not favorable,
        EXIT_NEGOTIATION if unreasonable
    """
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None

    if not isinstance(context.event, NegotiationEvent):
        return None

    data = context.event.data or {}
    negotiation_history = context.negotiation_history or []
    their_price = data.get("proposed_price")

    thread_info = context.market_state.get("thread_info", {})
    our_price = thread_info.get("our_initial_price")
    strategy = thread_info.get("our_strategy")

    if our_price is None or their_price is None:
        logger.info(f"[NEGOTIATION] Missing price data: our_price={our_price}, their_price={their_price}")
        return None  # Pass to next policy if price data missing

    # Ensure negotiation_id is in data for the builder
    if context.event.negotiation_id and "negotiation_id" not in data:
        data = {**data, "negotiation_id": context.event.negotiation_id}

    # Add our_price, their_price, and counterparty routing info for action builder
    data = {**data, "our_price": our_price, "their_price": their_price,
            "counterparty_url": thread_info.get("their_agent_id")}

    # Create action builder for clean action construction
    actions = NegotiationActionBuilder(data)

    REASONABLE_MULTIPLIER = 1.5  # Exit threshold (unchanged)
    CONVERGENCE_RATIO = 0.01    # Accept when within 1% of last counter

    # Strategy-aware price acceptance logic
    if strategy == "minimize":
        # Minimizer: our_price is the MAX we're willing to pay (ceiling)
        # Find last proposal we made (or fall back to initial ceiling)
        last_our_proposal = our_price
        if negotiation_history:
            for msg in reversed(negotiation_history):
                if msg.get("sender") == context.agent_id and msg.get("proposed_price"):
                    last_our_proposal = msg.get("proposed_price")
                    break

        if their_price <= last_our_proposal * (1 + CONVERGENCE_RATIO):
            # Their ask is within CONVERGENCE_RATIO above our last bid — converged
            logger.info(f"[NEGOTIATION][MINIMIZE] Converged: their_price {their_price} <= last_our_proposal {last_our_proposal} * {1 + CONVERGENCE_RATIO:.2f}, accepting")
            return actions.accept("convergence")
        elif their_price <= our_price * REASONABLE_MULTIPLIER:
            # Above last bid but reasonable — counter with midpoint, converging toward their price
            proposed_price = (last_our_proposal + their_price) // 2
            logger.info(f"[NEGOTIATION][MINIMIZE] Counter-offering {proposed_price} (midpoint of {last_our_proposal} and {their_price}, ceiling={our_price})")
            return actions.counter(proposed_price)
        else:
            # Unreasonable - far above ceiling
            logger.info(f"[NEGOTIATION][MINIMIZE] Their price {their_price} > {REASONABLE_MULTIPLIER}x our_price {our_price}, exiting")
            return actions.exit("price_unreasonable")

    elif strategy == "maximize":
        # Maximizer: our_price is the MIN we're willing to accept (floor)
        # Find last proposal we made (or fall back to initial floor)
        last_our_proposal = our_price
        if negotiation_history:
            for msg in reversed(negotiation_history):
                if msg.get("sender") == context.agent_id and msg.get("proposed_price"):
                    last_our_proposal = msg.get("proposed_price")
                    break

        if their_price >= last_our_proposal * (1 - CONVERGENCE_RATIO):
            # Their bid is within CONVERGENCE_RATIO below our last ask — converged
            logger.info(f"[NEGOTIATION][MAXIMIZE] Converged: their_price {their_price} >= last_our_proposal {last_our_proposal} * {1 - CONVERGENCE_RATIO:.2f}, accepting")
            return actions.accept("convergence")
        elif their_price >= our_price / REASONABLE_MULTIPLIER:
            # Below last ask but reasonable — counter with midpoint, converging toward their price
            proposed_price = (last_our_proposal + their_price) // 2
            logger.info(f"[NEGOTIATION][MAXIMIZE] Counter-offering {proposed_price} (midpoint of {last_our_proposal} and {their_price}, floor={our_price})")
            return actions.counter(proposed_price)
        else:
            # Unreasonable - far below floor
            logger.info(f"[NEGOTIATION][MAXIMIZE] Their price {their_price} < our_price/{REASONABLE_MULTIPLIER} {our_price / REASONABLE_MULTIPLIER:.1f}, exiting")
            return actions.exit("price_unreasonable")

    else:
        # No strategy specified - pass to next policy
        logger.info(f"[NEGOTIATION] No strategy specified, passing to next policy")
        return None


@policy_callable("negotiation.guard.bounded_rounds_and_timeout")
def negotiation_guard_bounded_rounds_and_timeout(context: DecisionContext) -> DomainAction | None:
    """Thread/termination policy: Enforce round limits and timeout.

    CGT role: Encodes the terminal checks and TIMEOUT/FAILURE outcomes
    from the Bilateral Negotiation Actions diagram.

    Returns:
        EXIT_NEGOTIATION if limits exceeded, None otherwise
    """
    from datetime import datetime

    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None

    if not isinstance(context.event, NegotiationEvent):
        return None

    negotiation_history = context.negotiation_history or []
    max_rounds = 10  # Max counter-offers from OUR side; bisection needs ~7 for 2000-unit spread
    timeout_seconds = 300  # 5 minutes default

    # Build data dict for action builder
    data = context.event.data or {}
    if context.event.negotiation_id and "negotiation_id" not in data:
        data = {**data, "negotiation_id": context.event.negotiation_id}
    actions = NegotiationActionBuilder(data)

    # Count only our own messages — history is now bilateral (both sides recorded),
    # so len(negotiation_history) would be ~2x actual rounds and expire too early.
    our_messages = [m for m in negotiation_history if m.get("sender") == context.agent_id]
    if len(our_messages) >= max_rounds:
        logger.info(f"[NEGOTIATION] Max rounds ({max_rounds}) exceeded, exiting")
        return actions.exit("max_rounds_exceeded")

    # Check for stale negotiation: no movement in OUR last two proposals.
    if len(our_messages) >= 2:
        last_two_ours = our_messages[-2:]
        prices = [m.get("proposed_price") for m in last_two_ours if m.get("proposed_price")]
        if len(prices) >= 2 and prices[-1] == prices[-2]:
            logger.info(f"[NEGOTIATION] No price movement in our last 2 proposals, exiting")
            return actions.exit("stale_negotiation")

    # Check timeout (if first message has timestamp)
    if negotiation_history:
        first_msg = negotiation_history[0]
        first_timestamp_str = first_msg.get("timestamp")
        if first_timestamp_str:
            try:
                first_timestamp = datetime.fromisoformat(first_timestamp_str.replace('Z', '+00:00'))
                elapsed = (datetime.now(first_timestamp.tzinfo) - first_timestamp).total_seconds()
                if elapsed > timeout_seconds:
                    logger.info(f"[NEGOTIATION] Timeout ({timeout_seconds}s) exceeded, exiting")
                    return actions.exit("timeout")
            except Exception as e:
                logger.warning(f"[NEGOTIATION] Failed to parse timestamp: {e}")

    # No limits exceeded - continue negotiation
    return None


@policy_callable("negotiation.action.safe_default_reject")
def negotiation_action_safe_default_reject(context: DecisionContext) -> DomainAction | None:
    """Fallback/safety policy: Reject if price data is malformed.

    CGT role: Ensures all negotiation games terminate cleanly even under error conditions.

    Returns:
        REJECT_OFFER if price data is invalid, None otherwise
    """
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None

    if not isinstance(context.event, NegotiationEvent):
        return None

    # Terminal events (exit, accept) have no proposed_price — nothing to reject
    if context.event.message_type in ("exit", "accept"):
        return None

    data = context.event.data or {}

    their_price = data.get("proposed_price")
    
    thread_info = context.market_state.get("thread_info", {})
    our_price = thread_info.get("our_initial_price")

    # Build data dict for action builder
    if context.event.negotiation_id and "negotiation_id" not in data:
        data = {**data, "negotiation_id": context.event.negotiation_id}
    actions = NegotiationActionBuilder(data)

    # If price data is missing or invalid, reject for safety
    if our_price is None or their_price is None:
        logger.warning(f"[NEGOTIATION] Missing price data, rejecting for safety")
        return actions.reject("missing_price_data")

    # Check for invalid price values
    if not isinstance(our_price, (int, float)) or not isinstance(their_price, (int, float)):
        logger.warning(f"[NEGOTIATION] Invalid price types, rejecting for safety")
        return actions.reject("invalid_price_types")

    if our_price <= 0 or their_price <= 0:
        logger.warning(f"[NEGOTIATION] Non-positive prices, rejecting for safety")
        return actions.reject("non_positive_prices")

    # Price data looks valid - pass to next policy (shouldn't reach here in normal flow)
    return None


@policy_callable("negotiation.action.handle_exit")
def negotiation_action_handle_exit(context: DecisionContext) -> DomainAction | None:
    """Mark the local negotiation thread as terminal when the counterparty sends an exit.

    Without this, agent_8000's thread stays status='active' in SQLite forever when
    agent_8001 exits — blocking future negotiations for the same order.
    """
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None

    if not isinstance(context.event, NegotiationEvent):
        return None

    if context.event.message_type != "exit":
        return None

    negotiation_id = context.event.negotiation_id
    if not negotiation_id:
        return None

    import asyncio

    async def _mark() -> None:
        async with NegotiationThreadTransaction("HANDLE_EXIT") as txn:
            await txn.mark_terminal(negotiation_id, "failure")

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_mark())
        else:
            loop.run_until_complete(_mark())
    except Exception as exc:
        logger.warning("[NEGOTIATION] Failed to mark thread terminal on received exit: %s", exc)

    data = context.event.data or {}
    reason = data.get("reason", "counterparty_exited")
    logger.info(
        "[NEGOTIATION] Counterparty exited negotiation %s (reason: %s) — thread marked terminal",
        negotiation_id,
        reason,
    )
    return None  # No action to send back



@policy_callable("negotiation.respond_to_make_offer")
async def negotiation_respond_to_make_offer(context: DecisionContext) -> DomainAction | None:
    et = context.event.event_type
    if et.value != "make_offer":
        return None
    if not isinstance(context.event, MakeOfferEvent):
        return None

    order_obj = context.event.order
    if not order_obj:
        return None

    # Convert to dict if it's a MarketOrder model
    if isinstance(order_obj, MarketOrder):
        incoming_order = order_obj.model_dump(mode="json")
    else:
        incoming_order = order_obj

    # Don't negotiate with our own orders (can arrive via self-send if registry returns them)
    from core.agent.app.utils.config import CONFIG as _CONFIG
    _our_url = (_CONFIG.base_url_override or "").strip().rstrip("/").lower()
    _their_url = (incoming_order.get("order_maker") or "").strip().rstrip("/").lower()
    if _our_url and _our_url == _their_url:
        logger.debug(
            "[NEGOTIATION] Skipping self-order (order_maker == our URL): %s",
            incoming_order.get("order_id"),
        )
        return None

    # Reject if incoming order has no compute resource — can't negotiate a non-compute trade
    _offer_res = incoming_order.get("offer_resource") or {}
    _demand_res = incoming_order.get("demand_resource") or {}
    if "gpu_model" not in _offer_res and "gpu_model" not in _demand_res:
        logger.warning(
            "[NEGOTIATION] Rejecting order with no compute resource: order_id=%s",
            incoming_order.get("order_id"),
        )
        return None

    their_proposed_price = _extract_initial_price_from_order(incoming_order)
    registry_client = get_registry_client()
    our_orders = await registry_client.query_orders({"status": "open"})
    our_order = None

    for order_dict in our_orders:
        if order_dict.get("order_id") == incoming_order.get("order_id"):
            continue
        order = MarketOrder.model_validate(order_dict)
        if determine_strategy_from_order(order):
            our_order = order_dict
            break

    if not our_order:
        actions = NegotiationActionBuilder({})
        return actions.reject("no_matching_order")

    market_order = MarketOrder.model_validate(our_order)
    strategy = determine_strategy_from_order(market_order)
    our_price = _extract_initial_price_from_order(our_order)

    their_order_id = incoming_order.get("order_id", "")
    our_order_id = our_order.get("order_id", "")
    negotiation_id = make_negotiation_id(our_order_id, their_order_id)

    # Canonical initiator guard: make_negotiation_id sorts the two order IDs, so both
    # agents produce the same negotiation_id. When both agents independently call
    # make_offer on each other's orders, this creates two competing threads.
    # Rule: the agent whose order_id sorts FIRST is the initiator — IF they already sent
    # their own make_offer outbound (i.e. an active thread exists). When they receive the
    # counterparty's make_offer, they drop it; the counterparty responds to theirs.
    # Exception: if no thread exists yet (e.g. we published first but got no_match because
    # the counterparty hadn't published yet), fall through and respond to their offer.
    canonical_first = min(our_order_id, their_order_id)
    if our_order_id == canonical_first:
        from core.agent.app.utils.config import CONFIG
        thread_store = get_thread_store()
        existing_thread = await thread_store.get_thread_info(
            negotiation_id=negotiation_id,
            owner_id=(CONFIG.base_url_override or ""),
        )
        if existing_thread is not None:
            logger.info(
                "[NEGOTIATION] Canonical initiator guard: our order (%s) sorts first and "
                "thread exists — dropping cross-initiated make_offer; counterparty will respond to ours.",
                our_order_id,
            )
            return None
        logger.info(
            "[NEGOTIATION] Canonical initiator guard: our order (%s) sorts first but no "
            "active thread found (we got no_match earlier) — responding to their offer.",
            our_order_id,
        )

    # Round guard: mirrors negotiation_guard_bounded_rounds_and_timeout but for make_offer path.
    # That guard only fires on `negotiation` events; this function handles `make_offer` events
    # and is in a separate chain, so the guard never applies here without this check.
    MAX_ROUNDS = 10
    _ts = get_thread_store()
    _thread_msgs = await _ts.get_thread(negotiation_id)
    _our_counters = [
        m for m in _thread_msgs
        if (m.get("sender") or "").strip().rstrip("/").lower() == _our_url
        and m.get("action_taken") == DomainActionType.COUNTER_OFFER.value
    ]
    _action_dict = {
        "negotiation_id": negotiation_id,
        "their_order_id": their_order_id,
        "our_order_id": our_order_id,
        "our_price": our_price,
        "their_price": their_proposed_price,
        "proposed_price": their_proposed_price,
        "our_strategy": strategy,
        "order": incoming_order,
        "counterparty_url": incoming_order.get("order_maker"),
    }
    if len(_our_counters) >= MAX_ROUNDS:
        logger.info(
            "[NEGOTIATION] make_offer round guard: reached MAX_ROUNDS=%d for negotiation %s — exiting.",
            MAX_ROUNDS, negotiation_id,
        )
        return NegotiationActionBuilder(_action_dict).exit("max_rounds")
    if len(_our_counters) >= 2:
        _last_prices = [m.get("proposed_price") for m in _our_counters[-2:]]
        if _last_prices[0] is not None and _last_prices[0] == _last_prices[1]:
            logger.info(
                "[NEGOTIATION] make_offer stale guard: price stuck at %s for negotiation %s — exiting.",
                _last_prices[0], negotiation_id,
            )
            return NegotiationActionBuilder(_action_dict).exit("stale_negotiation")

    actions = NegotiationActionBuilder({
        "negotiation_id": negotiation_id,
        "their_order_id": their_order_id,
        "our_order_id": our_order_id,
        "our_price": our_price,
        "their_price": their_proposed_price,
        "proposed_price": their_proposed_price,
        "our_strategy": strategy,
        "order": incoming_order,
        "counterparty_url": incoming_order.get("order_maker"),
    })

    CONVERGENCE_RATIO = 0.01  # Accept when within 1% of our price

    if strategy == "minimize":
        if their_proposed_price <= our_price * (1 + CONVERGENCE_RATIO):
            return actions.accept("convergence")
        if their_proposed_price <= our_price * 1.5:
            proposed_price = (our_price + their_proposed_price) // 2
            return actions.counter(proposed_price)
        return actions.exit("price_unreasonable")

    if strategy == "maximize":
        if their_proposed_price >= our_price * (1 - CONVERGENCE_RATIO):
            return actions.accept("convergence")
        if their_proposed_price >= our_price / 1.5:
            proposed_price = (our_price + their_proposed_price) // 2
            return actions.counter(proposed_price)
        return actions.exit("price_unreasonable")

    return actions.reject("unknown_strategy")
