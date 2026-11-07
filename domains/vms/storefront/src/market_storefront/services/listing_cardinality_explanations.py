"""Operator notices for pools whose projected cardinality mode needs one.

Read from the storefront's per-site projection state, which the composition
root builds once and passes in.
"""

from __future__ import annotations

from arkhai_vms_listings.listing_cardinality_mode import (
    resolve_vm_listing_cardinality_mode,
)
from market_capacity_publication import RESOURCE_POOL, SiteProjectionState


def listing_cardinality_mode_explanations(
    site_projections: SiteProjectionState,
) -> dict[str, dict[str, str]]:
    """Per-site, per-pool operator-visible notice for any pool whose
    projected `listing_cardinality_mode` needs one.

    Two distinct notices share this mapping, and a pool earns an entry for
    either: its supplied value was unrecognized and the VM domain's
    structural default was substituted, or its value was honored but
    arrived under the deprecated ingestion key. Both are things an operator
    must act on, and both name what to change; a pool carrying both
    conditions reports them together.

    A pool's absence from this mapping means nothing is owed -- the tag is
    absent under either spelling (ordinary default, nothing to explain) and
    it resolved to a recognized value -- not that its site hasn't loaded;
    a site whose resource-pool projection hasn't loaded yet simply
    contributes no pools to walk, as it contributes none to the state's
    held values more generally. Cheap and independent of full
    publication candidate generation: this only needs each pool's
    projected `policy_tags`, not pricing or availability.
    """
    result: dict[str, dict[str, str]] = {}
    for site, pools in site_projections.values(RESOURCE_POOL).items():
        if not pools:
            continue
        site_explanations: dict[str, str] = {}
        for pool in pools:
            pool_id = str(pool.get("pool_id") or "")
            if not pool_id:
                continue
            policy_tags = (pool.get("pool_metadata") or {}).get("policy_tags") or {}
            # Same structural-default rule `_projected_pool_rows` uses
            # (member_count == 1 -> specific_resource, backward
            # compatibility for an untagged pool). The default value only
            # affects a fallback message's text, not whether a notice is
            # produced, so it does not need to agree with what publication
            # would compute from live availability.
            enabled_member_count = sum(
                1
                for resource in pool.get("resources") or []
                if resource.get("enabled", True)
            )
            structural_default = (
                "specific_resource" if enabled_member_count == 1 else "fungible"
            )
            cardinality = resolve_vm_listing_cardinality_mode(
                policy_tags,
                structural_default=structural_default,
            )
            notices = [
                notice
                for notice in (
                    cardinality.fallback_explanation,
                    cardinality.deprecated_key_notice,
                )
                if notice
            ]
            if notices:
                site_explanations[pool_id] = "; ".join(notices)
        if site_explanations:
            result[site] = site_explanations
    return result
