"""VM-domain interpretation of the domain-neutral `region`/`sla` hints.

`kit/resource-pools.hints` owns the key names and generic reads; this
module owns how the VM domain resolves them against the storefront's own
local fallback/override data (`compute_capacity_pools.region`/`.sla`,
the storefront-side override tier -- see `resolve_sla` below).

Region and SLA are treated differently on purpose. Region is a plain fact
about where hardware sits -- no storefront override makes sense, since a
storefront claiming a different physical location than the truth would be
actively misleading. SLA has a real commercial/promise dimension: it gets
a storefront-side override *and* a storefront-wide trust gate deciding
whether a pool's own declared SLA is consulted at all, since some
storefronts legitimately never want to publish a site's self-reported SLA
claim, independent of whether any specific pool happens to have one.
"""

from __future__ import annotations

from typing import Any, Mapping


def resolve_region(policy_tags: Mapping[str, Any], *, fallback: str | None) -> str | None:
    """The pool's region: its declared hint if present, else ``fallback``
    (the storefront's local `compute_capacity_pools.region` value).

    A non-string or empty hint is treated the same as an absent one --
    region is meant to be human-readable descriptive text, not a value a
    consumer needs to further interpret, so anything that isn't usable
    text falls back rather than propagating a malformed value.
    """
    # Local import -- see resolve_vm_listing_mode's own comment in
    # domains.vms.listings.listing_mode for the reason (kept out of any
    # consumer that imports this module's signatures without calling it).
    from market_resource_pools.hints import raw_region

    hint = raw_region(policy_tags)
    if isinstance(hint, str) and hint:
        return hint
    return fallback


def resolve_sla(
    policy_tags: Mapping[str, Any],
    *,
    accept_pool_declared_sla: bool,
    storefront_override: float | None,
    config_default: float,
) -> float:
    """Resolve a pool's advertised SLA through the three-tier precedence:
    a per-pool storefront override (highest), a pool-declared hint
    (middle, only ever consulted when ``accept_pool_declared_sla`` is
    true), and the storefront's own configured default (lowest).

    ``storefront_override`` is the storefront operator's explicit
    per-pool value (from `compute_capacity_pools.sla`) if one is set,
    else ``None`` -- callers must pass ``None``, not ``0``, to mean "not
    set," since 0 is itself a meaningful (if extreme) SLA value.

    ``accept_pool_declared_sla`` gates the *entire* middle tier, not just
    a single pool's use of it -- when false, a pool's own claim is never
    read here, regardless of whether that specific pool has one, matching
    the storefront-wide trust decision this gate represents rather than a
    per-pool one (that's what the override tier is for).
    """
    if storefront_override is not None:
        return storefront_override
    if accept_pool_declared_sla:
        # Local import -- same reason as resolve_region, above.
        from market_resource_pools.hints import sla_value

        hint = sla_value(policy_tags)
        if hint is not None:
            return hint
    return config_default
