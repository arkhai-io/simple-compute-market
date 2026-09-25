"""Bare-metal listing derivation from a site's resource-pool projection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .projections import (
    BareMetalResourceProjection,
    TrustedBareMetalProjection,
    TrustedBareMetalResource,
)
from .schema import BareMetalListing

BARE_METAL_PUBLICATION_VIEW = "bare_metal.v2"


def trusted_bare_metal_projection(
    *,
    site_id: str,
    projection: Mapping[str, Any],
) -> TrustedBareMetalProjection:
    """Interpret one trusted site's resource-pool projection generation.

    ``projection`` is the site's response: its ``revision``, ``digest``, and
    ``resource_pools``. The caller supplies ``site_id`` from local trusted
    configuration; remote rows provide no routing authority.

    Listings derive from the view the site builds from each capacity
    declaration, the one admission accounts against, never from a view a
    storefront assembles from publication attributes, which could name a
    different machine than the one admission would reserve.

    Every resource carrying a bare-metal view is kept with its containing pool
    entry's ``pool_id`` and its own declared ``enabled``. The containing entry
    is authoritative for the resource's pool, so a view repeating a different
    pool, or naming a different Physical Resource than its container, refuses
    the whole generation, as does any malformed view: a consumer then holds
    what it derived from the site rather than guessing which copy is right.
    """
    raw_pools = projection.get("resource_pools")
    if not isinstance(raw_pools, list):
        raise ValueError("resource-pool projection must carry a resource_pools list")

    resources: list[TrustedBareMetalResource] = []
    for pool in raw_pools:
        if not isinstance(pool, Mapping):
            raise ValueError("resource-pool entry must be a mapping")
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
            if not isinstance(raw_view, Mapping):
                raise ValueError("bare-metal view must be a mapping")
            pool_id = pool.get("pool_id")
            if not isinstance(pool_id, str) or not pool_id.strip():
                raise ValueError("a bare-metal view's containing pool names no pool_id")
            enabled = raw_resource.get("enabled")
            if not isinstance(enabled, bool):
                raise ValueError("a projected resource must declare its enablement")
            view = BareMetalResourceProjection.model_validate(raw_view)
            if view.physical_resource_id != str(
                raw_resource.get("physical_resource_id") or ""
            ):
                raise ValueError(
                    "bare-metal view physical_resource_id conflicts with "
                    "the containing site projection",
                )
            resources.append(
                TrustedBareMetalResource(
                    pool_id=pool_id,
                    enabled=enabled,
                    view=view,
                )
            )

    return TrustedBareMetalProjection(
        site_id=site_id,
        revision=projection.get("revision"),
        digest=projection.get("digest"),
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
                capacity_backing="backed",
                host_id=resource.host_id,
                physical_host_id=resource.physical_host_id,
                access_methods=list(resource.access_methods),
                min_duration_seconds=min_duration_seconds,
                max_duration_seconds=max_duration_seconds,
                site=site,
                capabilities=capabilities,
            ),
        )
    return listings
