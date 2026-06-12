"""Quota-backed listing reconciliation.

An API-tokens listing derives from a quota resource in the tokens
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

from domains.apitokens.listings.models import (
    coerce_resource_dict,
    resource_is_api_tokens,
)

AvailabilityView = Mapping[tuple[str | None, str], int]
"""Available units keyed ``(site, resource_id)`` — the aggregator's
member key; ``(None, rid)`` matches home-site resources."""


def listing_quota_resource_id(listing_row: Mapping[str, Any]) -> str | None:
    """The quota resource a token listing derives from, if it names one."""
    offer = coerce_resource_dict(listing_row.get("offer_resource"))
    if offer.get("kind") != "api_tokens.v1":
        return None
    resource_id = offer.get("resource_id")
    return str(resource_id) if resource_id else None


def _available_units(
    availability: AvailabilityView | None,
    resource_id: str,
) -> int | None:
    """Best available count for a resource across sites; None = unknown."""
    if availability is None:
        return None
    best: int | None = None
    for (site, rid), units in availability.items():
        if rid == resource_id:
            best = units if best is None else max(best, units)
    return best


def stale_open_token_listing_ids(
    listing_rows: list[Mapping[str, Any]],
    *,
    availability: AvailabilityView | None,
) -> list[str]:
    """Open token listings whose quota resource is exhausted.

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
        if not resource_id:
            continue
        available = _available_units(availability, resource_id)
        if available is None or available < 1:
            stale.append(str(row["listing_id"]))
    return stale


def reopenable_token_listing_ids(
    listing_rows: list[Mapping[str, Any]],
    *,
    availability: AvailabilityView | None,
) -> list[str]:
    """Closed token listings whose quota resource has units again.

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
        if not resource_id:
            continue
        available = _available_units(availability, resource_id)
        if available is not None and available >= 1:
            reopenable.append(str(row["listing_id"]))
    return reopenable


def resource_is_api_tokens_listing(listing_row: Mapping[str, Any]) -> bool:
    """Whether a listing row offers API tokens."""
    return resource_is_api_tokens(listing_row.get("offer_resource"))
