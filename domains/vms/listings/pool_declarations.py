"""Read the advertisement, backing, and enablement a site declares for its pools.

The storefront reads these declarations live from each site's resource-pool
projection and never caches them. One site's projection generation is judged as a
whole, because whether an absent tag is a defect depends on whether its producer
emits the tags at all:

- A generation in which no pool carries either the advertisement or the backing
  declaration comes from a producer that predates them. Every pool in it reads as
  capacity-backed, with its delivery declaration serving as advertisement
  authorization. That reproduces the contract that applied before the declarations
  existed; it is not a default applied to a pool that omitted something.
- In any other generation, a pool whose declarations are absent, malformed, or
  violate a cross-declaration rule is unresolvable. It yields no new listing, and
  the listings already derived from it are held — neither closed nor refreshed —
  because an unknown declaration is not a withdrawn one.

See openspec/specs/storefront-publication/spec.md, "Backing is declared by the
projected pool".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from market_resource_pools import (
    ADVERTISABLE_MODES_POLICY_TAG,
    CAPACITY_BACKED,
    CAPACITY_BACKING_POLICY_TAG,
    PoolDeclarationError,
    declared_deliverable_modes,
    resolve_pool_declarations,
)

# Problem codes this module adds to the resource-pool resolver's own.
POOL_ENABLEMENT_UNDECLARED = "pool_enablement_undeclared"


@dataclass(frozen=True)
class ResolvedPool:
    """A pool whose declarations resolved."""

    capacity_backing: str
    advertisable_modes: frozenset[str]
    enabled: bool

    @property
    def backed(self) -> bool:
        return self.capacity_backing == CAPACITY_BACKED

    def advertises(self, offering_mode: str) -> bool:
        return offering_mode in self.advertisable_modes


@dataclass(frozen=True)
class SiteDeclarations:
    """One site generation's reading: resolved and unresolvable pools."""

    compatibility_rule: bool
    resolved: Mapping[str, ResolvedPool] = field(default_factory=dict)
    unresolvable: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


def _policy_tags(pool: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = pool.get("pool_metadata") or {}
    tags = metadata.get("policy_tags") if isinstance(metadata, Mapping) else None
    return tags if isinstance(tags, Mapping) else {}


def _declares_either(pool: Mapping[str, Any]) -> bool:
    tags = _policy_tags(pool)
    return (
        ADVERTISABLE_MODES_POLICY_TAG in tags or CAPACITY_BACKING_POLICY_TAG in tags
    )


def _enablement(
    pool: Mapping[str, Any], *, compatibility_rule: bool
) -> bool | None:
    """The pool's declared enablement, or ``None`` when it cannot be read.

    A producer predating the declarations may project no pool metadata at all,
    and enablement was not read under that contract, so absence there is not a
    disablement. A current producer always projects it.
    """
    metadata = pool.get("pool_metadata")
    enabled = metadata.get("enabled") if isinstance(metadata, Mapping) else None
    if isinstance(enabled, bool):
        return enabled
    return True if compatibility_rule else None


def read_site_declarations(pools: Sequence[Mapping[str, Any]]) -> SiteDeclarations:
    """Resolve every pool in one site's projection generation."""
    compatibility_rule = not any(_declares_either(pool) for pool in pools)
    resolved: dict[str, ResolvedPool] = {}
    unresolvable: dict[str, tuple[str, ...]] = {}
    for pool in pools:
        pool_id = str(pool.get("resource_pool_id") or "").strip()
        if not pool_id:
            continue
        tags = _policy_tags(pool)
        enabled = _enablement(pool, compatibility_rule=compatibility_rule)
        if enabled is None:
            unresolvable[pool_id] = (POOL_ENABLEMENT_UNDECLARED,)
            continue
        if compatibility_rule:
            try:
                advertisable = declared_deliverable_modes(tags)
            except ValueError:
                unresolvable[pool_id] = ("invalid_deliverable_modes",)
                continue
            resolved[pool_id] = ResolvedPool(CAPACITY_BACKED, advertisable, enabled)
            continue
        try:
            declarations = resolve_pool_declarations(tags)
        except PoolDeclarationError as exc:
            unresolvable[pool_id] = tuple(problem.code for problem in exc.problems)
            continue
        resolved[pool_id] = ResolvedPool(
            str(declarations.capacity_backing),
            frozenset(declarations.advertisable_modes),
            enabled,
        )
    return SiteDeclarations(compatibility_rule, resolved, unresolvable)


__all__ = [
    "POOL_ENABLEMENT_UNDECLARED",
    "ResolvedPool",
    "SiteDeclarations",
    "read_site_declarations",
]
