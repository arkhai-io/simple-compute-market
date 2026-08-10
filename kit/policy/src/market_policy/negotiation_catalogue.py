"""The negotiation-policy instantiation of the generic catalogue.

This module supplies the three things the generic machinery deliberately does
not know: what a well-formed negotiation policy is, what the domain hook
receives, and which built-in policies this package offers.

The role decides which *mechanisms* may contribute policies; a domain decides
which of its own policies to offer, and receives only the narrow context it
needs to make that decision. A domain cannot be handed a mechanism it did not
ask for, and cannot silently absorb a role option that was misspelled.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from market_policy.catalogue import (
    Catalogue,
    CatalogueBuilder,
    CatalogueSource,
    require_callable_item,
)
from market_policy.negotiation_middleware import (
    NegotiationMiddleware,
    max_rounds_guard,
    normalize_policies_by_escrow_kind_config,
)
from market_policy.scalar_policies import (
    accept_exact_listing_middleware,
    amount_bisection_middleware,
    bisection_middleware,
    buyer_counter_guard,
    buyer_escrow_shape_guard,
    escrow_shape_guard,
    listed_price_middleware,
)
from market_policy.sources import InlineSource

__all__ = [
    "NEGOTIATION_POLICY_KIND",
    "NegotiationCatalogue",
    "NegotiationPolicyRequest",
    "NegotiationPolicySource",
    "PolicyRole",
    "configured_policy_names",
    "negotiation_catalogue_builder",
    "scalar_escrow_policies",
]

NEGOTIATION_POLICY_KIND = "negotiation policy"


class PolicyRole(str, Enum):
    """The role a catalogue is being composed for.

    A domain's seller-side and buyer-side policies are different sets. Handing
    a storefront the buyer responder would let it resolve a name it must never
    resolve, which defeats the question a catalogue exists to answer.
    """

    BUYER = "buyer"
    STOREFRONT = "storefront"


@dataclass(frozen=True)
class NegotiationPolicyRequest:
    """What a domain is told when asked which policies it offers.

    Deliberately narrow and typed. An unexpected field is a ``TypeError`` at
    composition rather than a value a domain silently ignores.
    """

    role: PolicyRole
    #: Every name the composing role's configuration may resolve. A domain may
    #: use this to decide whether an expensive optional policy is worth
    #: loading; it is not a filter on the domain's ordinary policies.
    requested_policies: frozenset[str] = field(default_factory=frozenset)

    def wants_any(self, names: frozenset[str]) -> bool:
        return bool(self.requested_policies & names)


def configured_policy_names(
    negotiation_config: Any,
    *,
    default_chain: Sequence[str],
    default_terminal: str,
) -> frozenset[str]:
    """Every policy name this configuration could ask a catalogue to resolve.

    Composition needs this before the catalogue exists, because a domain may
    decide whether an expensive optional policy is worth loading. It is a
    superset, not the chain: a per-escrow-kind table contributes every kind's
    names even though one negotiation reaches only one of them.
    """

    raw = getattr(negotiation_config, "policies", None)
    names: set[str] = set(default_chain)
    names.add(default_terminal)

    by_kind = normalize_policies_by_escrow_kind_config(raw)
    if by_kind:
        for chain in by_kind.values():
            names.update(str(name).strip() for name in chain if str(name).strip())
        return frozenset(names)

    configured = [str(name).strip() for name in (raw or []) if str(name).strip()]
    names.update(configured)
    mode = (getattr(negotiation_config, "policy_mode", "") or "").strip()
    if mode:
        names.add(mode)
    return frozenset(names)


def negotiation_catalogue_builder() -> CatalogueBuilder[NegotiationMiddleware]:
    """A builder that validates negotiation policies and names them in errors."""
    return CatalogueBuilder[NegotiationMiddleware](
        kind=NEGOTIATION_POLICY_KIND, validate=require_callable_item
    )


def scalar_escrow_policies() -> InlineSource[NegotiationMiddleware]:
    """The generic escrow-negotiation policies this package implements.

    Offered as an ordinary source rather than a privileged default, so there is
    no base-set branch in the catalogue and no name that resolves differently
    depending on who offered it. A role that wants none of these composes
    without this source.
    """
    policies: Mapping[str, NegotiationMiddleware] = {
        "bisection": bisection_middleware,
        # Escrow-kind aliases for the same scalar bisection, so a chain
        # configured per escrow kind names the kind it operates on.
        "erc20_bisection": amount_bisection_middleware,
        "native_token_bisection": amount_bisection_middleware,
        "erc1155_bisection": amount_bisection_middleware,
        "listed_price": listed_price_middleware,
        "accept_exact_listing": accept_exact_listing_middleware,
        "buyer_counter_guard": buyer_counter_guard,
        "buyer_escrow_shape_guard": buyer_escrow_shape_guard,
        "escrow_shape_guard": escrow_shape_guard,
        "max_rounds_guard": max_rounds_guard,
    }
    return InlineSource(policies, label="kit-scalar-escrow")


#: A catalogue of negotiation middlewares. Callers annotate against this rather
#: than the bare generic, so the element type survives composition.
NegotiationCatalogue = Catalogue[NegotiationMiddleware]

#: A source offering negotiation middlewares.
NegotiationPolicySource = CatalogueSource[NegotiationMiddleware]
