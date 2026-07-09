"""VM implementation of the core storefront domain runtime."""

from __future__ import annotations

from typing import Any

from core_storefront.domain_runtime import StorefrontDomainRuntime

from .provision_terms import VM_PROVISION_KIND
from .schema import (
    VmListing,
    VmMaterialization,
    VmMessage,
    VmReceipt,
    VmResult,
    VmTerms,
)


def _normalize_listing(value: Any) -> VmListing:
    return VmListing.model_validate(value)


def _normalize_message(value: Any) -> VmMessage:
    return VmMessage.model_validate(value)


def _normalize_terms(value: Any) -> VmTerms:
    return VmTerms.model_validate(value)


def _normalize_materialization(value: Any) -> VmMaterialization:
    return VmMaterialization.model_validate(value)


def _normalize_receipt(value: Any) -> VmReceipt:
    return VmReceipt.model_validate(value)


def _normalize_result(value: Any) -> VmResult:
    return VmResult.model_validate(value)


VM_STOREFRONT_RUNTIME = StorefrontDomainRuntime(
    schema_id=VM_PROVISION_KIND,
    normalize_listing=_normalize_listing,
    normalize_message=_normalize_message,
    normalize_terms=_normalize_terms,
    normalize_materialization=_normalize_materialization,
    normalize_receipt=_normalize_receipt,
    normalize_result=_normalize_result,
)


def storefront_runtime() -> StorefrontDomainRuntime:
    """Return the VM domain runtime for core storefront composition."""
    return VM_STOREFRONT_RUNTIME

