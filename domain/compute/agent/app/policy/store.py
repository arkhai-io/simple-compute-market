from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from market_storefront.models.domain_models import (
    Action as DomainAction,
    ActionType as DomainActionType,
    ReceiveComputeObligationFulfillmentEvent,
    FulfillmentFailedEvent,
    ArbitrationCompleteEvent,
    DecisionContext,
    Listing,
    ListingCreatedEvent,
    ListingClosedEvent,
    ComputeResource,
    TokenResource,
    ComputeResourcePortfolio,
)
# AcceptOfferEvent, MakeOfferEvent, NegotiationEvent were removed in the
# listings rename refactor.  Callables that guarded on these types are
# temporarily no-ops (return None immediately) until the event model is restored.
from market_policy.registry import policy_callable
from market_policy.action_builders import NegotiationActionBuilder, make_negotiation_id
from market_policy.negotiation_thread import get_thread_store, NegotiationThreadTransaction
from market_storefront.utils.validation import determine_strategy_from_order
from registry_client import RegistryClient, RegistryClientError
from market_storefront.utils.config import CONFIG
from market_storefront.utils.action_executor import _extract_initial_price_from_order

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
    if not isinstance(context.event, ListingCreatedEvent):
        return None

    offer = context.event.offer
    demand = context.event.demand
    max_duration_seconds = context.event.max_duration_seconds

    # Enrich a bare ComputeResource offer (no resource_id) with the actual registered
    # portfolio resource so that resource_id and vm_host are populated.
    if isinstance(offer, ComputeResource) and offer.resource_id is None:
        portfolio = get_compute_resource_portfolio(context)
        if portfolio:
            for resource in portfolio.resources:
                if (
                    resource.gpu_model == offer.gpu_model
                    and resource.region == offer.region
                    and resource.sla >= offer.sla
                    and resource.gpu_count >= offer.gpu_count
                ):
                    offer = resource
                    break

    offer_payload = offer.model_dump(mode="json") if hasattr(offer, "model_dump") else offer
    demand_payload = demand.model_dump(mode="json") if hasattr(demand, "model_dump") else demand

    return DomainAction(
        action_type=DomainActionType.MAKE_OFFER,
        parameters={
            "offer": offer_payload,
            "demand": demand_payload,
            "max_duration_seconds": max_duration_seconds,
            # Propagate paused flag so action_executor skips the registry publish.
            "paused": bool(context.event.data.get("paused", False)) if isinstance(context.event.data, dict) else False,
        },
    )


@policy_callable("oc.action.close_order")
def oc_action_close_order(context: DecisionContext) -> DomainAction | None:
    if not isinstance(context.event, ListingClosedEvent):
        return None
    return DomainAction(
        action_type=DomainActionType.CLOSE_ORDER,
        parameters={"listing_id": context.event.listing_id},
    )


@policy_callable("ri.action.make_offer_from_resource")
def ri_action_make_offer_from_resource(context: DecisionContext) -> DomainAction | None:
    res = getattr(context.event, "resource", None)
    if not res:
        return None
    return DomainAction(
        action_type=DomainActionType.MAKE_OFFER,
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
    if True:  # AcceptOfferEvent removed; no-op until event model is restored
        return None

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

    agreed_price = getattr(context.event, "agreed_price", None)

    if compute_buyer:
        if escrow_uid:
            return None
        neg_id = make_negotiation_id(order.order_id, matched_order_id) if matched_order_id else None
        our_initial_price = _extract_initial_price_from_order(order)
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
                "our_price": agreed_price or our_initial_price,
                "their_price": agreed_price or our_initial_price,
                "our_strategy": "minimize",
            },
        )

    if not escrow_uid or not ssh_key:
        return None

    order_data = order.model_dump(mode="json")
    if agreed_price is not None:
        demand = order_data.get("demand_resource") or {}
        if isinstance(demand, dict) and "amount" in demand:
            order_data = {**order_data, "demand_resource": {**demand, "amount": agreed_price}}

    return DomainAction(
        action_type=DomainActionType.FULFILL_COMPUTE_OBLIGATION,
        parameters={
            "order": order_data,
            "escrow_uid": escrow_uid,
            "ssh_public_key": ssh_key,
            "oracle_address": order.oracle_address,
            "counterparty_url": sender_url,
            "matched_order_id": matched_order_id,
            "buyer_order_id": getattr(context.event, "buyer_order_id", None) or order.order_id,
        },
    )


