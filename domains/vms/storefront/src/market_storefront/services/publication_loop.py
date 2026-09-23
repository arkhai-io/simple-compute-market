"""The storefront's publication loop: one cycle derives, publishes, and reconciles.

A cycle derives candidates from every configured site's projection, publishes new
ones, refreshes the terms of open ones, closes those whose source no longer
supports them, holds those whose source cannot be read, and reopens those
reconciliation closed when their source supports them again. It never touches a
listing its seller closed. See openspec/specs/storefront-publication/spec.md,
"Publication runs as a controllable storefront lifecycle loop".

The shared publication runner in ``core_storefront`` is synchronous, so a cycle
runs it in a worker thread and each callback returns to the event loop for the
storefront's own async services. A dry run drives exactly the same callbacks,
which record what they would do instead of doing it, so a preview and a run
cannot disagree about what a cycle means.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

from core_storefront.publication_runner import (
    REOPEN_UNCHANGED,
    PublicationPayload,
    run_publication_cycle,
)
from domains.vms.listings.listing_comparison import (
    REFRESH_IN_PLACE,
    REFUSE,
    TERM_LISTING_FIELDS,
    UNCHANGED,
    compare_listing,
    refreshed_listing_resource,
)
from domains.vms.listings.reconciler import (
    available_compute_slices,
    open_listing_resource_keys,
    stale_open_listing_ids,
)
from market_capacity_publication import BoundListing, ReconciliationPlan

import market_storefront.container as container
from market_storefront.lifecycle import PUBLICATION, gate
from market_storefront.models.listing_models import VmCreateListingRequest
from market_storefront.publication_wiring import (
    VmPublicationSourceCallbacks,
    build_vm_storefront_publication_selection,
)
from market_storefront.services.capacity_client import (
    capacity_binding_for_listing,
    listing_source_projection,
    site_capacity_buckets,
)
from market_storefront.services.publication_service import (
    _candidate,
    _make_registry_client,
    build_publication_runtime,
)
from market_storefront.services.listing_source_check import (
    stored_listing_resource,
)
from market_storefront.services.publication_terms import (
    compile_publication_clauses,
    demands_for_publication_clauses,
    listing_resource_for_candidate,
    normalize_max_duration_seconds,
    pool_hint_resolution_settings,
)
from market_storefront.utils.config import (
    BASE_URL_OVERRIDE,
    get_evm_wallet_address,
    settings,
    settlement_publication_defaults,
    storefront_domain_registry,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

_DEFAULT_INTERVAL_SECONDS = 30.0

# Set when a site's resource-pool projection generation changes, so a change a
# site declares reaches the loop without waiting out its interval. A held loop
# stays held: the gate is consulted before any work either way.
_WAKE = asyncio.Event()


def wake_publication_loop() -> None:
    _WAKE.set()


@dataclass
class PublicationCycleReport:
    """What one cycle did, or in a dry run would do, and why."""

    dry_run: bool
    actions: list[dict[str, Any]] = field(default_factory=list)

    def record(self, action: str, **details: Any) -> None:
        self.actions.append({"action": action, **details})

    def as_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for item in self.actions:
            counts[item["action"]] = counts.get(item["action"], 0) + 1
        return {
            "loop": "publication",
            "dry_run": self.dry_run,
            "actions": list(self.actions),
            "counts": dict(sorted(counts.items())),
        }


def _source_of(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "site_id": candidate.get("site_id"),
        "pool_id": candidate.get("pool_id"),
        "resource_id": candidate.get("resource_id"),
        "gpu_count": candidate.get("gpu_count"),
        "capacity_backing": candidate.get("capacity_backing"),
    }


def _terms_of(record: Mapping[str, Any]) -> dict[str, Any]:
    return {name: record.get(name) for name in TERM_LISTING_FIELDS}


class VmPublicationCycle:
    """One publication cycle over the VM source."""

    def __init__(
        self,
        *,
        sqlite_client: Any,
        listing_service: Any,
        capacity_runtime: Any,
        registry: Any,
        storefront_url: str,
        wallet_address: str,
        dry_run: bool,
        request_builder: Callable[..., VmCreateListingRequest] | None = None,
    ) -> None:
        self._db = sqlite_client
        # How a candidate becomes a create request: its durable terms and the
        # clauses they compile to. Injected so a cycle can be exercised without
        # the operator's settlement configuration.
        self._request_builder = request_builder or self._create_request
        self._listings = listing_service
        self._capacity = capacity_runtime
        self._registry = registry
        self._storefront_url = storefront_url
        self._wallet_address = wallet_address
        self.report = PublicationCycleReport(dry_run=dry_run)
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._projection: Mapping[str, list[dict[str, Any]]] | None = None
        self._buckets: Mapping[str, list[dict[str, Any]]] | None = None
        self._availability: Mapping[tuple[str, str], int] | None = None
        self._home_site: str | None = None
        self._site_count = 0
        self._derived: dict[int, Any] = {}

    @property
    def dry_run(self) -> bool:
        return self.report.dry_run

    # -- bridging --------------------------------------------------------

    def _await(self, awaitable: Awaitable[T]) -> T:
        assert self._event_loop is not None
        return asyncio.run_coroutine_threadsafe(
            awaitable,  # type: ignore[arg-type]
            self._event_loop,
        ).result()

    # -- cycle -----------------------------------------------------------

    async def run(self) -> dict[str, Any]:
        self._event_loop = asyncio.get_running_loop()
        sites = list(self._capacity.site_ids)
        self._home_site = sites[0] if sites else None
        self._site_count = len(sites)
        if self._home_site is None:
            return self.report.as_dict()
        self._projection = listing_source_projection()
        self._buckets = (
            site_capacity_buckets() if self._projection is not None else None
        )
        try:
            self._availability = dict(await self._capacity.availability())
        except Exception as exc:
            # Unknown availability is not zero: nothing is closed or reopened
            # on it. New unbacked supply, which no availability bounds, still
            # publishes, and backed candidates are ranged as fully available
            # with the reservation boundary deciding authoritatively.
            logger.warning("[PUBLICATION] capacity availability unavailable: %s", exc)
            self._availability = None
        selection = build_vm_storefront_publication_selection(
            self._registry,
            VmPublicationSourceCallbacks(
                open_keys=self._open_keys,
                close_stale=self._close_stale,
                available_candidates=self._available_candidates,
                listing_resource=listing_resource_for_candidate,
                record_published=self._record_published,
                reopen_existing=self._reopen_existing,
            ),
        )
        await asyncio.to_thread(
            run_publication_cycle,
            selection.build_sources(),
            db_path=self._db.db_path,
            base_url=self._storefront_url,
            build_payload=self._build_payload,
            publish_listing=self._publish_listing,
            close_stale=self._availability is not None,
            skip_open=False,
        )
        return self.report.as_dict()

    # -- source callbacks (worker thread) --------------------------------

    def _open_keys(self, db_path: str) -> set[str]:
        return open_listing_resource_keys(
            db_path,
            home_site=self._home_site or "",
            configured_site_count=self._site_count,
        )

    def _available_candidates(self, db_path: str) -> list[dict[str, Any]]:
        holds: set[tuple[str, str, str]] = set()
        candidates = available_compute_slices(
            db_path,
            home_site=self._home_site or "",
            member_availability=self._availability,
            site_pool_projection=self._projection,
            site_capacity_buckets=self._buckets,
            hint_resolution=pool_hint_resolution_settings(),
            holds=holds,
        )
        for kind, site_id, source_id in sorted(holds):
            self.report.record("hold", site_id=site_id, **{f"{kind}_id": source_id})
        return candidates

    def _close_stale(self, db_path: str, _base_url: str) -> list[str]:
        stale = stale_open_listing_ids(
            db_path,
            home_site=self._home_site or "",
            configured_site_count=self._site_count,
            member_availability=self._availability,
            site_pool_projection=self._projection,
            site_capacity_buckets=self._buckets,
        )
        for listing_id in stale:
            self.report.record("close", listing_id=listing_id, reason="source_gone")
        if self.dry_run or not stale:
            return stale
        return self._await(self._reconciliation_close(stale))

    async def _reconciliation_close(self, listing_ids: list[str]) -> list[str]:
        bound = tuple(
            [
                BoundListing(
                    listing_id,
                    await capacity_binding_for_listing(self._db, listing_id),
                )
                for listing_id in listing_ids
            ]
        )
        result = await self._runtime().reconcile(ReconciliationPlan(close=bound))
        return list(result["closed"])

    def _build_payload(
        self,
        source: Any,
        candidate: dict[str, Any],
        listing_resource: dict[str, Any],
    ) -> PublicationPayload | str:
        try:
            request = self._request_builder(source, candidate, listing_resource)
            derived = self._await(self._listings.derive_listing(request))
        except Exception as exc:
            self.report.record(
                "refuse", source=_source_of(candidate), reason=str(exc)
            )
            return str(exc)
        self._derived[id(listing_resource)] = derived
        listing = derived.listing.model_dump(mode="json")
        return PublicationPayload(
            accepted_escrows=tuple(listing.get("accepted_escrows") or ()),
            settlement_options=tuple(listing.get("settlement_options") or ()),
            publication_clauses=tuple(derived.publication_clauses()),
            demands=tuple(listing.get("demands") or ()),
            max_duration_seconds=listing.get("max_duration_seconds"),
        )

    def _create_request(
        self,
        source: Any,
        candidate: dict[str, Any],
        listing_resource: dict[str, Any],
    ) -> VmCreateListingRequest:
        pricing = source.pricing_resource(candidate, listing_resource)
        raw_clauses = pricing.get("settlements")
        if raw_clauses is None:
            raw_clauses = [
                clause.model_dump(mode="json", exclude_defaults=True)
                for clause in settlement_publication_defaults()
            ]
        if not isinstance(raw_clauses, list) or not raw_clauses:
            raise ValueError(
                "no settlement clauses: set the pool's `settlements` pricing hint "
                "or configure [pricing].settlements"
            )
        clauses = compile_publication_clauses(raw_clauses)
        return VmCreateListingRequest(
            listing_resource=listing_resource,
            capacity_source={
                "site_id": candidate["site_id"],
                "pool_id": candidate.get("pool_id"),
                "resource_id": candidate.get("resource_id"),
                "gpu_count": candidate["gpu_count"],
            },
            settlements=list(clauses),
            demands=demands_for_publication_clauses(
                clauses, wallet_address=self._wallet_address
            ),
            max_duration_seconds=normalize_max_duration_seconds(
                pricing.get("max_duration_seconds")
            ),
        )

    def _publish_listing(
        self,
        listing_resource: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        derived = self._derived[id(listing_resource)]
        source = {
            "derivation_key": derived.binding.derivation_key,
            "capacity_backing": derived.binding.capacity_backing,
        }
        self.report.record("publish", source=source)
        if self.dry_run:
            return {"status": "planned"}
        try:
            return self._await(self._persist_new(derived))
        except Exception as exc:
            self.report.record("fail", source=source, reason=str(exc))
            raise

    async def _persist_new(self, derived: Any) -> dict[str, Any]:
        response = await self._listings.persist_derived_listing(derived)
        return {"status": response.status, "listing_id": response.listing_id}

    def _record_published(
        self, _db_path: str, _candidate: dict[str, Any], _listing_id: str
    ) -> None:
        # Creating the listing already wrote its durable binding.
        return None

    def _reopen_existing(
        self,
        _db_path: str,
        _base_url: str,
        candidate: dict[str, Any],
        listing_resource: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any] | None:
        derived = self._derived[id(listing_resource)]
        try:
            return self._await(self._reconcile_existing(candidate, derived))
        except Exception as exc:
            # The runner records this as a failed candidate; the report says
            # which source failed and why, so an operator does not have to
            # find it in a log.
            self.report.record("fail", source=_source_of(candidate), reason=str(exc))
            raise

    async def _reconcile_existing(
        self, candidate: dict[str, Any], derived: Any
    ) -> dict[str, Any] | None:
        existing = await self._db.load_listing_binding_by_derivation(
            derivation_key=derived.binding.derivation_key
        )
        if existing is None:
            return None
        listing_id = existing.listing_id
        stored = await self._db.load_listing(listing_id=listing_id)
        if stored is None:
            return None
        closed_by = await self._db.load_listing_closed_by(listing_id=listing_id)
        if closed_by == "seller":
            self.report.record(
                "skip", listing_id=listing_id, reason="closed_by_seller"
            )
            return {"status": REOPEN_UNCHANGED}

        fresh = derived.listing.model_dump(mode="json")
        stored_resource = stored_listing_resource(stored)
        comparison = compare_listing(
            stored_resource=stored_resource,
            stored_terms=_terms_of(stored),
            fresh_resource=fresh["listing_resource"],
            fresh_terms=_terms_of(fresh),
            binding_backing=existing.capacity_backing,
            source_backing=str(candidate.get("capacity_backing")),
        )
        is_open = stored.get("status") == "open"
        if comparison.outcome in REFUSE:
            logger.warning(
                "[PUBLICATION] listing %s from %s no longer matches its source in "
                "%s; %s",
                listing_id,
                _source_of(candidate),
                list(comparison.differing_fields),
                "closing it" if is_open else "not reopening it",
            )
            self.report.record(
                "close" if is_open else "refuse",
                listing_id=listing_id,
                reason=comparison.outcome,
                fields=list(comparison.differing_fields),
            )
            if is_open and not self.dry_run:
                await self._reconciliation_close([listing_id])
            return {"status": REOPEN_UNCHANGED}
        if is_open and comparison.outcome == UNCHANGED:
            return {"status": REOPEN_UNCHANGED}

        action = "refresh" if is_open else "reopen"
        self.report.record(
            action,
            listing_id=listing_id,
            reason=comparison.outcome,
            fields=list(comparison.differing_fields),
        )
        if self.dry_run:
            return {"status": REOPEN_UNCHANGED}
        assert comparison.outcome in REFRESH_IN_PLACE or not is_open
        await self._db.update_listing(
            listing_id=listing_id,
            listing_resource=refreshed_listing_resource(
                stored_resource=stored_resource,
                fresh_resource=fresh["listing_resource"],
                binding_backing=existing.capacity_backing,
            ),
            accepted_escrows=fresh.get("accepted_escrows"),
            settlement_options=fresh.get("settlement_options"),
            publication_clauses=derived.publication_clauses(),
            demands=fresh.get("demands"),
            max_duration_seconds=fresh.get("max_duration_seconds"),
        )
        refreshed = await self._db.load_listing(listing_id=listing_id)
        publication = await _candidate(self._db, refreshed)
        runtime = self._runtime()
        if is_open:
            return await runtime.publish(publication)
        return await runtime.reopen(publication)

    def _runtime(self) -> Any:
        return build_publication_runtime(
            self._db, registry_client_factory=_make_registry_client
        )


async def run_publication_cycle_once(*, dry_run: bool) -> dict[str, Any]:
    """Run, or preview, exactly one publication cycle — the timer's cycle."""

    cycle = VmPublicationCycle(
        sqlite_client=container.resolved_sqlite_client,
        listing_service=container.resolved_listing_service,
        capacity_runtime=container.resolved_capacity_runtime,
        registry=storefront_domain_registry(),
        storefront_url=BASE_URL_OVERRIDE,
        wallet_address=get_evm_wallet_address() or "",
        dry_run=dry_run,
    )
    return await cycle.run()


def _interval_seconds() -> float:
    capacity = getattr(settings, "capacity", None)
    return float(
        getattr(capacity, "publication_interval_seconds", 0)
        or _DEFAULT_INTERVAL_SECONDS
    )


async def publication_loop(
    run_cycle: Callable[..., Awaitable[dict[str, Any]]] = run_publication_cycle_once,
) -> None:
    """Timer-driven publication, woken early by a projection change."""
    while True:
        if gate(PUBLICATION):
            await asyncio.sleep(0.05)
            continue
        _WAKE.clear()
        try:
            await run_cycle(dry_run=False)
        except Exception:
            logger.exception("[PUBLICATION] publication cycle failed")
        try:
            await asyncio.wait_for(_WAKE.wait(), timeout=_interval_seconds())
        except asyncio.TimeoutError:
            pass


__all__ = [
    "PublicationCycleReport",
    "VmPublicationCycle",
    "publication_loop",
    "run_publication_cycle_once",
    "wake_publication_loop",
]
