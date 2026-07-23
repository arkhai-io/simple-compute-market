from core_storefront.publication_composition import (
    build_storefront_publication_selection,
)


def test_schema_opaque_selection_preserves_names_order_and_selected_kwargs():
    selection = build_storefront_publication_selection(
        ("external_one", "external_two"),
        source_kwargs_by_name={
            "external_one": {"one": True},
            "external_two": {"two": True},
            "unused": {"ignored": True},
        },
    )

    assert tuple(selection.source_names) == ("external_one", "external_two")
    assert selection.source_kwargs_by_name == {
        "external_one": {"one": True},
        "external_two": {"two": True},
    }


def test_empty_domain_selection_is_valid():
    selection = build_storefront_publication_selection(())
    assert tuple(selection.source_names) == ()
    assert selection.source_kwargs_by_name == {}
