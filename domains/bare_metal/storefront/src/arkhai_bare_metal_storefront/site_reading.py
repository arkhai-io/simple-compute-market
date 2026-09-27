"""How this storefront reads one site's pools for bare-metal publication.

Publication and the opening guard both read a site's resource-pool projection
the same way, so the guard rechecks a listing against exactly the reading that
published it. Each pool's declarations resolve through the resource-pool kit's
shared reader; its region is the pool's ``region`` hint.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from arkhai_bare_metal import (
    BARE_METAL_OFFERING_MODE,
    POOL_ADMITTED,
    POOL_HELD,
    POOL_NOT_ADMITTED,
)
from market_resource_pools import read_site_declarations
from market_resource_pools.hints import raw_listing_shapes, raw_region


def _policy_tags(pool: Mapping[str, Any]) -> Mapping[str, Any]:
    # A projected pool carries its declarations under ``pool_metadata``, where
    # the resource-pool kit's reader finds them too.
    metadata = pool.get("pool_metadata")
    tags = metadata.get("policy_tags") if isinstance(metadata, Mapping) else None
    return tags if isinstance(tags, Mapping) else {}


def pool_region(policy_tags: Mapping[str, Any]) -> str | None:
    """The region a pool declares, or ``None`` when it states no usable one.

    A non-string or blank hint is no region, as VM reads it: region is
    descriptive text a buyer filters on, never a value to repair.
    """
    hint = raw_region(policy_tags)
    return hint if isinstance(hint, str) and hint.strip() else None


@dataclass(frozen=True)
class SitePoolReading:
    """One site's pools as bare-metal publication reads them.

    ``admission`` maps every named pool to how it admits bare metal.
    ``unresolvable`` names the problems of each pool whose declarations do not
    resolve; ``unbacked`` the admitted-in-all-else pools that declare no
    capacity backing; ``regionless`` the admitted pools stating no region;
    ``listing_shapes_stated`` the pools stating shapes for bare metal, which
    are not read. ``regions`` holds each pool's region, if any.
    """

    admission: Mapping[str, str]
    regions: Mapping[str, str | None]
    unresolvable: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    unbacked: tuple[str, ...] = ()
    regionless: tuple[str, ...] = ()
    listing_shapes_stated: tuple[str, ...] = ()


def read_site_pools(pools: Sequence[Mapping[str, Any]]) -> SitePoolReading:
    """Read each projected pool's bare-metal admission and region.

    A pool is admitted when it is enabled, advertises bare metal, and is
    capacity-backed; every bare-metal listing is backed, so one derived from an
    unbacked pool would publish a backing its pool contradicts. A pool whose
    declarations do not resolve is held. The region is recorded for every pool;
    classification holds an admitted pool that has none.
    """
    declarations = read_site_declarations(pools)
    admission: dict[str, str] = {}
    unbacked: list[str] = []
    for pool_id in declarations.unresolvable:
        admission[pool_id] = POOL_HELD
    for pool_id, pool in declarations.resolved.items():
        if not pool.enabled or not pool.advertises(BARE_METAL_OFFERING_MODE):
            admission[pool_id] = POOL_NOT_ADMITTED
        elif not pool.backed:
            admission[pool_id] = POOL_NOT_ADMITTED
            unbacked.append(pool_id)
        else:
            admission[pool_id] = POOL_ADMITTED
    regions: dict[str, str | None] = {}
    shapes_stated: list[str] = []
    for pool in pools:
        pool_id = pool.get("pool_id")
        if not isinstance(pool_id, str) or not pool_id:
            continue
        tags = _policy_tags(pool)
        regions[pool_id] = pool_region(tags)
        if raw_listing_shapes(tags, BARE_METAL_OFFERING_MODE) is not None:
            shapes_stated.append(pool_id)
    return SitePoolReading(
        admission=admission,
        regions=regions,
        unresolvable=dict(declarations.unresolvable),
        unbacked=tuple(sorted(unbacked)),
        regionless=tuple(
            sorted(
                pool_id
                for pool_id, state in admission.items()
                if state == POOL_ADMITTED and regions.get(pool_id) is None
            )
        ),
        listing_shapes_stated=tuple(sorted(shapes_stated)),
    )


__all__ = ["SitePoolReading", "pool_region", "read_site_pools"]
