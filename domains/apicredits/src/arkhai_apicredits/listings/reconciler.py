"""Quota-backed listing reconciliation.

An API-credits listing derives from a quota resource in the tokens
service's ledger the way a VM derived listing derives from a pool
member. The reconciliation rule is simpler than the VM one because a
listing has no per-listing unit slice: it stays open while its quota
resource has any sellable units and closes on exhaustion (capacity
deltas from the event poller trigger the check; buyers pick the
quantity per deal, and the quota guard enforces the per-deal bound).

Pure functions over each listing's status and binding and an availability
view, so the storefront's persistence stays out of the concept module. Whether
availability bounds a listing is its backing's decision, which the caller
supplies as ``judge``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Mapping

from arkhai_apicredits.listings.models import coerce_resource_dict

AvailabilityView = Mapping[tuple[str, str], int]
"""Available units keyed by exact trusted ``(site_id, resource_id)``."""

Verdict = str | None
"""A reason a listing does not stand, or ``None`` when it does."""

Judge = Callable[["CreditListingSource", Callable[[], Verdict]], Verdict]
"""Judges one listing given its availability half.

The caller asks the listing's backing whether availability bounds it, so a rule
here supplies only what availability says and never decides that itself.
"""


@dataclass(frozen=True)
class CreditListingSource:
    """One credit listing as reconciliation reads it: its status and binding.

    ``site_id`` and ``resource_id`` come from the listing's durable binding,
    never from its published payload.
    """

    listing_id: str
    status: str
    closed_by: str | None
    site_id: str
    resource_id: str


def listing_quota_resource_id(listing_row: Mapping[str, Any]) -> str | None:
    """The quota resource a credit listing publishes, if it names one."""
    listing_resource = coerce_resource_dict(listing_row.get("listing_resource"))
    if listing_resource.get("kind") != "api_credits.v1":
        return None
    resource_id = listing_resource.get("resource_id")
    return str(resource_id) if resource_id else None


def _available_units(availability: AvailabilityView, source: CreditListingSource) -> int | None:
    return availability.get((source.site_id, source.resource_id))


def stale_open_credit_listing_ids(
    sources: Iterable[CreditListingSource],
    *,
    availability: AvailabilityView | None,
    judge: Judge,
) -> list[str]:
    """Open credit listings whose quota resource is exhausted.

    ``availability=None`` (authority unreachable) closes nothing — the
    next delta/reconcile converges. A resource missing from the view is
    treated as exhausted: the ledger is the source of sellable truth,
    and a listing whose resource is gone must not stay open.
    """
    if availability is None:
        return []
    stale: list[str] = []
    for source in sources:
        if source.status.strip() != "open":
            continue

        def exhausted(source: CreditListingSource = source) -> Verdict:
            available = _available_units(availability, source)
            return "exhausted" if available is None or available < 1 else None

        if judge(source, exhausted) is not None:
            stale.append(source.listing_id)
    return stale


def reopenable_credit_listing_ids(
    sources: Iterable[CreditListingSource],
    *,
    availability: AvailabilityView | None,
    judge: Judge,
) -> list[str]:
    """Closed credit listings whose quota resource has units again.

    ``availability=None`` reopens nothing: with no consumption
    information everything would look free, and reopening on ignorance
    over-sells (same rule as the VM reconciler). Only a listing
    reconciliation closed is a candidate; one its seller closed stays
    closed until the seller reopens it, whatever quota returns.
    """
    if availability is None:
        return []
    reopenable: list[str] = []
    for source in sources:
        if source.status.strip() != "closed" or source.closed_by != "reconciliation":
            continue

        def replenished(source: CreditListingSource = source) -> Verdict:
            available = _available_units(availability, source)
            return None if available is not None and available >= 1 else "exhausted"

        if judge(source, replenished) is None:
            reopenable.append(source.listing_id)
    return reopenable
