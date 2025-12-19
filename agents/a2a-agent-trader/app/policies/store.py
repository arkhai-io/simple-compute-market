from __future__ import annotations

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
    NegotiationEvent,
    ComputeResource,
    TokenResource,
    ComputeResourcePortfolio,
)
from app.policies.registry import policy_callable
from app.policies.sqlite_client import SQLiteClient
from app.utils.validation import extract_resources_from_make_offer_event

CacheKey = Tuple[str, str]  # (agent_id, trigger_type)


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

    escrow_uid = context.event.escrow_uid
    ssh_key = context.event.ssh_public_key

    return DomainAction(
        action_type=DomainActionType.FULFILL_COMPUTE_OBLIGATION,
        parameters={
            "order": context.event.order.model_dump(mode="json"),
            "escrow_uid": escrow_uid,
            "ssh_public_key": ssh_key,
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
    from app.schema.pydantic_models import ActionType
    
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None
    
    # Check if this is a negotiation event with price data
    if not isinstance(context.event, NegotiationEvent):
        return None
    
    data = context.event.data or {}
    our_price = data.get("our_price")
    their_price = data.get("their_price")
    
    # If prices are equal, short-circuit to accept (skip negotiation)
    if our_price is not None and their_price is not None and our_price == their_price:
        logger.info(f"[NEGOTIATION] Prices equal ({our_price}), accepting directly")
        return DomainAction(action_type=ActionType.ACCEPT_OFFER, parameters={
            "order_id": data.get("their_order_id"),
            "reason": "price_equal",
        })
    
    # Prices differ - continue to negotiation policies
    return None


@policy_callable("negotiation.action.price_interval_concession")
def negotiation_action_price_interval_concession(context: DecisionContext) -> DomainAction | None:
    """Price-based counter-offer policy using reservation band.
    
    CGT role: Implements the per-round "Strategic Decision" in the bilateral
    negotiation game, using thread state and resource-aware thresholds.
    
    Returns:
        ACCEPT_OFFER if their price is within our reservation band,
        COUNTER_OFFER with proposed price if outside but reasonable,
        EXIT_NEGOTIATION if far outside our band
    """
    from app.schema.pydantic_models import ActionType
    
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None
    
    if not isinstance(context.event, NegotiationEvent):
        return None
    
    data = context.event.data or {}
    our_price = data.get("our_price")
    their_price = data.get("their_price")
    negotiation_history = context.negotiation_history or []
    
    if our_price is None or their_price is None:
        return None  # Pass to next policy if price data missing
    
    # Determine reservation band from context
    # For now, use a simple heuristic: ±20% of our price
    # In production, derive from market_state, available_resources, etc.
    min_price = int(our_price * 0.8)  # We're willing to pay up to 20% more
    max_price = int(our_price * 1.2)  # We want at least 20% discount
    
    # Check if their price is within our reservation band
    if min_price <= their_price <= max_price:
        logger.info(f"[NEGOTIATION] Their price {their_price} within band [{min_price}, {max_price}], accepting")
        return DomainAction(action_type=ActionType.ACCEPT_OFFER, parameters={
            "order_id": data.get("their_order_id"),
            "reason": "within_reservation_band",
            "our_price": our_price,
            "their_price": their_price,
        })
    
    # Their price is outside our band - check if reasonable
    # Reasonable = within 2x or 0.5x (not completely unreasonable)
    reasonable_min = int(our_price * 0.5)
    reasonable_max = int(our_price * 2.0)
    
    if reasonable_min <= their_price <= reasonable_max:
        # Calculate counter-offer: midpoint between our last proposal and their current
        # For first round, use midpoint between our_price and their_price
        last_our_proposal = our_price
        if negotiation_history:
            # Find our last proposal from history
            for msg in reversed(negotiation_history):
                if msg.get("sender") == context.agent_id and msg.get("proposed_price"):
                    last_our_proposal = msg.get("proposed_price")
                    break
        
        # Propose midpoint (concession strategy)
        proposed_price = (last_our_proposal + their_price) // 2
        
        logger.info(f"[NEGOTIATION] Counter-offering {proposed_price} (between {last_our_proposal} and {their_price})")
        return DomainAction(action_type=ActionType.COUNTER_OFFER, parameters={
            "order_id": data.get("their_order_id"),
            "negotiation_id": context.event.negotiation_id,
            "proposed_price": proposed_price,
            "our_price": our_price,
            "their_price": their_price,
        })
    else:
        # Far outside reasonable range - exit negotiation
        logger.info(f"[NEGOTIATION] Their price {their_price} far outside reasonable range [{reasonable_min}, {reasonable_max}], exiting")
        return DomainAction(action_type=ActionType.EXIT_NEGOTIATION, parameters={
            "order_id": data.get("their_order_id"),
            "negotiation_id": context.event.negotiation_id,
            "reason": "price_far_outside_range",
        })


@policy_callable("negotiation.guard.bounded_rounds_and_timeout")
def negotiation_guard_bounded_rounds_and_timeout(context: DecisionContext) -> DomainAction | None:
    """Thread/termination policy: Enforce round limits and timeout.
    
    CGT role: Encodes the terminal checks and TIMEOUT/FAILURE outcomes
    from the Bilateral Negotiation Actions diagram.
    
    Returns:
        EXIT_NEGOTIATION if limits exceeded, None otherwise
    """
    from app.schema.pydantic_models import ActionType
    from datetime import datetime, timedelta
    
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None
    
    if not isinstance(context.event, NegotiationEvent):
        return None
    
    negotiation_history = context.negotiation_history or []
    max_rounds = 5  # Configurable default
    timeout_seconds = 300  # 5 minutes default
    
    # Check round limit
    if len(negotiation_history) >= max_rounds:
        logger.info(f"[NEGOTIATION] Max rounds ({max_rounds}) exceeded, exiting")
        return DomainAction(action_type=ActionType.EXIT_NEGOTIATION, parameters={
            "negotiation_id": context.event.negotiation_id,
            "reason": "max_rounds_exceeded",
        })
    
    # Check for stale negotiation (no price movement in last 2 rounds)
    if len(negotiation_history) >= 2:
        last_two = negotiation_history[-2:]
        prices = [msg.get("proposed_price") or msg.get("their_price") for msg in last_two if msg.get("proposed_price") or msg.get("their_price")]
        if len(prices) >= 2 and prices[-1] == prices[-2]:
            logger.info(f"[NEGOTIATION] No price movement in last 2 rounds, exiting")
            return DomainAction(action_type=ActionType.EXIT_NEGOTIATION, parameters={
                "negotiation_id": context.event.negotiation_id,
                "reason": "stale_negotiation",
            })
    
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
                    return DomainAction(action_type=ActionType.EXIT_NEGOTIATION, parameters={
                        "negotiation_id": context.event.negotiation_id,
                        "reason": "timeout",
                    })
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
    from app.schema.pydantic_models import ActionType
    
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None
    
    if not isinstance(context.event, NegotiationEvent):
        return None
    
    data = context.event.data or {}
    our_price = data.get("our_price")
    their_price = data.get("their_price")
    
    # If price data is missing or invalid, reject for safety
    if our_price is None or their_price is None:
        logger.warning(f"[NEGOTIATION] Missing price data, rejecting for safety")
        return DomainAction(action_type=ActionType.REJECT_OFFER, parameters={
            "order_id": data.get("their_order_id"),
            "negotiation_id": context.event.negotiation_id,
            "reason": "missing_price_data",
        })
    
    # Check for invalid price values
    if not isinstance(our_price, (int, float)) or not isinstance(their_price, (int, float)):
        logger.warning(f"[NEGOTIATION] Invalid price types, rejecting for safety")
        return DomainAction(action_type=ActionType.REJECT_OFFER, parameters={
            "order_id": data.get("their_order_id"),
            "negotiation_id": context.event.negotiation_id,
            "reason": "invalid_price_types",
        })
    
    if our_price <= 0 or their_price <= 0:
        logger.warning(f"[NEGOTIATION] Non-positive prices, rejecting for safety")
        return DomainAction(action_type=ActionType.REJECT_OFFER, parameters={
            "order_id": data.get("their_order_id"),
            "negotiation_id": context.event.negotiation_id,
            "reason": "non_positive_prices",
        })
    
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
    
    # Accept offer with resource details
    return DomainAction(
        action_type=ActionType.ACCEPT_OFFER,
        parameters={
            "order_id": order.order_id,
            "order": order,
            "offer_resource": offer_resource.model_dump(mode='json'),
            "demand_resource": demand_resource.model_dump(mode='json'),
        }
    )
