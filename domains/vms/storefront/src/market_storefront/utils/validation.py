"""Validation utilities for orders and resource extraction.

TODO(refactor): This module still includes compute-domain validation helpers.
Split domain-specific checks into the compute domain package as refactor continues.
"""

from __future__ import annotations

from typing import Any

from domains.vms.listings import (
    determine_strategy_from_order as _vm_determine_strategy_from_order,
    determine_strategy_from_resources as _vm_determine_strategy_from_resources,
)
from domains.vms.listings.models import (
    Listing,
    ComputeResource,
    ComputeDomainResource,
    TokenResource,
)


def validate_model(model_cls: Any, payload: dict[str, Any]) -> Any:
    """Validate a dict payload against a model class exposing model_validate()."""
    return model_cls.model_validate(payload)


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
) -> str | None:
    """Compatibility wrapper for VM-domain strategy selection."""
    return _vm_determine_strategy_from_resources(offer_resource)


def determine_strategy_from_order(order: Listing | None) -> str | None:
    """Compatibility wrapper for VM-domain strategy selection."""
    return _vm_determine_strategy_from_order(order)
