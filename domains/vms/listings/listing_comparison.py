"""Compare a stored VM listing with a fresh derivation of its own source.

A listing's identity is the physical resource it offers; every other published
field is a term of sale. Terms change in place. An identity change is never
applied to an existing listing: where the derivation key captures the changed
field the old key simply stops being derived, and where it does not, the listing
closes and stays closed while the difference persists.

A listing commits only to the fields it publishes. An identity field the stored
listing does not carry is no commitment, so it is neither a divergence nor added
to the listing by a refresh. Symmetrically, a source confirms only the fields it
resolves: an identity field the fresh derivation leaves unset — a region the
pool does not tag and no local fallback supplies — is not the source's to
contradict, so it is not a divergence either.

Capacity backing sits outside that split. It is recorded on the durable binding
at creation; the published value is always the binding's, so a listing that does
not yet disclose it is refreshed in place, while a source whose live backing
disagrees with the binding is treated like a diverged identity.

See openspec/specs/storefront-publication/spec.md, "A listing's identity is the
physical resource it offers".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# What the resource is, where it is, and how much of it one listing offers. The
# declared dimensions are listed so that, once publication carries them, they
# are identity without a change here.
IDENTITY_FIELDS: tuple[str, ...] = (
    "pool_id",
    "resource_id",
    "offering_mode",
    "resource_type",
    "resource_subtype",
    "gpu_model",
    "gpu_count",
    "vcpu_count",
    "ram_gb",
    "disk_gb",
    "region",
)

# Terms of sale carried inside the published listing shape.
TERM_RESOURCE_FIELDS: tuple[str, ...] = ("sla", "interruptible", "settlement_model")

# Terms of sale carried beside the listing shape.
TERM_LISTING_FIELDS: tuple[str, ...] = (
    "accepted_escrows",
    "settlement_options",
    "demands",
    "max_duration_seconds",
)

BACKING_FIELD = "capacity_backing"

UNCHANGED = "unchanged"
TERMS_DIFFER = "terms_differ"
BACKING_UNDISCLOSED = "backing_undisclosed"
IDENTITY_DIFFERS = "identity_differs"
BACKING_DISAGREES = "backing_disagrees"

# Outcomes that are refreshed in place and outcomes that close and refuse reopen.
REFRESH_IN_PLACE = frozenset({TERMS_DIFFER, BACKING_UNDISCLOSED})
REFUSE = frozenset({IDENTITY_DIFFERS, BACKING_DISAGREES})


@dataclass(frozen=True)
class ListingComparison:
    outcome: str
    differing_fields: tuple[str, ...] = ()


def _published(value: Any) -> bool:
    return value is not None


def compare_listing(
    *,
    stored_resource: Mapping[str, Any],
    stored_terms: Mapping[str, Any],
    fresh_resource: Mapping[str, Any],
    fresh_terms: Mapping[str, Any],
    binding_backing: str,
    source_backing: str,
) -> ListingComparison:
    """Classify how a stored listing differs from what its source now derives."""
    if source_backing != binding_backing:
        return ListingComparison(BACKING_DISAGREES, (BACKING_FIELD,))
    identity = tuple(
        name
        for name in IDENTITY_FIELDS
        if _published(stored_resource.get(name))
        and _published(fresh_resource.get(name))
        and stored_resource.get(name) != fresh_resource.get(name)
    )
    if identity:
        return ListingComparison(IDENTITY_DIFFERS, identity)
    terms = tuple(
        name
        for name in TERM_RESOURCE_FIELDS
        if stored_resource.get(name) != fresh_resource.get(name)
    ) + tuple(
        name
        for name in TERM_LISTING_FIELDS
        if stored_terms.get(name) != fresh_terms.get(name)
    )
    if terms:
        return ListingComparison(TERMS_DIFFER, terms)
    if stored_resource.get(BACKING_FIELD) != binding_backing:
        return ListingComparison(BACKING_UNDISCLOSED, (BACKING_FIELD,))
    return ListingComparison(UNCHANGED)


def refreshed_listing_resource(
    *,
    stored_resource: Mapping[str, Any],
    fresh_resource: Mapping[str, Any],
    binding_backing: str,
) -> dict[str, Any]:
    """The listing shape a refresh publishes: stored identity, fresh terms.

    Identity fields are taken from the stored listing, so a refresh never adds
    one the listing did not publish; term fields come from the fresh
    derivation; backing is the binding's.
    """
    refreshed = {
        name: stored_resource[name]
        for name in stored_resource
        if name not in TERM_RESOURCE_FIELDS and name != BACKING_FIELD
    }
    for name in TERM_RESOURCE_FIELDS:
        if name in fresh_resource:
            refreshed[name] = fresh_resource[name]
    refreshed[BACKING_FIELD] = binding_backing
    return refreshed


__all__ = [
    "BACKING_DISAGREES",
    "BACKING_UNDISCLOSED",
    "IDENTITY_DIFFERS",
    "IDENTITY_FIELDS",
    "REFRESH_IN_PLACE",
    "REFUSE",
    "TERMS_DIFFER",
    "TERM_LISTING_FIELDS",
    "TERM_RESOURCE_FIELDS",
    "UNCHANGED",
    "ListingComparison",
    "compare_listing",
    "refreshed_listing_resource",
]
