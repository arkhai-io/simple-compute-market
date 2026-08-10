"""Role composition of domain-declared negotiation policy sources.

The role authorizes mechanisms; the domain contributes only its own policies and
receives a narrow typed request. A mistyped role option is a TypeError here, not
a value a domain silently absorbs.
"""

from __future__ import annotations

import pytest
from core_storefront.negotiation_composition import (
    compose_negotiation_catalogue,
    domain_policy_sources,
)
from market_core import (
    MARKET_DOMAIN_CONTRACT_VERSION,
    DomainCapability,
    DomainIdentity,
    ImmutableNegotiationCapability,
    MarketDomainContract,
)
from market_policy import (
    CatalogueConflictError,
    InlineSource,
    NegotiationPolicyRequest,
    PolicyRole,
    UnknownCatalogueEntryError,
)


class _Codecs:
    @staticmethod
    def _identity(value):
        return value

    listing = message = terms = materialization = receipt = result = _identity


def _middleware(label):
    def _mw(history, context):
        return label

    return _mw


def _domain(identity, *, by_role=None):
    capabilities = set()
    negotiation = None
    if by_role is not None:
        capabilities.add(DomainCapability.NEGOTIATION)

        def _sources(request: NegotiationPolicyRequest):
            offered = by_role.get(request.role)
            if not offered:
                return ()
            return (InlineSource(offered, label=f"{identity}[{request.role.value}]"),)

        negotiation = ImmutableNegotiationCapability(policy_sources=_sources)
    return MarketDomainContract(
        identity=DomainIdentity(identity),
        contract_version=MARKET_DOMAIN_CONTRACT_VERSION,
        codecs=_Codecs(),
        declared_capabilities=frozenset(capabilities),
        negotiation=negotiation,
    )


def _storefront(domains, **kwargs):
    return compose_negotiation_catalogue(domains, role=PolicyRole.STOREFRONT, **kwargs)


def test_kit_policies_are_available_without_any_domain() -> None:
    catalogue = _storefront([])

    assert "bisection" in catalogue.names()
    assert "escrow_shape_guard" in catalogue.names()


def test_a_domain_contributes_its_own_policies() -> None:
    domain = _domain(
        "widgets",
        by_role={PolicyRole.STOREFRONT: {"widget_guard": _middleware("w")}},
    )

    catalogue = _storefront([domain])

    assert "widget_guard" in catalogue.names()
    assert "bisection" in catalogue.names()
    assert catalogue.provenance("widget_guard").startswith("widgets[storefront]")


def test_a_domain_declaring_no_capability_contributes_nothing() -> None:
    """A domain composing its chain as values is valid, not incomplete."""
    domain = _domain("direct")
    request = NegotiationPolicyRequest(role=PolicyRole.STOREFRONT)

    assert domain_policy_sources(domain, request) == ()
    assert "bisection" in _storefront([domain]).names()


def test_a_role_only_receives_the_policies_for_its_own_role() -> None:
    domain = _domain(
        "split",
        by_role={
            PolicyRole.STOREFRONT: {"seller_guard": _middleware("s")},
            PolicyRole.BUYER: {"buyer_responder": _middleware("b")},
        },
    )

    storefront = _storefront([domain])
    buyer = compose_negotiation_catalogue([domain], role=PolicyRole.BUYER)

    assert "seller_guard" in storefront.names()
    assert "buyer_responder" not in storefront.names()
    assert "buyer_responder" in buyer.names()
    with pytest.raises(UnknownCatalogueEntryError):
        storefront.resolve(["buyer_responder"])


def test_a_domain_shadowing_a_kit_name_fails_composition() -> None:
    domain = _domain(
        "greedy",
        by_role={PolicyRole.STOREFRONT: {"bisection": _middleware("mine")}},
    )

    with pytest.raises(CatalogueConflictError) as caught:
        _storefront([domain])

    message = str(caught.value)
    assert "bisection" in message
    assert "kit-scalar-escrow" in message
    assert "greedy" in message


def test_a_role_may_compose_without_the_kit_policies() -> None:
    """Composing kit out is the supported way to replace a built-in name."""
    domain = _domain(
        "replacement",
        by_role={PolicyRole.STOREFRONT: {"bisection": _middleware("mine")}},
    )

    catalogue = _storefront([domain], include_kit_policies=False)

    assert catalogue.names() == ("bisection",)
    assert catalogue.resolve(["bisection"])[0](None, None) == "mine"


def test_two_domains_offering_one_name_fail_naming_both() -> None:
    first = _domain(
        "first", by_role={PolicyRole.STOREFRONT: {"shared": _middleware("a")}}
    )
    second = _domain(
        "second", by_role={PolicyRole.STOREFRONT: {"shared": _middleware("b")}}
    )

    with pytest.raises(CatalogueConflictError) as caught:
        _storefront([first, second])

    assert "first" in str(caught.value)
    assert "second" in str(caught.value)


def test_the_requested_policy_set_reaches_the_domain() -> None:
    seen = {}

    def _sources(request: NegotiationPolicyRequest):
        seen["role"] = request.role
        seen["requested"] = request.requested_policies
        return ()

    domain = MarketDomainContract(
        identity=DomainIdentity("observant"),
        contract_version=MARKET_DOMAIN_CONTRACT_VERSION,
        codecs=_Codecs(),
        declared_capabilities=frozenset({DomainCapability.NEGOTIATION}),
        negotiation=ImmutableNegotiationCapability(policy_sources=_sources),
    )

    _storefront([domain], requested_policies=["bisection", "rl"])

    assert seen["role"] is PolicyRole.STOREFRONT
    assert seen["requested"] == frozenset({"bisection", "rl"})


def test_a_misspelled_role_option_fails_rather_than_being_absorbed() -> None:
    """The previous signature forwarded arbitrary options to every domain."""
    with pytest.raises(TypeError):
        _storefront([], directory_rootz=["/tmp/typo"])


def test_operator_directories_are_authorized_by_the_role(tmp_path) -> None:
    folder = tmp_path / "operator_guard"
    folder.mkdir()
    (folder / "policy.py").write_text(
        "def middleware(history, context):\n    return 'operator'\n",
        encoding="utf-8",
    )

    without = _storefront([])
    assert "operator_guard" not in without.names()

    with_dirs = _storefront([], directory_roots=[tmp_path])
    assert "operator_guard" in with_dirs.names()
    assert "operator-directories" in with_dirs.provenance("operator_guard")


def test_entry_points_are_authorized_by_the_role() -> None:
    """Off by default: an installed distribution cannot inject a policy unasked."""
    assert (
        compose_negotiation_catalogue(
            [], role=PolicyRole.STOREFRONT, include_entry_points=False
        ).names()
        == _storefront([]).names()
    )


def test_composed_catalogues_are_independent_per_role() -> None:
    storefront_domain = _domain(
        "storefront-side",
        by_role={PolicyRole.STOREFRONT: {"storefront_only": _middleware("s")}},
    )

    storefront = _storefront([storefront_domain])
    buyer = compose_negotiation_catalogue([storefront_domain], role=PolicyRole.BUYER)

    assert "storefront_only" in storefront.names()
    assert "storefront_only" not in buyer.names()
