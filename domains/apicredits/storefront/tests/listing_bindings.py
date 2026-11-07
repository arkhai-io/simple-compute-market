"""Write a credit listing with its durable binding, as listing creation does."""

from __future__ import annotations

from typing import Any

from market_resource_pools import ResolvedPool
from market_resource_pools_contracts.backing import BACKED, CapacityBacking

from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.listing_binding import (
    QuotaPool,
    prepare_api_credit_listing_binding,
)


async def upsert_bound_listing(
    db: Any,
    *,
    listing_id: str,
    pool_id: str = "default",
    backing: CapacityBacking = BACKED,
    **listing: Any,
) -> None:
    """``db.upsert_listing``'s arguments, stored with the binding creation records.

    The binding's site and quota resource are the ones the listing publishes,
    in a pool declaring ``backing`` that advertises API credits.
    """
    resource = listing["listing_resource"]
    binding = prepare_api_credit_listing_binding(
        listing_id=listing_id,
        site_id=str(resource["capacity_site_id"]),
        resource_id=str(resource["resource_id"]),
        pool=QuotaPool(pool_id, ResolvedPool(backing, frozenset({"api_credits"}), True)),
        domain=get_market_domain_contract(),
    )
    await db.upsert_listing_with_binding(binding=binding, **listing)
