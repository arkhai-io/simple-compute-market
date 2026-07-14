"""Bare-metal implementation of the core storefront domain runtime."""

from __future__ import annotations

from typing import Any

from core_storefront.domain_runtime import StorefrontDomainRuntime

from .schema import (
    BARE_METAL_SCHEMA_KIND,
    BareMetalAccessResult,
    BareMetalListing,
    BareMetalMaterialization,
    BareMetalMessage,
    BareMetalReceipt,
    BareMetalTerms,
)


def _normalize_listing(value: Any) -> BareMetalListing:
    return BareMetalListing.model_validate(value)


def _normalize_message(value: Any) -> BareMetalMessage:
    return BareMetalMessage.model_validate(value)


def _normalize_terms(value: Any) -> BareMetalTerms:
    return BareMetalTerms.model_validate(value)


def _normalize_materialization(value: Any) -> BareMetalMaterialization:
    return BareMetalMaterialization.model_validate(value)


def _normalize_receipt(value: Any) -> BareMetalReceipt:
    return BareMetalReceipt.model_validate(value)


def _normalize_result(value: Any) -> BareMetalAccessResult:
    return BareMetalAccessResult.model_validate(value)


BARE_METAL_STOREFRONT_RUNTIME = StorefrontDomainRuntime(
    schema_id=BARE_METAL_SCHEMA_KIND,
    normalize_listing=_normalize_listing,
    normalize_message=_normalize_message,
    normalize_terms=_normalize_terms,
    normalize_materialization=_normalize_materialization,
    normalize_receipt=_normalize_receipt,
    normalize_result=_normalize_result,
)


def storefront_runtime() -> StorefrontDomainRuntime:
    """Return the bare-metal domain runtime for core storefront composition."""
    return BARE_METAL_STOREFRONT_RUNTIME

