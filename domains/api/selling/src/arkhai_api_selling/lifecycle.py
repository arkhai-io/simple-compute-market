"""A quota-backed storefront's loops, their steps, its startup tasks, and its development seed.

See openspec/specs/market-composition/spec.md, "Storefront timer loops are held and
stepped through one kit controller".
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from core_storefront.domain_registry import (
    StorefrontDomainBindingError,
    StorefrontDomainRegistryError,
)
from core_storefront.stage_log import stage_event
from market_capacity_publication import (
    CapacityBindingError,
    CapacityConfigurationError,
    CapacityRuntime,
    SiteEventCycle,
    run_capacity_event_pollers,
)
from market_policy.identity import Identity as PolicyIdentity
from market_policy.negotiation_thread import get_thread_store
from market_site_client import SiteCapacityAdminClient, SiteCapacityAdminClientError
from market_storefront_kit import (
    LifecycleRouteError,
    NegotiationWatchdogPolicy,
    StorefrontLoopController,
    sweep_stale_negotiations,
)

from arkhai_api_selling.capacity import CapacitySite, QuotaCapacity
from arkhai_api_selling.contributions import SellingContributions
from arkhai_api_selling.issuance import decode_stored
from arkhai_api_selling.publication import all_listings
from arkhai_api_selling.publish_route import SERVICE_FIELDS

logger = logging.getLogger(__name__)

NEGOTIATION_WATCHDOG = "negotiation_watchdog"
SETTLEMENT_SERVICING = "settlement_servicing"
CAPACITY_EVENTS_POLLER = "capacity_events_poller"

#: The errors whose messages a recorded cycle outcome may carry: their text names
#: only public configuration and identifiers. Any other error is reported by type.
DISCLOSED_CYCLE_ERRORS: tuple[type[BaseException], ...] = (
    CapacityBindingError,
    CapacityConfigurationError,
    StorefrontDomainBindingError,
    StorefrontDomainRegistryError,
)


def loop_controller(**options: Any) -> StorefrontLoopController:
    """The loop controller for one storefront process, disclosing only ``DISCLOSED_CYCLE_ERRORS``."""
    options.setdefault("logger", logger)
    return StorefrontLoopController(disclosed_errors=DISCLOSED_CYCLE_ERRORS, **options)


def capacity_site_loop_name(site: str) -> str:
    """One site's poller name, so one site at its gate cannot answer for another still writing."""
    return f"{CAPACITY_EVENTS_POLLER}:{site}"


def capacity_site_gate(loops: StorefrontLoopController, site: str) -> Callable[[], bool]:
    """Declare one site's poller as a child of the aggregate loop and bind its gate."""
    return loops.declare(capacity_site_loop_name(site), parent=CAPACITY_EVENTS_POLLER)


def capacity_site_cycle_recorder(
    loops: StorefrontLoopController, site: str
) -> Callable[[SiteEventCycle], None]:
    """Record each of one site's timer cycles under the site's declared name."""
    record = loops.cycle_recorder(capacity_site_loop_name(site))

    def report(cycle: SiteEventCycle) -> None:
        record(cycle.exception)

    return report


@dataclass(frozen=True)
class LoopSettings:
    """Each loop's configured timing, read when the loops are registered or stepped."""

    watchdog: Callable[[], NegotiationWatchdogPolicy]
    settlement_servicing_interval: Callable[[], float]
    capacity_poll_interval: Callable[[], float]


@dataclass(frozen=True)
class ContributedLoop:
    """A timer loop a composed mechanism adds, registered and stepped like the storefront's own."""

    name: str
    route: str
    step: Callable[[], Awaitable[Mapping[str, Any]]]
    interval_seconds: float


