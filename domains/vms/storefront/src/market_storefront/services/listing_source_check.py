"""Check a listing against its own source, for the seller's inventory guard.

The guard asks two questions about one listing: does its source still declare
what it publishes, and — for a capacity-backed listing only — is the published
quantity free at its own site. Both are answered from a fresh derivation of the
listing's own site and pool or Physical Resource, never from capacity elsewhere,
using the same derivation publication uses, so whether a published field came
from site data or a local fallback is resolved exactly as it was when the
listing was derived. An unbacked listing makes no site call.

See openspec/specs/storefront-publication/spec.md, "The seller's inventory guard
checks a listing against its own source".
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from domains.vms.listings.listing_comparison import REFUSE, compare_listing
from domains.vms.listings.reconciler import (
    available_compute_slices,
    slice_identity,
    stored_listing_key,
)
from market_capacity_publication import CapacityBinding

from market_storefront.services.capacity_client import (
    listing_source_projection,
    site_capacity_buckets,
)

logger = logging.getLogger(__name__)


def stored_listing_resource(listing_record: Mapping[str, Any]) -> dict[str, Any]:
    """A stored listing's published shape as a mapping, however it was loaded."""
    raw = listing_record.get("listing_resource")
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump(mode="json")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return dict(raw) if isinstance(raw, Mapping) else {}


def _site_only(
    projection: Mapping[str, list[dict[str, Any]]] | None, site_id: str
) -> dict[str, list[dict[str, Any]]] | None:
    """One site's slice of a projection, or ``None`` when that site's is unknown.

    A site whose projection has not loaded is unknown, not empty: reading it as
    an empty list would say the site declares nothing, or has nothing free.
    """
    if projection is None or site_id not in projection:
        return None
    return {site_id: list(projection[site_id])}


def _slices_by_key(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        for field in ("resource_key", "legacy_resource_key"):
            if row.get(field):
                out[str(row[field])] = row
    return out


async def _pinned_site_availability(
    capacity_runtime: Any, site_id: str
) -> dict[tuple[str, str], int]:
    """Availability from the listing's own site only."""
    rows = await capacity_runtime.site_client(site_id).snapshot()
    view: dict[tuple[str, str], int] = {}
    for row in rows or []:
        resource_id = row.get("resource_id")
        available = row.get("available_units")
        if isinstance(resource_id, str) and resource_id.strip() and available is not None:
            view[(site_id, resource_id)] = max(int(available), 0)
    return view


async def check_listing_source(
    *,
    repository: Any,
    listing_record: Mapping[str, Any],
    binding: Any,
    capacity_runtime: Any,
) -> dict[str, Any]:
    """Return ``declared_match``, the differing fields, and ``available``.

    ``available`` is ``None`` for an unbacked listing, which has no
    availability to consult. A declared mismatch is logged with the fields
    that differ, because the buyer's refusal carries only its reason.
    """
    result = await _check_listing_source(
        repository=repository,
        listing_record=listing_record,
        binding=binding,
        capacity_runtime=capacity_runtime,
    )
    if not result["declared_match"]:
        logger.warning(
            "[GUARD] listing %s does not match its source at site %s (%s): %s",
            listing_record.get("listing_id"),
            binding.site_id,
            getattr(binding, "source_id", None),
            result["differing_fields"],
        )
    return result


async def _check_listing_source(
    *,
    repository: Any,
    listing_record: Mapping[str, Any],
    binding: Any,
    capacity_runtime: Any,
) -> dict[str, Any]:
    site_id = binding.site_id
    stored = stored_listing_resource(listing_record)
    key = stored_listing_key(stored, site_id)
    source_projection = listing_source_projection()
    projection = _site_only(source_projection, site_id)
    if source_projection is not None and projection is None:
        # Listings derive from site projections, and this site's has not
        # loaded: nothing can confirm the declaration, and the local tables are
        # not this listing's source.
        return {
            "declared_match": False,
            "differing_fields": ["source_unavailable"],
            "available": None,
        }
    buckets = _site_only(site_capacity_buckets(), site_id) if projection else None
    declared = _slices_by_key(
        available_compute_slices(
            repository.db_path,
            home_site=site_id,
            member_availability=None,
            site_pool_projection=projection,
            site_capacity_buckets=buckets,
            declared_range=True,
        )
    )
    fresh = declared.get(key) if key is not None else None
    if fresh is None:
        return {"declared_match": False, "differing_fields": ["source"], "available": None}
    comparison = compare_listing(
        stored_resource=stored,
        stored_terms={},
        fresh_resource=slice_identity(fresh),
        fresh_terms={},
        binding_backing=binding.capacity_backing,
        source_backing=str(fresh.get("capacity_backing")),
    )
    if comparison.outcome in REFUSE:
        return {
            "declared_match": False,
            "differing_fields": list(comparison.differing_fields),
            "available": None,
        }
    if not isinstance(binding, CapacityBinding):
        return {"declared_match": True, "differing_fields": [], "available": None}
    available_rows = available_compute_slices(
        repository.db_path,
        home_site=site_id,
        member_availability=await _pinned_site_availability(capacity_runtime, site_id),
        site_pool_projection=projection,
        site_capacity_buckets=buckets,
    )
    return {
        "declared_match": True,
        "differing_fields": [],
        "available": key in _slices_by_key(available_rows),
    }


__all__ = ["check_listing_source", "stored_listing_resource"]
