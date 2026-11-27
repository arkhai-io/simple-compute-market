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
from market_site_client import (
    SiteCapacityAdminClient,
    SiteCapacityAdminClientError,
    SiteCapacityClientError,
)
from market_storefront_kit import (
    LifecycleRouteError,
    NegotiationWatchdogPolicy,
    StorefrontLoopController,
    sweep_stale_negotiations,
)

from arkhai_api_selling.capacity import CapacitySite, QuotaCapacity
from arkhai_api_selling.contributions import SellingContributions
from arkhai_api_selling.issuance import decode_stored
from arkhai_api_selling.listings import SettlementMechanismUnreachable
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
    # None delays the first cycle one interval, as the storefront's own sweeps.
    initial_delay_seconds: float | None = None


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
        listing_seed: Callable[[], ListingSeedProgress | None] = lambda: None,
    ) -> None:
        self._sqlite_client = sqlite_client
        self._settlement_worker = settlement_worker
        self._capacity = capacity
        self._settings = settings
        self._contributed_loops = contributed_loops
        self._listing_seed = listing_seed

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

    async def listing_seed_step(self) -> Mapping[str, Any]:
        """One attempt at the configured seed listing, until it is done or given up."""
        seed = self._listing_seed()
        if seed is None:
            raise LifecycleRouteError(503, "no seed listing is configured")
        return await seed.step()

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
        # Registered with the loop it steps, which runs only when a seed is configured.
        if self._listing_seed() is not None:
            loops.register_step(
                LISTING_SEED, route=LISTING_SEED_ROUTE, step=self.listing_seed_step
            )
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
        hold the loops at startup; a contributed loop may start at once. While a seed is
        configured, the listing seed is registered too, its first attempt as its timer
        starts and retried every couple of seconds while it waits.
        """
        intervals = {
            NEGOTIATION_WATCHDOG: self._settings.watchdog().interval_seconds,
            SETTLEMENT_SERVICING: self._settings.settlement_servicing_interval(),
        }
        steps = {
            NEGOTIATION_WATCHDOG: ("negotiation-watchdog", self.negotiation_watchdog_step),
            SETTLEMENT_SERVICING: ("settlement-servicing", self.settlement_servicing_step),
        }
        delays = dict(intervals)
        for contributed in self._contributed_loops():
            intervals[contributed.name] = contributed.interval_seconds
            steps[contributed.name] = (contributed.route, contributed.step)
            delays[contributed.name] = (
                contributed.interval_seconds
                if contributed.initial_delay_seconds is None
                else contributed.initial_delay_seconds
            )
        for name, (route, step) in steps.items():
            loops.register_loop(
                name,
                route=route,
                step=step,
                interval_seconds=intervals[name],
                initial_delay_seconds=delays[name],
            )
        if self._listing_seed() is not None:
            intervals[LISTING_SEED] = LISTING_SEED_INTERVAL_SECONDS
            loops.register_loop(
                LISTING_SEED,
                route=LISTING_SEED_ROUTE,
                step=self.listing_seed_step,
                interval_seconds=LISTING_SEED_INTERVAL_SECONDS,
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
    startup_steps: Sequence[Callable[[], Awaitable[None]]] = (),
    capacity_runtime: CapacityRuntime | None = None,
    open_thread_store: Callable[..., Any] = get_thread_store,
) -> None:
    """Initialize the thread store, run the composed startup steps, then start every loop.

    The loops start last, so a sweep never runs before a startup step its work depends on.
    Nothing waits for the quota authority to answer: the configured seed listing is created
    by its loop's step, never here, and waits while the authority or a mechanism it uses
    cannot be reached.
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
    intervals = storefront_loops.register_loops(loops, capacity_runtime=capacity_runtime)
    loops.start_loops(task_logger=logger)
    for name, interval in intervals.items():
        logger.info("[STARTUP] %s loop started (interval=%ss)", name, interval)


