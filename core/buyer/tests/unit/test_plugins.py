"""Buyer domain entry-point discovery and startup validation."""

from __future__ import annotations

import pytest

import core_buyer.plugins as plugins_mod
from core_buyer.plugins import discover_domains
from market_core import (
    MARKET_DOMAIN_CONTRACT_VERSION,
    DomainContractValidationError,
    DomainIdentity,
    ImmutableCodecCapability,
    MarketDomainContract,
)


class _FakeEntryPoint:
    def __init__(self, name, loader):
        self.name = name
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


def test_discover_skips_import_failure(monkeypatch, capsys):
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

    assert discover_domains() == [good]
    assert "broken" in capsys.readouterr().err


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
    monkeypatch.setattr(plugins_mod, "_iter_entry_points", lambda: [])
    assert discover_domains() == []
