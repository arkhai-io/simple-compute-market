"""ListingService — quota-backed listing lifecycle.

A token listing derives from a quota resource in the tokens service's
ledger (ARCHITECTURE.md, "API-tokens market domain — Market shape"): ``publish_from_quota``
reads the resource's availability, writes the local listing row with an
``api_tokens.v1`` offer naming that resource, and fans out to the
registries. Closing goes through the shared publication path.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from core_storefront.stage_log import stage_event
from domains.apitokens.listings.models import ApiTokensResource

logger = logging.getLogger(__name__)


class ListingService:
    def __init__(self, *, sqlite_client) -> None:
        self._db = sqlite_client

    async def publish_from_quota(
        self,
        *,
        resource_id: str,
        service_name: str,
        accepted_escrows: list[dict[str, Any]],
        description: str | None = None,
        openapi_url: str | None = None,
        base_url: str | None = None,
        paused: bool = False,
    ) -> dict[str, Any]:
        """Create + publish a listing backed by a quota resource.

        The resource must exist in the quota ledger with sellable units —
        the listing's lifetime is tied to it from here on (capacity
        deltas close it on exhaustion and reopen it on replenishment).
        """
        from apitokens_storefront.services.capacity_client import (
            availability_view,
            build_capacity_client,
        )
        from apitokens_storefront.services.publication_service import (
            publish_order_to_registry,
        )
        from apitokens_storefront.utils.config import BASE_URL_OVERRIDE

        if not accepted_escrows:
            raise ValueError(
                "accepted_escrows must be a non-empty list of "
                "{chain_name, escrow_address, literal_fields, rates} entries."
            )

        capacity = build_capacity_client(lambda: self._db)
        availability = await availability_view(capacity)
        available = availability.get((None, resource_id))
        if available is None:
            available = next(
                (
                    units for (_site, rid), units in availability.items()
                    if rid == resource_id
                ),
                None,
            )
        if available is None:
            raise ValueError(
                f"Quota resource {resource_id!r} is not registered in the "
                "tokens service's ledger; register it before publishing."
            )
        if available < 1:
            raise ValueError(
                f"Quota resource {resource_id!r} has no sellable units "
                f"(available={available})."
            )

        offer = ApiTokensResource(
            service_name=service_name,
            description=description,
            openapi_url=openapi_url,
            base_url=base_url,
            resource_id=resource_id,
        )
        listing_id = str(uuid.uuid4())
        now_iso = datetime.now().isoformat()
        await self._db.upsert_listing(
            listing_id=listing_id,
            status="open",
            created_at=now_iso,
            updated_at=now_iso,
            offer_resource=offer.model_dump(mode="json"),
            accepted_escrows=accepted_escrows,
            demands=[],
            fulfillment_resource=None,
            max_duration_seconds=None,
            seller=BASE_URL_OVERRIDE,
            oracle_address=None,
            paused=paused,
        )
        stage_event(
            "discovery", "token_listing_created",
            listing_id=listing_id,
            resource_id=resource_id,
            service_name=service_name,
            available_units=available,
        )
        if paused:
            return {"status": "created", "listing_id": listing_id}

        row = await self._db.load_listing(listing_id=listing_id)
        publish_result = await publish_order_to_registry(row or {})
        return {
            "status": "created",
            "listing_id": listing_id,
            "registry_status": publish_result.get("status"),
        }

    async def close_listing(self, listing_id: str) -> dict[str, Any]:
        from apitokens_storefront.services.publication_service import close_order

        result = await close_order({"listing_id": listing_id})
        return {
            "status": result.get("status", "closed"),
            "listing_id": listing_id,
        }
