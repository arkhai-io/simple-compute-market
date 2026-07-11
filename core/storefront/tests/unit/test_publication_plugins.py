from __future__ import annotations

from typing import Any

import pytest

import core_storefront.publication_plugins as plugins
from core_storefront.publication_sources import PublicationSource


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


def test_load_publication_source_factory_from_entry_point(monkeypatch) -> None:
    monkeypatch.setattr(
        plugins,
        "_iter_entry_points",
        lambda: [FakeEntryPoint("bare_metal", "pkg:factory", _factory)],
    )

    assert plugins.list_publication_source_factories() == ["bare_metal"]
    assert plugins.load_publication_source_factory("bare-metal") is _factory
    assert plugins.build_publication_source("bare_metal").name == "demo"


def test_unknown_publication_source_mentions_available(monkeypatch) -> None:
    monkeypatch.setattr(
        plugins,
        "_iter_entry_points",
        lambda: [FakeEntryPoint("vms", "pkg:factory", _factory)],
    )

    with pytest.raises(KeyError, match="Installed sources: vms"):
        plugins.load_publication_source_factory("missing")


def test_duplicate_publication_source_names_are_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        plugins,
        "_iter_entry_points",
        lambda: [
            FakeEntryPoint("vms", "pkg_a:factory", _factory),
            FakeEntryPoint("vms", "pkg_b:factory", _factory),
        ],
    )

    with pytest.raises(RuntimeError, match="Multiple storefront publication sources"):
        plugins.load_publication_source_factory("vms")


def test_publication_source_factory_must_return_source(monkeypatch) -> None:
    monkeypatch.setattr(
        plugins,
        "_iter_entry_points",
        lambda: [FakeEntryPoint("bad", "pkg:factory", lambda: object())],
    )

    with pytest.raises(TypeError, match="expected PublicationSource"):
        plugins.build_publication_source("bad")
