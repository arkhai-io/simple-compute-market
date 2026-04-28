from __future__ import annotations

import logging
from typing import Any

from market_storefront.schema.pydantic_models import (
    Action as DomainAction,
    ActionType as DomainActionType,
    ReceiveComputeObligationFulfillmentEvent,
    FulfillmentFailedEvent,
    ArbitrationCompleteEvent,
    DecisionContext,
    MarketOrder,
    ComputeResource,
    TokenResource,
    ComputeResourcePortfolio,
)
from market_policy.registry import policy_callable
from market_storefront.utils.validation import determine_strategy_from_order
from service.clients.indexer import get_registry_client
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
    from market_storefront.schema.pydantic_models import ActionType, OrderCreateEvent

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
    from market_storefront.schema.pydantic_models import ActionType, OrderCloseEvent

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
    from market_storefront.schema.pydantic_models import ActionType

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

# Fulfillment failed -> acknowledge failure, reopen order
@policy_callable("ff.action.handle_fulfillment_failure")
def ff_action_handle_fulfillment_failure(context: DecisionContext) -> DomainAction | None:
    """When the seller notifies us that provisioning failed, handle the failure."""
    if not isinstance(context.event, FulfillmentFailedEvent):
        return None
    return DomainAction(
        action_type=DomainActionType.HANDLE_FULFILLMENT_FAILURE,
        parameters={
            "escrow_uid": context.event.escrow_uid,
            "reason": context.event.reason,
            "seller_order_id": context.event.seller_order_id,
            "negotiation_id": context.event.negotiation_id,
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


