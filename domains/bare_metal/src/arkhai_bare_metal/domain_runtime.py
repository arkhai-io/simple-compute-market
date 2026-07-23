"""Bare-metal implementation of the core market-domain contract."""

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


def _publication_source(**kwargs: Any) -> Any:
    from .storefront_adapter import bare_metal_publication_adapter

    return bare_metal_publication_adapter(**kwargs)


BARE_METAL_MARKET_DOMAIN = MarketDomainContract(
    identity=DomainIdentity(BARE_METAL_SCHEMA_KIND),
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
    """Return the bare-metal market-domain contract."""
    return BARE_METAL_MARKET_DOMAIN
