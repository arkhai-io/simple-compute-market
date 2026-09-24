from __future__ import annotations

from types import SimpleNamespace

from core_storefront.domain_plugins import (
    discover_storefront_domain_registry,
    parse_storefront_contribution_selections,
)
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
        listing_resource=lambda candidate: {"resource_id": candidate["resource_id"]},
        record_published=lambda *_args: None,
        reopen_existing=lambda *_args: None,
    )




def test_build_vm_publication_source_kwargs_maps_callbacks() -> None:
    callbacks = _vm_callbacks()

    kwargs = build_vm_publication_source_kwargs(callbacks)

    assert kwargs["open_keys"]("db") == {"open"}
    assert kwargs["close_stale"]("db", "url") == ["closed"]
    assert kwargs["available_candidates"]("db") == [{"resource_id": "vm-1"}]
    assert kwargs["listing_resource"]({"resource_id": "vm-1"}) == {
        "resource_id": "vm-1",
    }




def _combined_registry():
    """The registry a storefront selecting both compute domains freezes.

    Built by the same discovery over installed contributions that startup runs,
    from the selections a combined storefront configures.
    """
    return discover_storefront_domain_registry(
        parse_storefront_contribution_selections(
            [
                {
                    "contribution": "vms",
                    "offering_mode": "vm",
                    "domain_identity": "compute.v1",
                    "contract_version": "1.0",
                },
                {
                    "contribution": "bare_metal",
                    "offering_mode": "bare_metal",
                    "domain_identity": "bare_metal.v1",
                    "contract_version": "1.0",
                },
            ]
        )
    )


def test_vm_selection_builds_only_the_vm_source_beside_bare_metal() -> None:
    """The bare-metal source needs arguments only its own command supplies."""
    selection = build_vm_storefront_publication_selection(
        _combined_registry(), _vm_callbacks()
    )

    assert selection.source_names == ("vms",)
    assert [source.name for source in selection.build_sources()] == ["vms"]
