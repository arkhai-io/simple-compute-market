"""Buyer domain entry-point discovery and startup validation."""

from __future__ import annotations

import core_buyer.plugins as plugins_mod
import pytest
from core_buyer.plugins import discover_domains
from market_core import (
    MARKET_DOMAIN_CONTRACT_VERSION,
    DomainContractValidationError,
    DomainIdentity,
    ImmutableCodecCapability,
    MarketDomainContract,
)


class _FakeEntryPoint:
    def __init__(self, name, loader, value="pkg.module:OBJECT"):
        self.name = name
        self.value = value
        self._loader = loader

    def load(self):
        return self._loader()


def _domain(identity: str) -> MarketDomainContract:
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
    )


def test_discover_fails_on_import_failure(monkeypatch):
    """A declared domain that cannot load is a broken install, not an absence.

    Skipping it and continuing reported "no buyer domain is installed" for a
    distribution that was installed and incomplete, pointing readers at
    configuration instead of packaging.
    """
    good = _domain("good")

    def _boom():
        raise ImportError("missing native dep")

    monkeypatch.setattr(
        plugins_mod,
        "_iter_entry_points",
        lambda: [
            _FakeEntryPoint("broken", _boom),
            _FakeEntryPoint("good", lambda: good),
        ],
    )

    with pytest.raises(plugins_mod.DomainPluginLoadError) as caught:
        discover_domains()

    message = str(caught.value)
    assert "broken" in message
    assert "missing native dep" in message


def test_discover_rejects_mistyped_entry_point(monkeypatch):
    monkeypatch.setattr(
        plugins_mod,
        "_iter_entry_points",
        lambda: [_FakeEntryPoint("mistyped", lambda: object())],
    )

    with pytest.raises(TypeError, match="MarketDomainContract"):
        discover_domains()


def test_discover_rejects_duplicate_identities(monkeypatch):
    monkeypatch.setattr(
        plugins_mod,
        "_iter_entry_points",
        lambda: [
            _FakeEntryPoint("one", lambda: _domain("same")),
            _FakeEntryPoint("two", lambda: _domain("same")),
        ],
    )

    with pytest.raises(DomainContractValidationError, match="duplicate.*same"):
        discover_domains()


def test_discover_empty_when_nothing_installed(monkeypatch):
    monkeypatch.setattr(plugins_mod, "_iter_entry_points", list)
    assert discover_domains() == []


def test_load_failure_names_the_distribution_target(monkeypatch):
    """The message must identify what to fix: the domain and its target.

    An incomplete wheel advertises an entry point it cannot satisfy. Naming
    only the domain leaves the reader guessing whether the fault is
    configuration or packaging.
    """

    def _incomplete():
        raise ModuleNotFoundError("No module named 'widgets.listings.listing_mode'")

    monkeypatch.setattr(
        plugins_mod,
        "_iter_entry_points",
        lambda: [_FakeEntryPoint("widgets", _incomplete, value="widgets.cli:domain")],
    )

    with pytest.raises(plugins_mod.DomainPluginLoadError) as caught:
        discover_domains()

    message = str(caught.value)
    assert "widgets" in message
    assert "listing_mode" in message
    assert "widgets.cli:domain" in message


def test_a_healthy_sibling_does_not_mask_a_broken_domain(monkeypatch):
    """Discovery is all-or-nothing; a partial domain set is not a valid result."""
    monkeypatch.setattr(
        plugins_mod,
        "_iter_entry_points",
        lambda: [
            _FakeEntryPoint("healthy", lambda: _domain("healthy")),
            _FakeEntryPoint(
                "broken", lambda: (_ for _ in ()).throw(ImportError("boom"))
            ),
        ],
    )

    with pytest.raises(plugins_mod.DomainPluginLoadError):
        discover_domains()
