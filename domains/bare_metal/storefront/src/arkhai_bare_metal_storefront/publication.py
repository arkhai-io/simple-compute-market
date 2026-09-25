"""One bare-metal publication run: derive, publish, reconcile, and converge.

A run fetches every configured site's resource-pool projection through that
site's own client, reads each pool's declarations through the shared site
declaration reader, and classifies every bare-metal resource (see
``arkhai_bare_metal.storefront_publication``). Candidates are published,
refreshed, or reopened; listings whose resource is unavailable or withdrawn
close; listings at a site whose projection could not be read, or in a pool
whose declarations do not resolve, are held. Every run then converges each
registry on its listings' local status.

Sites are fetched one by one rather than through the aggregate capacity
client, whose snapshot omits a site it could not reach: an unreachable site
is unknown, not empty, and must hold its listings rather than delist them.
See openspec/specs/storefront-publication/spec.md, "A site whose projection
is not held holds its listings".

The capacity-publication kit's cycle driver runs the synchronous core
publication runner in a worker thread and returns each callback to the event
loop for the storefront's own async persistence and the kit publication runtime.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, TypeVar

from arkhai_bare_metal import (
    BARE_METAL_OFFERING_MODE,
    CANDIDATE,
    HELD,
    IDENTITY_CHANGED,
    POOL_ADMITTED,
    POOL_HELD,
    POOL_NOT_ADMITTED,
    UNAVAILABLE,
    UNCHANGED,
    BareMetalListing,
    BareMetalSiteClassification,
    classify_bare_metal_resources,
    compare_bare_metal_listing,
    listing_terms,
    trusted_bare_metal_projection,
)
from core_storefront.domain_registry import StorefrontDomainRegistry
from core_storefront.publication_composition import (
    build_storefront_publication_selection,
)
from core_storefront.publication_runner import (
    REOPEN_UNCHANGED,
    PublicationPayload,
    PublicationSourceSelection,
)
from core_storefront.sqlite_client import SellerClosedListingError
from market_capacity_publication import (
    BoundListing,
    PublicationCycleDriver,
    PublicationCycleReport,
    ReconciliationPlan,
    converge_registries,
)
from market_identity import Identity
from market_resource_pools import read_site_declarations

from .publication_service import (
    BareMetalPublicationHooks,
    RegistryClientFactory,
    bare_metal_publication_candidate,
    build_publication_runtime,
)
from .sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)

T = TypeVar("T")

PayloadBuilder = Callable[[dict[str, Any]], Awaitable[PublicationPayload]]

# Why reconciliation closes a listing, as the report names it.
CLOSE_SOURCE_GONE = "source_gone"
CLOSE_UNAVAILABLE = "unavailable"


def build_bare_metal_publication_selection(
    registry: StorefrontDomainRegistry,
    *,
    open_keys: Callable[[str], set[str]],
    close_stale: Callable[[str, str], list[str]],
    available_candidates: Callable[[str], list[dict[str, Any]]],
    record_published: Callable[[str, dict[str, Any], str], None],
    reopen_existing: Callable[..., dict[str, Any] | None],
) -> PublicationSourceSelection:
    """Select the exact registered bare-metal publication capability."""
    registration = registry.resolve_mode(BARE_METAL_OFFERING_MODE)
    selection = build_storefront_publication_selection(
        registry,
        contributions=(registration.contribution_id,),
        source_kwargs_by_contribution={
            registration.contribution_id: {
                "open_keys": open_keys,
                "close_stale": close_stale,
                "available_candidates": available_candidates,
                "record_published": record_published,
                "reopen_existing": reopen_existing,
            },
        },
    )
    (source,) = selection.sources
    if source.name != registration.contribution_id:
        raise ValueError(
            "bare-metal publication source must match its registered contribution"
        )

    def listing_resource(candidate: dict[str, Any]) -> dict[str, Any]:
        listing_resource = source.listing_resource(candidate)
        listing_resource["offering_mode"] = registration.binding.offering_mode
        return listing_resource

    return PublicationSourceSelection(
        sources=(replace(source, listing_resource=listing_resource),),
    )


def _source_of(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "site_id": candidate.get("site_id"),
        "pool_id": candidate.get("pool_id"),
        "physical_resource_id": candidate.get("physical_resource_id"),
    }


def _stored_resource(stored: Mapping[str, Any]) -> dict[str, Any]:
    raw = stored.get("listing_resource")
    value = json.loads(raw) if isinstance(raw, str) else raw
    return dict(value) if isinstance(value, Mapping) else {}


class BareMetalPublicationCycle:
    """One run of bare-metal publication over every configured site."""

    def __init__(
        self,
        *,
        sqlite_client: SQLiteClient,
        registry: StorefrontDomainRegistry,
        site_clients: Mapping[str, Any],
        registry_client_factory: RegistryClientFactory,
        registry_url: str,
        storefront_url: str,
        seller_principal: Identity,
        build_payload: PayloadBuilder,
    ) -> None:
        self._db = sqlite_client
        self._registry = registry
        self._site_clients = dict(site_clients)
        self._storefront_url = storefront_url
        self._seller_principal = seller_principal
        self._payload_builder = build_payload
        self._runtime = build_publication_runtime(
            sqlite_client,
            registry_client_factory,
            registry_url=registry_url,
            storefront_url=storefront_url,
        )
        self._hooks = BareMetalPublicationHooks(sqlite_client)
        self.report = PublicationCycleReport()
        self._driver = PublicationCycleDriver()
        self._classifications: dict[str, BareMetalSiteClassification] = {}
        self._held_pools: set[tuple[str, str]] = set()
        self._candidates: list[dict[str, Any]] = []
        self._pending: dict[int, dict[str, Any]] = {}

    def _await(self, awaitable: Awaitable[T]) -> T:
        return self._driver.call(awaitable)

    # -- run -------------------------------------------------------------

    async def run(self) -> dict[str, Any]:
        for site_id in sorted(self._site_clients):
            await self._classify_site(site_id)
        selection = build_bare_metal_publication_selection(
            self._registry,
            open_keys=self._open_keys,
            close_stale=self._close_stale,
            available_candidates=lambda _db_path: list(self._candidates),
            record_published=self._record_published,
            reopen_existing=self._reopen_existing,
        )
        result = await self._driver.run(
            selection.build_sources(),
            db_path=self._db.db_path,
            base_url=self._storefront_url,
            build_payload=self._build_payload,
            publish_listing=self._publish_listing,
            close_stale=True,
            skip_open=False,
        )
        for candidate, reason in result.failed:
            logger.warning(
                "bare-metal candidate %s failed: %s", _source_of(candidate), reason
            )
        await converge_registries(self._runtime, self.report)
        return self.report.as_dict()

    async def _classify_site(self, site_id: str) -> None:
        """Fetch, accept, and classify one site, or hold it as unknown."""
        try:
            response = await self._site_clients[site_id].resource_pool_projection()
        except Exception as exc:
            logger.warning(
                "bare-metal site %s projection is unavailable: %s", site_id, exc
            )
            self.report.record(
                "hold", site_id=site_id, reason="site_projection_unknown", error=str(exc)
            )
            return
        try:
            generation = trusted_bare_metal_projection(
                site_id=site_id, projection=response
            )
        except ValueError as exc:
            logger.warning(
                "bare-metal site %s projection generation refused: %s", site_id, exc
            )
            self.report.record(
                "hold", site_id=site_id, reason="site_projection_refused", error=str(exc)
            )
            return
        classification = classify_bare_metal_resources(
            generation,
            pool_admission=self._pool_admission(site_id, response["resource_pools"]),
        )
        self._classifications[site_id] = classification
        for item in classification.of(HELD):
            self.report.record(
                "hold",
                site_id=site_id,
                pool_id=item.pool_id,
                physical_resource_id=item.physical_resource_id,
                reason="pool_unresolvable",
            )
        for candidate in classification.candidates:
            candidate["derivation_key"] = self._key(
                site_id, candidate["pool_id"], candidate["physical_resource_id"]
            )
            self._candidates.append(candidate)

    def _pool_admission(
        self, site_id: str, pools: list[Mapping[str, Any]]
    ) -> dict[str, str]:
        declarations = read_site_declarations(pools)
        admission: dict[str, str] = {}
        for pool_id, problems in sorted(declarations.unresolvable.items()):
            admission[pool_id] = POOL_HELD
            self._held_pools.add((site_id, pool_id))
            logger.warning(
                "bare-metal pool %s at %s is unresolvable: %s",
                pool_id,
                site_id,
                ", ".join(problems),
            )
        for pool_id, pool in sorted(declarations.resolved.items()):
            if not pool.enabled or not pool.advertises(BARE_METAL_OFFERING_MODE):
                admission[pool_id] = POOL_NOT_ADMITTED
            elif not pool.backed:
                # Every bare-metal listing is capacity-backed; one derived from
                # an unbacked pool would publish a backing its pool contradicts.
                admission[pool_id] = POOL_NOT_ADMITTED
                self.report.record(
                    "refuse",
                    site_id=site_id,
                    pool_id=pool_id,
                    reason="pool_unbacked",
                )
                logger.warning(
                    "bare-metal pool %s at %s is unbacked; bare-metal listings "
                    "are capacity-backed, so none is derived from it",
                    pool_id,
                    site_id,
                )
            else:
                admission[pool_id] = POOL_ADMITTED
        return admission

    def _key(self, site_id: str, pool_id: str, physical_resource_id: str) -> str:
        return self._db.bare_metal_derivation_key(
            site_id=site_id,
            pool_id=pool_id,
            physical_resource_id=physical_resource_id,
        )

    # -- reconciliation (worker thread) ----------------------------------

    def _open_keys(self, _db_path: str) -> set[str]:
        bindings = self._await(
            self._db.list_open_bare_metal_listing_bindings(
                site_ids=tuple(self._site_clients)
            )
        )
        return {binding.derivation_key for binding in bindings}

    def _close_stale(self, _db_path: str, _base_url: str) -> list[str]:
        """Close from the disjoint classes, only at sites whose generation was accepted.

        A candidate's listing is left to publication; a resource that is
        unavailable closes its listing for availability; a held pool's
        listings are untouched; every other open listing at the site — its
        resource withdrawn, or no longer projected under the pool its binding
        records — closes as a withdrawn source. Each listing is in at most one
        class, so the plan never names one twice.
        """
        if not self._classifications:
            return []
        bindings = self._await(
            self._db.list_open_bare_metal_listing_bindings(
                site_ids=tuple(self._classifications)
            )
        )
        classes: dict[str, str] = {}
        for site_id, classification in self._classifications.items():
            for item in classification.resources:
                classes[
                    self._key(site_id, item.pool_id, item.physical_resource_id)
                ] = item.classification
        plan: list[str] = []
        reasons: dict[str, str] = {}
        for binding in bindings:
            classification = classes.get(binding.derivation_key)
            if classification == CANDIDATE:
                continue
            if classification == HELD or (
                binding.pool_id is not None
                and (binding.site_id, binding.pool_id) in self._held_pools
            ):
                continue
            reason = (
                CLOSE_UNAVAILABLE if classification == UNAVAILABLE else CLOSE_SOURCE_GONE
            )
            plan.append(binding.listing_id)
            reasons[binding.listing_id] = reason
        if not plan:
            return []
        result = self._await(self._reconciliation_close(plan))
        for listing_id in result["closed"]:
            self.report.record("close", listing_id=listing_id, reason=reasons[listing_id])
        for listing_id in result["failed_closes"]:
            self.report.record("fail", listing_id=listing_id, reason="local_close_failed")
        return list(result["closed"])

    async def _reconciliation_close(
        self, listing_ids: list[str]
    ) -> dict[str, tuple[str, ...]]:
        bound: list[BoundListing] = []
        for listing_id in listing_ids:
            binding = await self._hooks.binding_for_listing(listing_id)
            if binding is None:
                raise RuntimeError(f"open listing {listing_id!r} has no binding")
            bound.append(BoundListing(listing_id, binding))
        return await self._runtime.reconcile(ReconciliationPlan(close=tuple(bound)))

    # -- publication (worker thread) -------------------------------------

    def _build_payload(
        self,
        _source: Any,
        candidate: dict[str, Any],
        listing_resource: dict[str, Any],
    ) -> PublicationPayload | str:
        try:
            payload = self._await(self._payload_builder(candidate))
        except Exception as exc:
            self.report.record("refuse", source=_source_of(candidate), reason=str(exc))
            return str(exc)
        self._pending[id(listing_resource)] = candidate
        return payload

    def _record_published(
        self, _db_path: str, _candidate: dict[str, Any], _listing_id: str
    ) -> None:
        # The listing and its binding were written before any registry was told.
        return None

    def _publish_listing(
        self,
        listing_resource: dict[str, Any],
        accepted_escrows: list[dict[str, Any]],
        demands: list[dict[str, Any]],
        max_duration_seconds: int | None,
        *,
        settlement_options: list[dict[str, Any]] | None = None,
        publication_clauses: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        candidate = self._pending.pop(id(listing_resource))
        try:
            response = self._await(
                self._publish_new(
                    candidate,
                    listing_resource,
                    accepted_escrows=accepted_escrows,
                    settlement_options=settlement_options or [],
                    publication_clauses=publication_clauses or [],
                    demands=demands,
                    max_duration_seconds=max_duration_seconds,
                )
            )
        except Exception as exc:
            self.report.record("fail", source=_source_of(candidate), reason=str(exc))
            raise
        self.report.record(
            "publish",
            listing_id=response.get("listing_id"),
            source=_source_of(candidate),
            status=response.get("status"),
        )
        return response

    async def _publish_new(
        self,
        candidate: dict[str, Any],
        listing_resource: dict[str, Any],
        *,
        accepted_escrows: list[dict[str, Any]],
        settlement_options: list[dict[str, Any]],
        publication_clauses: list[dict[str, Any]],
        demands: list[dict[str, Any]],
        max_duration_seconds: int | None,
    ) -> dict[str, Any]:
        listing_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        # Recorded locally, with its binding, before any registry is told: a
        # registry must never hold a listing the storefront has no record of.
        await self._db.upsert_bare_metal_listing(
            listing_id=listing_id,
            status="open",
            created_at=now,
            updated_at=now,
            seller_principal=self._seller_principal,
            storefront_url=self._storefront_url,
            listing=_listing(listing_resource, max_duration_seconds),
            accepted_escrows=accepted_escrows,
            settlement_options=settlement_options,
            publication_clauses=publication_clauses,
            demands=demands,
            site_id=str(candidate["site_id"]),
            pool_id=str(candidate["pool_id"]),
            physical_resource_id=str(candidate["physical_resource_id"]),
        )
        published = await self._runtime.publish(
            await bare_metal_publication_candidate(self._db, listing_id)
        )
        return {**published, "listing_id": listing_id}

    def _reopen_existing(
        self,
        _db_path: str,
        _base_url: str,
        candidate: dict[str, Any],
        listing_resource: dict[str, Any],
        accepted_escrows: list[dict[str, Any]],
        demands: list[dict[str, Any]],
        max_duration_seconds: int | None,
        *,
        settlement_options: list[dict[str, Any]] | None = None,
        publication_clauses: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        try:
            result = self._await(
                self._reconcile_existing(
                    candidate,
                    listing_resource,
                    accepted_escrows=accepted_escrows,
                    settlement_options=settlement_options or [],
                    publication_clauses=publication_clauses or [],
                    demands=demands,
                    max_duration_seconds=max_duration_seconds,
                )
            )
        except Exception as exc:
            self.report.record("fail", source=_source_of(candidate), reason=str(exc))
            raise
        if result is None:
            return None
        # A new listing is created only when nothing is bound under the key.
        self._pending.pop(id(listing_resource), None)
        return result

    async def _reconcile_existing(
        self,
        candidate: dict[str, Any],
        listing_resource: dict[str, Any],
        *,
        accepted_escrows: list[dict[str, Any]],
        settlement_options: list[dict[str, Any]],
        publication_clauses: list[dict[str, Any]],
        demands: list[dict[str, Any]],
        max_duration_seconds: int | None,
    ) -> dict[str, Any] | None:
        existing = await self._db.load_listing_binding_by_derivation(
            derivation_key=str(candidate["derivation_key"])
        )
        if existing is None:
            return None
        listing_id = existing.listing_id
        stored = await self._db.load_listing(listing_id=listing_id)
        if stored is None:
            raise RuntimeError(f"listing {listing_id!r} has a binding and no listing")
        if stored.get("closed_by") == "seller":
            self.report.record("skip", listing_id=listing_id, reason="closed_by_seller")
            return {"status": REOPEN_UNCHANGED}

        fresh_resource = _persisted_resource(listing_resource, max_duration_seconds)
        fresh_terms = {
            "accepted_escrows": accepted_escrows,
            "settlement_options": settlement_options,
            "demands": demands,
            "max_duration_seconds": max_duration_seconds,
        }
        comparison = compare_bare_metal_listing(
            stored_resource=_stored_resource(stored),
            stored_terms=listing_terms(stored),
            fresh_resource=fresh_resource,
            fresh_terms=fresh_terms,
        )
        is_open = stored.get("status") == "open"
        if comparison.outcome == IDENTITY_CHANGED:
            logger.warning(
                "bare-metal listing %s no longer matches its Physical Resource in %s; %s",
                listing_id,
                list(comparison.differing_fields),
                "closing it" if is_open else "not reopening it",
            )
            if is_open:
                result = await self._reconciliation_close([listing_id])
                if listing_id in result["closed"]:
                    self.report.record(
                        "close",
                        listing_id=listing_id,
                        reason=IDENTITY_CHANGED,
                        fields=list(comparison.differing_fields),
                    )
                else:
                    self.report.record(
                        "fail", listing_id=listing_id, reason="local_close_failed"
                    )
            else:
                self.report.record(
                    "refuse",
                    listing_id=listing_id,
                    reason=IDENTITY_CHANGED,
                    fields=list(comparison.differing_fields),
                )
            return {"status": REOPEN_UNCHANGED}
        if is_open and comparison.outcome == UNCHANGED:
            return {"status": REOPEN_UNCHANGED}

        await self._db.update_listing(
            listing_id=listing_id,
            listing_resource=fresh_resource,
            accepted_escrows=accepted_escrows,
            settlement_options=settlement_options,
            publication_clauses=publication_clauses,
            demands=demands,
            max_duration_seconds=max_duration_seconds,
        )
        publication = await bare_metal_publication_candidate(self._db, listing_id)
        if is_open:
            result = await self._runtime.publish(publication)
        else:
            try:
                result = await self._runtime.reopen(
                    publication, reopened_by="reconciliation"
                )
            except SellerClosedListingError:
                self.report.record(
                    "skip", listing_id=listing_id, reason="closed_by_seller"
                )
                return {"status": REOPEN_UNCHANGED}
        self.report.record(
            "refresh" if is_open else "reopen",
            listing_id=listing_id,
            fields=list(comparison.differing_fields),
            status=result.get("status"),
        )
        return result


def _listing(
    listing_resource: Mapping[str, Any], max_duration_seconds: int | None
) -> BareMetalListing:
    raw = dict(listing_resource)
    raw.pop("offering_mode", None)
    raw["max_duration_seconds"] = max_duration_seconds
    return BareMetalListing.model_validate(raw)


def _persisted_resource(
    listing_resource: Mapping[str, Any], max_duration_seconds: int | None
) -> dict[str, Any]:
    """The listing resource exactly as the storefront persists it."""
    resource = _listing(listing_resource, max_duration_seconds).model_dump(
        mode="json", exclude_none=True
    )
    resource["offering_mode"] = BARE_METAL_OFFERING_MODE
    return resource


__all__ = [
    "BareMetalPublicationCycle",
    "build_bare_metal_publication_selection",
]
