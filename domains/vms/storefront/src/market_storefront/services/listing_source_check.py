"""Check a listing against its own source, for the seller's inventory guard.

The check asks two questions about one listing: does its source still declare
what it publishes, and — where the listing's backing says availability bounds
it — is the published quantity free at its own site. Both are answered from a
fresh derivation of the listing's own site and pool, never from capacity
elsewhere, using the same derivation publication uses, so every published field
resolves exactly as it did when the listing was derived. The binding's backing
delegate decides whether the second question is asked at all, so a listing
availability does not bound makes no availability call.

It answers with the policy kit's ``ListingSourceVerdict``, which the negotiation
runtime enforces before every seller decision and every acceptance. Only a
freshly confirmed projection confirms the listing: every family the check reads
must have been confirmed by a successful poll within the storefront's
source-confirmation window. Every listing reads the resource-pool family; a
fungible listing also reads the capacity-bucket family, from which its
availability is computed, while a listing bound to one resource does not. A
family that is not held, whose latest poll failed, or whose last confirmation
is older than the window cannot confirm the listing, which is retryable rather
than a mismatch. Publication reads the same held generations
without this rule, because holding listings through an outage is its job.

See openspec/specs/storefront-publication/spec.md, "The seller's inventory guard
checks a listing against its own source".
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from arkhai_vms_listings.listing_comparison import REFUSE, compare_listing
from arkhai_vms_listings.reconciler import (
    PoolHintResolutionSettings,
    ShapeFeasibility,
    available_compute_slices,
    slice_identity,
    stored_listing_key,
)
from market_capacity_publication import (
    CAPACITY_BUCKET,
    RESOURCE_POOL,
    CapacityBindingError,
    SiteProjectionState,
    freshly_confirmed,
)
from market_policy.listing_source import ListingSourceVerdict
from market_resource_pools_contracts.backing import capacity_backing

import market_storefront.container as container
from market_storefront.services.capacity_client import (
    site_capacity_buckets,
    site_pool_projection,
)
from market_storefront.services.shape_feasibility import vm_shape_feasibility
from market_storefront.utils.config import source_confirmation_seconds

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
    projection: Mapping[str, list[dict[str, Any]]], site_id: str
) -> dict[str, list[dict[str, Any]]] | None:
    """One site's slice of a projection, or ``None`` when that site's is unknown.

    A site whose projection has not loaded is unknown, not empty: reading it as
    an empty list would say the site declares nothing, or has nothing free.
    """
    if site_id not in projection:
        return None
    return {site_id: list(projection[site_id])}


def _unconfirmed(
    site_projections: SiteProjectionState,
    site_id: str,
    *,
    reads_buckets: bool,
    now: datetime,
    window_seconds: float,
) -> str | None:
    """Why the site's projections cannot confirm a listing now, or ``None``.

    The resource-pool family is always read, and the capacity-bucket family
    when ``reads_buckets``. Every site holds both families, so a bucket family
    with no generation is not held and confirms nothing; nor is a stale one
    dropped in favour of the pool rows, which would make what is computed
    depend on freshness.
    """
    try:
        read = [(RESOURCE_POOL, site_projections.view(site_id, RESOURCE_POOL))]
        if reads_buckets:
            read.append((CAPACITY_BUCKET, site_projections.view(site_id, CAPACITY_BUCKET)))
    except CapacityBindingError:
        return f"site {site_id!r} is not a configured capacity site"
    for family, view in read:
        if view.value is None:
            # Nothing can confirm the declaration the listing was derived from.
            return f"site {site_id!r} {family} projection is not loaded"
        if not freshly_confirmed(view, now=now, window_seconds=window_seconds):
            confirmed = view.fetched_at.isoformat() if view.fetched_at else "never"
            return (
                f"site {site_id!r} {family} projection is not freshly confirmed "
                f"(state {view.state.value}, last confirmed {confirmed}, "
                f"window {window_seconds:g}s)"
            )
    return None


def _slices_by_key(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["resource_key"]): row for row in rows if row.get("resource_key")}


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
    site_projections: SiteProjectionState,
    shape_feasible: ShapeFeasibility | None = None,
    confirmation_window_seconds: float | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ListingSourceVerdict:
    """Check one listing against its own source.

    Both questions use the same shape feasibility publication does: the
    declared match asks whether the listing's own source is still feasible for
    its shape on declared capacity, and availability whether it is feasible now,
    where the binding's backing says availability bounds it. A declared mismatch is
    logged with the fields that differ, because the buyer's refusal carries only
    its reason.

    ``confirmation_window_seconds`` defaults to the configured
    source-confirmation window, and ``clock`` -- the time a confirmation's age
    is measured at -- to the current UTC time.
    """
    verdict = await _check_listing_source(
        repository=repository,
        listing_record=listing_record,
        binding=binding,
        capacity_runtime=capacity_runtime,
        site_projections=site_projections,
        shape_feasible=shape_feasible or vm_shape_feasibility(),
        window_seconds=(
            source_confirmation_seconds()
            if confirmation_window_seconds is None
            else confirmation_window_seconds
        ),
        now=(clock or _utc_now)(),
    )
    if verdict.outcome == "declared_mismatch":
        logger.warning(
            "[GUARD] listing %s does not match its source at site %s (%s): %s",
            listing_record.get("listing_id"),
            binding.site_id,
            getattr(binding, "source_id", None),
            list(verdict.differing_fields),
        )
    return verdict


async def _check_listing_source(
    *,
    repository: Any,
    listing_record: Mapping[str, Any],
    binding: Any,
    capacity_runtime: Any,
    site_projections: SiteProjectionState,
    shape_feasible: ShapeFeasibility,
    window_seconds: float,
    now: datetime,
) -> ListingSourceVerdict:
    site_id = binding.site_id
    stored = stored_listing_resource(listing_record)
    # The listing's key comes from its durable binding, never its published fields.
    recorded = await repository.load_listing_binding(
        listing_id=str(listing_record.get("listing_id"))
    )
    key = stored_listing_key(
        recorded.source_envelope_json if recorded is not None else None, stored, site_id
    )
    # A listing bound to one resource is an exact listing, whose availability
    # is that resource's; a fungible listing's is computed from the site's
    # capacity buckets.
    fungible = recorded is None or recorded.physical_resource_id is None
    # Judged and then read with nothing awaited between, so the generations
    # derived from are the ones just confirmed, and a confirmed family is held.
    unconfirmed = _unconfirmed(
        site_projections,
        site_id,
        reads_buckets=fungible,
        now=now,
        window_seconds=window_seconds,
    )
    if unconfirmed is not None:
        return ListingSourceVerdict("unverifiable", unconfirmed)
    projection = _site_only(site_pool_projection(site_projections), site_id)
    buckets = (
        _site_only(site_capacity_buckets(site_projections), site_id) if fungible else None
    )
    # Only the admissibility default affects which listings derive; the
    # terms these settings also carry are discarded by the comparison below.
    admissibility = PoolHintResolutionSettings(
        admissibility_default=container.resolved_admissibility_default
    )

    async def declared() -> ListingSourceVerdict | None:
        slices = _slices_by_key(
            available_compute_slices(
                repository.db_path,
                member_availability=None,
                site_pool_projection=projection,
                site_capacity_buckets=buckets,
                declared_range=True,
                hint_resolution=admissibility,
                shape_feasible=shape_feasible,
            )
        )
        fresh = slices.get(key) if key is not None else None
        if fresh is None:
            return ListingSourceVerdict(
                "declared_mismatch", "the listing's source is absent", ("source",)
            )
        comparison = compare_listing(
            stored_resource=stored,
            stored_terms={},
            fresh_resource=slice_identity(fresh),
            fresh_terms={},
            binding_backing=binding.backing,
            source_backing=capacity_backing(fresh.get("capacity_backing")),
        )
        if comparison.outcome in REFUSE:
            return ListingSourceVerdict(
                "declared_mismatch",
                "the listing differs from its source",
                tuple(comparison.differing_fields),
            )
        return None

    async def available() -> ListingSourceVerdict | None:
        try:
            member_availability = await _pinned_site_availability(
                capacity_runtime, site_id
            )
        except Exception as exc:  # noqa: BLE001 - any failure leaves the source unknown
            return ListingSourceVerdict(
                "unverifiable", f"site {site_id!r} capacity could not be read: {exc}"
            )
        available_rows = available_compute_slices(
            repository.db_path,
            member_availability=member_availability,
            site_pool_projection=projection,
            site_capacity_buckets=buckets,
            hint_resolution=admissibility,
            shape_feasible=shape_feasible,
        )
        if key not in _slices_by_key(available_rows):
            return ListingSourceVerdict(
                "unavailable", "the published quantity is not free"
            )
        return None

    verdict = await binding.backing.judge_async(declared, available)
    return verdict if verdict is not None else ListingSourceVerdict("matches")


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = ["check_listing_source", "stored_listing_resource"]
