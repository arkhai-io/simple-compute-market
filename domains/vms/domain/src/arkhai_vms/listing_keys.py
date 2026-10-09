"""Structural keys of VM listings.

A key names what a listing sells: the site, the pool or specific resource it is
drawn from, and its listing shape by digest. Site, pool, and resource identifiers
are operator-chosen, so each is length-prefixed and no identifier can run into
the next. Stored listings are found by these exact strings, so their byte form is
fixed.

A listing bound before shapes was keyed by GPU count instead. Those keys are
still read, to recognise such listings, and never derived for a new one.
"""

from __future__ import annotations

from typing import Any

from market_core.identifier_encoding import length_prefixed


def _required_site(site_id: str) -> str:
    if not site_id or not site_id.strip():
        raise ValueError("site_id must be non-empty")
    return site_id


def _required_gpu_count(gpu_count: Any) -> int:
    if isinstance(gpu_count, bool) or not isinstance(gpu_count, int) or gpu_count <= 0:
        raise ValueError(f"gpu_count must be a positive integer, not {gpu_count!r}")
    return gpu_count


def listing_shape_key(
    site_id: str,
    *,
    shape_digest: str,
    pool_id: str | None = None,
    resource_id: str | None = None,
) -> str:
    """The key of one listing shape from a pool or a specific resource.

    A resource names a specific-resource listing and takes precedence over its
    pool, as it does in the capacity claim. The shape enters by digest, so which
    source produced the shape never changes the key.
    """
    _required_site(site_id)
    if not shape_digest:
        raise ValueError("shape_digest must be non-empty")
    if resource_id:
        return f"{length_prefixed(site_id)}:{length_prefixed(resource_id)}:shape:{shape_digest}"
    if pool_id:
        return f"pool:{length_prefixed(site_id)}:{length_prefixed(pool_id)}:shape:{shape_digest}"
    raise ValueError("a listing shape key needs a pool or a resource")


def listing_resource_key(site_id: str, resource_id: str, gpu_count: int) -> str:
    """The key a specific-resource listing bound before shapes occupies."""
    _required_site(site_id)
    return (
        f"{length_prefixed(site_id)}:{length_prefixed(resource_id)}"
        f":gpus:{_required_gpu_count(gpu_count)}"
    )


def listing_pool_key(site_id: str, pool_id: str, gpu_count: int) -> str:
    """The key a fungible-pool listing bound before shapes occupies."""
    _required_site(site_id)
    return (
        f"pool:{length_prefixed(site_id)}:{length_prefixed(pool_id)}"
        f":gpus:{_required_gpu_count(gpu_count)}"
    )


__all__ = ["listing_pool_key", "listing_resource_key", "listing_shape_key"]
