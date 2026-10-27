"""The API-credit storefront's loops: one cycle of each, and each loop's timer.

Each step calls the operation the loop's timer invokes and returns what it
returns, so an operator advancing a held loop exercises production behaviour.
Every loop is registered on the storefront's one loop controller twice over:
its step when the services start (``register_api_credit_lifecycle_steps``), so
every lifecycle route can run one, and the loop itself when the startup tasks
run (``register_api_credit_loops``), which ``start_loops`` then starts. Each
sweep is a timer loop: the controller's timer runs its step through the same
cycle boundary an operator's step takes, one cycle at a time. The
capacity-event pollers are a fan-out, the exception in shape: the kit runs
them one cycle per site inside the aggregate loop's task, serializes each
site's cycle with that site's step itself, and reports each site's timer
cycles under the site's own name, declared as the aggregate loop's child. See
openspec/specs/market-composition/spec.md, "Storefront timer loops are held and
stepped through one kit controller". Steps resolve their collaborators from the
container when they run.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from functools import partial
from typing import Any

from core_storefront.domain_registry import (
    StorefrontDomainBindingError,
    StorefrontDomainRegistryError,
)
from core_storefront.stage_log import stage_event
from market_alkahest import ALKAHEST_CHAIN_PROBE_LOOP, ALKAHEST_CHAIN_PROBE_ROUTE
from market_capacity_publication import (
    CapacityBindingError,
    CapacityConfigurationError,
    SiteEventCycle,
)
from market_storefront_kit import (
    LifecycleRouteError,
    NegotiationWatchdogPolicy,
    StorefrontLoopController,
    sweep_stale_negotiations,
)

import apicredits_storefront.container as _container
from apicredits_storefront.listing_seed import LISTING_SEED, LISTING_SEED_ROUTE
from apicredits_storefront.services.capacity_client import (
    build_capacity_runtime,
    capacity_events_poller_loop,
    capacity_poll_interval,
    configured_site_ids,
)
from apicredits_storefront.utils.config import seconds_setting, settlement_servicing_interval

logger = logging.getLogger(__name__)

NEGOTIATION_WATCHDOG = "negotiation_watchdog"
SETTLEMENT_SERVICING = "settlement_servicing"
PAYMENT_RECONCILIATION = "payment_reconciliation"
CAPACITY_EVENTS_POLLER = "capacity_events_poller"

#: The errors whose messages a recorded cycle outcome may carry: the capacity
#: and domain-registration refusals the storefront's cycles raise for a site or
#: binding that does not resolve, or a registration that does not match durable
#: state. Their text names keys, configured site, listing, and domain
#: identifiers, and reasons, all public configuration; none carries a secret or
#: a credential. The check is `isinstance`, so a subclass of one is disclosed
#: too; every other exception reaches status by its type alone.
DISCLOSED_CYCLE_ERRORS: tuple[type[BaseException], ...] = (
    CapacityBindingError,
    CapacityConfigurationError,
    StorefrontDomainBindingError,
    StorefrontDomainRegistryError,
)


def api_credit_loop_controller(**options: Any) -> StorefrontLoopController:
    """The loop controller for one API-credit storefront process.

    ``options`` are the controller's own seams (a clock, a cycle-lock factory);
    the disclosed error types are always this storefront's.
    """
    options.setdefault("logger", logger)
    return StorefrontLoopController(disclosed_errors=DISCLOSED_CYCLE_ERRORS, **options)


def capacity_site_loop_name(site: str) -> str:
    """The gated name of one site's capacity-event poller.

    Each site acknowledges under its own name, so one site reaching its gate
    cannot answer for another still writing.
    """
    return f"{CAPACITY_EVENTS_POLLER}:{site}"


def capacity_site_gate(loops: StorefrontLoopController, site: str) -> Callable[[], bool]:
    """Declare one site's capacity-event poller as a child of the aggregate
    loop, whose task runs its cycles, and bind its gate."""
    return loops.declare(capacity_site_loop_name(site), parent=CAPACITY_EVENTS_POLLER)


def capacity_site_cycle_recorder(
    loops: StorefrontLoopController, site: str
) -> Callable[[SiteEventCycle], None]:
    """Where one site's capacity-event poller reports each cycle its timer ran.

    The kit serializes each site's cycles under that site's cursor lock rather
    than the controller's, so each cycle's outcome is recorded through the
    recorder the controller issues the site's declared name
    (`capacity_site_gate` first).
    """
    record = loops.cycle_recorder(capacity_site_loop_name(site))

    def report(cycle: SiteEventCycle) -> None:
        record(cycle.exception)

    return report


def negotiation_watchdog_policy() -> NegotiationWatchdogPolicy:
    """The watchdog's timeout and interval, as configured, each refused by its
    key unless it is a usable number of seconds."""
    return NegotiationWatchdogPolicy(
        timeout_seconds=seconds_setting("negotiation_timeout_seconds", 1800),
        interval_seconds=seconds_setting("negotiation_watchdog_interval", 60),
        log_loop_start=False,
        log_cutoff=False,
    )


def _payment_reconciliation_interval() -> float:
    return seconds_setting("payment_reconciliation_interval", 30)


def _sqlite_client() -> Any:
    if _container.resolved_sqlite_client is None:
        raise LifecycleRouteError(503, "storefront persistence is not initialized")
    return _container.resolved_sqlite_client


async def negotiation_watchdog_step() -> Mapping[str, Any]:
    policy = negotiation_watchdog_policy()
    abandoned = await sweep_stale_negotiations(
        _sqlite_client(),
        policy,
        emit_stage_event=stage_event,
        logger=logger,
    )
    if abandoned:
        logger.info(
            "[WATCHDOG] marked %d stale thread(s) as %s", abandoned, policy.terminal_state
        )
    return {"loop": NEGOTIATION_WATCHDOG, "abandoned": int(abandoned)}


async def settlement_servicing_step() -> Mapping[str, Any]:
    worker = _container.resolved_settlement_worker
    if worker is None:
        raise LifecycleRouteError(503, "settlement servicing worker is not initialized")
    processed = await worker.run_once()
    return {"loop": SETTLEMENT_SERVICING, "processed": int(processed)}


def payment_reconciliation_service() -> Any | None:
    """The payment settlement service, or None when payments is not composed."""
    composition = _container.resolved_settlement_composition
    return composition.payment_service(_sqlite_client()) if composition is not None else None


async def payment_reconciliation_step() -> Mapping[str, Any]:
    service = payment_reconciliation_service()
    if service is None:
        return {"loop": PAYMENT_RECONCILIATION, "attempted": 0, "failed": 0}
    done = await service.reconcile_once()
    return {"loop": PAYMENT_RECONCILIATION, "attempted": done.attempted, "failed": done.failed}


async def alkahest_chain_probe_step() -> Mapping[str, Any]:
    """Probe each configured chain."""
    probe = _container.resolved_alkahest_chain_probe
    if probe is None:
        raise LifecycleRouteError(503, "Alkahest chain probe is not composed")
    return {"loop": ALKAHEST_CHAIN_PROBE_LOOP, **(await probe.step())}


async def listing_seed_step() -> Mapping[str, Any]:
    """One attempt at the configured seed listing, until it is done or given up."""
    seed = _container.resolved_listing_seed
    if seed is None:
        raise LifecycleRouteError(503, "no seed listing is configured")
    return await seed.step()


#: How often the seed is retried while it waits. Short, so the seed publishes
#: moments after the chain probe's first cycle reaches its chain rather than a
#: whole probe interval later; a cycle once the seed is done or given up does
#: nothing.
LISTING_SEED_INTERVAL_SECONDS = 2.0


def _listing_seed_interval() -> float:
    """The seed's retry interval, no longer than the chain probe's, so a seed
    waiting on a chain retries after every probe cycle."""
    probe = _container.resolved_alkahest_chain_probe
    if probe is None:
        return LISTING_SEED_INTERVAL_SECONDS
    return min(LISTING_SEED_INTERVAL_SECONDS, probe.interval_seconds)


def _capacity_runtime() -> Any:
    client = _sqlite_client()
    try:
        return build_capacity_runtime(lambda: client)
    except RuntimeError as exc:
        raise LifecycleRouteError(503, str(exc)) from exc


async def capacity_events_step() -> Mapping[str, Any]:
    """One cycle of each site's quota capacity-event feed, at the poller's cursor."""
    runtime = _capacity_runtime()
    sites = [(await runtime.drain_events_once(site_id)).to_dict() for site_id in runtime.site_ids]
    return {
        "loop": CAPACITY_EVENTS_POLLER,
        "sites": sites,
        "applied_count": sum(int(site["applied_count"]) for site in sites),
    }


async def capacity_events_preview() -> Mapping[str, Any]:
    """Each site's pending events, reported without applying them or moving a cursor."""
    runtime = _capacity_runtime()
    sites = [(await runtime.preview_events_once(site_id)).to_dict() for site_id in runtime.site_ids]
    return {
        "loop": CAPACITY_EVENTS_POLLER,
        "dry_run": True,
        "sites": sites,
        "pending_count": sum(int(site["pending_count"]) for site in sites),
    }


