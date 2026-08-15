from core_storefront import publication_composition
from core_storefront.publication_sources import PublicationSource


def _source(name: str) -> PublicationSource:
    return PublicationSource(
        name=name,
        open_keys=lambda _db: set(),
        close_stale=lambda _db, _url: [],
        available_candidates=lambda _db: [],
        skip_keys=lambda _candidate: set(),
        offer_resource=lambda candidate: candidate,
        record_published=lambda *_args: None,
        reopen_existing=lambda *_args: None,
        reopen_error_label=name,
    )


def test_selection_freezes_sources_built_from_the_supplied_registry(monkeypatch):
    registry = object()
    observed = []

    def build(candidate, **kwargs):
        observed.append((candidate, kwargs))
        return (_source("vms"), _source("bare_metal"))

    monkeypatch.setattr(
        publication_composition,
        "build_registry_publication_sources",
        build,
    )

    selection = publication_composition.build_storefront_publication_selection(
        registry,
        source_kwargs_by_contribution={"vms": {"one": True}},
    )

    assert selection.source_names == ("vms", "bare_metal")
    assert observed == [
        (
            registry,
            {"source_kwargs_by_contribution": {"vms": {"one": True}}},
        )
    ]
