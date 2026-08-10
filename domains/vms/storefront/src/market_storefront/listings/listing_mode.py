"""VM-domain interpretation of the domain-neutral `listing_mode` hint.

`kit/resource-pools.hints` owns the key name and generic read; this module
owns what the VM domain accepts and what it structurally defaults to when
the tag is absent or unrecognized. Unknown values remain forward-compatible
opaque metadata rather than a validation failure -- no other package
encodes VM's specific accepted values.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

VmListingMode = Literal["fungible", "specific_resource"]

_VM_LISTING_MODES: tuple[VmListingMode, ...] = ("fungible", "specific_resource")


def resolve_vm_listing_mode(
    policy_tags: Mapping[str, Any],
    *,
    structural_default: VmListingMode,
) -> tuple[VmListingMode, str | None]:
    """Resolve a pool's `listing_mode` for VM publication.

    ``structural_default`` is the mode this pool would have gotten before
    `listing_mode` existed as an explicit tag -- callers pass "specific_resource"
    for a pool with exactly one enabled member and "fungible" otherwise,
    matching `available_compute_slices`' own pre-existing `member_count == 1`
    heuristic. This preserves backward compatibility for any pool projected
    without `pool_metadata`/`policy_tags` at all (an older producer, or one
    that simply hasn't been tagged) -- the caller must not hardcode one
    constant default regardless of member count, or a single-member pool
    that always resolved to a specific-resource listing would silently
    start publishing fungible (pool-keyed) listings instead the moment this
    resolver is wired in, breaking every existing derived-listing mapping
    keyed on that resource's identity.

    Returns ``(mode, explanation)``. ``explanation`` is ``None`` unless the
    raw tag was present but unrecognized, in which case ``structural_default``
    is used and the explanation is meant to be surfaced on an operator-visible
    status surface (never fails projection ingestion or blocks publication).
    """
    # Local import: `market_resource_pools` stays out of any consumer that
    # merely imports this module's types/signatures without ever calling
    # this resolver (e.g. `market_storefront.listings.reconciler` importing
    # `resolve_vm_listing_mode` at its own module level) -- notably the
    # buyer distribution, which imports `market_storefront.listings` for
    # unrelated helpers and has no reason to depend on `kit/resource-pools`.
    from market_resource_pools.hints import raw_listing_mode

    raw = raw_listing_mode(policy_tags)
    if raw is None:
        return structural_default, None
    if raw in _VM_LISTING_MODES:
        return raw, None  # type: ignore[return-value]
    return (
        structural_default,
        f"unrecognized listing_mode {raw!r}, using {structural_default!r}",
    )
