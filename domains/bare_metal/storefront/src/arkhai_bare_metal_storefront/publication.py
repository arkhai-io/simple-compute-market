"""One bare-metal publication cycle: derive, publish, reconcile, and converge.

A cycle reads every configured site's resource-pool projection from the
storefront's held projection state and fetches no site: the state's poller
keeps it current. It accepts each held generation's bare-metal views as this
domain reads them, reads each pool's declarations and region (see
``site_reading``), and classifies every bare-metal resource (see
``arkhai_bare_metal.storefront_publication``). Candidates are published,
refreshed, or reopened; listings whose resource is unavailable or withdrawn
close; listings at a site whose projection is not held or whose generation this
domain refuses, in a pool whose declarations do not resolve, or in a pool that
resolves no positive maximum lease duration, are held. A candidate that can
publish no settlement option is refused: its open listing closes when the
storefront's configuration rules out every mechanism its clauses name, and is
held while any of them is unknown. Every cycle then converges each registry the
storefront publishes to on its listings' local status.

A held generation may be stale -- its site's latest poll failed -- and the
cycle derives from it all the same, because holding a site's listings through
an outage is publication's job. A site holding no generation is unknown, not
empty, and holds its listings rather than delisting them. See
openspec/specs/storefront-publication/spec.md, "A site whose projection is not
held holds its listings".

The capacity-publication kit's cycle driver runs the synchronous core
publication runner in a worker thread and returns each callback to the event
loop for the storefront's own async persistence and the kit publication runtime.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, TypeVar

from arkhai_bare_metal import (
    BACKING_CHANGED,
    BARE_METAL_OFFERING_MODE,
    CANDIDATE,
    HELD,
    IDENTITY_CHANGED,
    POOL_ADMITTED,
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
    NoSettlementOption,
    PublicationPayload,
    PublicationSourceSelection,
)
from core_storefront.sqlite_client import SellerClosedListingError
from core_storefront.site_projections import ProjectionCacheView
from market_capacity_publication import (
    RESOURCE_POOL,
    BoundListing,
    PublicationCycleDriver,
    PublicationCycleReport,
    ReconciliationPlan,
    RefusedCandidates,
    SiteDerivationLog,
    SiteProjectionState,
    backing_changed,
    converge_registries,
)
from market_identity import Identity
from market_storefront_kit import LifecycleRouteError
from market_resource_pools_contracts.backing import capacity_backing

from .listing_binding import bare_metal_listing_binding
from .publication_service import (
    BareMetalPublicationHooks,
    RegistryClientFactory,
    bare_metal_publication_candidate,
    build_publication_runtime,
)
from .pool_overrides import (
    BareMetalPoolOverride,
    positive_lease_bound,
    read_bare_metal_pool_overrides,
)
from .site_reading import SitePoolReading, read_site_pools
from .sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)

T = TypeVar("T")

PayloadBuilder = Callable[[dict[str, Any]], Awaitable[PublicationPayload]]

# Why reconciliation closes a listing, as the report names it.
CLOSE_SOURCE_GONE = "source_gone"
CLOSE_UNAVAILABLE = "unavailable"


class BareMetalPublicationError(LifecycleRouteError):
    """A publication cycle the storefront cannot compose, and why.

    Its text names what is missing -- the site projection state, a registry,
    the settlement configuration -- and never a configured value, so a recorded
    cycle outcome carries it. A step answers it as 503: the storefront cannot
    publish until it is composed with what it names.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(503, detail)


def _no_stage(_stage: str) -> None:
    return None