@policy_callable("rcf.action.trust_fulfillment")
def rcf_action_trust_fulfillment(context: DecisionContext) -> DomainAction | None:
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


@policy_callable("ff.action.handle_fulfillment_failure")
def ff_action_handle_fulfillment_failure(context: DecisionContext) -> DomainAction | None:
    if not isinstance(context.event, FulfillmentFailedEvent):
        return None
    return DomainAction(
        action_type=DomainActionType.HANDLE_FULFILLMENT_FAILURE,
        parameters={
            "escrow_uid": context.event.escrow_uid,
            "reason": context.event.reason,
            "seller_order_id": context.event.seller_order_id,
            "buyer_order_id": context.event.buyer_order_id,
        },
    )


@policy_callable("arb.action.collect_escrow_after_arbitration")
def arb_action_collect_escrow_after_arbitration(context: DecisionContext) -> DomainAction | None:
    if not isinstance(context.event, ArbitrationCompleteEvent):
        return None

    data = getattr(context.event, "data", {}) or {}
    escrow_uid = getattr(context.event, "escrow_uid", None) or data.get("escrow_uid")
    fulfillment_uid = getattr(context.event, "fulfillment_uid", None) or data.get("fulfillment_uid")

    if not escrow_uid or not fulfillment_uid:
        return None

    return DomainAction(
        action_type=DomainActionType.COLLECT_ESCROW,
        parameters={
            "escrow_uid": escrow_uid,
            "fulfillment_uid": fulfillment_uid,
            "decisions": getattr(context.event, "decisions", None) or data.get("decisions"),
            "oracle_address": getattr(context.event, "oracle_address", None) or data.get("oracle_address"),
            "status": getattr(context.event, "status", None) or data.get("status"),
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
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None
    if True:  # NegotiationEvent removed; no-op until event model is restored
        return None

    data = context.event.data or {}
    their_price = data.get("proposed_price")
    thread_info = context.market_state.get("thread_info", {})
    negotiation_history = context.negotiation_history or []

    last_our_proposal = thread_info.get("our_initial_price")
    if negotiation_history:
        for msg in reversed(negotiation_history):
            if msg.get("sender") == context.agent_id and msg.get("proposed_price"):
                last_our_proposal = msg.get("proposed_price")
                break

    if last_our_proposal is not None and their_price is not None and last_our_proposal == their_price:
        logger.info("[NEGOTIATION] Prices equal (%s), accepting directly", last_our_proposal)
        data = {
            **data,
            "counterparty_url": thread_info.get("their_agent_id"),
            "our_price": thread_info.get("our_initial_price"),
            "their_price": their_price,
            "our_strategy": thread_info.get("our_strategy"),
        }
        return NegotiationActionBuilder(data).accept("price_equal")
    return None


@policy_callable("negotiation.action.price_interval_concession")
def negotiation_action_price_interval_concession(context: DecisionContext) -> DomainAction | None:
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None
    if True:  # NegotiationEvent removed; no-op until event model is restored
        return None

    data = context.event.data or {}
    negotiation_history = context.negotiation_history or []
    their_price = data.get("proposed_price")

    thread_info = context.market_state.get("thread_info", {})
    our_price = thread_info.get("our_initial_price")
    strategy = thread_info.get("our_strategy")

    if our_price is None or their_price is None:
        logger.info("[NEGOTIATION] Missing price data: our_price=%s, their_price=%s", our_price, their_price)
        return None

    if context.event.negotiation_id and "negotiation_id" not in data:
        data = {**data, "negotiation_id": context.event.negotiation_id}

    data = {**data, "our_price": our_price, "their_price": their_price,
            "counterparty_url": thread_info.get("their_agent_id")}
    actions = NegotiationActionBuilder(data)

    REASONABLE_MULTIPLIER = 1.5
    CONVERGENCE_RATIO = 0.01

    if strategy == "minimize":
        last_our_proposal = our_price
        if negotiation_history:
            for msg in reversed(negotiation_history):
                if msg.get("sender") == context.agent_id and msg.get("proposed_price"):
                    last_our_proposal = msg.get("proposed_price")
                    break
        if their_price <= last_our_proposal * (1 + CONVERGENCE_RATIO):
            return actions.accept("convergence")
        elif their_price <= our_price * REASONABLE_MULTIPLIER:
            return actions.counter((last_our_proposal + their_price) // 2)
        else:
            return actions.exit("price_unreasonable")

    elif strategy == "maximize":
        last_our_proposal = our_price
        if negotiation_history:
            for msg in reversed(negotiation_history):
                if msg.get("sender") == context.agent_id and msg.get("proposed_price"):
                    last_our_proposal = msg.get("proposed_price")
                    break
        if their_price >= last_our_proposal * (1 - CONVERGENCE_RATIO):
            return actions.accept("convergence")
        elif their_price >= our_price / REASONABLE_MULTIPLIER:
            return actions.counter((last_our_proposal + their_price) // 2)
        else:
            return actions.exit("price_unreasonable")

    return None


@policy_callable("negotiation.guard.bounded_rounds_and_timeout")
def negotiation_guard_bounded_rounds_and_timeout(context: DecisionContext) -> DomainAction | None:
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None
    if True:  # NegotiationEvent removed; no-op until event model is restored
        return None

    negotiation_history = context.negotiation_history or []
    max_rounds = 10
    timeout_seconds = 300

    data = context.event.data or {}
    if context.event.negotiation_id and "negotiation_id" not in data:
        data = {**data, "negotiation_id": context.event.negotiation_id}
    actions = NegotiationActionBuilder(data)

    our_messages = [m for m in negotiation_history if m.get("sender") == context.agent_id]
    if len(our_messages) >= max_rounds:
        return actions.exit("max_rounds_exceeded")

    if len(our_messages) >= 2:
        prices = [m.get("proposed_price") for m in our_messages[-2:] if m.get("proposed_price")]
        if len(prices) >= 2 and prices[-1] == prices[-2]:
            return actions.exit("stale_negotiation")

    if negotiation_history:
        first_timestamp_str = negotiation_history[0].get("timestamp")
        if first_timestamp_str:
            try:
                first_ts = datetime.fromisoformat(first_timestamp_str.replace("Z", "+00:00"))
                elapsed = (datetime.now(first_ts.tzinfo) - first_ts).total_seconds()
                if elapsed > timeout_seconds:
                    return actions.exit("timeout")
            except Exception as exc:
                logger.warning("[NEGOTIATION] Failed to parse timestamp: %s", exc)

    return None


@policy_callable("negotiation.action.safe_default_reject")
def negotiation_action_safe_default_reject(context: DecisionContext) -> DomainAction | None:
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None
    if True:  # NegotiationEvent removed; no-op until event model is restored
        return None

    if context.event.message_type in ("exit", "accept"):
        return None

    data = context.event.data or {}
    their_price = data.get("proposed_price")
    thread_info = context.market_state.get("thread_info", {})
    our_price = thread_info.get("our_initial_price")

    if context.event.negotiation_id and "negotiation_id" not in data:
        data = {**data, "negotiation_id": context.event.negotiation_id}
    actions = NegotiationActionBuilder(data)

    if our_price is None or their_price is None:
        return actions.reject("missing_price_data")
    if not isinstance(our_price, (int, float)) or not isinstance(their_price, (int, float)):
        return actions.reject("invalid_price_types")
    if our_price <= 0 or their_price <= 0:
        return actions.reject("non_positive_prices")

    return None


@policy_callable("negotiation.action.handle_exit")
def negotiation_action_handle_exit(context: DecisionContext) -> DomainAction | None:
    et = context.event.event_type
    trigger = et.value if hasattr(et, "value") else str(et)
    if trigger != "negotiation":
        return None
    if True:  # NegotiationEvent removed; no-op until event model is restored
        return None

    if context.event.message_type != "exit":
        return None

    negotiation_id = context.event.negotiation_id
    if not negotiation_id:
        return None

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
    logger.info(
        "[NEGOTIATION] Counterparty exited negotiation %s (reason: %s) — thread marked terminal",
        negotiation_id, data.get("reason", "counterparty_exited"),
    )
    return None


@policy_callable("negotiation.respond_to_make_offer")
async def negotiation_respond_to_make_offer(context: DecisionContext) -> DomainAction | None:
    et = context.event.event_type
    if et.value != "make_offer":
        return None
    if True:  # MakeOfferEvent removed; no-op until event model is restored
        return None

    order_obj = context.event.order
    if not order_obj:
        return None

    incoming_order = order_obj.model_dump(mode="json") if isinstance(order_obj, Listing) else order_obj

    _our_url = (CONFIG.base_url_override or "").strip().rstrip("/").lower()
    _their_url = (incoming_order.get("order_maker") or "").strip().rstrip("/").lower()
    if _our_url and _our_url == _their_url:
        return None

    _offer_res = incoming_order.get("offer_resource") or {}
    _demand_res = incoming_order.get("demand_resource") or {}
    if "gpu_model" not in _offer_res and "gpu_model" not in _demand_res:
        logger.warning("[NEGOTIATION] Rejecting order with no compute resource: %s", incoming_order.get("order_id"))
        return None

    their_proposed_price = _extract_initial_price_from_order(incoming_order)
    registry_url = getattr(CONFIG, "registry_url", None) or getattr(CONFIG, "indexer_url", "http://localhost:8080")
    async with RegistryClient(registry_url) as registry_client:
        orders_resp = await registry_client.list_orders(status="open")
    our_order = None

    for order_summary in orders_resp.orders:
        order_dict = {
            "order_id": str(order_summary.id),
            "offer_resource": order_summary.offer,
            "demand_resource": order_summary.demand,
            "status": order_summary.status,
        }
        if order_dict.get("order_id") == incoming_order.get("order_id"):
            continue
        order = Listing.model_validate(order_dict)
        if determine_strategy_from_order(order):
            our_order = order_dict
            break

    if not our_order:
        return NegotiationActionBuilder({}).reject("no_matching_order")

    market_order = Listing.model_validate(our_order)
    strategy = determine_strategy_from_order(market_order)
    our_price = _extract_initial_price_from_order(our_order)

    their_order_id = incoming_order.get("order_id", "")
    our_order_id = our_order.get("order_id", "")
    negotiation_id = make_negotiation_id(our_order_id, their_order_id)

    canonical_first = min(our_order_id, their_order_id)
    if our_order_id == canonical_first:
        thread_store = get_thread_store()
        existing_thread = await thread_store.get_thread_info(
            negotiation_id=negotiation_id,
            owner_id=(CONFIG.base_url_override or ""),
        )
        if existing_thread is not None:
            return None

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
        return NegotiationActionBuilder(_action_dict).exit("max_rounds")
    if len(_our_counters) >= 2:
        _last_prices = [m.get("proposed_price") for m in _our_counters[-2:]]
        if _last_prices[0] is not None and _last_prices[0] == _last_prices[1]:
            return NegotiationActionBuilder(_action_dict).exit("stale_negotiation")

    actions = NegotiationActionBuilder(_action_dict)
    CONVERGENCE_RATIO = 0.01

    if strategy == "minimize":
        if their_proposed_price <= our_price * (1 + CONVERGENCE_RATIO):
            return actions.accept("convergence")
        if their_proposed_price <= our_price * 1.5:
            return actions.counter((our_price + their_proposed_price) // 2)
        return actions.exit("price_unreasonable")

    if strategy == "maximize":
        if their_proposed_price >= our_price * (1 - CONVERGENCE_RATIO):
            return actions.accept("convergence")
        if their_proposed_price >= our_price / 1.5:
            return actions.counter((our_price + their_proposed_price) // 2)
        return actions.exit("price_unreasonable")

    return actions.reject("unknown_strategy")
