from __future__ import annotations

from typing import Any

import pytest

import core_storefront.publication_plugins as plugins
from core_storefront.publication_sources import PublicationSource
from market_core import (
    MARKET_DOMAIN_CONTRACT_VERSION,
    DomainCapability,
    DomainIdentity,
    ImmutableCodecCapability,
    ImmutablePublicationCapability,
    MarketDomainContract,
)


class FakeEntryPoint:
    def __init__(self, name: str, value: str, target: Any):
        self.name = name
        self.value = value
        self._target = target

    def load(self) -> Any:
        return self._target


def _factory(**_kwargs: Any) -> PublicationSource:
    return PublicationSource(
        name="demo",
        open_keys=lambda _db: set(),
        close_stale=lambda _db, _url, _key: [],
        available_candidates=lambda _db: [],
        skip_keys=lambda _candidate: set(),
        offer_resource=lambda candidate: dict(candidate),
        record_published=lambda _db, _candidate, _listing_id: None,
        reopen_existing=lambda *_args: None,
        reopen_error_label="reopen demo",
    )


def _domain(factory=_factory) -> MarketDomainContract:
    normalize = lambda value: value
    return MarketDomainContract(
        identity=DomainIdentity("external.v1"),
        contract_version=MARKET_DOMAIN_CONTRACT_VERSION,
        codecs=ImmutableCodecCapability(
            normalize_listing=normalize,
            normalize_message=normalize,
            normalize_terms=normalize,
            normalize_materialization=normalize,
            normalize_receipt=normalize,
            normalize_result=normalize,
        ),
        declared_capabilities=frozenset({DomainCapability.PUBLICATION}),
        publication=ImmutablePublicationCapability(source_factory=factory),
    )


def test_build_publication_source_from_domain_entry_point(monkeypatch) -> None:
    monkeypatch.setattr(
        plugins,
        "_iter_entry_points",
        lambda: [FakeEntryPoint("external", "pkg:domain", _domain())],
    )

    assert plugins.list_publication_source_factories() == ["external"]
    assert plugins.build_publication_source("external").name == "demo"


def test_direct_publication_domain_is_not_a_source_factory(monkeypatch) -> None:
    domain = _domain()
    domain = MarketDomainContract(
        identity=domain.identity,
        contract_version=domain.contract_version,
        codecs=domain.codecs,
        declared_capabilities=domain.declared_capabilities,
        publication=ImmutablePublicationCapability(publish=lambda **_: None),
    )
    monkeypatch.setattr(
        plugins,
        "_iter_entry_points",
        lambda: [FakeEntryPoint("direct", "pkg:domain", domain)],
    )

    assert plugins.list_publication_source_factories() == []


def test_unknown_domain_mentions_available(monkeypatch) -> None:
    monkeypatch.setattr(
        plugins,
        "_iter_entry_points",
        lambda: [FakeEntryPoint("external", "pkg:domain", _domain())],
    )

    with pytest.raises(KeyError, match="Installed publication domains: external"):
        plugins.build_publication_source("missing")


def test_duplicate_domain_entry_names_are_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        plugins,
        "_iter_entry_points",
        lambda: [
            FakeEntryPoint("external", "pkg_a:domain", _domain()),
            FakeEntryPoint("external", "pkg_b:domain", _domain()),
        ],
    )

    with pytest.raises(RuntimeError, match="Multiple storefront market domains"):
        plugins.build_publication_source("external")


def test_publication_capability_must_return_source(monkeypatch) -> None:
    monkeypatch.setattr(
        plugins,
        "_iter_entry_points",
        lambda: [
            FakeEntryPoint("bad", "pkg:domain", _domain(lambda **_: object()))
        ],
    )

    with pytest.raises(TypeError, match="expected PublicationSource"):
        plugins.build_publication_source("bad")
