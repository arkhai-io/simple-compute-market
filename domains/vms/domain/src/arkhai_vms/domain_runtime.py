"""VM implementation of the core market-domain contract."""

from __future__ import annotations

from typing import Any

from market_core import (
    MARKET_DOMAIN_CONTRACT_VERSION,
    DomainCapability,
    DomainIdentity,
    ImmutableCodecCapability,
    ImmutablePublicationCapability,
    MarketDomainContract,
)

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


def _publication_source(**kwargs: Any) -> Any:
    from .storefront_adapter import vm_publication_adapter

    return vm_publication_adapter(**kwargs)


VM_MARKET_DOMAIN = MarketDomainContract(
    identity=DomainIdentity(VM_PROVISION_KIND),
    contract_version=MARKET_DOMAIN_CONTRACT_VERSION,
    codecs=ImmutableCodecCapability(
        normalize_listing=_normalize_listing,
        normalize_message=_normalize_message,
        normalize_terms=_normalize_terms,
        normalize_materialization=_normalize_materialization,
        normalize_receipt=_normalize_receipt,
        normalize_result=_normalize_result,
    ),
    declared_capabilities=frozenset({DomainCapability.PUBLICATION}),
    publication=ImmutablePublicationCapability(
        source_factory=_publication_source,
    ),
)


def market_domain() -> MarketDomainContract:
    """Return the VM market-domain contract."""
    return VM_MARKET_DOMAIN