class StorefrontLoops:
    """The storefront's steps and loops; each collaborator is read when a step runs."""

    def __init__(
        self,
        *,
        sqlite_client: Callable[[], Any | None],
        settlement_worker: Callable[[], Any | None],
        capacity: QuotaCapacity,
        settings: LoopSettings,
        contributed_loops: Callable[[], Sequence[ContributedLoop]] = tuple,
    ) -> None:
        self._sqlite_client = sqlite_client
        self._settlement_worker = settlement_worker
        self._capacity = capacity
        self._settings = settings
        self._contributed_loops = contributed_loops

    def _db(self) -> Any:
        db = self._sqlite_client()
        if db is None:
            raise LifecycleRouteError(503, "storefront persistence is not initialized")
        return db

    async def negotiation_watchdog_step(self) -> Mapping[str, Any]:
        policy = self._settings.watchdog()
        abandoned = await sweep_stale_negotiations(
            self._db(),
            policy,
            emit_stage_event=stage_event,
            logger=logger,
        )
        if abandoned:
            logger.info(
                "[WATCHDOG] marked %d stale thread(s) as %s", abandoned, policy.terminal_state
            )
        return {"loop": NEGOTIATION_WATCHDOG, "abandoned": int(abandoned)}

    async def settlement_servicing_step(self) -> Mapping[str, Any]:
        worker = self._settlement_worker()
        if worker is None:
            raise LifecycleRouteError(503, "settlement servicing worker is not initialized")
        processed = await worker.run_once()
        return {"loop": SETTLEMENT_SERVICING, "processed": int(processed)}

    def _capacity_runtime(self) -> CapacityRuntime:
        db = self._db()
        try:
            return self._capacity.runtime(lambda: db)
        except RuntimeError as exc:
            raise LifecycleRouteError(503, str(exc)) from exc

    async def capacity_events_step(self) -> Mapping[str, Any]:
        """One cycle of each site's quota capacity-event feed, at the poller's cursor."""
        runtime = self._capacity_runtime()
        sites = [
            (await runtime.drain_events_once(site_id)).to_dict() for site_id in runtime.site_ids
        ]
        return {
            "loop": CAPACITY_EVENTS_POLLER,
            "sites": sites,
            "applied_count": sum(int(site["applied_count"]) for site in sites),
        }

    async def capacity_events_preview(self) -> Mapping[str, Any]:
        """Each site's pending events, reported without applying them or moving a cursor."""
        runtime = self._capacity_runtime()
        sites = [
            (await runtime.preview_events_once(site_id)).to_dict()
            for site_id in runtime.site_ids
        ]
        return {
            "loop": CAPACITY_EVENTS_POLLER,
            "dry_run": True,
            "sites": sites,
            "pending_count": sum(int(site["pending_count"]) for site in sites),
        }

    async def capacity_events_poller_loop(
        self, loops: StorefrontLoopController, *, runtime: CapacityRuntime | None = None
    ) -> None:
        """Tail every quota authority's capacity-event feed, each site under its own gated name."""
        interval = self._settings.capacity_poll_interval()
        if runtime is None:
            runtime = self._capacity.runtime(self._sqlite_client)
        await run_capacity_event_pollers(
            functools.partial(runtime.poll_events, interval_seconds=interval),
            gate=loops.loop_gate(CAPACITY_EVENTS_POLLER),
            site_gate=functools.partial(capacity_site_gate, loops),
            wait=loops.idle,
            record_site_cycle=functools.partial(capacity_site_cycle_recorder, loops),
        )

    def register_steps(self, loops: StorefrontLoopController) -> None:
        """Register every loop's step, so each lifecycle route can run one."""
        loops.register_step(
            NEGOTIATION_WATCHDOG,
            route="negotiation-watchdog",
            step=self.negotiation_watchdog_step,
        )
        loops.register_step(
            SETTLEMENT_SERVICING,
            route="settlement-servicing",
            step=self.settlement_servicing_step,
        )
        for contributed in self._contributed_loops():
            loops.register_step(contributed.name, route=contributed.route, step=contributed.step)
        loops.register_step(
            CAPACITY_EVENTS_POLLER,
            route="capacity-events",
            step=self.capacity_events_step,
            preview=self.capacity_events_preview,
        )

    def _capacity_site_names(self, runtime: CapacityRuntime | None) -> tuple[str, ...]:
        """Each site's poller name, declared before the fan-out starts."""
        if runtime is not None:
            sites = tuple(runtime.site_ids)
        else:
            try:
                sites = self._capacity.configured_site_ids()
            except RuntimeError:
                sites = ()
        return tuple(capacity_site_loop_name(site) for site in sites)

    def register_loops(
        self,
        loops: StorefrontLoopController,
        *,
        capacity_runtime: CapacityRuntime | None = None,
    ) -> dict[str, float]:
        """Register each sweep's timer and the capacity-event fan-out; return each loop's interval.

        A sweep's first cycle is due one interval after its timer starts, so an operator can
        hold the loops at startup.
        """
        intervals = {
            NEGOTIATION_WATCHDOG: self._settings.watchdog().interval_seconds,
            SETTLEMENT_SERVICING: self._settings.settlement_servicing_interval(),
        }
        steps = {
            NEGOTIATION_WATCHDOG: ("negotiation-watchdog", self.negotiation_watchdog_step),
            SETTLEMENT_SERVICING: ("settlement-servicing", self.settlement_servicing_step),
        }
        for contributed in self._contributed_loops():
            intervals[contributed.name] = contributed.interval_seconds
            steps[contributed.name] = (contributed.route, contributed.step)
        for name, (route, step) in steps.items():
            loops.register_loop(
                name,
                route=route,
                step=step,
                interval_seconds=intervals[name],
                initial_delay_seconds=intervals[name],
            )
        loops.register_fan_out(
            CAPACITY_EVENTS_POLLER,
            route="capacity-events",
            step=self.capacity_events_step,
            preview=self.capacity_events_preview,
            run=functools.partial(
                self.capacity_events_poller_loop, loops, runtime=capacity_runtime
            ),
            children=functools.partial(self._capacity_site_names, capacity_runtime),
        )
        intervals[CAPACITY_EVENTS_POLLER] = self._settings.capacity_poll_interval()
        return intervals


