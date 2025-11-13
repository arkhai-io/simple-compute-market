"""Validation utilities for alerts, orders, and resource extraction."""

from typing import Any
from pydantic import ValidationError

from app.schema.pydantic_models import (
    ResourceAlertRequest,
    MarketOrder,
    ComputeResource,
    TokenResource,
    Resource,
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

