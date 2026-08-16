"""One-shot trusted-site publication command wiring."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from arkhai_bare_metal import (
    BareMetalListing,
    BareMetalResourceProjection,
    TrustedBareMetalProjection,
    bare_metal_digest,
)
from core_storefront.publication_command import (
    StorefrontPublicationCommandCallbacks,
    StorefrontPublicationCommandConfig,
)
from market_identity import Identity, TrustedIdentitySet
from market_settlement_runtime import SettlementPublicationClause
from pydantic_core import to_jsonable_python
from registry_client import ListingRequest, SyncRegistryClient, UpdateListingRequest

from .publication import (
    build_bare_metal_publication_selection,
    run_bare_metal_publication,
)
from .runtime import BareMetalStorefrontRuntime, build_runtime_from_environment
from .server import build_bare_metal_storefront_registry


def _json_env(name: str) -> Any:
    try:
        return json.loads(os.environ[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must contain valid JSON") from exc


def _instant(name: str) -> datetime:
    value = os.environ.get(name, "")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise RuntimeError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _registry(runtime: BareMetalStorefrontRuntime) -> SyncRegistryClient:
    raw_principals = _json_env("BARE_METAL_STOREFRONT_REGISTRY_PRINCIPALS")
    if not isinstance(raw_principals, list):
        raise RuntimeError("registry principals must be a JSON list")
    trust = TrustedIdentitySet(
        identities=tuple(Identity.model_validate(item) for item in raw_principals)
    )
    return SyncRegistryClient(
        os.environ["BARE_METAL_STOREFRONT_REGISTRY_URL"],
        signer=runtime.marketplace_signer,
        caller_role="seller",
        expected_registries=trust,
        registry_authority=os.environ["BARE_METAL_STOREFRONT_REGISTRY_AUTHORITY"],
    )


def _whole_resource_available(row: dict[str, Any]) -> bool:
    capacity = row.get("capacity")
    available = row.get("available")
    if not row.get("enabled", True):
        return False
    if not isinstance(capacity, dict) or not isinstance(available, dict):
        return row.get("state") == "available"
    compared = False
    for key, raw_total in capacity.items():
        try:
            total = Decimal(str(raw_total))
            remaining = Decimal(str(available.get(key, 0)))
        except (InvalidOperation, TypeError, ValueError):
            return False
        if not total.is_finite() or not remaining.is_finite() or total < 0:
            return False
        if total > 0:
            compared = True
            if remaining < total:
                return False
    return compared


def _projections(
    runtime: BareMetalStorefrontRuntime,
) -> tuple[TrustedBareMetalProjection, ...]:
    if runtime.capacity_client is None:
        raise RuntimeError("trusted site capacity client is unavailable")
    rows = asyncio.run(runtime.capacity_client.snapshot())
    grouped: dict[str, list[BareMetalResourceProjection]] = {
        binding.site_id: [] for binding in runtime.site_bindings
    }
    for row in rows:
        site_id = str(row.get("site") or "")
        if site_id not in grouped:
            raise RuntimeError("capacity snapshot returned an untrusted site")
        resource_id = str(
            row.get("physical_resource_id") or row.get("resource_id") or ""
        )
        attributes = (
            row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
        )
        publication = attributes.get("bare_metal_publication")
        if not isinstance(publication, dict) or not publication.get("enabled", False):
            continue
        grouped[site_id].append(
            BareMetalResourceProjection(
                physical_resource_id=resource_id,
                pool_id=str(row.get("pool_id") or "") or None,
                physical_host_id=str(publication.get("physical_host_id") or ""),
                machine_id=str(publication.get("machine_id") or ""),
                available=_whole_resource_available(row),
                allocation_mode=publication.get("allocation_mode", "exclusive"),
                access_methods=list(publication.get("access_methods") or []),
                capacity=dict(row.get("capacity") or {}),
                capabilities=dict(publication.get("capabilities") or {}),
            )
        )
    return tuple(
        TrustedBareMetalProjection(
            site_id=site_id,
            revision=0,
            digest=bare_metal_digest(
                [item.model_dump(mode="json") for item in resources]
            ),
            complete=True,
            resources=resources,
        )
        for site_id, resources in sorted(grouped.items())
    )


def run_publication_once() -> dict[str, Any]:
    """Publish one exact round from freshly authenticated site projections."""

    runtime = build_runtime_from_environment()
    if runtime.settlement_composition is None:
        raise RuntimeError(
            "shared settlement configuration is required for publication"
        )
    clauses_raw = _json_env("BARE_METAL_STOREFRONT_PUBLICATION_CLAUSES")
    deadlines_raw = _json_env("BARE_METAL_STOREFRONT_FUNDING_DEADLINES")
    if not isinstance(clauses_raw, list) or not isinstance(deadlines_raw, dict):
        raise RuntimeError("publication clauses/deadlines have invalid JSON shapes")
    clauses = tuple(
        SettlementPublicationClause.model_validate(item) for item in clauses_raw
    )
    funding_deadlines = {
        str(profile): datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        for profile, value in deadlines_raw.items()
    }
    demands = _json_env("BARE_METAL_STOREFRONT_DEMANDS")
    if not isinstance(demands, list):
        raise RuntimeError("BARE_METAL_STOREFRONT_DEMANDS must be a JSON list")
    offer_expiry = _instant("BARE_METAL_STOREFRONT_OFFER_EXPIRES_AT")
    fulfillment_deadline = _instant("BARE_METAL_STOREFRONT_FULFILLMENT_DEADLINE")
    max_duration = int(os.environ["BARE_METAL_STOREFRONT_MAX_DURATION_SECONDS"])

    client = _registry(runtime)

    def close_listing(
        _base_url: str, listing_id: str, _reason: str | None = None
    ) -> dict[str, Any]:
        client.update_listing(
            listing_id, UpdateListingRequest(updates={"status": "closed"})
        )
        return {"status": "closed", "listing_id": listing_id}

    def publish_existing_listing(*, listing_id: str, **values: Any) -> dict[str, Any]:
        updates = {
            "status": "open",
            "offer_resource": values["offer"],
            "accepted_escrows": values["accepted_escrows"],
            "settlement_options": values["settlement_options"],
            "demands": values["demands"],
            "max_duration_seconds": values["max_duration_seconds"],
            "storefront_url": values["storefront_url"],
        }
        client.update_listing(listing_id, UpdateListingRequest(updates=updates))
        return {"status": "published", "listing_id": listing_id}

    projections = _projections(runtime)
    selection = build_bare_metal_publication_selection(
        build_bare_metal_storefront_registry(domain=runtime.domain),
        projection_snapshot=lambda: projections,
        close_listing=close_listing,
        publish_existing_listing=publish_existing_listing,
    )
    publication_candidates: dict[int, dict[str, Any]] = {}

    def build_payload(
        _source: Any, candidate: dict[str, Any], offer: dict[str, Any]
    ) -> Any:
        publication_candidates[id(offer)] = candidate
        return asyncio.run(
            runtime.settlement_composition.publication_payload(
                candidate=candidate,
                clauses=clauses,
                offer_expires_at=offer_expiry,
                funding_deadlines=funding_deadlines,
                fulfillment_deadline=fulfillment_deadline,
                demands=demands,
                max_duration_seconds=max_duration,
            )
        )

    def publish_offer(
        offer: dict[str, Any],
        accepted_escrows: list[dict[str, Any]],
        published_demands: list[dict[str, Any]],
        duration: int | None,
        *,
        settlement_options: list[dict[str, Any]] | None = None,
        publication_clauses: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        candidate = publication_candidates.pop(id(offer), None)
        if candidate is None:
            raise RuntimeError("publication candidate binding is unavailable")
        listing_id = uuid.uuid4().hex
        request = ListingRequest(
            listing_id=listing_id,
            offer=offer,
            accepted_escrows=accepted_escrows,
            settlement_options=settlement_options or [],
            demands=published_demands,
            max_duration_seconds=duration,
            storefront_url=runtime.storefront_url,
        )
        client.publish_listing(request)
        raw_listing = dict(offer)
        raw_listing.pop("virtualization_type", None)
        raw_listing["max_duration_seconds"] = duration
        now = datetime.now(timezone.utc).isoformat()
        asyncio.run(
            runtime.db.upsert_bare_metal_listing(
                listing_id=listing_id,
                status="open",
                created_at=now,
                updated_at=now,
                seller_principal=runtime.seller_principal,
                storefront_url=runtime.storefront_url,
                listing=BareMetalListing.model_validate(raw_listing),
                accepted_escrows=accepted_escrows,
                settlement_options=settlement_options or [],
                publication_clauses=publication_clauses or [],
                demands=published_demands,
                site_id=str(candidate["site_id"]),
                pool_id=str(candidate["pool_id"]),
                physical_resource_id=str(candidate["physical_resource_id"]),
            )
        )
        return {"status": "published", "listing_id": listing_id}

    try:
        result = run_bare_metal_publication(
            selection,
            config=StorefrontPublicationCommandConfig(
                db_path=runtime.db.db_path,
                base_url=runtime.storefront_url,
            ),
            callbacks=StorefrontPublicationCommandCallbacks(
                build_payload=build_payload,
                publish_offer=publish_offer,
            ),
        )
        return to_jsonable_python(
            {
                "closed": result.closed,
                "published": result.published,
                "failed": result.failed,
                "skipped": result.skipped,
            }
        )
    finally:
        client.close()


__all__ = ["run_publication_once"]
