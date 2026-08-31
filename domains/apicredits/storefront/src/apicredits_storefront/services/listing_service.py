"""ListingService — quota-backed listing lifecycle.

A credit listing derives from a quota resource in the credits service's
ledger (ARCHITECTURE.md, "API-credits market domain — Market shape"): ``publish_from_quota``
reads the resource's availability, writes the local listing row with an
``api_credits.v1`` offer naming that resource, and fans out to the
registries. Closing goes through the shared publication path.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from core_storefront.stage_log import stage_event
from market_identity import Identity

logger = logging.getLogger(__name__)


class ListingService:
    def __init__(
        self,
        *,
        sqlite_client,
        seller_principal: Identity,
        settlement_composition,
    ) -> None:
        self._db = sqlite_client
        self._seller_principal = seller_principal
        self._settlement_composition = settlement_composition

    async def publish_from_quota(
        self,
        *,
        resource_id: str,
        service_name: str,
        accepted_escrows: list[dict[str, Any]],
        settlement_clauses: list[dict[str, Any]] | None = None,
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
        from apicredits_storefront.services.capacity_client import (
            build_capacity_runtime,
        )
        from apicredits_storefront.domain_runtime import get_market_domain_contract
        from apicredits_storefront.utils.config import BASE_URL_OVERRIDE

        from apicredits_storefront.utils.config import settlement_publication_defaults

        clauses = (
            settlement_publication_defaults()
            if settlement_clauses is None
            else tuple(settlement_clauses)
        )
        configured_escrows, settlement_options, readiness = (
            await self._settlement_composition.publication_artifacts(
                {
                    "claimant_principal": self._seller_principal,
                    "resource_id": resource_id,
                    "service": service_name,
                },
                list(clauses) if clauses else None,
            )
            if clauses or not accepted_escrows
            else ([], [], await self._settlement_composition.readiness())
        )
        accepted_escrows = [*accepted_escrows, *configured_escrows]
        if not accepted_escrows and not settlement_options:
            blockers = [
                blocker.code
                for status in readiness
                if status.enabled
                for blocker in status.blockers
            ]
            suffix = f" ({', '.join(blockers)})" if blockers else ""
            raise ValueError(f"no settlement alternative is ready{suffix}")

        capacity = build_capacity_runtime(lambda: self._db)
        availability = await capacity.availability()
        matches = [
            (site_id, units)
            for (site_id, rid), units in availability.items()
            if rid == resource_id
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Quota resource {resource_id!r} must resolve to exactly one "
                f"trusted capacity site; found {len(matches)}."
            )
        capacity_site_id, available = matches[0]
        if available < 1:
            raise ValueError(
                f"Quota resource {resource_id!r} has no sellable units "
                f"(available={available})."
            )

        listing = get_market_domain_contract().codecs.listing(
            {
                "offer_resource": {
                    "service_name": service_name,
                    "description": description,
                    "openapi_url": openapi_url,
                    "base_url": base_url,
                    "resource_id": resource_id,
                    "capacity_site_id": capacity_site_id,
                    "offering_mode": "api_credits",
                },
                "accepted_escrows": accepted_escrows,
                "settlement_options": settlement_options,
                "demands": [],
            }
        )
        listing_id = str(uuid.uuid4())
        now_iso = datetime.now().isoformat()
        await self._db.upsert_listing(
            listing_id=listing_id,
            status="open",
            created_at=now_iso,
            updated_at=now_iso,
            offer_resource=listing.offer_resource.model_dump(mode="json"),
            accepted_escrows=listing.accepted_escrows,
            settlement_options=listing.settlement_options,
            demands=listing.demands,
            fulfillment_resource=None,
            max_duration_seconds=None,
            storefront_url=BASE_URL_OVERRIDE,
            seller_principal=self._seller_principal,
            oracle_address=None,
            paused=paused,
        )
        stage_event(
            "discovery",
            "token_listing_created",
            listing_id=listing_id,
            resource_id=resource_id,
            service_name=service_name,
            available_units=available,
        )
        if paused:
            return {"status": "created", "listing_id": listing_id}

        row = await self._db.load_listing(listing_id=listing_id)
        publication = get_market_domain_contract().publication
        assert publication is not None and publication.publish is not None
        publish_result = await publication.publish(row or {})
        return {
            "status": "created",
            "listing_id": listing_id,
            "registry_status": publish_result.get("status"),
        }

    async def close_listing(self, listing_id: str) -> dict[str, Any]:
        from apicredits_storefront.services.publication_service import close_order

        result = await close_order({"listing_id": listing_id})
        return {
            "status": result.get("status", "closed"),
            "listing_id": listing_id,
        }
