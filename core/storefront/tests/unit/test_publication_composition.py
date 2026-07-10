from __future__ import annotations

from core_storefront.publication_composition import (
    BARE_METAL_PUBLICATION_SOURCE,
    VM_PUBLICATION_SOURCE,
    build_bare_metal_publication_selection,
    build_multi_domain_publication_selection,
    build_storefront_publication_selection,
    build_vm_publication_selection,
)


def test_build_storefront_publication_selection_keeps_order_and_kwargs() -> None:
    selection = build_storefront_publication_selection(
        (VM_PUBLICATION_SOURCE, BARE_METAL_PUBLICATION_SOURCE),
        source_kwargs_by_name={
            VM_PUBLICATION_SOURCE: {"vm": True},
            BARE_METAL_PUBLICATION_SOURCE: {"bare_metal": True},
            "unused": {"ignored": True},
        },
    )

    assert tuple(selection.source_names) == (
        VM_PUBLICATION_SOURCE,
        BARE_METAL_PUBLICATION_SOURCE,
    )
    assert selection.source_kwargs_by_name == {
        VM_PUBLICATION_SOURCE: {"vm": True},
        BARE_METAL_PUBLICATION_SOURCE: {"bare_metal": True},
    }


def test_domain_specific_selection_helpers() -> None:
    vm_selection = build_vm_publication_selection({"open_keys": object()})
    bare_metal_selection = build_bare_metal_publication_selection({"snapshot": object()})

    assert tuple(vm_selection.source_names) == (VM_PUBLICATION_SOURCE,)
    assert tuple(bare_metal_selection.source_names) == (BARE_METAL_PUBLICATION_SOURCE,)


def test_multi_domain_selection_can_select_subset() -> None:
    selection = build_multi_domain_publication_selection(
        vm_source_kwargs={"vm": True},
        bare_metal_source_kwargs={"bare_metal": True},
        source_names=(BARE_METAL_PUBLICATION_SOURCE,),
    )

    assert tuple(selection.source_names) == (BARE_METAL_PUBLICATION_SOURCE,)
    assert selection.source_kwargs_by_name == {
        BARE_METAL_PUBLICATION_SOURCE: {"bare_metal": True},
    }
