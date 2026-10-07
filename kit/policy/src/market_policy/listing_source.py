"""A listing checked against its own source, and what that check refuses.

A listing published from a declaration (a site's pool or Physical Resource) is
rechecked against that source before a seller agrees terms. The domain reads the
source and reports a :class:`ListingSourceVerdict`; :func:`classify_listing_source`
is the one place a verdict becomes a refusal, used both by the negotiation runtime,
which enforces it on every round and acceptance whatever a policy chain contains,
and by ``has_matching_inventory_guard``, which refuses at its chain position so the
guards ahead of it refuse a malformed request for its own reason first.

See openspec/specs/storefront-publication/spec.md, "The seller's inventory guard
checks a listing against its own source".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationRound,
    NegotiationStep,
    register_negotiation_middleware,
)

ListingSourceOutcome = Literal[
    "matches", "declared_mismatch", "unavailable", "unverifiable"
]

#: The source no longer declares what the listing published.
NO_MATCHING_DECLARATION = "no_matching_declaration"
#: The source declares it, but the capacity it backs is not free now.
NO_MATCHING_INVENTORY = "no_matching_inventory"
#: The source could not be read or verified; nothing is known to be wrong.
LISTING_SOURCE_UNVERIFIABLE = "listing_source_unverifiable"


@dataclass(frozen=True, slots=True)
class ListingSourceVerdict:
    """What a domain's check of one listing against its source found.

    ``reason`` and ``differing_fields`` are for the seller's log; a buyer sees only
    the classified refusal reason, which names no source detail.
    """

    outcome: ListingSourceOutcome
    reason: str | None = None
    differing_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.outcome not in (
            "matches",
            "declared_mismatch",
            "unavailable",
            "unverifiable",
        ):
            raise ValueError(f"unknown listing-source outcome {self.outcome!r}")


@dataclass(frozen=True, slots=True)
class ListingSourceRefusal:
    """A refusal a verdict requires; a retryable one means the source was unknown."""

    reason: str
    retryable: bool = False


def classify_listing_source(
    verdict: ListingSourceVerdict | None,
) -> ListingSourceRefusal | None:
    """The refusal ``verdict`` requires, or ``None`` when the listing matches.

    A missing verdict is refused as a declared mismatch: a caller that should have
    checked the source and did not cannot say the listing still matches it.
    """

    if verdict is None:
        return ListingSourceRefusal(NO_MATCHING_DECLARATION)
    if verdict.outcome == "matches":
        return None
    if verdict.outcome == "declared_mismatch":
        return ListingSourceRefusal(NO_MATCHING_DECLARATION)
    if verdict.outcome == "unavailable":
        return ListingSourceRefusal(NO_MATCHING_INVENTORY)
    return ListingSourceRefusal(LISTING_SOURCE_UNVERIFIABLE, retryable=True)


@register_negotiation_middleware("has_matching_inventory_guard")
def has_matching_inventory_guard(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Veto a listing its own source no longer supports, or cannot supply.

    Reads the verdict the negotiation runtime obtained for this round. A retryable
    refusal is left to the runtime, which refuses it before any write: a chain can
    only reject, and a rejection would end a negotiation a retry could complete.
    """

    refusal = classify_listing_source(context.listing_source)
    if refusal is None or refusal.retryable:
        return None, context
    return NegotiationDecision(action="reject", reason=refusal.reason), context


__all__ = [
    "LISTING_SOURCE_UNVERIFIABLE",
    "NO_MATCHING_DECLARATION",
    "NO_MATCHING_INVENTORY",
    "ListingSourceOutcome",
    "ListingSourceRefusal",
    "ListingSourceVerdict",
    "classify_listing_source",
    "has_matching_inventory_guard",
]
