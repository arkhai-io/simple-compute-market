"""Quota-backed listing reconciliation.

An API-credits listing derives from a quota resource in the tokens
service's ledger the way a VM derived listing derives from a pool
member. The reconciliation rule is simpler than the VM one because a
listing has no per-listing unit slice: it stays open while its quota
resource has any sellable units and closes on exhaustion (capacity
deltas from the event poller trigger the check; buyers pick the
quantity per deal, and the quota guard enforces the per-deal bound).

Pure functions over listing rows + an availability view so the
storefront's persistence stays out of the concept module.
"""

from __future__ import annotations

from typing import Any, Mapping

from domains.apicredits.listings.models import (
    coerce_resource_dict,
    resource_is_api_credits,
)

AvailabilityView = Mapping[tuple[str, str], int]
"""Available units keyed by exact trusted ``(site_id, resource_id)``."""


def listing_quota_resource_id(listing_row: Mapping[str, Any]) -> str | None:
    """The quota resource a credit listing derives from, if it names one."""
    offer = coerce_resource_dict(listing_row.get("offer_resource"))
    if offer.get("kind") != "api_credits.v1":
        return None
    resource_id = offer.get("resource_id")
    return str(resource_id) if resource_id else None

def listing_capacity_site_id(listing_row: Mapping[str, Any]) -> str | None:
    offer = coerce_resource_dict(listing_row.get("offer_resource"))
    site_id = offer.get("capacity_site_id")
    return str(site_id) if site_id else None


def _available_units(
    availability: AvailabilityView | None,
    site_id: str,
    resource_id: str,
) -> int | None:
    if availability is None:
        return None
    return availability.get((site_id, resource_id))


def stale_open_credit_listing_ids(
    listing_rows: list[Mapping[str, Any]],
    *,
    availability: AvailabilityView | None,
) -> list[str]:
    """Open credit listings whose quota resource is exhausted.

    ``availability=None`` (authority unreachable) closes nothing — the
    next delta/reconcile converges. A resource missing from the view is
    treated as exhausted: the ledger is the source of sellable truth,
    and a listing whose backing resource is gone must not stay open.
    """
    if availability is None:
        return []
    stale: list[str] = []
    for row in listing_rows:
        if (row.get("status") or "").strip() != "open":
            continue
        resource_id = listing_quota_resource_id(row)
        site_id = listing_capacity_site_id(row)
        if not resource_id or not site_id:
            continue
        available = _available_units(availability, site_id, resource_id)
        if available is None or available < 1:
            stale.append(str(row["listing_id"]))
    return stale


def reopenable_credit_listing_ids(
    listing_rows: list[Mapping[str, Any]],
    *,
    availability: AvailabilityView | None,
) -> list[str]:
    """Closed credit listings whose quota resource has units again.

    ``availability=None`` reopens nothing: with no consumption
    information everything would look free, and reopening on ignorance
    over-sells (same rule as the VM reconciler).
    """
    if availability is None:
        return []
    reopenable: list[str] = []
    for row in listing_rows:
        if (row.get("status") or "").strip() != "closed":
            continue
        resource_id = listing_quota_resource_id(row)
        site_id = listing_capacity_site_id(row)
        if not resource_id or not site_id:
            continue
        available = _available_units(availability, site_id, resource_id)
        if available is not None and available >= 1:
            reopenable.append(str(row["listing_id"]))
    return reopenable


def resource_is_api_credits_listing(listing_row: Mapping[str, Any]) -> bool:
    """Whether a listing row offers API credits."""
    return resource_is_api_credits(listing_row.get("offer_resource"))
