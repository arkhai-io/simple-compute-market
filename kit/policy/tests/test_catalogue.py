"""Composition guarantees for the generic catalogue.

Each failure mode here was previously silent. A missing name resolved against
whatever import order had populated a module-level registry, a broken provider
was skipped, and two providers offering one name resolved to whichever was
imported last.
"""

from __future__ import annotations

import pytest
from market_policy import (
    Catalogue,
    CatalogueBuilder,
    CatalogueConflictError,
    CatalogueItemTypeError,
    CatalogueSource,
    CatalogueSourceError,
    InlineSource,
    UnknownCatalogueEntryError,
    negotiation_catalogue_builder,
    require_callable_item,
    scalar_escrow_policies,
)


def _middleware(label):
    def _mw(history, context):
        return label

    return _mw


class _RaisingSource:
    def describe(self) -> str:
        return "explosive-source"

    def load(self):
        raise OSError("registry unreachable")


class _NonCallableSource:
    def describe(self) -> str:
        return "confused-source"

    def load(self):
        return {"not_a_policy": "this is a string"}


def test_source_implementations_satisfy_the_protocol() -> None:
    assert isinstance(InlineSource({}), CatalogueSource)
    assert isinstance(scalar_escrow_policies(), CatalogueSource)
    assert isinstance(_RaisingSource(), CatalogueSource)


def test_kit_policies_compose_as_an_ordinary_source() -> None:
    catalogue = (
        negotiation_catalogue_builder().add_loader(scalar_escrow_policies()).build()
    )

    assert "bisection" in catalogue.names()
    assert catalogue.provenance("bisection").startswith("kit-scalar-escrow")


def test_resolve_returns_items_in_the_order_given() -> None:
    catalogue = (
        negotiation_catalogue_builder()
        .add_loader(
            InlineSource({"first": _middleware("a"), "second": _middleware("b")})
        )
        .build()
    )

    resolved = catalogue.resolve(["second", "first", "second"])

    assert [item(None, None) for item in resolved] == ["b", "a", "b"]


def test_resolution_does_not_mutate_the_catalogue() -> None:
    catalogue = (
        negotiation_catalogue_builder()
        .add_loader(InlineSource({"only": _middleware("only")}))
        .build()
    )
    before = catalogue.names()

    catalogue.resolve(["only"])
    with pytest.raises(UnknownCatalogueEntryError):
        catalogue.resolve(["absent"])

    assert catalogue.names() == before


def test_built_catalogue_rejects_mutation() -> None:
    catalogue = (
        negotiation_catalogue_builder()
        .add_loader(InlineSource({"only": _middleware("only")}))
        .build()
    )

    with pytest.raises(TypeError):
        catalogue._by_name["sneaky"] = _middleware("sneaky")


def test_catalogue_is_a_read_only_mapping() -> None:
    catalogue = (
        negotiation_catalogue_builder()
        .add_loader(InlineSource({"only": _middleware("only")}))
        .build()
    )

    assert list(catalogue) == ["only"]
    assert len(catalogue) == 1
    assert catalogue["only"](None, None) == "only"


def test_two_sources_offering_one_name_fail_naming_both() -> None:
    builder = (
        negotiation_catalogue_builder()
        .add_loader(InlineSource({"shared": _middleware("a")}, label="alpha"))
        .add_loader(InlineSource({"shared": _middleware("b")}, label="beta"))
    )

    with pytest.raises(CatalogueConflictError) as caught:
        builder.build()

    message = str(caught.value)
    assert "shared" in message
    assert "alpha" in message
    assert "beta" in message
    assert "negotiation policy" in message


def test_a_raising_source_fails_composition_rather_than_being_skipped() -> None:
    builder = (
        negotiation_catalogue_builder()
        .add_loader(InlineSource({"fine": _middleware("fine")}))
        .add_loader(_RaisingSource())
    )

    with pytest.raises(CatalogueSourceError) as caught:
        builder.build()

    assert "explosive-source" in str(caught.value)


def test_the_injected_validator_rejects_a_malformed_item() -> None:
    with pytest.raises(CatalogueItemTypeError) as caught:
        negotiation_catalogue_builder().add_loader(_NonCallableSource()).build()

    message = str(caught.value)
    assert "not_a_policy" in message
    assert "confused-source" in message
    assert "str" in message


def test_a_catalogue_without_a_validator_accepts_any_item() -> None:
    """Validation is the caller's choice, not the machinery's."""
    catalogue = (
        CatalogueBuilder(kind="widget")
        .add_loader(InlineSource({"plain": "a string"}))
        .build()
    )

    assert catalogue["plain"] == "a string"


def test_a_custom_validator_is_honoured() -> None:
    def _require_int(name, item):
        if not isinstance(item, int):
            raise CatalogueItemTypeError(f"{name!r} is not an int")

    builder = CatalogueBuilder(kind="counter", validate=_require_int).add_loader(
        InlineSource({"bad": "nope"})
    )

    with pytest.raises(CatalogueItemTypeError) as caught:
        builder.build()

    assert "counter source" in str(caught.value)


def test_require_callable_item_is_reusable_standalone() -> None:
    require_callable_item("fine", lambda: None)
    with pytest.raises(CatalogueItemTypeError):
        require_callable_item("bad", object())


def test_unknown_name_lists_what_is_available_and_names_no_package() -> None:
    catalogue = (
        negotiation_catalogue_builder()
        .add_loader(InlineSource({"present": _middleware("present")}))
        .build()
    )

    with pytest.raises(UnknownCatalogueEntryError) as caught:
        catalogue.resolve(["present", "absent"])

    message = str(caught.value)
    assert "absent" in message
    assert "present" in message
    # The superseded resolver told operators to "ensure the VM policy package
    # is imported" -- a domain reference inside the generic policy layer.
    assert "import" not in message.lower()


