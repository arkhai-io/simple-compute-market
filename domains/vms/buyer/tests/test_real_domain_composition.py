"""The real VM buyer domain contract, composed by the real buyer role.

Every other suite for this seam substitutes a constructed contract. This one
joins the production pieces — the contract the ``market.buyer_domains`` entry
point publishes, the buyer role's composition, and the domain's own policy
sources — because the parts can each be correct while the wiring between them
is missing.

That is not hypothetical: the buyer contract initially declared no negotiation
capability, so a buyer configured for an RL chain could not resolve one. Every
component test passed.
"""

from __future__ import annotations

import pytest
from core_buyer.negotiation_composition import compose_buyer_negotiation_catalogue
from market_core import DomainCapability
from market_policy import UnknownCatalogueEntryError

from domains.vms.buyer.cli import domain
from domains.vms.negotiation.policy_sources import (
    RL_POLICY_NAMES,
    VM_SELLER_POLICIES,
)


def test_the_published_contract_declares_the_negotiation_capability() -> None:
    assert domain.has_capability(DomainCapability.NEGOTIATION)
    assert domain.capability(DomainCapability.NEGOTIATION) is not None


def test_the_published_contract_declares_the_buyer_capability() -> None:
    """Guards against the negotiation addition displacing what was there."""
    assert domain.has_capability(DomainCapability.BUYER)
    assert domain.buyer is not None


@pytest.mark.parametrize("rl_name", sorted(RL_POLICY_NAMES))
def test_a_buyer_configured_for_rl_resolves_it_from_the_real_contract(
    rl_name: str,
) -> None:
    catalogue = compose_buyer_negotiation_catalogue(
        [domain], requested_policies=[rl_name, "listed_price"]
    )

    assert rl_name in catalogue.names()
    assert catalogue.provenance(rl_name) == "vm-torch-strategy"
    assert catalogue.resolve([rl_name])


def test_a_buyer_not_asking_for_rl_does_not_receive_it() -> None:
    catalogue = compose_buyer_negotiation_catalogue(
        [domain], requested_policies=["listed_price"]
    )

    assert not set(catalogue.names()) & RL_POLICY_NAMES


def test_the_real_contract_offers_no_seller_guard_to_a_buyer() -> None:
    catalogue = compose_buyer_negotiation_catalogue(
        [domain], requested_policies=list(VM_SELLER_POLICIES)
    )

    for seller_only in VM_SELLER_POLICIES:
        assert seller_only not in catalogue.names()
        with pytest.raises(UnknownCatalogueEntryError):
            catalogue.resolve([seller_only])


def test_the_kit_vocabulary_is_available_alongside_the_domain_offer() -> None:
    catalogue = compose_buyer_negotiation_catalogue([domain])

    assert "listed_price" in catalogue.names()
    assert "buyer_escrow_shape_guard" in catalogue.names()
