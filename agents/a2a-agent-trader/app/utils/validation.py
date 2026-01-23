"""Validation utilities for alerts, orders, and resource extraction."""

from typing import Any
from pydantic import ValidationError

from app.schema.pydantic_models import (
    ResourceAlertRequest,
    MarketOrder,
    ComputeResource,
    TokenResource,
    Resource,
    MakeOfferEvent,
    DecisionContext,
)


def validate_alert(alert_dict: dict[str, Any]) -> ResourceAlertRequest:
    """Validate and convert alert dictionary to ResourceAlertRequest.
    
    Args:
        alert_dict: Dictionary containing alert data
        
    Returns:
        Validated ResourceAlertRequest instance
        
    Raises:
        ValidationError: If alert structure is invalid
    """
    return ResourceAlertRequest.model_validate(alert_dict)


def validate_market_order(order_dict: dict[str, Any]) -> MarketOrder:
    """Validate and convert market order dictionary to MarketOrder.
    
    Args:
        order_dict: Dictionary containing market order data
        
    Returns:
        Validated MarketOrder instance
        
    Raises:
        ValidationError: If order structure is invalid
    """
    return MarketOrder.model_validate(order_dict)


def extract_compute_resource(resource: Resource) -> ComputeResource | None:
    """Type-safe extraction of ComputeResource from Resource.
    
    Args:
        resource: Resource instance (could be ComputeResource or TokenResource)
        
    Returns:
        ComputeResource if resource is ComputeResource, None otherwise
    """
    if isinstance(resource, ComputeResource):
        return resource
    return None


def extract_token_resource(resource: Resource) -> TokenResource | None:
    """Type-safe extraction of TokenResource from Resource.
    
    Args:
        resource: Resource instance (could be ComputeResource or TokenResource)
        
    Returns:
        TokenResource if resource is TokenResource, None otherwise
    """
    if isinstance(resource, TokenResource):
        return resource
    return None


def extract_resources_from_make_offer_event(
    context: DecisionContext,
) -> tuple[MarketOrder | None, Resource | None, Resource | None]:
    """Safely extract offer_resource and demand_resource from MakeOfferEvent.

    Extracts resources from a MakeOfferEvent, returning the order and both resources.
    Callers can use isinstance() to check resource types as needed.

    Args:
        context: DecisionContext containing the event

    Returns:
        Tuple of (order, offer_resource, demand_resource)
        - order: MarketOrder instance if event is MakeOfferEvent, None otherwise
        - offer_resource: Resource instance (ComputeResource or TokenResource) if order exists, None otherwise
        - demand_resource: Resource instance (ComputeResource or TokenResource) if order exists, None otherwise
    """
    if not isinstance(context.event, MakeOfferEvent):
        return None, None, None

    order = context.event.order
    offer_resource = order.offer_resource
    demand_resource = order.demand_resource

    return order, offer_resource, demand_resource


def determine_strategy_from_resources(
    offer_resource: Resource | None,
    demand_resource: Resource | None,
) -> str | None:
    """Determine negotiation strategy from resource types.

    In a compute-for-token market:
    - Maximizer (offering compute): offers ComputeResource, demands TokenResource
    - Minimizer (demanding compute): offers TokenResource, demands ComputeResource

    Args:
        offer_resource: Resource being offered
        demand_resource: Resource being demanded

    Returns:
        "minimize" if demanding compute (wants lowest rate), "maximize" if offering compute (wants highest rate), None if unclear
    """
    if not offer_resource or not demand_resource:
        return None

    is_offering_compute = isinstance(offer_resource, ComputeResource)
    is_demanding_compute = isinstance(demand_resource, ComputeResource)

    if is_demanding_compute:
        return "minimize"
    elif is_offering_compute:
        return "maximize"
    else:
        return None


def determine_strategy_from_order(order: MarketOrder | None) -> str | None:
    """Determine negotiation strategy from a MarketOrder.

    Args:
        order: MarketOrder instance

    Returns:
        "minimize" if demanding compute (wants lowest rate), "maximize" if offering compute (wants highest rate), None if unclear
    """
    if not order:
        return None

    return determine_strategy_from_resources(order.offer_resource, order.demand_resource)

