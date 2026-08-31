from __future__ import annotations

from types import SimpleNamespace

from market_storefront.publication_wiring import (
    VmPublicationSourceCallbacks,
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




def test_build_vm_publication_source_kwargs_maps_callbacks() -> None:
    callbacks = _vm_callbacks()

    kwargs = build_vm_publication_source_kwargs(callbacks)

    assert kwargs["open_keys"]("db") == {"open"}
    assert kwargs["close_stale"]("db", "url") == ["closed"]
    assert kwargs["available_candidates"]("db") == [{"resource_id": "vm-1"}]
    assert kwargs["offer_resource"]({"resource_id": "vm-1"}) == {
        "resource_id": "vm-1",
    }




def test_vm_selection_passes_exact_contribution_kwargs(monkeypatch) -> None:
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
    assert calls[0][0] is registry
    assert tuple(calls[0][1]["source_kwargs_by_contribution"]) == ("vms",)
    assert all(candidate is registry for candidate, _ in calls)
