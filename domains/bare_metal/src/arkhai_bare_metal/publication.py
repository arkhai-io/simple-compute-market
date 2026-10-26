"""Bare-metal listing derivation from a site's resource-pool projection."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from arkhai_compute import COMPUTE_CAPABILITY_SCHEMA
from market_capability_shape import flatten_shape
from market_resource_pools_contracts.backing import CapacityBacking

from .projections import (
    BareMetalResourceProjection,
    BareMetalViewProblems,
    TrustedBareMetalProjection,
    TrustedBareMetalResource,
)
from .schema import BARE_METAL_LISTING_DELIVERY_TERMS, BareMetalListing
from .shapes import derive_bare_metal_shape

BARE_METAL_PUBLICATION_VIEW = "bare_metal.v2"


def trusted_bare_metal_projection(
    *,
    site_id: str,
    projection: Mapping[str, Any],
    backings: Mapping[str, CapacityBacking],
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

    ``backings`` maps each pool whose declarations the caller resolved, reading
    the whole generation, to its backing delegate. Each view's delivery terms
    are held to its pool's backing (see ``TrustedBareMetalResource``), so a
    view contradicting its pool's backing refuses the generation too; a pool
    absent from ``backings`` has no backing to hold its views to.

    A resource the site could build no bare-metal view for carries the reasons
    under ``publication_view_problems``; each is kept in ``view_problems``. A
    resource carrying both the view and a problem for it, or problems that are
    not a list of text, is malformed and refuses the generation.
    """
    raw_pools = projection.get("resource_pools")
    if not isinstance(raw_pools, list):
        raise ValueError("resource-pool projection must carry a resource_pools list")

    resources: list[TrustedBareMetalResource] = []
    view_problems: list[BareMetalViewProblems] = []
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
            problems = raw_resource.get("publication_view_problems") or {}
            if not isinstance(problems, Mapping):
                raise ValueError("publication_view_problems must be a mapping")
            raw_view = views.get(BARE_METAL_PUBLICATION_VIEW)
            raw_problems = problems.get(BARE_METAL_PUBLICATION_VIEW)
            if raw_view is None and raw_problems is None:
                continue
            pool_id = pool.get("pool_id")
            if not isinstance(pool_id, str) or not pool_id.strip():
                raise ValueError("a bare-metal view's containing pool names no pool_id")
            enabled = raw_resource.get("enabled")
            if not isinstance(enabled, bool):
                raise ValueError("a projected resource must declare its enablement")
            if raw_problems is not None:
                if raw_view is not None:
                    raise ValueError(
                        "a resource carries both a bare-metal view and its problems"
                    )
                if not isinstance(raw_problems, list) or not all(
                    isinstance(problem, str) for problem in raw_problems
                ):
                    raise ValueError("bare-metal view problems must be a list of text")
                view_problems.append(
                    BareMetalViewProblems(
                        pool_id=pool_id,
                        physical_resource_id=str(
                            raw_resource.get("physical_resource_id") or ""
                        ),
                        enabled=enabled,
                        problems=tuple(raw_problems),
                    )
                )
                continue
            if not isinstance(raw_view, Mapping):
                raise ValueError("bare-metal view must be a mapping")
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
            backing = backings.get(pool_id)
            resources.append(
                TrustedBareMetalResource(
                    pool_id=pool_id,
                    enabled=enabled,
                    view=view,
                    capacity_backing=backing.label if backing is not None else None,
                    declared_capacity=dict(declared_capacity),
                    declared_attributes=dict(declared_attributes),
                )
            )

    return TrustedBareMetalProjection(
        site_id=site_id,
        revision=projection.get("revision"),
        digest=projection.get("digest"),
        resources=resources,
        view_problems=view_problems,
    )


def _availability(resource: TrustedBareMetalResource) -> Callable[[], str | None]:
    def available() -> str | None:
        return None if resource.view.available else "unavailable"

    return available


def available_bare_metal_listings(
    resources: Iterable[TrustedBareMetalResource],
    *,
    backing: CapacityBacking,
    region: str,
    min_duration_seconds: int | None = None,
    max_duration_seconds: int | None = None,
) -> list[BareMetalListing]:
    """Derive listings from trusted resources of one pool that ``backing`` admits.

    Where the pool's backing says availability bounds its resources, only a
    resource whose whole machine is available yields a listing; availability
    is never read otherwise. Each listing publishes its pool's backing label,
    the listing delivery terms its view carries and no others, and its
    resource's declared shape under the compute family's flat names. A
    resource whose declaration does not read as a shape raises
    ``BareMetalShapeError``; callers that must hold rather than fail classify
    resources first (see ``storefront_publication``).
    """
    listings: list[BareMetalListing] = []
    for resource in resources:
        if backing.judge(lambda: None, _availability(resource)) is not None:
            continue
        shape = derive_bare_metal_shape(
            resource.declared_capacity, resource.declared_attributes
        )
        flat = flatten_shape(shape, COMPUTE_CAPABILITY_SCHEMA)
        # Through the delegate, so an unbacked listing carries none of them
        # even where its view states one as empty.
        carried = backing.carry_delivery_terms(
            {name: getattr(resource.view, name) for name in BARE_METAL_LISTING_DELIVERY_TERMS}
        )
        terms = {name: value for name, value in carried.items() if value is not None}
        listings.append(
            BareMetalListing(
                capacity_backing=backing.label,
                **terms,
                min_duration_seconds=min_duration_seconds,
                max_duration_seconds=max_duration_seconds,
                region=region,
                **dict(flat.quantities),
                **dict(flat.attributes),
            ),
        )
    return listings
