"""Write a credit listing with its durable binding, as listing creation does."""

from __future__ import annotations

from typing import Any

from arkhai_api_selling.quota_listing import QuotaPool, prepare_listing_binding
from market_resource_pools import ResolvedPool
from market_resource_pools_contracts.backing import BACKED, CapacityBacking

from apicredits_storefront.container import SELLING_CONTRIBUTIONS
from apicredits_storefront.domain_runtime import get_market_domain_contract


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
    binding = prepare_listing_binding(
        SELLING_CONTRIBUTIONS,
        listing_id=listing_id,
        site_id=str(resource["capacity_site_id"]),
        listing_resource=resource,
        pool=QuotaPool(pool_id, ResolvedPool(backing, frozenset({"api_credits"}), True)),
        domain=get_market_domain_contract(),
    )
    await db.upsert_listing_with_binding(binding=binding, **listing)
