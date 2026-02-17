from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Tuple

from app.policies.evaluator import CallableEvaluator
from app.schema.pydantic_models import (
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
from app.policies.registry import policy_callable
from app.utils.sqlite_client import SQLiteClient
from app.policies.action_builders import NegotiationActionBuilder
from app.utils.validation import (
    extract_resources_from_make_offer_event,
    determine_strategy_from_order,
)
from app.utils.registry_client import get_registry_client
from app.utils.action_executor import _extract_initial_price_from_order
from app.utils.config import CONFIG

CacheKey = Tuple[str, str]  # (agent_id, trigger_type)

logger = logging.getLogger(__name__)


class PolicyStore:
    def __init__(self, sqlite_client: SQLiteClient):
        self._sqlite = sqlite_client
        self._registry: Dict[str, Callable[[DecisionContext], DomainAction | None]] = {}
        self._cache: Dict[CacheKey, Dict[str, Any]] = {}
        # Composite name -> ordered list of component callable names
        self._composites: Dict[str, List[str]] = {}

    def register_callable(self, name: str, func: Callable[[DecisionContext], DomainAction | None]) -> None:
        self._registry[name] = func

    def register_callables(self, mapping: Dict[str, Callable[[DecisionContext], DomainAction | None]]) -> None:
        for name, func in mapping.items():
            self._registry[name] = func

    def register_composite(self, name: str, components: List[str]) -> None:
        """Record composite chain membership for discovery and auditing."""
        self._composites[name] = list(components)

    def get_composite(self, name: str) -> List[str] | None:
        return self._composites.get(name)

    def list_composites(self) -> Dict[str, List[str]]:
        return dict(self._composites)

    async def save_policy(
        self,
        *,
        agent_id: str,
        policy_name: str,
        trigger_type: str,
        callable_ref: str | None = None,
    ) -> None:
        await self._sqlite.save_policy(
            agent_id=agent_id,
            name=policy_name,
            trigger_type=trigger_type,
            callable_ref=callable_ref,
        )
        # If this references a registered composite, persist its ordered components for SQL queries
        if callable_ref and callable_ref in self._composites:
            try:
                await self._sqlite.save_policy_composite(
                    agent_id=agent_id,
                    policy_name=policy_name,
                    components=self._composites[callable_ref],
                )
            except Exception:
                # Non-fatal; policy remains usable even if composite persistence fails
                pass
        self._cache.pop((agent_id, trigger_type), None)

    async def _load_cached(self, *, agent_id: str, trigger_type: str) -> Dict[str, Any]:
        key = (agent_id, trigger_type)
        if key in self._cache:
            return self._cache[key]
        rows = await self._sqlite.load_policies_by_trigger(agent_id=agent_id, trigger_type=trigger_type)
        callables: List[str] = []
        for row in rows:
            if row.get("callable_ref"):
                callables.append(row["callable_ref"]) 
        data = {"callables": callables}
        self._cache[key] = data
        return data

    async def evaluate_policy(self, *, agent_id: str, context: DecisionContext) -> DomainAction | None:
        # Normalize trigger type to string for storage/lookup consistency
        trigger_type: str
        et = context.event.event_type
        trigger_type = et.value if hasattr(et, "value") else str(et)
        data = await self._load_cached(agent_id=agent_id, trigger_type=trigger_type)
        # Evaluate policies by callable_ref; support composite by expanding from DB
        policy_action: DomainAction | None = None
        for ref in data["callables"]:
            # Direct callable
            if ref in self._registry:
                ce = CallableEvaluator(self._registry[ref])
                policy_action = await ce.evaluate(context)
                if policy_action is not None:
                    break
            # Composite: expand ordered components from DB and execute
            try:
                components = await self._sqlite.load_policy_composite(agent_id=agent_id, policy_name=ref)
            except Exception:
                components = []
            if components:
                for comp in components:
                    func = self._registry.get(comp)
                    if not func:
                        continue
                    ce = CallableEvaluator(func)
                    policy_action = await ce.evaluate(context)
                    if policy_action is not None:
                        break
                if policy_action is not None:
                    break
        return policy_action


# ----- Negotiation policies -----

@policy_callable("simple_negotiation_random")
def simple_negotiation_random(context: DecisionContext) -> DomainAction | None:
    """50/50 accept/reject for negotiation offers."""
    import random
    from app.schema.pydantic_models import ActionType

    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None
    
    # Check message_type - could be on event attribute or in data
    msg_type = getattr(context.event, "message_type", None) or context.event.data.get("message_type")
    if msg_type != "offer":
        return None
    
    choice = random.choice([ActionType.ACCEPT_OFFER, ActionType.REJECT_OFFER])
    return DomainAction(action_type=choice, parameters={})


@policy_callable("simple_negotiation_callable")
def simple_negotiation_callable(context: DecisionContext) -> DomainAction | None:
    """Accept offer if GPU threshold is met, otherwise reject."""
    from app.schema.pydantic_models import ActionType

    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None
    
    # Check message_type - could be on event attribute or in data
    msg_type = getattr(context.event, "message_type", None) or context.event.data.get("message_type")
    if msg_type != "offer":
        return None
    
    total_gpus = int(context.available_resources.get("total_gpus", 0))
    gpu_threshold = 1  # Default threshold
    if total_gpus < gpu_threshold:
        return DomainAction(action_type=ActionType.REJECT_OFFER, parameters={})
    return DomainAction(action_type=ActionType.ACCEPT_OFFER, parameters={})


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
    from app.schema.pydantic_models import ActionType, OrderCreateEvent

    if not isinstance(context.event, OrderCreateEvent):
        return None

    offer = context.event.offer
    demand = context.event.demand
    duration_hours = context.event.duration_hours

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
    from app.schema.pydantic_models import ActionType, OrderCloseEvent

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
    from app.schema.pydantic_models import ActionType

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
    """When we receive an AcceptOfferEvent, move directly to fulfill compute obligation."""
    if not isinstance(context.event, AcceptOfferEvent):
        return None

    # Only the compute provider (seller) should fulfill.
    # context.event.order is the maker's order (we are the maker receiving this event).
    # If our order offers tokens (not compute), we are the buyer — skip.
    order = context.event.order
    offer_res = order.offer_resource if hasattr(order, "offer_resource") else {}
    if isinstance(offer_res, dict):
        if "gpu_model" not in offer_res:
            return None
    elif not hasattr(offer_res, "gpu_model"):
        return None

    escrow_uid = context.event.escrow_uid
    ssh_key = context.event.ssh_public_key
    agreed_price = context.event.agreed_price

    # Derive negotiation_id so the FULFILL handler can mark the maker's thread terminal
    # and update the maker's order status.
    our_order_id = context.event.order.order_id  # maker's order (we are the maker)
    their_order_id = context.event.taker_order_id  # taker's order
    negotiation_id = None
    if our_order_id and their_order_id:
        negotiation_id = f"{min(our_order_id, their_order_id)}_{max(our_order_id, their_order_id)}"

    return DomainAction(
        action_type=DomainActionType.FULFILL_COMPUTE_OBLIGATION,
        parameters={
            "order": context.event.order.model_dump(mode="json"),
            "escrow_uid": escrow_uid,
            "ssh_public_key": ssh_key,
            "our_order_id": our_order_id,
            "their_order_id": their_order_id,
            "negotiation_id": negotiation_id,
            "agreed_price": agreed_price,
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
            "counterparty_url": getattr(context.event, "source", None),
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
    our_price = thread_info.get("our_initial_price")

    # Inject order IDs from thread_info so downstream actions can find counterparty
    data = {**data,
        "our_order_id": thread_info.get("our_order_id"),
        "their_order_id": thread_info.get("their_order_id"),
    }

    if our_price is not None and their_price is not None and our_price == their_price:
        logger.info(f"[NEGOTIATION] Prices equal ({our_price}), accepting directly")
        actions = NegotiationActionBuilder(data)
        return actions.accept("price_equal", agreed_price=their_price)

    return None


REASONABLE_MULTIPLIER = 1.5
MAX_NEGOTIATION_ROUNDS = 5


def _relaxed_acceptance_threshold(our_price, strategy, round_num, max_rounds):
    """Compute round-dependent acceptance threshold with linear relaxation.

    Each agent's threshold linearly relaxes from initial price toward max concession
    boundary (1.5x) over the negotiation rounds:
    - Minimizer (buyer): Round 0 accepts at ceiling, final round at ceiling x 1.5
    - Maximizer (seller): Round 0 accepts at floor, final round at floor / 1.5
    """
    concession_fraction = min(round_num / max(max_rounds - 1, 1), 1.0)
    if strategy == "minimize":
        max_concession = int(our_price * REASONABLE_MULTIPLIER)
        return our_price + int((max_concession - our_price) * concession_fraction)
    else:
        max_concession = int(our_price / REASONABLE_MULTIPLIER)
        return our_price - int((our_price - max_concession) * concession_fraction)


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

    # Add our_price, their_price, and order IDs to data for action builder
    data = {**data,
        "our_price": our_price,
        "their_price": their_price,
        "our_order_id": thread_info.get("our_order_id"),
        "their_order_id": thread_info.get("their_order_id"),
    }

    # Create action builder for clean action construction
    actions = NegotiationActionBuilder(data)

    # Strategy-aware price acceptance logic with round-dependent threshold relaxation
    current_round = len(negotiation_history)
    acceptance_threshold = _relaxed_acceptance_threshold(our_price, strategy, current_round, MAX_NEGOTIATION_ROUNDS)

    if strategy == "minimize":
        # Minimizer: our_price is the MAX we're willing to pay (ceiling)
        # Accept if at or below relaxed threshold, counter if reasonable, exit if unreasonable

        if their_price <= acceptance_threshold:
            # Favorable - at or below our relaxed ceiling
            logger.info(f"[NEGOTIATION][MINIMIZE] Their price {their_price} <= threshold {acceptance_threshold} (round {current_round}), accepting")
            return actions.accept("favorable_price", agreed_price=their_price)
        elif their_price <= our_price * REASONABLE_MULTIPLIER:
            # Above threshold but reasonable - counter with midpoint
            last_our_proposal = our_price
            if negotiation_history:
                for msg in reversed(negotiation_history):
                    if msg.get("sender") == context.agent_id and msg.get("proposed_price"):
                        last_our_proposal = msg.get("proposed_price")
                        break

            proposed_price = (last_our_proposal + their_price) // 2
            logger.info(f"[NEGOTIATION][MINIMIZE] Counter-offering {proposed_price} (between {last_our_proposal} and {their_price})")
            return actions.counter(proposed_price)
        else:
            # Unreasonable - far above ceiling
            logger.info(f"[NEGOTIATION][MINIMIZE] Their price {their_price} > {REASONABLE_MULTIPLIER}x our_price {our_price}, exiting")
            return actions.exit("price_unreasonable")

    elif strategy == "maximize":
        # Maximizer: our_price is the MIN we're willing to accept (floor)
        # Accept if at or above relaxed threshold, counter if reasonable, exit if unreasonable

        if their_price >= acceptance_threshold:
            # Favorable - at or above our relaxed floor
            logger.info(f"[NEGOTIATION][MAXIMIZE] Their price {their_price} >= threshold {acceptance_threshold} (round {current_round}), accepting")
            return actions.accept("favorable_price", agreed_price=their_price)
        elif their_price >= our_price / REASONABLE_MULTIPLIER:
            # Below threshold but reasonable - counter with midpoint
            last_our_proposal = our_price
            if negotiation_history:
                for msg in reversed(negotiation_history):
                    if msg.get("sender") == context.agent_id and msg.get("proposed_price"):
                        last_our_proposal = msg.get("proposed_price")
                        break

            proposed_price = (last_our_proposal + their_price) // 2
            logger.info(f"[NEGOTIATION][MAXIMIZE] Counter-offering {proposed_price} (between {last_our_proposal} and {their_price})")
            return actions.counter(proposed_price)
        else:
            # Unreasonable - far below floor
            logger.info(f"[NEGOTIATION][MAXIMIZE] Their price {their_price} < our_price/{REASONABLE_MULTIPLIER} {our_price / REASONABLE_MULTIPLIER}, exiting")
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

    # Build data dict for action builder
    data = context.event.data or {}
    if context.event.negotiation_id and "negotiation_id" not in data:
        data = {**data, "negotiation_id": context.event.negotiation_id}
    actions = NegotiationActionBuilder(data)

    # Terminal state guard: reject if negotiation already terminated (H1)
    thread_info = context.market_state.get("thread_info", {})
    if thread_info.get("terminal_state"):
        logger.info(f"[NEGOTIATION] Negotiation already terminated ({thread_info['terminal_state']}), rejecting")
        # NOTE: "already_terminated:" prefix is used by action_executor.py to suppress
        # echo exit notifications. Do not change this prefix without updating that guard.
        return actions.exit(f"already_terminated:{thread_info['terminal_state']}")

    # Handle incoming exit notification from counterparty
    message_type = data.get("message_type") or context.event.message_type
    if message_type == "exit":
        exit_reason = (data.get("data") or {}).get("reason", "counterparty_exited")
        logger.info(f"[NEGOTIATION] Received exit notification from counterparty: {exit_reason}")
        # NOTE: "counterparty_exited:" prefix is used by action_executor.py to suppress
        # echo exit notifications. Do not change this prefix without updating that guard.
        return actions.exit(f"counterparty_exited:{exit_reason}")

    negotiation_history = context.negotiation_history or []
    max_rounds = 5  # Configurable default
    timeout_seconds = 300  # 5 minutes default

    # Check round limit
    if len(negotiation_history) >= max_rounds:
        logger.info(f"[NEGOTIATION] Max rounds ({max_rounds}) exceeded, exiting")
        return actions.exit("max_rounds_exceeded")

    # Check for stale negotiation (no price movement in last 2 rounds)
    if len(negotiation_history) >= 2:
        last_two = negotiation_history[-2:]
        prices = [msg.get("proposed_price") or msg.get("their_price") for msg in last_two if msg.get("proposed_price") or msg.get("their_price")]
        if len(prices) >= 2 and prices[-1] == prices[-2]:
            logger.info(f"[NEGOTIATION] No price movement in last 2 rounds, exiting")
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

    data = context.event.data or {}

    their_price = data.get("proposed_price")

    thread_info = context.market_state.get("thread_info", {})
    our_price = thread_info.get("our_initial_price")

    # Build data dict for action builder with order IDs from thread_info
    if context.event.negotiation_id and "negotiation_id" not in data:
        data = {**data, "negotiation_id": context.event.negotiation_id}
    data = {**data,
        "our_order_id": thread_info.get("our_order_id"),
        "their_order_id": thread_info.get("their_order_id"),
    }
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


@policy_callable("mo.action.accept_offer")
def mo_action_accept_offer(context: DecisionContext) -> DomainAction | None:
    """Accept offer policy that validates resources and checks agent capacity.
    
    Extracts offer_resource and demand_resource from MakeOfferEvent.
    - If demand is a ComputeResource: checks if agent has sufficient capacity, rejects if not.
    - If demand is a TokenResource: accepts the offer (simulated assumption: we have enough tokens).
    Includes resource details in action parameters.
    """
    from app.schema.pydantic_models import ActionType
    
    # Only process MakeOfferEvent
    if not isinstance(context.event, MakeOfferEvent):
        return None
    
    # Extract order and resources using utility function
    order, offer_resource, demand_resource = extract_resources_from_make_offer_event(context)
    
    if order is None:
        return None
    
    # Check agent capacity for demand resource if it's a ComputeResource
    if isinstance(demand_resource, ComputeResource):
        # Get portfolio from available_resources
        portfolio_dict = context.available_resources
        if portfolio_dict and "resources" in portfolio_dict:
            try:
                portfolio = ComputeResourcePortfolio.model_validate(portfolio_dict)
                if not portfolio.has_capacity(demand_resource):
                    # Agent doesn't have capacity - reject
                    return DomainAction(
                        action_type=ActionType.REJECT_OFFER,
                        parameters={
                            "reason": "insufficient_capacity",
                            "demand_resource": demand_resource.model_dump(mode="json"),
                        }
                    )
            except Exception as e:
                # If portfolio validation fails, log and continue
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"[POLICY] Failed to validate portfolio: {e}")
    elif isinstance(demand_resource, TokenResource):
        # If demand is a TokenResource, accept the offer
        # Simulated assumption: we have enough tokens in our wallet
        pass
    
    # Extract agreed price from whichever resource is the TokenResource
    agreed_price = None
    if isinstance(offer_resource, TokenResource):
        agreed_price = offer_resource.amount
    elif isinstance(demand_resource, TokenResource):
        agreed_price = demand_resource.amount

    # Accept offer with resource details
    return DomainAction(
        action_type=ActionType.ACCEPT_OFFER,
        parameters={
            "order_id": order.order_id,
            "order": order,
            "offer_resource": offer_resource.model_dump(mode='json'),
            "demand_resource": demand_resource.model_dump(mode='json'),
            "agreed_price": agreed_price,
        }
    )


def _resources_are_complementary(our_order: dict, their_order: dict) -> bool:
    """Check if two orders have complementary resource types (M1).

    Complementary means our offer type matches their demand type and vice versa.
    E.g., if we offer compute and demand tokens, they should offer tokens and demand compute.
    """
    def _is_compute(res: Any) -> bool:
        return isinstance(res, dict) and "gpu_model" in res

    our_offer = our_order.get("offer_resource", {})
    our_demand = our_order.get("demand_resource", {})
    their_offer = their_order.get("offer_resource", {})
    their_demand = their_order.get("demand_resource", {})

    return (_is_compute(our_offer) == _is_compute(their_demand) and
            _is_compute(our_demand) == _is_compute(their_offer))


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

    their_proposed_price = _extract_initial_price_from_order(incoming_order)
    registry_client = get_registry_client()
    our_orders = await registry_client.query_orders({"status": "open"})
    # C1: Filter to only our own orders to prevent matching another agent's order
    our_orders = [o for o in our_orders if o.get("order_maker") == CONFIG.base_url_override]
    our_order = None

    for order_dict in our_orders:
        if order_dict.get("order_id") == incoming_order.get("order_id"):
            continue
        order = MarketOrder.model_validate(order_dict)
        strategy = determine_strategy_from_order(order)
        if not strategy:
            continue
        # M1: Verify resource compatibility — our order's demand should match their offer type
        if _resources_are_complementary(order_dict, incoming_order):
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
    negotiation_id = f"{min(our_order_id, their_order_id)}_{max(our_order_id, their_order_id)}"

    actions = NegotiationActionBuilder({
        "negotiation_id": negotiation_id,
        "their_order_id": their_order_id,
        "our_order_id": our_order_id,
        "our_price": our_price,
        "their_price": their_proposed_price,
        "proposed_price": their_proposed_price,
        "our_strategy": strategy,
    })

    # Round 0 threshold — functionally identical to our_price at round 0
    threshold = _relaxed_acceptance_threshold(our_price, strategy, 0, MAX_NEGOTIATION_ROUNDS)

    if strategy == "minimize":
        if their_proposed_price <= threshold:
            return actions.accept("favorable_price", agreed_price=their_proposed_price)
        if their_proposed_price <= our_price * REASONABLE_MULTIPLIER:
            proposed_price = (our_price + their_proposed_price) // 2
            return actions.counter(proposed_price)
        return actions.exit("price_unreasonable")

    if strategy == "maximize":
        if their_proposed_price >= threshold:
            return actions.accept("favorable_price", agreed_price=their_proposed_price)
        if their_proposed_price >= our_price / REASONABLE_MULTIPLIER:
            proposed_price = (our_price + their_proposed_price) // 2
            return actions.counter(proposed_price)
        return actions.exit("price_unreasonable")

    return actions.reject("unknown_strategy")
