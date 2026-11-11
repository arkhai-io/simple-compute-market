"""Resolve and check a requested VM shape before seller pricing."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing
from typing import Any, NoReturn

from arkhai_vms import vm_listing_resource_shape
from arkhai_vms_listings.listing_shapes import resolve_vm_listing_shapes, resolve_shape
from market_capacity_publication import RESOURCE_POOL, SiteProjectionState
from market_negotiation_runtime import OfferUnfulfillableError
from market_pool_overrides import read_pool_overrides

from market_storefront import container


async def check_requested_shape(
    *,
    repository: Any,
    listing_id: str,
    listing_resource: Mapping[str, Any],
    requested_resource: Mapping[str, Any],
    site_projections: SiteProjectionState,
    feasibility: Callable[[dict[str, dict[str, Any]]], None] | None = None,
) -> dict[str, dict[str, Any]]:
    """Resolve the listing's own policy, never another shape's constraints.

    Round-zero flat requests may state only changed dimensions. The caller
    supplies their effective resource; later grouped revisions are whole shapes.
    Source confirmation is separate from requested-shape feasibility: the held
    pool supplies policy, not an authoritative capacity probe.

    The checks run in order: policy resolution, admissibility, ``feasibility``
    (the caller's check of the requested shape against capacity, which raises
    to refuse it), then the commercial guard on GPU model and region.
    """
    def refuse(reason: str) -> NoReturn:
        raise OfferUnfulfillableError(reason, listing_id=listing_id)

    shape = vm_listing_resource_shape(requested_resource)
    recorded = await repository.load_listing_binding(listing_id=listing_id)
    if recorded is None or not recorded.pool_id:
        refuse("shape_policy_unavailable: listing has no durable pool binding")
    pools = site_projections.values(RESOURCE_POOL).get(recorded.site_id) or []
    pool = next(
        (pool for pool in pools if str(pool.get("pool_id")) == recorded.pool_id), None
    )
    if pool is None:
        refuse("shape_policy_unavailable: listing pool projection is not held")
    with closing(sqlite3.connect(repository.db_path)) as conn:
        override = next(
            (
                entry for entry in read_pool_overrides(conn, offering_mode="vm")
                if entry.site_id == recorded.site_id and entry.pool_id == recorded.pool_id
            ),
            None,
        )
    if override is not None and override.problems:
        refuse(f"shape_policy_unavailable: {override.problems}")
    advertised = vm_listing_resource_shape(listing_resource)
    resolution = resolve_vm_listing_shapes(
        (pool.get("pool_metadata") or {}).get("policy_tags") or {},
        pool.get("resources") or [],
        configured_default=container.resolved_admissibility_default,
        override_shapes=override.listing_shapes if override is not None else None,
        # Generated listings have only the configured default as their policy.
        # Membership and source freshness belong to the listing-source check.
        generator=lambda _members, _policy: (advertised,),
    )
    if resolution.unreadable:
        refuse(f"shape_policy_unavailable: {resolution.problems}")
    advertised_digest = resolve_shape(advertised).digest
    listing = next(
        (entry for entry in resolution.listings
         if entry.shape.digest == advertised_digest),
        None,
    )
    if listing is None or listing.policy is None:
        refuse("shape_policy_unavailable: advertised shape has no computable policy")
    problems = listing.policy.admissibility_problems(shape)
    if problems:
        refuse(f"shape_inadmissible: {tuple(str(problem) for problem in problems)}")

    # Requested-shape authoritative feasibility is not composed: the source
    # check confirms only the advertised listing, not this requested shape. The
    # caller's stand-in, if any, runs in its place, before the commercial guard.
    if feasibility is not None:
        feasibility(shape)
    mismatches = {
        key: {"requested": requested_resource[key], "listing": listing_resource.get(key)}
        for key in ("gpu_model", "region")
        if requested_resource.get(key) is not None
        and requested_resource[key] != listing_resource.get(key)
    }
    if mismatches:
        refuse(f"shape_commercially_infeasible: {mismatches}")
    return shape