def register_api_credit_lifecycle_steps(loops: StorefrontLoopController) -> None:
    """Register every loop's step, so each lifecycle route can run one."""
    loops.register_step(
        NEGOTIATION_WATCHDOG, route="negotiation-watchdog", step=negotiation_watchdog_step
    )
    loops.register_step(
        SETTLEMENT_SERVICING, route="settlement-servicing", step=settlement_servicing_step
    )
    # Registered with the loop it steps, which runs only when payments is composed.
    if payment_reconciliation_service() is not None:
        loops.register_step(
            PAYMENT_RECONCILIATION,
            route="payment-reconciliation",
            step=payment_reconciliation_step,
        )
    loops.register_step(
        CAPACITY_EVENTS_POLLER,
        route="capacity-events",
        step=capacity_events_step,
        preview=capacity_events_preview,
    )
    # Registered with the loop it steps, which runs only when Alkahest is composed.
    if _container.resolved_alkahest_chain_probe is not None:
        loops.register_step(
            ALKAHEST_CHAIN_PROBE_LOOP,
            route=ALKAHEST_CHAIN_PROBE_ROUTE,
            step=alkahest_chain_probe_step,
        )
    # Registered with the loop it steps, which runs only when a seed is configured.
    if _container.resolved_listing_seed is not None:
        loops.register_step(LISTING_SEED, route=LISTING_SEED_ROUTE, step=listing_seed_step)


