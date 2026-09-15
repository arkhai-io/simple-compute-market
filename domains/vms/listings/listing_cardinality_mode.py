"""VM-domain interpretation of the domain-neutral `listing_cardinality_mode` hint.

`kit/resource-pools.hints` owns the key name and generic read; this module
owns what the VM domain accepts and what it structurally defaults to when
the tag is absent or unrecognized. Unknown values remain forward-compatible
opaque metadata rather than a validation failure -- no other package
encodes VM's specific accepted values.

The hint's scope is cardinality: how many listing candidates a pool yields
and how each is independently identified. A value describing what is
offered, how a deal settles, or whether an admission authority backs the
listing is out of scope for it. See
`openspec/specs/storefront-publication/spec.md#domain-owned-publication-and-hold-hints`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

VmListingCardinalityMode = Literal["fungible", "specific_resource"]

_VM_LISTING_CARDINALITY_MODES: tuple[VmListingCardinalityMode, ...] = (
    "fungible",
    "specific_resource",
)


@dataclass(frozen=True)
class VmListingCardinalityResolution:
    """A resolved cardinality plus the two operator notices it may owe.

    The notices are separate fields rather than one message because they
    mean opposite things to an operator: ``fallback_explanation`` says the
    pool's declared value was not usable and a default was substituted,
    while ``deprecated_key_notice`` says the declared value *was* honored
    but arrived under a key that will stop being read. Merging them into
    one channel would report an old-but-correct pool as misconfigured.
    """

    mode: VmListingCardinalityMode
    fallback_explanation: str | None = None
    deprecated_key_notice: str | None = None


def resolve_vm_listing_cardinality_mode(
    policy_tags: Mapping[str, Any],
    *,
    structural_default: VmListingCardinalityMode,
) -> VmListingCardinalityResolution:
    """Resolve a pool's `listing_cardinality_mode` for VM publication.

    ``structural_default`` is the mode this pool would have gotten before the
    hint existed as an explicit tag -- callers pass "specific_resource"
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

    A value supplied under the deprecated key resolves normally and carries
    a notice; it must not fall through to ``structural_default``, because
    the key is optional and a producer that has not been upgraded would
    otherwise be silently reclassified rather than refused.
    """
    # Local import: `market_resource_pools` stays out of any consumer that
    # merely imports this module's types/signatures without ever calling
    # this resolver (e.g. `domains.vms.listings.reconciler` importing the
    # resolver at its own module level) -- notably the buyer distribution,
    # which imports `domains.vms.listings` for unrelated helpers and has no
    # reason to depend on `kit/resource-pools`.
    from market_resource_pools.hints import (
        DEPRECATED_LISTING_MODE_POLICY_TAG,
        LISTING_CARDINALITY_MODE_POLICY_TAG,
        listing_cardinality_mode_source,
        raw_listing_cardinality_mode,
    )

    raw = raw_listing_cardinality_mode(policy_tags)
    if raw is None:
        # Absence is the encoding for "no cardinality question applies", so
        # the fallback is silent here and explained only when a value was
        # actually supplied and rejected.
        return VmListingCardinalityResolution(mode=structural_default)

    took_deprecated_key = (
        listing_cardinality_mode_source(policy_tags)
        == DEPRECATED_LISTING_MODE_POLICY_TAG
    )
    notice = (
        f"pool declares {DEPRECATED_LISTING_MODE_POLICY_TAG!r}; "
        f"rename it to {LISTING_CARDINALITY_MODE_POLICY_TAG!r}"
        if took_deprecated_key
        else None
    )

    if raw in _VM_LISTING_CARDINALITY_MODES:
        return VmListingCardinalityResolution(
            mode=raw,  # type: ignore[arg-type]
            deprecated_key_notice=notice,
        )
    return VmListingCardinalityResolution(
        mode=structural_default,
        fallback_explanation=(
            f"unrecognized {LISTING_CARDINALITY_MODE_POLICY_TAG} {raw!r}, "
            f"using {structural_default!r}"
        ),
        deprecated_key_notice=notice,
    )
