"""Live policy callables for the compute domain.

Three flows currently fan out from `PolicyService` through this module:
  * `oc.action.make_offer_from_order_create` — `ListingCreatedEvent` → `MAKE_OFFER`
  * `oc.action.close_order`                  — `ListingClosedEvent`  → `CLOSE_ORDER`
  * `ri.action.make_offer_from_resource`     — `ResourceImbalanceEvent` (surplus) → `MAKE_OFFER`

Plus two guards used inside the resource-imbalance composite:
  * `ri.guard.trigger_is_resource_imbalance`
  * `ri.guard.resource_present`

The legacy negotiation / accept-offer / fulfillment / arbitration callables
were no-ops (`if True: return None`) since the listings rename refactor and
have been removed. Negotiation round decisions go through
`sync_negotiation.py` directly via `NegotiationStrategy`, not the
`@policy_callable` chain.
"""

from __future__ import annotations

import logging
from typing import Any

from market_storefront.models.domain_models import (
    Action as DomainAction,
    ActionType as DomainActionType,
    DecisionContext,
    ListingCreatedEvent,
    ListingClosedEvent,
    NegotiationRequestedEvent,
    ComputeResource,
    ComputeResourcePortfolio,
)
from market_policy.registry import policy_callable
from market_storefront.utils.config import CONFIG
from service.clients.token import TOKEN_REGISTRY

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


# ---------------------------------------------------------------------------
# Pre-thread negotiation guards (used inside the negotiate_request composite)
# ---------------------------------------------------------------------------


def _coerce_resource_dict(value: Any) -> dict[str, Any]:
    """Listings persist offer/demand as JSON text; normalise to a dict."""
    import json
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


@policy_callable("negotiate.guard.has_matching_inventory")
def negotiate_guard_has_matching_inventory(
    context: DecisionContext,
) -> DomainAction | None:
    """Veto a negotiation request when no available portfolio resource
    matches the listing's offer (gpu_model + region).

    Designed for the *immediate-deal* seller: capacity must exist now.
    Operators running futures or off-chain-matched flows drop this guard
    from the negotiate-request composite — the seller will then accept
    threads against listings whose inventory will materialise later.

    Read-only against ``context.available_resources["resources"]``
    (which ``policy_service._consult_policy`` populates from
    ``db.list_resources()``); never mutates state. Listings whose offer
    isn't compute (token-for-token swaps) are treated as always-
    fulfillable here — capacity for those is enforced by the chain.
    """
    if not isinstance(context.event, NegotiationRequestedEvent):
        return None

    offer = _coerce_resource_dict(context.event.listing.get("offer_resource"))
    if "gpu_model" not in offer:
        return None  # not a compute listing — pass through

    required: dict[str, Any] = {}
    for key in ("region", "gpu_model"):
        v = offer.get(key)
        if v is not None:
            required[key] = v

    portfolio_raw = (context.available_resources or {}).get("resources") or []
    for row in portfolio_raw:
        # ``available_resources`` carries the full SQLite row — only
        # ``state == 'available'`` rows are eligible. The portfolio loader
        # in ``policy_service`` returns every resource regardless of
        # state, so we filter here.
        if (row.get("state") or "").strip() != "available":
            continue
        attrs = row.get("attributes")
        if isinstance(attrs, str):
            try:
                import json
                attrs = json.loads(attrs)
            except (ValueError, TypeError):
                continue
        if not isinstance(attrs, dict):
            continue
        if all(attrs.get(k) == v for k, v in required.items()):
            return None  # found a match, pass

    return DomainAction(
        action_type=DomainActionType.REJECT_OFFER,
        parameters={
            "reason": "no_matching_inventory",
            "listing_id": context.event.listing_id,
        },
    )


# ---------------------------------------------------------------------------
# Resource-imbalance guards (used inside the resource_imbalance composite)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Listing lifecycle actions
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Resource-imbalance action
# ---------------------------------------------------------------------------

@policy_callable("ri.action.make_offer_from_resource")
def ri_action_make_offer_from_resource(context: DecisionContext) -> DomainAction | None:
    """Build a MAKE_OFFER for a resource imbalance.

    Only handles `surplus` (we have spare capacity, sell it). For any
    other imbalance type the callable returns None — deficit alerts are
    a buy-side concern that this storefront doesn't handle. The action
    must carry full `offer` and `demand` parameters or
    `action_executor.execute_action` will reject it on dispatch.
    """
    res = getattr(context.event, "resource", None)
    if not res or not isinstance(res, ComputeResource):
        return None

    imbalance_type = getattr(context.event, "imbalance_type", "surplus")
    if imbalance_type != "surplus":
        return None

    # Resolve the demand-side token from CONFIG defaults; same path the
    # auto-publish loop uses when synthesising listings from the seller's
    # resource portfolio.
    if not CONFIG.default_min_price:
        logger.info(
            "[RI POLICY] Skipping MAKE_OFFER for surplus alert: "
            "[seller.pricing].default_min_price not configured"
        )
        return None
    try:
        token_meta = TOKEN_REGISTRY.require(CONFIG.default_token)
    except Exception as exc:
        logger.warning(
            "[RI POLICY] Skipping MAKE_OFFER: cannot resolve default token %r: %s",
            CONFIG.default_token, exc,
        )
        return None

    offer_payload = res.model_dump(mode="json")
    demand_payload = {
        "token": {
            "symbol": token_meta.symbol,
            "contract_address": token_meta.contract_address,
            "decimals": token_meta.decimals,
        },
        "amount": int(CONFIG.default_min_price),
    }

    return DomainAction(
        action_type=DomainActionType.MAKE_OFFER,
        parameters={
            "offer": offer_payload,
            "demand": demand_payload,
            "max_duration_seconds": CONFIG.default_max_duration_seconds or None,
            "paused": False,
        },
    )
