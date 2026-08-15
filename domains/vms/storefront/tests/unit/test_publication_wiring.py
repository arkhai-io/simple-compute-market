from __future__ import annotations

from types import SimpleNamespace

from market_storefront.publication_wiring import (
    BareMetalPublicationSourceCallbacks,
    VmPublicationSourceCallbacks,
    build_bare_metal_publication_source_kwargs,
    build_bare_metal_storefront_publication_selection,
    build_storefront_publication_selection,
    build_vm_publication_source_kwargs,
    build_vm_storefront_publication_selection,
)


def _vm_callbacks() -> VmPublicationSourceCallbacks:
    return VmPublicationSourceCallbacks(
        open_keys=lambda _db: {"open"},
        close_stale=lambda _db, _url: ["closed"],
        available_candidates=lambda _db: [{"resource_id": "vm-1"}],
        offer_resource=lambda candidate: {"resource_id": candidate["resource_id"]},
        record_published=lambda *_args: None,
        reopen_existing=lambda *_args: None,
    )


def _bare_metal_callbacks(
    snapshot: list[dict[str, Any]] | None = None,
) -> BareMetalPublicationSourceCallbacks:
    return BareMetalPublicationSourceCallbacks(
        capacity_snapshot=lambda: snapshot,
        close_listing=lambda _url, listing_id: {
            "status": "closed",
            "listing_id": listing_id,
        },
        publish_existing_listing=lambda **kwargs: {
            "status": "published",
            "listing_id": kwargs["listing_id"],
        },
    )


def test_build_vm_publication_source_kwargs_maps_callbacks() -> None:
    callbacks = _vm_callbacks()

    kwargs = build_vm_publication_source_kwargs(callbacks)

    assert kwargs["open_keys"]("db") == {"open"}
    assert kwargs["close_stale"]("db", "url") == ["closed"]
    assert kwargs["available_candidates"]("db") == [{"resource_id": "vm-1"}]
    assert kwargs["offer_resource"]({"resource_id": "vm-1"}) == {
        "resource_id": "vm-1",
    }


def test_build_bare_metal_publication_source_kwargs_normalizes_missing_snapshot() -> None:
    kwargs = build_bare_metal_publication_source_kwargs(
        _bare_metal_callbacks(snapshot=None),
    )

    assert kwargs["capacity_snapshot"]() == []
    assert kwargs["close_listing"]("url", "listing-1")["status"] == "closed"
    assert kwargs["publish_existing_listing"](listing_id="listing-1")["status"] == "published"


def test_selection_helpers_pass_the_exact_registry(monkeypatch) -> None:
    import market_storefront.publication_wiring as wiring

    registry = object()
    calls = []

    def build(candidate, **kwargs):
        calls.append((candidate, kwargs))
        return SimpleNamespace(source_names=tuple(kwargs["source_kwargs_by_contribution"]))

    monkeypatch.setattr(wiring, "_build_core_publication_selection", build)

    assert build_vm_storefront_publication_selection(
        registry, _vm_callbacks()
    ).source_names == ("vms",)
    assert build_bare_metal_storefront_publication_selection(
        registry, _bare_metal_callbacks([])
    ).source_names == ("bare_metal",)
    assert build_storefront_publication_selection(
        registry=registry,
        vm_callbacks=_vm_callbacks(),
        bare_metal_callbacks=_bare_metal_callbacks([]),
    ).source_names == ("vms", "bare_metal")
    assert all(candidate is registry for candidate, _ in calls)
