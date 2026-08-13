"""Role composition of the buyer's negotiation policy catalogue.

The buyer's offer is narrower than a storefront's: it authorizes no filesystem
or entry-point mechanism, and a domain's seller-side guards are not visible to
it. Both properties were previously unexpressible — every name lived in one
process-global registry that any import could add to.
"""

from __future__ import annotations

import pytest
from core_buyer.negotiation_composition import (
    compose_buyer_negotiation_catalogue,
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


def test_kit_policies_are_available_without_any_domain():
    catalogue = compose_buyer_negotiation_catalogue([])

    assert "bisection" in catalogue.names()
    assert "buyer_escrow_shape_guard" in catalogue.names()


def test_a_domain_contributes_only_its_buyer_side_policies():
    domain = _domain(
        "split",
        by_role={
            PolicyRole.BUYER: {"buyer_responder": _middleware("b")},
            PolicyRole.STOREFRONT: {"seller_guard": _middleware("s")},
        },
    )

    catalogue = compose_buyer_negotiation_catalogue([domain])

    assert "buyer_responder" in catalogue.names()
    assert "seller_guard" not in catalogue.names()
    with pytest.raises(UnknownCatalogueEntryError):
        catalogue.resolve(["seller_guard"])


def test_a_domain_declaring_no_capability_contributes_nothing():
    domain = _domain("direct")
    request = NegotiationPolicyRequest(role=PolicyRole.BUYER)

    assert domain_policy_sources(domain, request) == ()
    assert "bisection" in compose_buyer_negotiation_catalogue([domain]).names()


def test_the_requested_set_reaches_the_domain_for_conditional_offers():
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

    compose_buyer_negotiation_catalogue([domain], requested_policies=["rl"])

    assert seen["role"] is PolicyRole.BUYER
    assert seen["requested"] == frozenset({"rl"})


def test_a_domain_shadowing_a_kit_name_fails_composition():
    domain = _domain(
        "greedy", by_role={PolicyRole.BUYER: {"bisection": _middleware("mine")}}
    )

    with pytest.raises(CatalogueConflictError) as caught:
        compose_buyer_negotiation_catalogue([domain])

    assert "bisection" in str(caught.value)


def test_the_buyer_authorizes_no_filesystem_or_entry_point_mechanism():
    """Nothing in buyer.toml may cause a policy to be loaded from disk."""
    import inspect

    signature = inspect.signature(compose_buyer_negotiation_catalogue)

    assert "directory_roots" not in signature.parameters
    assert "include_entry_points" not in signature.parameters


def test_composing_without_kit_policies_yields_only_domain_policies():
    domain = _domain(
        "replacement",
        by_role={PolicyRole.BUYER: {"bisection": _middleware("mine")}},
    )

    catalogue = compose_buyer_negotiation_catalogue(
        [domain], include_kit_policies=False
    )

    assert catalogue.names() == ("bisection",)
    assert catalogue.resolve(["bisection"])[0](None, None) == "mine"
