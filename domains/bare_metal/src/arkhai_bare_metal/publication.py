"""Bare-metal listing derivation from a site's resource-pool projection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from arkhai_compute import COMPUTE_CAPABILITY_SCHEMA
from market_capability_shape import flatten_shape

from .projections import (
    BareMetalResourceProjection,
    TrustedBareMetalProjection,
    TrustedBareMetalResource,
)
from .schema import BareMetalListing
from .shapes import derive_bare_metal_shape

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
            declared_capacity = raw_resource.get("capacity") or {}
            declared_attributes = raw_resource.get("attributes") or {}
            if not isinstance(declared_capacity, Mapping) or not isinstance(
                declared_attributes, Mapping
            ):
                raise ValueError(
                    "a projected resource's capacity and attributes must be mappings"
                )
            resources.append(
                TrustedBareMetalResource(
                    pool_id=pool_id,
                    enabled=enabled,
                    view=view,
                    declared_capacity=dict(declared_capacity),
                    declared_attributes=dict(declared_attributes),
                )
            )

    return TrustedBareMetalProjection(
        site_id=site_id,
        revision=projection.get("revision"),
        digest=projection.get("digest"),
        resources=resources,
    )


def available_bare_metal_listings(
    resources: Iterable[TrustedBareMetalResource],
    *,
    region: str,
    min_duration_seconds: int | None = None,
    max_duration_seconds: int | None = None,
) -> list[BareMetalListing]:
    """Derive listings from trusted resources whose whole machine is available.

    Each listing publishes its resource's declared shape under the compute
    family's flat names. A resource whose declaration does not read as a shape
    raises ``BareMetalShapeError``; callers that must hold rather than fail
    classify resources first (see ``storefront_publication``).
    """
    listings: list[BareMetalListing] = []
    for resource in resources:
        if not resource.view.available:
            continue
        shape = derive_bare_metal_shape(
            resource.declared_capacity, resource.declared_attributes
        )
        flat = flatten_shape(shape, COMPUTE_CAPABILITY_SCHEMA)
        listings.append(
            BareMetalListing(
                capacity_backing="backed",
                host_id=resource.view.host_id,
                physical_host_id=resource.view.physical_host_id,
                access_methods=list(resource.view.access_methods),
                min_duration_seconds=min_duration_seconds,
                max_duration_seconds=max_duration_seconds,
                region=region,
                **dict(flat.quantities),
                **dict(flat.attributes),
            ),
        )
    return listings
