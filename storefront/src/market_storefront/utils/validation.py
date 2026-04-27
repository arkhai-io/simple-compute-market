"""Validation utilities for alerts, orders, and resource extraction.

TODO(refactor): This module still includes compute-domain validation helpers.
Split domain-specific checks into the compute domain package as refactor continues.
"""

from __future__ import annotations

from typing import Any

from market_storefront.schema.pydantic_models import (
    ResourceAlertRequest,
    MarketOrder,
    ComputeResource,
    ComputeDomainResource,
    TokenResource,
    MakeOfferEvent,
    DecisionContext,
)


def validate_model(model_cls: Any, payload: dict[str, Any]) -> Any:
    """Validate a dict payload against a model class exposing model_validate()."""
    return model_cls.model_validate(payload)


def validate_alert(alert_dict: dict[str, Any]) -> ResourceAlertRequest:
    """Validate and convert alert dictionary to ResourceAlertRequest."""
    return validate_model(ResourceAlertRequest, alert_dict)


def validate_market_order(order_dict: dict[str, Any]) -> MarketOrder:
    """Validate and convert market order dictionary to MarketOrder."""
    return validate_model(MarketOrder, order_dict)


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


def extract_resources_from_make_offer_event(
    context: DecisionContext,
) -> tuple[MarketOrder | None, ComputeDomainResource | None, ComputeDomainResource | None]:
    """Safely extract offer_resource and demand_resource from MakeOfferEvent."""
    if not isinstance(context.event, MakeOfferEvent):
        return None, None, None

    order = context.event.order
    offer_resource = order.offer_resource
    demand_resource = order.demand_resource

    return order, offer_resource, demand_resource


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


def determine_strategy_from_order(order: MarketOrder | None) -> str | None:
    """Determine negotiation strategy from a MarketOrder."""
    if not order:
        return None

    return determine_strategy_from_resources(order.offer_resource, order.demand_resource)
