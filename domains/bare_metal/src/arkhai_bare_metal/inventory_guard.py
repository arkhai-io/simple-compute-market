"""Rechecking a bare-metal listing against its own source before terms are agreed.

Seller policy must not agree terms for a listing whose published fields its
source no longer supports. A bare-metal listing's shape comes from its Physical
Resource's declaration and its region from its pool, so the recheck reads both
back from the site's projection through the same classification publication
uses: whatever publication would now publish for the resource is what the
listing must still be. It checks the declaration, not availability; a machine
leased since publication still matches its declaration. See
openspec/specs/storefront-publication/spec.md, "The seller's inventory guard
checks a listing against its own source" and "Bare-metal opening rechecks its
listing against its source".

This is pure: the caller fetches the projection and resolves each pool's
admission and region, and turns the outcome into its own refusal.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .projections import TrustedBareMetalProjection
from .storefront_publication import (
    CANDIDATE,
    HELD,
    UNAVAILABLE,
    classify_bare_metal_resources,
)

#: The listing still matches what its source declares.
SOURCE_MATCHES = "match"
#: The source declares something other than the listing published, or can no
#: longer be read as the shape the listing published.
SOURCE_MISMATCH = "declared_mismatch"
#: The source no longer offers the resource: it is missing, withdrawn, or its
#: pool no longer admits bare metal.
SOURCE_ABSENT = "absent"


@dataclass(frozen=True)
class ListingSourceCheck:
    """One recheck's outcome and the reason it names."""

    outcome: str
    reason: str

    @property
    def matches(self) -> bool:
        return self.outcome == SOURCE_MATCHES


def recheck_bare_metal_listing_source(
    generation: TrustedBareMetalProjection,
    *,
    pool_admission: Mapping[str, str],
    pool_regions: Mapping[str, str | None],
    pool_id: str,
    physical_resource_id: str,
    shape_digest: str,
    region: str,
) -> ListingSourceCheck:
    """Whether the listing bound to this resource still matches its source."""
    classification = classify_bare_metal_resources(
        generation, pool_admission=pool_admission, pool_regions=pool_regions
    )
    item = next(
        (
            resource
            for resource in classification.resources
            if resource.pool_id == pool_id
            and resource.physical_resource_id == physical_resource_id
        ),
        None,
    )
    if item is None:
        return ListingSourceCheck(
            SOURCE_ABSENT, "the resource is no longer projected under its pool"
        )
    if item.classification == HELD:
        if item.problems:
            detail = "; ".join(item.problems)
            return ListingSourceCheck(
                SOURCE_MISMATCH, f"the declaration no longer reads as a shape: {detail}"
            )
        if pool_regions.get(pool_id) is None:
            return ListingSourceCheck(SOURCE_MISMATCH, "the pool no longer states a region")
        return ListingSourceCheck(
            SOURCE_MISMATCH, "the pool's declarations do not resolve"
        )
    if item.classification not in (CANDIDATE, UNAVAILABLE):
        return ListingSourceCheck(
            SOURCE_ABSENT, "the resource or its pool no longer offers bare metal"
        )
    if item.shape_digest != shape_digest:
        return ListingSourceCheck(
            SOURCE_MISMATCH, "the declared shape differs from the published shape"
        )
    if pool_regions.get(pool_id) != region:
        return ListingSourceCheck(
            SOURCE_MISMATCH, "the pool's region differs from the published region"
        )
    return ListingSourceCheck(SOURCE_MATCHES, "the listing matches its source")


__all__ = [
    "SOURCE_ABSENT",
    "SOURCE_MATCHES",
    "SOURCE_MISMATCH",
    "ListingSourceCheck",
    "recheck_bare_metal_listing_source",
]