def build_bare_metal_publication_selection(
    registry: StorefrontDomainRegistry,
    *,
    open_keys: Callable[[str], set[str]],
    close_stale: Callable[[str, str], list[str]],
    available_candidates: Callable[[str], list[dict[str, Any]]],
    record_published: Callable[[str, dict[str, Any], str], None],
    reopen_existing: Callable[..., dict[str, Any] | None],
    close_candidate_listing: Callable[[str, str, dict[str, Any], str], None],
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
                "close_candidate_listing": close_candidate_listing,
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
    """One cycle of bare-metal publication over every configured site.

    ``site_projections`` is the storefront's one held projection state and
    ``site_ids`` its configured sites. ``default_max_duration_seconds`` is the
    configured lease bound a pool's override replaces; the configured clauses
    are the payload builder's. ``enter_stage`` names each stage the
    cycle reaches -- ``compose``, ``run``, ``converge`` -- for the loop
    controller's record of a failed cycle, and ``derivation`` receives each
    site's holds, refusals, and reports once the cycle has derived them.
    """

    def __init__(
        self,
        *,
        sqlite_client: SQLiteClient,
        registry: StorefrontDomainRegistry,
        site_projections: SiteProjectionState,
        site_ids: Sequence[str],
        registry_client_factory: RegistryClientFactory,
        registry_urls: Sequence[str],
        storefront_url: str,
        seller_principal: Identity,
        build_payload: PayloadBuilder,
        default_max_duration_seconds: int | None = None,
        enter_stage: Callable[[str], None] = _no_stage,
        derivation: SiteDerivationLog | None = None,
    ) -> None:
        self._db = sqlite_client
        # A configured bound that is absent or not positive bounds nothing, so
        # a pool relying on it is held rather than published unbounded.
        self._default_max_duration = positive_lease_bound(default_max_duration_seconds)
        self._registry = registry
        self._site_projections = site_projections
        self._site_ids = tuple(site_ids)
        self._enter_stage = enter_stage
        self._derivation = derivation
        self._storefront_url = storefront_url
        self._seller_principal = seller_principal
        self._payload_builder = build_payload
        self._runtime = build_publication_runtime(
            sqlite_client,
            registry_client_factory,
            registry_urls=registry_urls,
            storefront_url=storefront_url,
        )
        self._hooks = BareMetalPublicationHooks(sqlite_client)
        self.report = PublicationCycleReport()
        self._driver = PublicationCycleDriver()
        self._classifications: dict[str, BareMetalSiteClassification] = {}
        self._held_pools: set[tuple[str, str]] = set()
        self._candidates: list[dict[str, Any]] = []
        self._pending: dict[int, dict[str, Any]] = {}
        self._refusals = RefusedCandidates(
            self.report,
            call=self._await,
            listings=sqlite_client,
            derivation_key=lambda candidate: str(candidate["derivation_key"]),
            derivation_source=_source_of,
            reconciliation_close=self._reconciliation_close,
        )
        self._overrides: dict[tuple[str, str], BareMetalPoolOverride] = {}
        self._dry_run = False

    def _await(self, awaitable: Awaitable[T]) -> T:
        return self._driver.call(awaitable)

    # -- run -------------------------------------------------------------

    async def run(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Run one cycle; with ``dry_run``, report what it would do and do none of it.

        A dry run reads the held projections, the stored listings, and the
        registries as a cycle would, and writes nothing: no listing, binding,
        close, publication, or registry repair. Its report names each open,
        close, refresh, reopen, and hold the cycle would make.
        """
        self._dry_run = dry_run
        self.report.dry_run = dry_run
        self._enter_stage("compose")
        # Read once, before any site, so every site in a cycle sees one view.
        self._overrides = await asyncio.to_thread(
            read_bare_metal_pool_overrides,
            self._db.db_path,
            configured_max_duration_seconds=self._default_max_duration,
        )
        # Every site's held generation is read together, with nothing awaited
        # between, so one cycle reads one generation of each site.
        held = {
            site_id: self._site_projections.view(site_id, RESOURCE_POOL)
            for site_id in self._site_ids
        }
        for site_id in sorted(held):
            self._classify_site(site_id, held[site_id])
        selection = build_bare_metal_publication_selection(
            self._registry,
            open_keys=self._open_keys,
            close_stale=self._close_stale,
            available_candidates=lambda _db_path: list(self._candidates),
            record_published=self._record_published,
            reopen_existing=self._reopen_existing,
            close_candidate_listing=self._refusals.close_candidate_listing,
        )
        self._enter_stage("run")
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
            # A candidate whose payload was refused is in the site derivation,
            # whose log records it once when it appears, not every cycle.
            if self._refusals.refused(candidate):
                continue
            logger.warning(
                "bare-metal candidate %s failed: %s", _source_of(candidate), reason
            )
        if self._derivation is not None:
            self._derivation.record(
                self._registry.resolve_mode(BARE_METAL_OFFERING_MODE).contribution_id,
                self.report,
                self._site_ids,
            )
        self._enter_stage("converge")
        await converge_registries(self._runtime, self.report)
        return self.report.as_dict()

    def _classify_site(self, site_id: str, view: ProjectionCacheView[Any]) -> None:
        """Accept and classify one site's held generation, or hold the site.

        Every hold, refusal, and report goes to the cycle's report, which the
        site-derivation log records and logs as each entry appears and clears.
        """
        if view.value is None or view.identity is None:
            self.report.record(
                "hold",
                site_id=site_id,
                reason="site_projection_unknown",
                **({"error": view.last_error} if view.last_error else {}),
            )
            return
        response = {
            "revision": view.identity.revision,
            "digest": view.identity.digest,
            "resource_pools": list(view.value),
        }
        pools = response["resource_pools"]
        site_overrides = {
            pool_id: override
            for (override_site, pool_id), override in self._overrides.items()
            if override_site == site_id
        }
        try:
            # The pools are read first: which backing each view's delivery
            # terms answer to depends on the whole generation's declarations.
            reading = read_site_pools(
                pools,
                override_asking_rates={
                    pool_id: override.asking_rates
                    for pool_id, override in site_overrides.items()
                    if not override.problems and override.asking_rates is not None
                },
                override_problems={
                    pool_id: override.problems or override.term_conflicts
                    for pool_id, override in site_overrides.items()
                    if override.problems or override.term_conflicts
                },
            )
            generation = trusted_bare_metal_projection(
                site_id=site_id, projection=response, backings=reading.backings
            )
        except ValueError as exc:
            self.report.record(
                "hold", site_id=site_id, reason="site_projection_refused", error=str(exc)
            )
            return
        held_pools = self._report_pools(site_id, reading, site_overrides)
        classification = classify_bare_metal_resources(
            generation,
            pool_admission=reading.admission,
            pool_backings=reading.backings,
            pool_regions=reading.regions,
            pool_asking_rates=reading.published_asking_rates(),
        )
        self._classifications[site_id] = classification
        for item in classification.of(HELD):
            # A pool held whole is reported once, with its reasons, above; a
            # machine in it is reported too only for its own declaration. One
            # the site built no view for is reported as unbuildable below.
            if item.view_unbuildable or (item.pool_id in held_pools and not item.problems):
                continue
            self.report.record(
                "hold",
                site_id=site_id,
                pool_id=item.pool_id,
                physical_resource_id=item.physical_resource_id,
                reason="declaration_unresolvable" if item.problems else "pool_unresolvable",
                **({"problems": list(item.problems)} if item.problems else {}),
            )
        for unbuildable in generation.view_problems:
            # The site built no view for this resource, so it yields no
            # listing; an open one is held, as an unreadable declaration is,
            # and closes only as a withdrawn source: its declaration disabled,
            # or its pool no longer admitting bare metal. The reasons are its
            # declaration's, named for the seller.
            self.report.record(
                "report",
                site_id=site_id,
                pool_id=unbuildable.pool_id,
                physical_resource_id=unbuildable.physical_resource_id,
                reason="publication_view_unbuildable",
                problems=list(unbuildable.problems),
            )
        for item in classification.resources:
            if item.publication_capabilities_ignored:
                self.report.record(
                    "report",
                    site_id=site_id,
                    pool_id=item.pool_id,
                    physical_resource_id=item.physical_resource_id,
                    reason="publication_capabilities_ignored",
                )
        self._report_unpublished_rates(site_id, reading, classification)
        unpublishable = self._hold_unbounded_pools(site_id, reading, site_overrides)
        for candidate in classification.candidates:
            if candidate["pool_id"] in unpublishable:
                continue
            override = site_overrides.get(candidate["pool_id"])
            if override is not None:
                _apply_override(candidate, override)
            candidate["derivation_key"] = self._key(
                site_id,
                candidate["pool_id"],
                candidate["physical_resource_id"],
                candidate["shape_digest"],
            )
            self._candidates.append(candidate)

    def _hold_unbounded_pools(
        self,
        site_id: str,
        reading: SitePoolReading,
        site_overrides: Mapping[str, BareMetalPoolOverride],
    ) -> set[str]:
        """Hold each admitted pool whose maximum lease duration resolves to nothing.

        A pool's bound is its override's maximum, else the configured default;
        one that is absent or not positive leaves its listings nothing to
        publish as their maximum, so they are held -- neither published,
        refreshed, nor closed -- and the pool is reported.
        """
        unbounded: set[str] = set()
        for pool_id, admission in sorted(reading.admission.items()):
            if admission != POOL_ADMITTED:
                continue
            override = site_overrides.get(pool_id)
            stated = override.max_duration_seconds if override is not None else None
            bound = stated if stated is not None else self._default_max_duration
            if positive_lease_bound(bound) is not None:
                continue
            unbounded.add(pool_id)
            self._held_pools.add((site_id, pool_id))
            self.report.record(
                "hold", site_id=site_id, pool_id=pool_id, reason="pool_lease_bound_missing"
            )
        return unbounded

    def _report_pools(
        self,
        site_id: str,
        reading: SitePoolReading,
        site_overrides: Mapping[str, BareMetalPoolOverride],
    ) -> set[str]:
        """Hold every pool a site's declarations leave unpublishable, each once
        per reason with what makes it so, and record each pool-level refusal and
        report. Returns the pools held, whether or not they have members: a
        held pool's open listings are neither refreshed nor closed."""
        held: set[str] = set()

        def hold(pool_id: str, reason: str, problems: Sequence[str] = ()) -> None:
            held.add(pool_id)
            self._held_pools.add((site_id, pool_id))
            self.report.record(
                "hold",
                site_id=site_id,
                pool_id=pool_id,
                reason=reason,
                **({"problems": list(problems)} if problems else {}),
            )

        for pool_id, problems in sorted(reading.unresolvable.items()):
            hold(pool_id, "pool_unresolvable", problems)
        # Held, not withdrawn: a missing region is a declaration to repair, and
        # the listings it already published stay as they are.
        for pool_id in sorted(reading.regionless):
            hold(pool_id, "pool_region_missing")
        for pool_id, problems in sorted(reading.unreadable_overrides.items()):
            override = site_overrides.get(pool_id)
            hold(
                pool_id,
                "pool_override_terms_conflict"
                if override is not None and override.term_conflicts
                else "pool_override_unreadable",
                problems,
            )
        for pool_id, problems in sorted(reading.unreadable_asking_rates.items()):
            hold(pool_id, "asking_rates_unreadable", problems)
        for pool_id in reading.listing_shapes_stated:
            self.report.record(
                "report",
                site_id=site_id,
                pool_id=pool_id,
                reason="listing_shapes_not_applicable",
            )
        return held

    def _report_unpublished_rates(
        self, site_id: str, reading: SitePoolReading, classification: Any
    ) -> None:
        """Report each priced shape no machine in its pool publishes: such a
        price reaches no buyer, which the seller should be able to see."""
        published: dict[str, set[str]] = {}
        for candidate in classification.candidates:
            published.setdefault(candidate["pool_id"], set()).add(candidate["shape_digest"])
        for pool_id, resolution in sorted(reading.asking_rates.items()):
            if reading.admission.get(pool_id) != POOL_ADMITTED:
                continue
            unpublished = resolution.unpublished(published.get(pool_id, ()))
            if unpublished:
                self.report.record(
                    "report",
                    site_id=site_id,
                    pool_id=pool_id,
                    reason="asking_rate_shape_unpublished",
                    shapes=[unpublished[digest] for digest in sorted(unpublished)],
                )

    def _key(
        self, site_id: str, pool_id: str, physical_resource_id: str, shape_digest: str
    ) -> str:
        return self._db.bare_metal_derivation_key(
            site_id=site_id,
            pool_id=pool_id,
            physical_resource_id=physical_resource_id,
            shape_digest=shape_digest,
        )

    # -- reconciliation (worker thread) ----------------------------------

    def _open_keys(self, _db_path: str) -> set[str]:
        bindings = self._await(
            self._db.list_open_bare_metal_listing_bindings(site_ids=self._site_ids)
        )
        return {binding.derivation_key for binding in bindings}

    def _close_stale(self, _db_path: str, _base_url: str) -> list[str]:
        """Close from the disjoint classes, only at sites whose generation was accepted.

        Each open binding is matched to its resource by the site, pool, and
        Physical Resource it records, before its key: a resource held for an
        unreadable declaration has no shape and so no key to match on. Then:

        - a held resource, or one in a held pool, leaves the listing as it is;
        - a candidate under the binding's own key is left to publication;
        - an unavailable resource under the binding's own key closes for
          availability;
        - anything else closes as a withdrawn source: a withdrawn or absent
          resource, or one whose key differs because its declared shape changed
          or because the binding predates shape-bearing keys. A changed shape's
          successor is published under its new key in the same run.

        Each listing is in at most one class, so the plan never names one twice.
        """
        if not self._classifications:
            return []
        bindings = self._await(
            self._db.list_open_bare_metal_listing_bindings(
                site_ids=tuple(self._classifications)
            )
        )
        resources = {
            (site_id, item.pool_id, item.physical_resource_id): item
            for site_id, classification in self._classifications.items()
            for item in classification.resources
        }
        plan: list[str] = []
        reasons: dict[str, str] = {}
        for binding in bindings:
            if (binding.site_id, binding.pool_id) in self._held_pools:
                continue
            item = resources.get(
                (binding.site_id, binding.pool_id, binding.physical_resource_id)
            )
            if item is not None and item.classification == HELD:
                continue
            same_key = (
                item is not None
                and item.shape_digest is not None
                and binding.derivation_key
                == self._key(
                    binding.site_id,
                    item.pool_id,
                    item.physical_resource_id,
                    item.shape_digest,
                )
            )
            if same_key and item.classification == CANDIDATE:
                continue
            reason = (
                CLOSE_UNAVAILABLE
                if same_key and item.classification == UNAVAILABLE
                else CLOSE_SOURCE_GONE
            )
            plan.append(binding.listing_id)
            reasons[binding.listing_id] = reason
        if not plan:
            return []
        if self._dry_run:
            for listing_id in plan:
                self.report.record("close", listing_id=listing_id, reason=reasons[listing_id])
            return plan
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
    ) -> PublicationPayload | NoSettlementOption | str:
        """The candidate's payload, or its refusal recorded under its site.

        A candidate with no settlement option is refused where configuration
        rules out every mechanism its clauses name, and held while any of them
        is unknown; the runner then closes or keeps its open listing.
        """
        try:
            payload = self._await(self._payload_builder(candidate))
        except Exception as exc:
            return self._refusals.refuse(candidate, exc)
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
        if self._dry_run:
            # Nothing is recorded or published, so the listing has no identity.
            return {"listing_id": None, "status": "dry_run"}
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
        binding = await bare_metal_listing_binding(self._db, listing_id)
        if binding is None:
            raise RuntimeError(f"listing {listing_id!r} has no complete binding")
        comparison = compare_bare_metal_listing(
            backing_changed=backing_changed(
                binding, capacity_backing(listing_resource["capacity_backing"])
            ),
            stored_resource=_stored_resource(stored),
            stored_terms=listing_terms(stored),
            fresh_resource=fresh_resource,
            fresh_terms=fresh_terms,
        )
        is_open = stored.get("status") == "open"
        if comparison.outcome in (IDENTITY_CHANGED, BACKING_CHANGED):
            logger.warning(
                "bare-metal listing %s no longer matches its Physical Resource in %s; %s",
                listing_id,
                list(comparison.differing_fields),
                "closing it" if is_open else "not reopening it",
            )
            if is_open and self._dry_run:
                self.report.record(
                    "close",
                    listing_id=listing_id,
                    reason=comparison.outcome,
                    fields=list(comparison.differing_fields),
                )
            elif is_open:
                result = await self._reconciliation_close([listing_id])
                if listing_id in result["closed"]:
                    self.report.record(
                        "close",
                        listing_id=listing_id,
                        reason=comparison.outcome,
                        fields=list(comparison.differing_fields),
                    )
                else:
                    self.report.record(
                        "fail", listing_id=listing_id, reason="local_close_failed"
                    )
            else:
                # A refusal, like every one a cycle makes, names its site, pool,
                # and Physical Resource, so it reaches the site's derivation.
                self.report.record(
                    "refuse",
                    **_source_of(candidate),
                    listing_id=listing_id,
                    reason=comparison.outcome,
                    fields=list(comparison.differing_fields),
                )
            return {"status": REOPEN_UNCHANGED}
        if is_open and comparison.outcome == UNCHANGED:
            return {"status": REOPEN_UNCHANGED}
        if self._dry_run:
            action = "refresh" if is_open else "reopen"
            self.report.record(
                action,
                listing_id=listing_id,
                fields=list(comparison.differing_fields),
                status="dry_run",
            )
            logger.info(
                "bare-metal listing %s would be %s (dry run): %s",
                listing_id,
                "refreshed" if is_open else "reopened",
                list(comparison.differing_fields),
            )
            # The preview changes nothing, so the driver is told the listing is
            # unchanged, which it skips; it counts `published` and `disabled` as
            # published and any other status as a failed candidate.
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


def _apply_override(candidate: dict[str, Any], override: BareMetalPoolOverride) -> None:
    """Carry a pool's override to its candidate as plain values.

    The candidate is handed to mechanism option builders, so it holds clause
    data and bounds rather than the override itself. A clause list replaces the
    configured clauses as a whole; each bound replaces the configured bound.
    """
    if override.clauses is not None:
        candidate["override_clauses"] = [
            clause.model_dump(mode="json") for clause in override.clauses
        ]
    if override.max_duration_seconds is not None:
        candidate["override_max_duration_seconds"] = override.max_duration_seconds
    if override.min_duration_seconds is not None:
        candidate["listing_resource"]["min_duration_seconds"] = (
            override.min_duration_seconds
        )


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
    "BareMetalPublicationError",
    "build_bare_metal_publication_selection",
]
