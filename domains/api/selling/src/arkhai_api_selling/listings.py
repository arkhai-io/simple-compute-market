"""Creating and publishing a listing over a quota resource, as the domain's mapping of an operator's request."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from core_storefront.stage_log import stage_event
from market_core import MarketDomainContract
from market_identity import Identity

from arkhai_api_selling.capacity import QuotaCapacity
from arkhai_api_selling.contributions import QuotaSource, SellingContributions
from arkhai_api_selling.issuance import issuance_subject
from arkhai_api_selling.publication import publication_refusal
from arkhai_api_selling.quota_listing import QuotaPool, prepare_listing_binding, quota_pool

logger = logging.getLogger(__name__)

ReleaseConditions = Callable[[Sequence[Mapping[str, Any]]], list[dict[str, Any]]]
"""The release conditions a listing advertising accepted escrows publishes."""


def admissible_settlement_terms(
    pool: QuotaPool,
    stages: Mapping[str, Any],
    *,
    accepted_escrows: list[dict[str, Any]],
    settlement_options: list[dict[str, Any]],
    escrow_mechanism: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The settlement terms the pool's backing lets a listing publish.

    Without an admission authority, a stage that issues against quota would take funds
    for credits that cannot be reserved, so its terms are dropped.
    """
    backing = pool.declaration.backing

    def fulfils_through_capacity(mechanism: str) -> bool:
        return stages[mechanism].fulfils_through_capacity

    kept_options, dropped = backing.admissible_settlement(
        settlement_options,
        mechanism=lambda option: str(option.get("mechanism")),
        fulfils_through_capacity=fulfils_through_capacity,
    )
    if accepted_escrows:
        if escrow_mechanism is None:
            raise ValueError("this storefront publishes no accepted escrows")
        _, escrow_dropped = backing.admissible_settlement(
            (escrow_mechanism,),
            mechanism=str,
            fulfils_through_capacity=fulfils_through_capacity,
        )
        if escrow_dropped:
            accepted_escrows = []
            dropped = (*dropped, *escrow_dropped)
    if not kept_options and not accepted_escrows:
        raise ValueError(
            f"pool {pool.pool_id!r} leaves no settlement option its "
            f"{backing.label} listings may publish"
            + (f" (dropped: {', '.join(dict.fromkeys(dropped))})" if dropped else "")
        )
    return accepted_escrows, list(kept_options)


class ListingService:
    def __init__(
        self,
        contributions: SellingContributions,
        *,
        sqlite_client: Any,
        seller_principal: Identity,
        settlement_composition: Any,
        domain: MarketDomainContract,
        capacity: QuotaCapacity,
        publish: Callable[[Mapping[str, Any]], Awaitable[dict[str, Any]]],
        close: Callable[[str], Awaitable[dict[str, Any]]],
        settlement_defaults: Callable[[], Sequence[Mapping[str, Any]]],
        storefront_url: str | None,
        escrow_mechanism: str | None = None,
        release_conditions: ReleaseConditions | None = None,
    ) -> None:
        self._contributions = contributions
        self._db = sqlite_client
        self._seller_principal = seller_principal
        self._settlement_composition = settlement_composition
        self._domain = domain
        self._capacity = capacity
        self._publish = publish
        self._close = close
        self._settlement_defaults = settlement_defaults
        self._storefront_url = storefront_url
        self._escrow_mechanism = escrow_mechanism
        self._release_conditions = release_conditions

    async def publish_from_quota(
        self,
        *,
        resource_id: str,
        accepted_escrows: list[dict[str, Any]],
        settlement_clauses: list[dict[str, Any]] | None = None,
        paused: bool = False,
        **request: Any,
    ) -> dict[str, Any]:
        """Create and publish a listing over ``resource_id``; ``request`` is what the domain's mapping reads."""
        clauses = (
            tuple(self._settlement_defaults())
            if settlement_clauses is None
            else tuple(settlement_clauses)
        )
        configured_escrows, settlement_options, readiness = (
            await self._settlement_composition.publication_artifacts(
                {
                    "claimant_principal": self._seller_principal,
                    "resource_id": resource_id,
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

        capacity = self._capacity.runtime(lambda: self._db)
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
        projection = await capacity.site_client(capacity_site_id).resource_pool_projection()
        pool = quota_pool(
            self._contributions, projection["resource_pools"], resource_id=resource_id
        )
        accepted_escrows, settlement_options = admissible_settlement_terms(
            pool,
            self._settlement_composition.stages,
            accepted_escrows=accepted_escrows,
            settlement_options=settlement_options,
            escrow_mechanism=self._escrow_mechanism,
        )
        demands = (
            self._release_conditions(accepted_escrows)
            if accepted_escrows and self._release_conditions is not None
            else []
        )

        listing = self._domain.codecs.listing(
            {
                "listing_resource": self._contributions.publication_mapping(
                    request,
                    QuotaSource(
                        site_id=capacity_site_id,
                        resource_id=resource_id,
                        offering_mode=self._contributions.offering_mode,
                    ),
                ),
                "accepted_escrows": accepted_escrows,
                "settlement_options": settlement_options,
                "demands": demands,
            }
        )
        listing_resource = listing.listing_resource.model_dump(mode="json")
        reason = publication_refusal(self._contributions, listing_resource)
        if reason is not None:
            raise ValueError(reason)
        listing_id = str(uuid.uuid4())
        binding = prepare_listing_binding(
            self._contributions,
            listing_id=listing_id,
            site_id=capacity_site_id,
            listing_resource=listing_resource,
            pool=pool,
            domain=self._domain,
        )
        now_iso = datetime.now().isoformat()
        await self._db.upsert_listing_with_binding(
            binding=binding,
            status="open",
            created_at=now_iso,
            updated_at=now_iso,
            listing_resource=listing_resource,
            accepted_escrows=listing.accepted_escrows,
            settlement_options=[
                option.model_dump(mode="json") for option in listing.settlement_options
            ],
            demands=listing.demands,
            fulfillment_resource=None,
            max_duration_seconds=None,
            storefront_url=self._storefront_url,
            seller_principal=self._seller_principal,
            oracle_address=None,
            paused=paused,
        )
        stage_event(
            "discovery",
            "token_listing_created",
            listing_id=listing_id,
            resource_id=resource_id,
            service_name=issuance_subject(
                self._contributions, listing_resource, listing_id=listing_id
            ).service,
            available_units=available,
        )
        if paused:
            return {"status": "created", "listing_id": listing_id}

        row = await self._db.load_listing(listing_id=listing_id)
        publish_result = await self._publish(row or {})
        return {
            "status": "created",
            "listing_id": listing_id,
            "registry_status": publish_result.get("status"),
        }

    async def close_listing(self, listing_id: str) -> dict[str, Any]:
        result = await self._close(listing_id)
        return {
            "status": result.get("status", "closed"),
            "listing_id": listing_id,
        }
