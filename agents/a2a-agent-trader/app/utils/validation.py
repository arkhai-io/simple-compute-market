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
) -> tuple[MarketOrder | None, ComputeResource | None, ComputeResource | None, TokenResource | None, TokenResource | None]:
    """Safely extract offer_resource and demand_resource from MakeOfferEvent.
    
    Extracts and categorizes resources from a MakeOfferEvent, returning them
    as typed tuples for easy access in policy functions. Also returns the order
    for convenience to avoid redundant extraction.
    
    Args:
        context: DecisionContext containing the event
        
    Returns:
        Tuple of (order, offer_compute, demand_compute, offer_token, demand_token)
        - order: MarketOrder instance if event is MakeOfferEvent, None otherwise
        - Each resource element is None if the corresponding resource is not of that type.
    """
    if not isinstance(context.event, MakeOfferEvent):
        return None, None, None, None, None
    
    order = context.event.order
    offer_resource = order.offer_resource
    demand_resource = order.demand_resource
    
    offer_compute = offer_resource if isinstance(offer_resource, ComputeResource) else None
    offer_token = offer_resource if isinstance(offer_resource, TokenResource) else None
    demand_compute = demand_resource if isinstance(demand_resource, ComputeResource) else None
    demand_token = demand_resource if isinstance(demand_resource, TokenResource) else None
    
    return order, offer_compute, demand_compute, offer_token, demand_token