async def stop_background_tasks(loops: StorefrontLoopController | None) -> None:
    """Stop every loop and wait for it to end, before shutdown clears what the loops read.

    A cancelled loop may still be unwinding across an await, so cancelling alone is
    not enough. ``loops`` is None when the storefront never started them.
    """
    if loops is not None:
        await loops.stop_loops()


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

LISTING_SEED = "listing_seed"
LISTING_SEED_ROUTE = "listing-seed"

#: How often the seed is retried while it waits. Short, so the seed publishes
#: moments after a mechanism it waits on is first reached rather than a whole
#: interval later; a cycle once the seed is done or given up does nothing.
LISTING_SEED_INTERVAL_SECONDS = 2.0

PENDING = "pending"
WAITING = "waiting"
GIVEN_UP = "given_up"
DONE = "done"

#: Why a seed waits: the quota authority did not answer.
AUTHORITY_UNANSWERED = "credits_service_unanswered"
#: Why a seed waits: a mechanism it uses is unknown; the report names which.
SETTLEMENT_MECHANISM_UNREACHED = "settlement_mechanism_unreached"


class ListingSeedGivenUp(Exception):
    """The cycle in which the seed gave up; its message is the error's type."""


class _Waiting(Exception):
    """A dependency the seed needs has not answered; the next cycle retries."""

    def __init__(self, reason: str, *, mechanisms: tuple[str, ...] = ()) -> None:
        super().__init__(reason)
        self.reason = reason
        self.mechanisms = mechanisms


def _unanswered(exc: SiteCapacityClientError) -> bool:
    """Whether a site-client failure is the authority not answering, rather
    than refusing: no response at all, or a server error."""
    return exc.status_code is None or exc.status_code >= 500


@dataclass(frozen=True)
class ListingSeed:
    """A development seed: the quota to register and the listing to publish over it.

    :meth:`progress` binds a ``[seed]`` table to the ``listing-seed`` loop
    step's state. The seed is never created during startup; see
    :class:`ListingSeedProgress` for what each cycle does.
    """

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
        """Register the seed's quota resource through the authority's capacity-administration API.

        The site is resolved when the seed registers, so a site the configuration
        cannot name gives the seed up rather than stopping startup. A
        re-registration re-asserts the resource. Raises the client's error, which
        says whether the authority refused or did not answer.
        """
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
        await admin_client.register_resource(
            resource_id,
            pool_id=self.pool_id,
            capacity={"units": total_units},
            resource_type=self.contributions.offering_mode,
        )

    async def find_listing(self, resource_id: str) -> str | None:
        """The open listing that derives from ``resource_id``, if any.

        Every open listing is read: a seeded listing missed here is one the seed
        would create a second time.
        """
        for row in await all_listings(self.sqlite_client(), status="open"):
            listing_resource = decode_stored(row.get("listing_resource") or {})
            if not isinstance(listing_resource, Mapping):
                continue
            if self.contributions.issuance_projection(listing_resource).resource_id == resource_id:
                return str(row.get("listing_id"))
        return None

    async def publish(self, seed: Mapping[str, Any]) -> dict[str, Any]:
        """Create the seed's listing, waiting for every mechanism it uses."""
        listing_service = self.listing_service()
        if listing_service is None:
            raise RuntimeError("listing service is not initialized")
        return await listing_service.publish_from_quota(
            resource_id=str(seed["resource_id"]),
            accepted_escrows=self.accepted_escrows(seed),
            wait_for_every_mechanism=True,
            **{
                key: value
                for key, value in seed.items()
                if key not in QUOTA_SETTINGS | self.settlement_settings | SERVICE_FIELDS
            },
        )

    def progress(self, seed: Any) -> ListingSeedProgress | None:
        """The ``[seed]`` table's progress, or None without a seed's ``resource_id``."""
        if not isinstance(seed, Mapping) or not seed.get("resource_id"):
            return None
        return ListingSeedProgress(
            seed=dict(seed),
            register_quota=self.register_quota,
            find_listing=self.find_listing,
            publish=self.publish,
        )


