"""Pure bare-metal publication decisions over one site's accepted generation.

Every Physical Resource carrying a bare-metal view falls into exactly one
class, and a storefront builds its reconciliation from those disjoint classes:

- **candidate** — its pool admits bare metal, its declaration is enabled, and
  its view says the whole machine is available: published, refreshed, or
  reopened;
- **unavailable** — as a candidate, but the machine is not wholly available
  (leased, say): its listing closes for availability and reopens when free;
- **held** — its pool's declarations do not resolve: its listing is neither
  closed nor refreshed, since an unknown declaration is not a withdrawn one;
- **withdrawn** — anything else, a disabled declaration or a pool that does
  not admit bare metal: its listing closes as a withdrawn source.

Enablement is read from the projected resource and never from the view,
whose ``available`` is the declaration's enablement and whole-resource
availability together; reading it would turn a withdrawn declaration into an
availability close. See openspec/specs/storefront-publication/spec.md,
"Source publication and capacity availability reconcile separately".

Nothing here reads or writes storefront state; the storefront owns that.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .projections import TrustedBareMetalProjection, TrustedBareMetalResource
from .publication import available_bare_metal_listings

# How a storefront's reading of a pool's declarations admits bare metal.
POOL_ADMITTED = "admitted"
POOL_HELD = "held"
POOL_NOT_ADMITTED = "not_admitted"

CANDIDATE = "candidate"
UNAVAILABLE = "unavailable"
HELD = "held"
WITHDRAWN = "withdrawn"


@dataclass(frozen=True)
class ClassifiedBareMetalResource:
    """One Physical Resource's class, with the source identity it carries."""

    classification: str
    site_id: str
    pool_id: str
    physical_resource_id: str


@dataclass(frozen=True)
class BareMetalSiteClassification:
    """One site generation, every bare-metal resource in exactly one class."""

    site_id: str
    candidates: tuple[dict[str, Any], ...]
    resources: tuple[ClassifiedBareMetalResource, ...]

    def of(self, classification: str) -> tuple[ClassifiedBareMetalResource, ...]:
        return tuple(
            item for item in self.resources if item.classification == classification
        )


def bare_metal_source_identity(*, pool_id: str, physical_resource_id: str) -> dict[str, str]:
    """The source identity a bare-metal listing's derivation key is built from.

    It includes the pool, so a Physical Resource moved to another pool derives
    a new listing and its old one closes as a withdrawn source: advertisement
    is authorized by the pool a listing's binding records.
    """
    return {"pool_id": pool_id, "physical_resource_id": physical_resource_id}


def _classify(
    resource: TrustedBareMetalResource, admission: str
) -> str:
    if admission == POOL_HELD:
        return HELD
    if admission != POOL_ADMITTED or not resource.enabled:
        return WITHDRAWN
    return CANDIDATE if resource.view.available else UNAVAILABLE


def classify_bare_metal_resources(
    generation: TrustedBareMetalProjection,
    *,
    pool_admission: Mapping[str, str],
    site_labels: dict[str, str] | None = None,
) -> BareMetalSiteClassification:
    """Classify every bare-metal resource in one accepted site generation.

    ``pool_admission`` maps each pool to :data:`POOL_ADMITTED`,
    :data:`POOL_HELD`, or :data:`POOL_NOT_ADMITTED`, as the caller read the
    pool's declarations; a pool it does not name admits nothing.
    """
    candidates: list[dict[str, Any]] = []
    classified: list[ClassifiedBareMetalResource] = []
    for resource in generation.resources:
        classification = _classify(
            resource, pool_admission.get(resource.pool_id, POOL_NOT_ADMITTED)
        )
        classified.append(
            ClassifiedBareMetalResource(
                classification=classification,
                site_id=generation.site_id,
                pool_id=resource.pool_id,
                physical_resource_id=resource.physical_resource_id,
            )
        )
        if classification != CANDIDATE:
            continue
        (listing,) = available_bare_metal_listings([resource.view], site=site_labels)
        candidates.append(
            {
                "site_id": generation.site_id,
                "pool_id": resource.pool_id,
                "physical_resource_id": resource.physical_resource_id,
                "projection_revision": generation.revision,
                "projection_digest": generation.digest,
                "host_id": listing.host_id,
                "physical_host_id": listing.physical_host_id,
                "listing_resource": listing.model_dump(mode="json", exclude_none=True),
                "listing": listing,
            }
        )
    return BareMetalSiteClassification(
        site_id=generation.site_id,
        candidates=tuple(candidates),
        resources=tuple(classified),
    )


# A bare-metal listing's published identity is the machine it offers. Every
# other published field is a term of sale, refreshed in place.
IDENTITY_FIELDS = (
    "kind",
    "offering_mode",
    "host_id",
    "physical_host_id",
    "capabilities",
    "site",
)
TERM_RESOURCE_FIELDS = (
    "access_methods",
    "min_duration_seconds",
    "max_duration_seconds",
    "capacity_backing",
)
TERM_LISTING_FIELDS = (
    "accepted_escrows",
    "settlement_options",
    "demands",
    "max_duration_seconds",
)

UNCHANGED = "unchanged"
REFRESH = "refresh"
IDENTITY_CHANGED = "identity_changed"


@dataclass(frozen=True)
class BareMetalListingComparison:
    outcome: str
    differing_fields: tuple[str, ...] = ()


def compare_bare_metal_listing(
    *,
    stored_resource: Mapping[str, Any],
    stored_terms: Mapping[str, Any],
    fresh_resource: Mapping[str, Any],
    fresh_terms: Mapping[str, Any],
) -> BareMetalListingComparison:
    """Compare a stored listing with a fresh candidate bound under the same key.

    A changed identity field is refused rather than refreshed: the listing
    would silently start offering a different machine under an identity a
    buyer already saw. A field the stored listing does not publish is no
    commitment, so its first appearance is not an identity change.
    """
    diverged = tuple(
        name
        for name in IDENTITY_FIELDS
        if stored_resource.get(name) is not None
        and stored_resource.get(name) != fresh_resource.get(name)
    )
    if diverged:
        return BareMetalListingComparison(IDENTITY_CHANGED, diverged)
    changed = tuple(
        name
        for name in TERM_RESOURCE_FIELDS
        if stored_resource.get(name) != fresh_resource.get(name)
    ) + tuple(
        f"listing.{name}"
        for name in TERM_LISTING_FIELDS
        if _normalized(stored_terms.get(name), name)
        != _normalized(fresh_terms.get(name), name)
    )
    return BareMetalListingComparison(REFRESH if changed else UNCHANGED, changed)


def _normalized(value: Any, name: str) -> Any:
    # A list-valued term stored as absent and published as empty is one term.
    if name != "max_duration_seconds" and value is None:
        return []
    return value


def listing_terms(record: Mapping[str, Any]) -> dict[str, Any]:
    """The term fields of a stored or fresh listing record."""
    return {name: record.get(name) for name in TERM_LISTING_FIELDS}
