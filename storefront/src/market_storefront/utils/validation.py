"""Validation utilities for alerts, orders, and resource extraction.

TODO(refactor): This module still includes compute-domain validation helpers.
Split domain-specific checks into the compute domain package as refactor continues.
"""

from __future__ import annotations

from typing import Any

from market_storefront.schema.pydantic_models import (
    ResourceAlertRequest,
    Listing,
    ComputeResource,
    ComputeDomainResource,
    TokenResource,
)


def validate_model(model_cls: Any, payload: dict[str, Any]) -> Any:
    """Validate a dict payload against a model class exposing model_validate()."""
    return model_cls.model_validate(payload)


def validate_alert(alert_dict: dict[str, Any]) -> ResourceAlertRequest:
    """Validate and convert alert dictionary to ResourceAlertRequest."""
    return validate_model(ResourceAlertRequest, alert_dict)


def validate_market_order(order_dict: dict[str, Any]) -> Listing:
    """Validate and convert market order dictionary to Listing."""
    return validate_model(Listing, order_dict)


def extract_compute_resource(resource: ComputeDomainResource) -> ComputeResource | None:
    """Type-safe extraction of ComputeResource from Resource."""
    if isinstance(resource, ComputeResource):
        return resource
    return None


def extract_token_resource(resource: ComputeDomainResource) -> TokenResource | None:
    """Type-safe extraction of TokenResource from Resource."""
    if isinstance(resource, TokenResource):
        return resource
    return None


def determine_strategy_from_resources(
    offer_resource: ComputeDomainResource | None,
    demand_resource: ComputeDomainResource | None,
) -> str | None:
    """Determine negotiation strategy from resource types."""
    if not offer_resource or not demand_resource:
        return None

    is_offering_compute = isinstance(offer_resource, ComputeResource)
    is_demanding_compute = isinstance(demand_resource, ComputeResource)

    if is_demanding_compute:
        return "minimize"
    if is_offering_compute:
        return "maximize"
    return None


def determine_strategy_from_order(order: Listing | None) -> str | None:
    """Determine negotiation strategy from a Listing."""
    if not order:
        return None

    return determine_strategy_from_resources(order.offer_resource, order.demand_resource)