def _capacity_site_names(runtime: Any | None) -> tuple[str, ...]:
    """Each site's capacity-event poller name, declared up front: the given
    runtime's sites, else the configured ones.

    A configuration naming no site fails the fan-out itself when it starts, and
    a site the fan-out reaches later declares itself then.
    """
    if runtime is not None:
        sites = tuple(runtime.site_ids)
    else:
        try:
            sites = configured_site_ids()
        except RuntimeError:
            sites = ()
    return tuple(capacity_site_loop_name(site) for site in sites)


def register_api_credit_loops(
    loops: StorefrontLoopController, *, capacity_runtime: Any | None = None
) -> dict[str, float]:
    """Register every loop with its configured interval: each sweep's timer
    over its step, and the capacity-event pollers' fan-out.

    The sweeps are the watchdog, settlement servicing, and, while Arkhai
    payments is composed, payment reconciliation. Intervals are read when this
    runs, so startup registers what the running configuration states. Each
    sweep changes durable deals, so its first cycle is due one interval after
    its timer starts, giving an operator who holds the loops as the storefront
    starts a whole interval to do so. While Alkahest is composed the chain
    probe is registered too, its first cycle as its timer starts, since
    readiness reads every chain unprobed until it has run. While a seed is
    configured, the listing seed is registered too, its first attempt as its
    timer starts and retried every couple of seconds while it waits.
    ``capacity_runtime`` is the runtime the pollers drain, the configured one
    unless given. ``start_loops`` on the controller then starts every one.
    Returns each registered loop's interval, by loop name.
    """
    intervals = {
        NEGOTIATION_WATCHDOG: negotiation_watchdog_policy().interval_seconds,
        SETTLEMENT_SERVICING: settlement_servicing_interval(),
    }
    steps = {
        NEGOTIATION_WATCHDOG: ("negotiation-watchdog", negotiation_watchdog_step),
        SETTLEMENT_SERVICING: ("settlement-servicing", settlement_servicing_step),
    }
    if payment_reconciliation_service() is not None:
        intervals[PAYMENT_RECONCILIATION] = _payment_reconciliation_interval()
        steps[PAYMENT_RECONCILIATION] = ("payment-reconciliation", payment_reconciliation_step)
    for name, (route, step) in steps.items():
        loops.register_loop(
            name,
            route=route,
            step=step,
            interval_seconds=intervals[name],
            initial_delay_seconds=intervals[name],
        )
    probe = _container.resolved_alkahest_chain_probe
    if probe is not None:
        intervals[ALKAHEST_CHAIN_PROBE_LOOP] = probe.interval_seconds
        loops.register_loop(
            ALKAHEST_CHAIN_PROBE_LOOP,
            route=ALKAHEST_CHAIN_PROBE_ROUTE,
            step=alkahest_chain_probe_step,
            interval_seconds=probe.interval_seconds,
        )
    if _container.resolved_listing_seed is not None:
        intervals[LISTING_SEED] = _listing_seed_interval()
        loops.register_loop(
            LISTING_SEED,
            route=LISTING_SEED_ROUTE,
            step=listing_seed_step,
            interval_seconds=intervals[LISTING_SEED],
        )
    loops.register_fan_out(
        CAPACITY_EVENTS_POLLER,
        route="capacity-events",
        step=capacity_events_step,
        preview=capacity_events_preview,
        run=partial(capacity_events_poller_loop, loops, runtime=capacity_runtime),
        children=partial(_capacity_site_names, capacity_runtime),
    )
    intervals[CAPACITY_EVENTS_POLLER] = capacity_poll_interval()
    return intervals


__all__ = [
    "CAPACITY_EVENTS_POLLER",
    "DISCLOSED_CYCLE_ERRORS",
    "NEGOTIATION_WATCHDOG",
    "PAYMENT_RECONCILIATION",
    "SETTLEMENT_SERVICING",
    "api_credit_loop_controller",
    "capacity_site_cycle_recorder",
    "capacity_site_gate",
    "capacity_site_loop_name",
    "negotiation_watchdog_policy",
    "register_api_credit_lifecycle_steps",
    "register_api_credit_loops",
]
