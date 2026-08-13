"""The real API-credit buyer domain contract, composed by the real buyer role.

Every component was correct and the wiring between them was missing: the domain
offered its buyer-side responder, the buyer role forwarded requests, the catalogue
resolved names — and the published buyer contract declared no negotiation
capability, so `market credits buy` could not resolve `answer_key_challenge`.
Component tests all passed; the end-to-end run caught it.
"""

from __future__ import annotations

import pytest
from core_buyer.negotiation_composition import compose_buyer_negotiation_catalogue
from market_core import DomainCapability
from market_policy import UnknownCatalogueEntryError

from domains.apicredits.buyer.cli import domain
from domains.apicredits.negotiation.buyer_policies import APICREDITS_BUYER_GUARDS
from domains.apicredits.negotiation.policy_sources import (
    API_CREDITS_BUYER_POLICIES,
    API_CREDITS_SELLER_POLICIES,
)


def test_the_published_contract_declares_both_capabilities() -> None:
    assert domain.has_capability(DomainCapability.BUYER)
    assert domain.has_capability(DomainCapability.NEGOTIATION)


def test_the_cli_default_chain_resolves_from_the_real_contract() -> None:
    """The chain `market credits buy` loads, resolved as the buyer role builds it."""
    names = [*APICREDITS_BUYER_GUARDS, "listed_price"]
    catalogue = compose_buyer_negotiation_catalogue([domain], requested_policies=names)

    assert catalogue.resolve(names)


@pytest.mark.parametrize("name", sorted(API_CREDITS_BUYER_POLICIES))
def test_each_buyer_side_policy_resolves(name: str) -> None:
    catalogue = compose_buyer_negotiation_catalogue([domain], requested_policies=[name])

    assert name in catalogue.names()


def test_the_seller_guards_are_not_offered_to_a_buyer() -> None:
    catalogue = compose_buyer_negotiation_catalogue(
        [domain], requested_policies=list(API_CREDITS_SELLER_POLICIES)
    )

    for seller_only in API_CREDITS_SELLER_POLICIES:
        assert seller_only not in catalogue.names()
        with pytest.raises(UnknownCatalogueEntryError):
            catalogue.resolve([seller_only])
