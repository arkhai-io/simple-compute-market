"""Bare-metal listing derivation from trusted per-resource projections."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .projections import BareMetalResourceProjection, TrustedBareMetalProjection
from .schema import BareMetalListing

BARE_METAL_PUBLICATION_VIEW = "bare_metal.v1"


def _length_prefixed(value: str) -> str:
    """Encode a field so its boundary is unambiguous regardless of its
    own content -- ``site_id``/``physical_resource_id`` are operator-
    chosen strings with no character restrictions (``physical_resource_id``
    is a bare ``pydantic`` ``str`` field, ``min_length=1`` only), so naive
    delimiter-joining these fields is not collision-free:
    ``site_id="a", physical_resource_id="b:c"`` and
    ``site_id="a:b", physical_resource_id="c"`` would otherwise produce
    an identical key. A decimal length prefix followed by exactly that
    many characters fixes each field's boundary exactly, independent of
    its contents, making the overall key injective (different inputs
    always produce different keys). Kept local to this module rather
    than shared with the VM domain's equivalent -- domains do not
    depend on each other for this.
    """
    return f"{len(value)}:{value}"


def bare_metal_listing_key(
    *,
    site_id: str,
    physical_resource_id: str,
) -> str:
    """Return the site-scoped derivation key for one Physical Resource."""
    if not site_id.strip():
        raise ValueError("site_id must be non-empty")
    if not physical_resource_id.strip():
        raise ValueError("physical_resource_id must be non-empty")
    return (
        f"bare-metal:{_length_prefixed(site_id)}"
        f":{_length_prefixed(physical_resource_id)}"
    )


def trusted_bare_metal_projection(
    *,
    site_id: str,
    revision: int,
    digest: str,
    resource_pools: Iterable[Mapping[str, Any]],
    complete: bool,
    stale: bool = False,
) -> TrustedBareMetalProjection:
    """Interpret one trusted site's complete resource-pool generation.

    The caller supplies ``site_id`` from local trusted configuration. Remote
    resource rows provide no routing authority. A malformed enabled view fails
    the complete generation rather than being silently skipped.
    """
    if not complete:
        return TrustedBareMetalProjection(
            site_id=site_id,
            revision=revision,
            digest=digest,
            complete=False,
            stale=stale,
            resources=[],
        )

    resources: list[BareMetalResourceProjection] = []
    for pool in resource_pools:
        raw_resources = pool.get("resources") or []
        if not isinstance(raw_resources, list):
            raise ValueError("resource-pool resources must be a list")
        for raw_resource in raw_resources:
            if not isinstance(raw_resource, Mapping):
                raise ValueError("projected resource must be a mapping")
            views = raw_resource.get("publication_views") or {}
            if not isinstance(views, Mapping):
                raise ValueError("publication_views must be a mapping")
            raw_view = views.get(BARE_METAL_PUBLICATION_VIEW)
            if raw_view is None:
                continue
            view = BareMetalResourceProjection.model_validate(raw_view)
            projected_id = str(
                raw_resource.get("physical_resource_id") or "",
            )
            if view.physical_resource_id != projected_id:
                raise ValueError(
                    "bare-metal view physical_resource_id conflicts with "
                    "the containing site projection",
                )
            resources.append(view)

    return TrustedBareMetalProjection(
        site_id=site_id,
        revision=revision,
        digest=digest,
        complete=True,
        stale=stale,
        resources=resources,
    )


def available_bare_metal_listings(
    resources: Iterable[BareMetalResourceProjection | Mapping[str, Any]],
    *,
    min_duration_seconds: int | None = None,
    max_duration_seconds: int | None = None,
    site: dict[str, str] | None = None,
) -> list[BareMetalListing]:
    """Derive listings from validated available specific-resource views."""
    listings: list[BareMetalListing] = []
    for raw in resources:
        resource = BareMetalResourceProjection.model_validate(raw)
        if not resource.available:
            continue
        capabilities = dict(resource.capacity)
        for key, value in resource.capabilities.items():
            existing = capabilities.get(key)
            if key in capabilities and existing != value:
                raise ValueError(
                    f"capacity and capabilities conflict for: {key}",
                )
            capabilities[key] = value
        listings.append(
            BareMetalListing(
                machine_id=resource.machine_id,
                physical_host_id=resource.physical_host_id,
                access_methods=list(resource.access_methods),
                min_duration_seconds=min_duration_seconds,
                max_duration_seconds=max_duration_seconds,
                site=site,
                capabilities=capabilities,
            ),
        )
    return listings