@dataclass
class ListingSeedProgress:
    """The seed's progress across the ``listing-seed`` step's cycles.

    Each cycle tries once, and the outcome decides what the next does:

    - **waiting** while a dependency has not answered: the quota authority could
      not be reached for the quota registration or for the reads the create
      makes of the resource's availability and pool, or a mechanism the seed
      uses is unknown, unready only for reachability. A listing's options are
      fixed when it is created, so the seed waits for every mechanism it uses
      rather than publishing without one. Nothing is logged at error level.
    - **given up** on any other failure, which waiting does not repair. The
      cycle that gives up fails, so the loop controller records and logs it
      once; later cycles do nothing.
    - **done** once a listing derives from the seed's resource, whether this
      step created it or found it.

    A cycle's report names why the seed waits or gave up by a reason code and an
    error type, never an error's text, which may carry a dependency's address.
    """

    seed: Mapping[str, Any]
    register_quota: Callable[..., Awaitable[None]]
    find_listing: Callable[[str], Awaitable[str | None]]
    publish: Callable[[Mapping[str, Any]], Awaitable[Mapping[str, Any]]]
    state: str = PENDING
    reason: str | None = None
    mechanisms: tuple[str, ...] = ()
    listing_id: str | None = None
    attempts: int = 0
    # The authority re-asserts a registration, so once it has answered there is
    # nothing to send again while the seed waits on a mechanism.
    registered: bool = False

    @property
    def resource_id(self) -> str:
        return str(self.seed["resource_id"])

    def report(self) -> dict[str, Any]:
        return {
            "loop": LISTING_SEED,
            "state": self.state,
            "reason": self.reason,
            "mechanisms": list(self.mechanisms),
            "listing_id": self.listing_id,
            "attempts": self.attempts,
        }

    async def step(self) -> dict[str, Any]:
        """One attempt, unless the seed is done or given up.

        Raises ``ListingSeedGivenUp`` from the cycle that gives up.
        """
        if self.state in (DONE, GIVEN_UP):
            return self.report()
        self.attempts += 1
        try:
            await self._attempt()
        except _Waiting as waiting:
            if (self.state, self.reason, self.mechanisms) != (
                WAITING,
                waiting.reason,
                waiting.mechanisms,
            ):
                logger.info(
                    "[SEED] listing seed for %s waiting: %s %s",
                    self.resource_id,
                    waiting.reason,
                    ",".join(waiting.mechanisms),
                )
            self.state, self.reason, self.mechanisms = (
                WAITING,
                waiting.reason,
                waiting.mechanisms,
            )
        except Exception as exc:
            self.state, self.reason, self.mechanisms = GIVEN_UP, type(exc).__name__, ()
            raise ListingSeedGivenUp(self.reason) from exc
        return self.report()

    async def _attempt(self) -> None:
        existing = await self.find_listing(self.resource_id)
        if existing is not None:
            self.state, self.reason, self.mechanisms = DONE, None, ()
            self.listing_id = existing
            logger.info("[SEED] listing %s already derives from %s", existing, self.resource_id)
            return
        if not self.registered:
            try:
                await self.register_quota(
                    resource_id=self.resource_id,
                    total_units=int(self.seed.get("total_units", 100)),
                )
            except SiteCapacityAdminClientError as exc:
                if _unanswered(exc):
                    raise _Waiting(AUTHORITY_UNANSWERED) from exc
                raise
            self.registered = True
        try:
            result = await self.publish(self.seed)
        except SettlementMechanismUnreachable as exc:
            raise _Waiting(
                SETTLEMENT_MECHANISM_UNREACHED, mechanisms=exc.mechanisms
            ) from exc
        except SiteCapacityClientError as exc:
            if _unanswered(exc):
                raise _Waiting(AUTHORITY_UNANSWERED) from exc
            raise
        self.state, self.reason, self.mechanisms = DONE, None, ()
        self.listing_id = str(result.get("listing_id"))
        logger.info(
            "[SEED] published listing %s (registry=%s)",
            self.listing_id,
            result.get("registry_status"),
        )
