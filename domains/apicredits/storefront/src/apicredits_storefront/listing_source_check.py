"""Rechecking an API-credit listing against its source, for the seller's inventory guard.

The negotiation runtime asks before every seller decision and every acceptance.
The declared half confirms that the listing's quota resource is still in its
bound pool, that the pool is enabled and advertises API credits, and that the
pool still declares the backing the listing was bound with. The available half
requires at least one available unit, the condition listing creation requires;
the binding's backing delegate decides whether it is asked. A source the
storefront cannot read is unverifiable, which the runtime refuses as
retryable. See openspec/specs/api-credits/spec.md, "An API-credit listing is
rechecked against its source".
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from market_capacity_publication import backing_changed
from market_policy.listing_source import ListingSourceVerdict

from apicredits_storefront.listing_binding import (
    QuotaPoolUnavailable,
    api_credit_listing_binding,
    quota_pool,
)

#: Check one listing, by id, against its own source.
ListingSourceCheck = Callable[[Any, str], Awaitable[ListingSourceVerdict]]


def build_listing_source_check(
    capacity: Callable[[Any], Any],
) -> ListingSourceCheck:
    """A check reading each listing's own site through its trusted site client.

    ``capacity`` returns the aggregate capacity client for a repository; the
    check reads only the site the listing's binding names.
    """

    async def check(repository: Any, listing_id: str) -> ListingSourceVerdict:
        binding = await api_credit_listing_binding(repository, listing_id)
        if binding is None:
            return ListingSourceVerdict(
                "declared_mismatch", "the listing has no trusted source binding"
            )
        try:
            site = capacity(repository).site(binding.site_id)
        except KeyError:
            return ListingSourceVerdict(
                "unverifiable", f"site {binding.site_id!r} is not configured"
            )

        async def declared() -> ListingSourceVerdict | None:
            try:
                projection = await site.resource_pool_projection()
            except Exception as exc:  # noqa: BLE001 - any failure leaves the source unknown
                return ListingSourceVerdict(
                    "unverifiable",
                    f"site {binding.site_id!r} could not confirm the listing's source: {exc}",
                )
            try:
                pool = quota_pool(
                    projection["resource_pools"], resource_id=binding.source_id
                )
            except QuotaPoolUnavailable as exc:
                return ListingSourceVerdict("declared_mismatch", str(exc))
            if backing_changed(binding, pool.declaration.backing):
                return ListingSourceVerdict(
                    "declared_mismatch",
                    "the pool's backing differs from the listing's",
                    ("capacity_backing",),
                )
            return None

        async def available() -> ListingSourceVerdict | None:
            try:
                rows = await site.snapshot()
            except Exception as exc:  # noqa: BLE001 - any failure leaves the source unknown
                return ListingSourceVerdict(
                    "unverifiable",
                    f"site {binding.site_id!r} capacity could not be read: {exc}",
                )
            units = next(
                (
                    row.get("available_units")
                    for row in rows or ()
                    if row.get("resource_id") == binding.source_id
                ),
                None,
            )
            if units is None or int(units) < 1:
                return ListingSourceVerdict(
                    "unavailable", "the quota resource has no available unit"
                )
            return None

        verdict = await binding.backing.judge_async(declared, available)
        return verdict if verdict is not None else ListingSourceVerdict("matches")

    return check


__all__ = ["ListingSourceCheck", "build_listing_source_check"]
