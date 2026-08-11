"""The API-credit domain's declared negotiation policy sources.

Seller-side guards and the buyer-side key responder are different offers. A
storefront that could resolve the buyer responder would be able to name a policy
it must never run.
"""

from __future__ import annotations

import pytest
from market_policy import (
    CatalogueSource,
    InlineSource,
    NegotiationPolicyRequest,
    PolicyRole,
    negotiation_catalogue_builder,
    scalar_escrow_policies,
)

from domains.apicredits.negotiation.policy_sources import (
    API_CREDITS_BUYER_POLICIES,
    API_CREDITS_DEFAULT_SELLER_CHAIN,
    API_CREDITS_SELLER_POLICIES,
    api_credits_policy_sources,
)


def _request(role):
    return NegotiationPolicyRequest(
        role=role, requested_policies=frozenset(API_CREDITS_DEFAULT_SELLER_CHAIN)
    )


def test_the_seller_offer_is_the_guard_set() -> None:
    sources = api_credits_policy_sources(_request(PolicyRole.STOREFRONT))

    assert len(sources) == 1
    assert isinstance(sources[0], InlineSource)
    assert set(sources[0].load()) == set(API_CREDITS_SELLER_POLICIES)


def test_the_buyer_offer_is_the_responder_set() -> None:
    sources = api_credits_policy_sources(_request(PolicyRole.BUYER))

    assert set(sources[0].load()) == set(API_CREDITS_BUYER_POLICIES)


def test_the_two_offers_do_not_overlap() -> None:
    assert not set(API_CREDITS_SELLER_POLICIES) & set(API_CREDITS_BUYER_POLICIES)


def test_the_seller_offer_excludes_the_buyer_responder() -> None:
    seller = api_credits_policy_sources(_request(PolicyRole.STOREFRONT))[0].load()

    assert "answer_key_challenge" not in seller


def test_every_source_satisfies_the_protocol() -> None:
    for role in PolicyRole:
        for source in api_credits_policy_sources(_request(role)):
            assert isinstance(source, CatalogueSource)


def test_sources_describe_the_role_they_were_built_for() -> None:
    for role in PolicyRole:
        described = api_credits_policy_sources(_request(role))[0].describe()
        assert role.value in described


def test_the_default_seller_chain_interleaves_domain_and_kit_policies() -> None:
    domain_owned = set(API_CREDITS_SELLER_POLICIES)
    chained = set(API_CREDITS_DEFAULT_SELLER_CHAIN)

    assert domain_owned <= chained
    assert chained - domain_owned, "the chain must also draw on the policy kit"


def test_the_default_seller_chain_resolves_against_a_composed_catalogue() -> None:
    catalogue = (
        negotiation_catalogue_builder()
        .add_loader(scalar_escrow_policies())
        .add_loaders(api_credits_policy_sources(_request(PolicyRole.STOREFRONT)))
        .build()
    )

    resolved = catalogue.resolve(list(API_CREDITS_DEFAULT_SELLER_CHAIN))

    assert len(resolved) == len(API_CREDITS_DEFAULT_SELLER_CHAIN)
    assert catalogue.provenance("credit_quota_guard").startswith(
        "arkhai-apicredits-domain"
    )
    assert catalogue.provenance("listed_price").startswith("kit-scalar-escrow")


def test_the_domain_offers_no_name_the_kit_already_offers() -> None:
    """Composition would fail on a conflict; this asserts the offer is disjoint."""
    kit_names = set(scalar_escrow_policies().load())

    assert not kit_names & set(API_CREDITS_SELLER_POLICIES)
    assert not kit_names & set(API_CREDITS_BUYER_POLICIES)


@pytest.mark.parametrize("role", list(PolicyRole))
def test_a_role_receives_a_non_empty_offer(role) -> None:
    assert api_credits_policy_sources(_request(role))
