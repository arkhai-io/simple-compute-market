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
    bare_metal_shape_digest,
    bare_metal_shape_problems,
)
from market_resource_pools import (
    AskingRateResolution,
    read_site_declarations,
    resolve_asking_rates,
)
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


def resolve_bare_metal_asking_rates(
    policy_tags: Mapping[str, Any], *, override_rates: Any = None
) -> AskingRateResolution:
    """A pool's bare-metal asking rates by shape digest: the override's, else
    the pool's, else none.

    Keyed by the digest a bare-metal listing's derivation identity uses, so an
    entry prices exactly the machines whose declared shape it names.
    """
    return resolve_asking_rates(
        policy_tags,
        BARE_METAL_OFFERING_MODE,
        override_rates=override_rates,
        shape_digest=bare_metal_shape_digest,
        shape_problems=bare_metal_shape_problems,
    )


@dataclass(frozen=True)
class SitePoolReading:
    """One site's pools as bare-metal publication reads them.

    ``admission`` maps every named pool to how it admits bare metal.
    ``unresolvable`` names the problems of each pool whose declarations do not
    resolve; ``unbacked`` the admitted-in-all-else pools that declare no
    capacity backing; ``regionless`` the admitted pools stating no region;
    ``listing_shapes_stated`` the pools stating shapes for bare metal, which
    are not read. ``regions`` holds each pool's region, if any.
    ``asking_rates`` holds each pool's resolved rates; an admitted pool whose
    rates cannot be read is held and named in ``unreadable_asking_rates``.
    """

    admission: Mapping[str, str]
    regions: Mapping[str, str | None]
    unresolvable: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    unbacked: tuple[str, ...] = ()
    regionless: tuple[str, ...] = ()
    listing_shapes_stated: tuple[str, ...] = ()
    asking_rates: Mapping[str, AskingRateResolution] = field(default_factory=dict)
    unreadable_asking_rates: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    unreadable_overrides: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def published_asking_rates(self) -> dict[str, dict[str, dict[str, str]]]:
        """Each pool's published rates by shape digest."""
        return {
            pool_id: {digest: rate.published() for digest, rate in resolution.rates.items()}
            for pool_id, resolution in self.asking_rates.items()
        }


def read_site_pools(
    pools: Sequence[Mapping[str, Any]],
    *,
    override_asking_rates: Mapping[str, Any] | None = None,
    override_problems: Mapping[str, tuple[str, ...]] | None = None,
) -> SitePoolReading:
    """Read each projected pool's bare-metal admission and region.

    A pool is admitted when it is enabled, advertises bare metal, and is
    capacity-backed; every bare-metal listing is backed, so one derived from an
    unbacked pool would publish a backing its pool contradicts. A pool whose
    declarations do not resolve is held. The region is recorded for every pool;
    classification holds an admitted pool that has none.
    ``override_asking_rates`` maps a pool to the storefront override's rate
    list; a pool it does not name takes its own declaration. Rates the domain
    cannot read hold the pool rather than falling through to a lower tier.
    ``override_problems`` names each pool whose stored override cannot be read;
    it holds an admitted pool for the same reason.
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
    asking_rates: dict[str, AskingRateResolution] = {}
    unreadable_rates: dict[str, tuple[str, ...]] = {}
    unreadable_overrides: dict[str, tuple[str, ...]] = {}
    for pool_id, problems in (override_problems or {}).items():
        if problems and admission.get(pool_id) == POOL_ADMITTED:
            admission[pool_id] = POOL_HELD
            unreadable_overrides[pool_id] = tuple(problems)
    for pool in pools:
        pool_id = pool.get("pool_id")
        if not isinstance(pool_id, str) or not pool_id:
            continue
        tags = _policy_tags(pool)
        regions[pool_id] = pool_region(tags)
        if raw_listing_shapes(tags, BARE_METAL_OFFERING_MODE) is not None:
            shapes_stated.append(pool_id)
        resolution = resolve_bare_metal_asking_rates(
            tags, override_rates=(override_asking_rates or {}).get(pool_id)
        )
        asking_rates[pool_id] = resolution
        if resolution.unreadable and admission.get(pool_id) == POOL_ADMITTED:
            admission[pool_id] = POOL_HELD
            unreadable_rates[pool_id] = tuple(
                f"{resolution.source}: {problem}" for problem in resolution.problems
            )
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
        asking_rates=asking_rates,
        unreadable_asking_rates=unreadable_rates,
        unreadable_overrides=unreadable_overrides,
    )


__all__ = [
    "SitePoolReading",
    "pool_region",
    "read_site_pools",
    "resolve_bare_metal_asking_rates",
]
