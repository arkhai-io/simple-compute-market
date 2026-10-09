"""Whether a projected source could serve the claim a VM listing would produce.

Publication asks this of every listing shape: build the capacity claim the
listing's reservation would send, and judge it with the site authority's own
exported resource-feasibility predicate, so publication and admission cannot
disagree about resource kind, dimensions, or attributes.

It is resource feasibility, not admission. The site's reservation also checks
the pool's delivery mode, its provider's host requirement, holds over the lease
window, and physical-host conflicts, none of which a projection carries. See
openspec/specs/storefront-publication/spec.md, "A listing shape is published
only where a source member is feasible for it".

The projection names things differently from the predicate's snapshot row: a
member is ``physical_resource_id`` under its pool entry's ``pool_id``, and a
capacity bucket names its attributes ``grouping_attributes``. The adapters
below map them; nothing else is inferred.
In particular a member that states no ``resource_type`` is not given one, and
reconciliation holds it before it reaches this check.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from market_site import dict_resource_satisfies_claim

from market_storefront.services.capacity_client import (
    VM_MIRROR_DIMENSION,
    VM_UNIT_CLAIM_KEYS,
)
from market_storefront.services.vm_job_spec_service import (
    compute_capacity_claim_from_order,
)

Predicate = Callable[..., bool]
ClaimBuilder = Callable[[dict[str, Any]], dict[str, Any]]


def member_snapshot_row(
    pool_id: str,
    member: Mapping[str, Any],
    *,
    use_available: bool,
) -> dict[str, Any]:
    """A projected pool member as the predicate's snapshot row.

    With ``use_available``, the member's reported availability; a member that
    reports none is unknown rather than empty and is judged on its declared
    capacity.
    """
    available = member.get("available") if use_available else None
    return {
        "resource_id": str(member.get("physical_resource_id") or ""),
        "pool_id": pool_id,
        "resource_type": member.get("resource_type"),
        "resource_subtype": member.get("resource_subtype"),
        "attributes": dict(member.get("attributes") or {}),
        "available": dict(available if available is not None else member.get("capacity") or {}),
    }


def bucket_snapshot_row(bucket: Mapping[str, Any]) -> dict[str, Any]:
    """A capacity bucket as the predicate's snapshot row.

    A bucket stands for members with identical availability and names none of
    them, so it can answer only a claim that pins no resource.
    """
    return {
        "resource_id": "",
        "pool_id": str(bucket.get("pool_id") or ""),
        "resource_type": bucket.get("resource_type"),
        "resource_subtype": bucket.get("resource_subtype"),
        "attributes": dict(bucket.get("grouping_attributes") or {}),
        "available": dict(bucket.get("available") or {}),
    }


class SiteShapeFeasibility:
    """Judge listing shapes with the site's claim semantics."""

    def __init__(
        self,
        *,
        predicate: Predicate = dict_resource_satisfies_claim,
        claim_builder: ClaimBuilder = compute_capacity_claim_from_order,
        unit_claim_keys: Sequence[str] = VM_UNIT_CLAIM_KEYS,
        mirror_dimension: str = VM_MIRROR_DIMENSION,
    ) -> None:
        self._predicate = predicate
        self._claim_builder = claim_builder
        self._unit_claim_keys = tuple(unit_claim_keys)
        self._mirror_dimension = mirror_dimension

    def claim(self, listing_resource: Mapping[str, Any]) -> dict[str, Any]:
        """The capacity claim a listing with these fields would reserve with."""
        return self._claim_builder({"listing_resource": dict(listing_resource)})

    def _judge(self, row: Mapping[str, Any], listing_resource: Mapping[str, Any]) -> bool:
        return self._predicate(
            row,
            self.claim(listing_resource),
            unit_claim_keys=self._unit_claim_keys,
            mirror_dimension=self._mirror_dimension,
        )

    def member_feasible(
        self,
        listing_resource: Mapping[str, Any],
        *,
        pool_id: str,
        member: Mapping[str, Any],
        use_available: bool,
    ) -> bool:
        return self._judge(
            member_snapshot_row(pool_id, member, use_available=use_available),
            listing_resource,
        )

    def bucket_feasible(
        self,
        listing_resource: Mapping[str, Any],
        *,
        bucket: Mapping[str, Any],
    ) -> bool:
        return self._judge(bucket_snapshot_row(bucket), listing_resource)


_DEFAULT = SiteShapeFeasibility()


def vm_shape_feasibility() -> SiteShapeFeasibility:
    """The storefront's feasibility judge, composed with the VM claim semantics."""
    return _DEFAULT


__all__ = [
    "SiteShapeFeasibility",
    "bucket_snapshot_row",
    "member_snapshot_row",
    "vm_shape_feasibility",
]