def test_unknown_name_reports_every_missing_name_at_once() -> None:
    catalogue = negotiation_catalogue_builder().build()

    with pytest.raises(UnknownCatalogueEntryError) as caught:
        catalogue.resolve(["one", "two"])

    assert "one" in str(caught.value)
    assert "two" in str(caught.value)


def test_the_kind_appears_in_errors_so_messages_read_per_catalogue() -> None:
    catalogue = CatalogueBuilder(kind="aggregation policy").build()

    with pytest.raises(UnknownCatalogueEntryError) as caught:
        catalogue.resolve(["absent"])

    assert "unknown aggregation policy" in str(caught.value)


def test_two_roles_compose_independent_catalogues_in_one_process() -> None:
    buyer = (
        negotiation_catalogue_builder()
        .add_loader(InlineSource({"buyer_only": _middleware("b")}))
        .build()
    )
    storefront = (
        negotiation_catalogue_builder()
        .add_loader(InlineSource({"storefront_only": _middleware("s")}))
        .build()
    )

    assert buyer.names() == ("buyer_only",)
    assert storefront.names() == ("storefront_only",)
    with pytest.raises(UnknownCatalogueEntryError):
        buyer.resolve(["storefront_only"])


def test_an_empty_catalogue_is_valid() -> None:
    """A role composing no sources is a configuration question, not an error."""
    catalogue = negotiation_catalogue_builder().build()

    assert catalogue.names() == ()
    assert catalogue.resolve([]) == []


def test_catalogue_is_the_type_callers_annotate_against() -> None:
    catalogue = negotiation_catalogue_builder().build()

    assert isinstance(catalogue, Catalogue)


# --- generic typing ---------------------------------------------------------


def test_the_catalogue_machinery_is_parameterised_by_item_type() -> None:
    """The runtime behaviour was always generic; the typing now says so.

    A caller composing a catalogue of something other than middlewares should
    keep its element type rather than falling back to `Any`.
    """
    assert Catalogue[int] is not None
    assert CatalogueBuilder[int] is not None
    assert CatalogueSource[int] is not None


def test_a_typed_builder_composes_a_typed_catalogue() -> None:
    builder: CatalogueBuilder[int] = CatalogueBuilder(kind="counter")
    catalogue = builder.add_loader(InlineSource({"seven": 7})).build()

    assert catalogue["seven"] == 7
    assert catalogue.resolve(["seven"]) == [7]


def test_the_negotiation_alias_carries_its_element_type() -> None:
    """The alias should add static precision, not only a friendlier name."""
    from market_policy import NegotiationCatalogue, NegotiationMiddleware

    assert NegotiationCatalogue is not Catalogue
    assert NegotiationCatalogue == Catalogue[NegotiationMiddleware]


def test_a_non_callable_catalogue_needs_no_callable_validator() -> None:
    """`require_callable_item` is negotiation's choice, not the machinery's."""
    catalogue = (
        CatalogueBuilder(kind="threshold")
        .add_loader(InlineSource({"low": 1, "high": 99}))
        .build()
    )

    assert catalogue.resolve(["high", "low"]) == [99, 1]


# --- buyer policy catalogue -------------------------------------------------


def test_a_buyer_policy_catalogue_validates_its_item_type() -> None:
    """The second registry converted: buyer policies are objects, not callables.

    Proves the injected validator is what makes a catalogue item-appropriate —
    `require_callable_item` would have accepted anything callable here.
    """
    from market_policy import CatalogueItemTypeError, buyer_policy_catalogue_builder

    builder = buyer_policy_catalogue_builder().add_loader(
        InlineSource({"not_a_policy": lambda: None}, label="confused")
    )

    with pytest.raises(CatalogueItemTypeError) as caught:
        builder.build()

    message = str(caught.value)
    assert "buyer policy source" in message
    assert "not a BuyerPolicy" in message


def test_a_buyer_policy_catalogue_accepts_a_real_policy() -> None:
    from market_policy import BuyerPolicy, buyer_policy_catalogue_builder

    policy = BuyerPolicy(name="thrifty", middlewares=("bisection",))
    catalogue = (
        buyer_policy_catalogue_builder()
        .add_loader(InlineSource({policy.name: policy}, label="test"))
        .build()
    )

    assert catalogue["thrifty"] is policy
    assert catalogue.names() == ("thrifty",)


def test_duplicate_buyer_policy_names_fail_instead_of_last_write_winning() -> None:
    """The superseded registry documented "last registration wins"."""
    from market_policy import BuyerPolicy, buyer_policy_catalogue_builder

    first = BuyerPolicy(name="contested", middlewares=("listed_price",))
    second = BuyerPolicy(name="contested", middlewares=("bisection",))

    builder = (
        buyer_policy_catalogue_builder()
        .add_loader(InlineSource({"contested": first}, label="alpha"))
        .add_loader(InlineSource({"contested": second}, label="beta"))
    )

    with pytest.raises(CatalogueConflictError) as caught:
        builder.build()

    assert "alpha" in str(caught.value)
    assert "beta" in str(caught.value)


def test_an_unknown_buyer_policy_names_no_package_to_install() -> None:
    """The superseded message guessed: "is the domain plugin installed?"."""
    from market_policy import BuyerPolicy, buyer_policy_catalogue_builder

    policy = BuyerPolicy(name="present", middlewares=())
    catalogue = (
        buyer_policy_catalogue_builder()
        .add_loader(InlineSource({"present": policy}, label="test"))
        .build()
    )

    with pytest.raises(UnknownCatalogueEntryError) as caught:
        catalogue.resolve(["absent"])

    message = str(caught.value)
    assert "unknown buyer policy" in message
    assert "present" in message
    assert "installed" not in message
