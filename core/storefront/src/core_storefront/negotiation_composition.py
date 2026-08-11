"""Role-owned composition of one negotiation policy catalogue.

This is the only place the two vocabularies meet. The generic policy layer
defines what a source is and knows nothing of domains; a domain declares which
of its own policies it offers and knows nothing of composition.

The division of authority is deliberate. The **role** decides which mechanisms
may contribute policies — its own built-ins, operator directories, installed
entry points — and constructs those sources itself. A **domain** contributes
only its own policies, and receives a narrow typed request rather than a bag of
options, so a mistyped role setting fails here instead of being absorbed.

The catalogue is built once and injected. It is not module state: one process
may compose more than one role, and a test must be able to compose a
deliberately invalid catalogue to assert the resulting error.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from market_core import DomainCapability, MarketDomainContract
from market_policy import (
    NEGOTIATION_MIDDLEWARE_GROUP,
    DirectorySource,
    EntryPointSource,
    NegotiationCatalogue,
    NegotiationMiddleware,
    NegotiationPolicyRequest,
    NegotiationPolicySource,
    PolicyRole,
    negotiation_catalogue_builder,
    scalar_escrow_policies,
)

__all__ = ["compose_negotiation_catalogue", "domain_policy_sources"]

#: Symbol a directory-supplied negotiation policy module must expose.
_DIRECTORY_POLICY_SYMBOL = "middleware"


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


def compose_negotiation_catalogue(
    domains: Sequence[MarketDomainContract],
    *,
    role: PolicyRole,
    requested_policies: Iterable[str] = (),
    include_kit_policies: bool = True,
    include_entry_points: bool = False,
    directory_roots: Iterable[str | Path] = (),
) -> NegotiationCatalogue:
    """Build the catalogue this role resolves configured policy names against.

    Every mechanism other than a domain's own policies is authorized here by
    name. ``include_kit_policies=False`` is the supported way to replace a
    built-in policy, because a name offered twice is an error.
    """
    builder = negotiation_catalogue_builder()

    if include_kit_policies:
        builder.add_loader(scalar_escrow_policies())
    if include_entry_points:
        builder.add_loader(
            EntryPointSource[NegotiationMiddleware](group=NEGOTIATION_MIDDLEWARE_GROUP)
        )
    roots = tuple(directory_roots)
    if roots:
        builder.add_loader(
            DirectorySource[NegotiationMiddleware].from_paths(
                roots, symbol=_DIRECTORY_POLICY_SYMBOL, label="operator-directories"
            )
        )

    request = NegotiationPolicyRequest(
        role=role, requested_policies=frozenset(requested_policies)
    )
    for domain in domains:
        builder.add_loaders(domain_policy_sources(domain, request))
    return builder.build()