async def start_background_tasks(
    storefront_loops: StorefrontLoops,
    loops: StorefrontLoopController,
    *,
    sqlite_client: Any,
    storefront_url: str,
    preflight: Callable[[], Awaitable[None]],
    seed: Callable[[], Awaitable[None]],
    startup_steps: Sequence[Callable[[], Awaitable[None]]] = (),
    capacity_runtime: CapacityRuntime | None = None,
    open_thread_store: Callable[..., Any] = get_thread_store,
) -> None:
    """Initialize the thread store, run the composed startup steps, the preflight, and the seed, then start every loop.

    The loops start last, so a sweep never runs before a startup step its work depends on.
    """
    open_thread_store(
        sqlite_client=sqlite_client,
        identity=PolicyIdentity(agent_url=storefront_url),
    )
    logger.info(
        "[STARTUP] Negotiation thread store initialized (storefront_url=%s)",
        storefront_url,
    )
    for step in startup_steps:
        await step()
    await preflight()
    await seed()
    intervals = storefront_loops.register_loops(loops, capacity_runtime=capacity_runtime)
    loops.start_loops(task_logger=logger)
    for name, interval in intervals.items():
        logger.info("[STARTUP] %s loop started (interval=%ss)", name, interval)


def seed_site(sites: Mapping[str, CapacitySite], selected: str | None) -> CapacitySite:
    """The pinned site a seed's quota is registered at: the selected one, else the only one."""
    if selected:
        try:
            return sites[selected]
        except KeyError as exc:
            raise RuntimeError(f"unknown capacity.seed_site {selected!r}") from exc
    if len(sites) != 1:
        raise RuntimeError("capacity.seed_site is required with multiple sites")
    return next(iter(sites.values()))


QUOTA_SETTINGS = frozenset({"resource_id", "total_units"})


@dataclass(frozen=True)
class ListingSeed:
    """A development seed: the quota to register and the listing to publish over it."""

    contributions: SellingContributions
    sqlite_client: Callable[[], Any]
    listing_service: Callable[[], Any | None]
    signer: Callable[[], Any | None]
    site: Callable[[], CapacitySite]
    accepted_escrows: Callable[[Mapping[str, Any]], list[dict[str, Any]]]
    settlement_settings: frozenset[str]
    pool_id: str
    admin_client: Callable[..., Any] = SiteCapacityAdminClient

    async def register_quota(self, *, resource_id: str, total_units: int) -> None:
        """Register the seed's quota resource through the authority's capacity-administration API."""
        site = self.site()
        signer = self.signer()
        if signer is None:
            raise RuntimeError("marketplace signer is unavailable for quota registration")
        admin_client = self.admin_client(
            site.url,
            signer=signer,
            expected_authorities=site.expected_authorities,
            timeout=30.0,
            transport=None,
            max_timestamp_skew=300,
        )
        try:
            await admin_client.register_resource(
                resource_id,
                pool_id=self.pool_id,
                capacity={"units": total_units},
                resource_type=self.contributions.offering_mode,
            )
        except SiteCapacityAdminClientError as exc:
            raise RuntimeError(
                f"quota registration for {resource_id!r} at {site.url!r} failed: {exc}"
            ) from exc
        logger.info(
            "[STARTUP] Seeded quota resource %s (total_units=%d) in the ledger",
            resource_id,
            total_units,
        )

    async def run(self, seed: Any) -> None:
        """Register the ``[seed]`` table's quota and publish a listing over it; a failure is logged, not raised."""
        if not isinstance(seed, Mapping) or not seed.get("resource_id"):
            return
        resource_id = str(seed["resource_id"])
        try:
            db = self.sqlite_client()
            # Idempotent: skip if a listing already derives from this resource.
            for row in await all_listings(db, status="open"):
                listing_resource = decode_stored(row.get("listing_resource") or {})
                if not isinstance(listing_resource, Mapping):
                    continue
                subject = self.contributions.issuance_projection(listing_resource)
                if subject.resource_id == resource_id:
                    logger.info(
                        "[STARTUP] Demo listing for resource %s already present; skipping seed",
                        resource_id,
                    )
                    return

            await self.register_quota(
                resource_id=resource_id,
                total_units=int(seed.get("total_units", 100)),
            )
            listing_service = self.listing_service()
            if listing_service is None:
                raise RuntimeError("listing service is not initialized")
            result = await listing_service.publish_from_quota(
                resource_id=resource_id,
                accepted_escrows=self.accepted_escrows(seed),
                **{
                    key: value
                    for key, value in seed.items()
                    if key not in QUOTA_SETTINGS | self.settlement_settings | SERVICE_FIELDS
                },
            )
            logger.info(
                "[STARTUP] Seeded demo listing %s (registry=%s)",
                result.get("listing_id"),
                result.get("registry_status"),
            )
        except Exception as exc:  # noqa: BLE001 - a seed must not crash the storefront
            logger.error("[STARTUP] Demo listing seed failed: %s", exc, exc_info=True)
