"""API-credits implementation of the core storefront domain runtime."""

from __future__ import annotations

from typing import Any

from core_storefront.domain_runtime import StorefrontDomainRuntime

from domains.apicredits.schema import (
    API_CREDITS_SCHEMA_KIND,
    ApiCreditsListing,
    ApiCreditsMaterialization,
    ApiCreditsMessage,
    ApiCreditsReceipt,
    ApiCreditsResult,
    ApiCreditsTerms,
)


def _normalize_listing(value: Any) -> ApiCreditsListing:
    return ApiCreditsListing.model_validate(value)


def _normalize_message(value: Any) -> ApiCreditsMessage:
    return ApiCreditsMessage.model_validate(value)


def _normalize_terms(value: Any) -> ApiCreditsTerms:
    return ApiCreditsTerms.model_validate(value)


def _normalize_materialization(value: Any) -> ApiCreditsMaterialization:
    return ApiCreditsMaterialization.model_validate(value)


def _normalize_receipt(value: Any) -> ApiCreditsReceipt:
    return ApiCreditsReceipt.model_validate(value)


def _normalize_result(value: Any) -> ApiCreditsResult:
    return ApiCreditsResult.model_validate(value)


API_CREDITS_STOREFRONT_RUNTIME = StorefrontDomainRuntime(
    schema_id=API_CREDITS_SCHEMA_KIND,
    normalize_listing=_normalize_listing,
    normalize_message=_normalize_message,
    normalize_terms=_normalize_terms,
    normalize_materialization=_normalize_materialization,
    normalize_receipt=_normalize_receipt,
    normalize_result=_normalize_result,
)


def storefront_runtime() -> StorefrontDomainRuntime:
    """Return the API-credits domain runtime for core storefront composition."""
    return API_CREDITS_STOREFRONT_RUNTIME
