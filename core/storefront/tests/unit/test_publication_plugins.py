from __future__ import annotations

from typing import Any

import pytest
from market_core import (
    MARKET_DOMAIN_CONTRACT_VERSION,
    DomainCapability,
    DomainIdentity,
    ImmutableCodecCapability,
    ImmutableFulfillmentCapability,
    ImmutablePublicationCapability,
    ImmutableSettlementCapability,
    ImmutableStorefrontCapability,
    MarketDomainContract,
)

from core_storefront.domain_registry import (
    StorefrontDomainRegistration,
    StorefrontDomainRegistry,
)
from core_storefront.publication_plugins import build_registry_publication_sources
from core_storefront.publication_sources import PublicationSource


def _source(name: str) -> PublicationSource:
    return PublicationSource(
        name=name,
        open_keys=lambda _db: set(),
        close_stale=lambda _db, _url: [],
        available_candidates=lambda _db: [],
        skip_keys=lambda _candidate: set(),
        offer_resource=lambda candidate: dict(candidate),
        record_published=lambda _db, _candidate, _listing_id: None,
        reopen_existing=lambda *_args: None,
        reopen_error_label=f"reopen {name}",
    )


def _domain(identity: str, source_factory) -> MarketDomainContract:
    normalize = lambda value: value
    return MarketDomainContract(
        identity=DomainIdentity(identity),
        contract_version=MARKET_DOMAIN_CONTRACT_VERSION,
        codecs=ImmutableCodecCapability(
            normalize_listing=normalize,
            normalize_message=normalize,
            normalize_terms=normalize,
            normalize_materialization=normalize,
            normalize_receipt=normalize,
            normalize_result=normalize,
        ),
        declared_capabilities=frozenset(
            {
                DomainCapability.PUBLICATION,
                DomainCapability.STOREFRONT,
                DomainCapability.SETTLEMENT,
                DomainCapability.FULFILLMENT,
            }
        ),
        publication=ImmutablePublicationCapability(source_factory=source_factory),
        storefront=ImmutableStorefrontCapability(run_negotiation_policy=normalize),
        settlement=ImmutableSettlementCapability(verify=normalize, build_plan=normalize),
        fulfillment=ImmutableFulfillmentCapability(fulfill=normalize),
    )


def _registry(*registrations: tuple[str, str, str, Any]) -> StorefrontDomainRegistry:
    return StorefrontDomainRegistry(
        StorefrontDomainRegistration(
            offering_mode=mode,
            contribution_id=contribution,
            contract=_domain(identity, factory),
        )
        for mode, contribution, identity, factory in registrations
    )


def test_sources_are_built_from_frozen_registration_order_once():
    calls: list[tuple[str, dict[str, Any]]] = []

    def factory(name: str):
        def build(**kwargs):
            calls.append((name, kwargs))
            return _source(name)

        return build

    registry = _registry(
        ("vm", "vms", "compute.v1", factory("vms")),
        ("bare_metal", "bare_metal", "bare_metal.v1", factory("bare_metal")),
    )

    sources = build_registry_publication_sources(
        registry,
        source_kwargs_by_contribution={
            "vms": {"price": "2"},
            "bare_metal": {"lease": True},
        },
    )

    assert tuple(source.name for source in sources) == ("vms", "bare_metal")
    assert calls == [("vms", {"price": "2"}), ("bare_metal", {"lease": True})]


def test_unknown_source_kwargs_fail_before_any_factory_call():
    called = False

    def factory(**_kwargs):
        nonlocal called
        called = True
        return _source("vms")

    registry = _registry(("vm", "vms", "compute.v1", factory))

    with pytest.raises(KeyError, match="unknown contributions"):
        build_registry_publication_sources(
            registry,
            source_kwargs_by_contribution={"missing": {}},
        )
    assert called is False


def test_publication_capability_must_return_source():
    registry = _registry(
        ("vm", "vms", "compute.v1", lambda **_: object()),
    )

    with pytest.raises(TypeError, match="expected PublicationSource"):
        build_registry_publication_sources(registry)


def test_duplicate_returned_source_names_are_rejected():
    registry = _registry(
        ("vm", "vms", "compute.v1", lambda **_: _source("same")),
        (
            "bare_metal",
            "bare_metal",
            "bare_metal.v1",
            lambda **_: _source("same"),
        ),
    )

    with pytest.raises(ValueError, match="duplicate publication source"):
        build_registry_publication_sources(registry)
