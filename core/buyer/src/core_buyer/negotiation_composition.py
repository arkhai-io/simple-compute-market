"""Role-owned composition of the buyer's negotiation policy catalogue.

The buyer composes separately from the storefront rather than sharing one
helper. That is not duplication for its own sake: composition is the point at
which a role decides which mechanisms may contribute policies, and the buyer's
answer differs from a storefront's. A shared helper would have to be
parameterised until it expressed both, which is the option sink this design
replaced.

Kit cannot own this either. Composition reads market-domain contracts, and the
generic policy layer must not know that domains exist.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from market_core import DomainCapability, MarketDomainContract
from market_policy import (
    NegotiationCatalogue,
    NegotiationPolicyRequest,
    NegotiationPolicySource,
    PolicyRole,
    negotiation_catalogue_builder,
    scalar_escrow_policies,
)

__all__ = ["compose_buyer_negotiation_catalogue", "domain_policy_sources"]


def domain_policy_sources(
    domain: MarketDomainContract, request: NegotiationPolicyRequest
) -> tuple[NegotiationPolicySource, ...]:
    """Return the policies ``domain`` offers for ``request``, or none.

    A domain that composes its negotiation middlewares as values exposes no
    names to configuration and declares no negotiation capability. That is a
    valid domain, not an incomplete one, so absence yields an empty tuple.
    """
    if not domain.has_capability(DomainCapability.NEGOTIATION):
        return ()
    capability = domain.capability(DomainCapability.NEGOTIATION)
    if capability is None:
        return ()
    return tuple(capability.policy_sources(request))


def compose_buyer_negotiation_catalogue(
    domains: Sequence[MarketDomainContract],
    *,
    requested_policies: Iterable[str] = (),
    include_kit_policies: bool = True,
) -> NegotiationCatalogue:
    """Build the catalogue the buyer resolves configured policy names against.

    The buyer authorizes no filesystem or entry-point mechanism. Its policy
    surface is the generic escrow vocabulary plus whatever its installed
    domains offer for the buyer role, so nothing in ``buyer.toml`` can cause a
    policy to be loaded from disk.
    """
    builder = negotiation_catalogue_builder()
    if include_kit_policies:
        builder.add_loader(scalar_escrow_policies())

    request = NegotiationPolicyRequest(
        role=PolicyRole.BUYER, requested_policies=frozenset(requested_policies)
    )
    for domain in domains:
        builder.add_loaders(domain_policy_sources(domain, request))
    return builder.build()
