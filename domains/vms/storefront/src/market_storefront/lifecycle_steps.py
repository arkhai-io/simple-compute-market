"""One cycle of each VM storefront loop, registered as that loop's step.

Each step is the operation the loop's timer runs, and returns what that
operation returns, so an operator advancing a held loop exercises production
behaviour rather than a test path. None drives an iteration of the loop itself,
and none implements a transition the loop does not.

Steps resolve their collaborators from the container when they run, not when
they are registered, so they answer the same way whether or not startup has
started the loops. The steps are registered when this module is imported, which
the server does, so every lifecycle route can run one. Startup registers each
loop's timer over its step with `register_vm_loops` and then starts the timers:
the controller's timer gates, runs the step through the one cycle boundary an
operator's step takes, and waits. The capacity-event pollers are the one
exception in shape: their per-site fan-out lives in the capacity-publication kit, which
serializes each site's cycle with that site's step itself; startup registers
their aggregate as a fan-out beside the timers, and starts it with them.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from core_storefront.stage_log import stage_event
from market_capacity_publication import SiteProjectionState
from market_contact_exchange import INTRODUCTION_RETENTION_ROUTE
from market_storefront_kit import (
    LifecycleRouteError,
    NegotiationWatchdogPolicy,
    sweep_stale_negotiations,
)

import market_storefront.container as _container
from market_storefront.lifecycle import (
    CAPACITY_EVENTS_POLLER,
    enter_stage,
    FULFILLMENT_RESUME,
    INTRODUCTION_RETENTION,
    NEGOTIATION_WATCHDOG,
    PUBLICATION,
    SETTLEMENT_SERVICING,
    SITE_PROJECTION_POLLER,
    capacity_site_loop_name,
    register_fan_out,
    register_loop,
    register_step,
)
from market_storefront.services.fulfillment_resume_runtime import (
    fulfillment_resume_cycle_once,
)
from market_storefront.services.publication_loop import (
    new_publication_wake,
    publication_interval_seconds,
    run_publication_cycle_once,
)
from market_storefront.services.capacity_client import (
    capacity_events_poller_loop,
    site_projection_status,
)
from market_storefront.utils.config import (
    configured_capacity_sites,
    settings,
    settlement_servicing_interval,
    site_projection_poll_interval,
)

logger = logging.getLogger(__name__)


def _sqlite_client() -> Any:
    if _container.resolved_sqlite_client is None:
        raise LifecycleRouteError(503, "storefront persistence is not initialized")
    return _container.resolved_sqlite_client


def _site_projections() -> SiteProjectionState:
    if _container.resolved_site_projections is None:
        raise LifecycleRouteError(503, "site projection state is unavailable")
    return _container.resolved_site_projections


def _capacity_runtime() -> Any:
    if _container.resolved_capacity_runtime is None:
        raise LifecycleRouteError(503, "capacity runtime is unavailable")
    return _container.resolved_capacity_runtime


def negotiation_watchdog_policy() -> NegotiationWatchdogPolicy:
    """The watchdog's configured timeout and interval."""
    return NegotiationWatchdogPolicy(
        timeout_seconds=float(settings.negotiation_timeout_seconds),
        interval_seconds=float(settings.negotiation_watchdog_interval),
    )


async def negotiation_watchdog_step() -> Mapping[str, Any]:
    """One stale-negotiation sweep, under the watchdog's configured policy."""
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
    composition = _container.resolved_settlement_composition
    if composition is None:
        raise LifecycleRouteError(503, "settlement composition is not initialized")
    processed = await composition.worker.run_once()
    return {"loop": SETTLEMENT_SERVICING, "processed": int(processed)}


async def fulfillment_resume_step() -> Mapping[str, Any]:
    """Re-drive unfinished accepted deliveries, then accepted payment deals."""
    await fulfillment_resume_cycle_once(sqlite_client=_sqlite_client())
    return {"loop": FULFILLMENT_RESUME}


async def site_projections_step() -> Mapping[str, Any]:
    """The projection poller's cycle: poll every site's families in place.

    The timer runs this same step, so an operator stepping the held poller runs
    exactly its cycle: a site that cannot be reached keeps its last generation
    as `stale`, and a resource-pool change wakes publication.
    """
    state = _site_projections()
    await state.poll_once()
    return {"loop": SITE_PROJECTION_POLLER, "sites": site_projection_status(state)}


async def capacity_events_step() -> Mapping[str, Any]:
    """Run exactly one cycle of each site's capacity-event feed.

    One cycle per site per call, not a drain to the head: a truncated page
    reports `truncated`, so a caller advancing deliberately steps again and sees
    each page separately. It addresses the same per-site cursor the running
    poller holds, and is intended to run while the loop is held, so the advance
    has the feed to itself.
    """
    runtime = _capacity_runtime()
    sites = [(await runtime.drain_events_once(site_id)).to_dict() for site_id in runtime.site_ids]
    logger.info("[ADMIN] Capacity-event cycle advanced: %s", sites)
    return {
        "loop": CAPACITY_EVENTS_POLLER,
        "sites": sites,
        "applied_count": sum(int(site["applied_count"]) for site in sites),
    }


async def capacity_events_preview() -> Mapping[str, Any]:
    """Read each site's feed and report the cycle without running it.

    Capacity deltas are what close and reopen derived listings, so an advance
    changes what buyers can discover; a caller that sees the pending events
    first can assert on the cause before committing to the effect. Emits
    nothing, reconciles nothing, and leaves every cursor where it was.
    """
    runtime = _capacity_runtime()
    sites = [(await runtime.preview_events_once(site_id)).to_dict() for site_id in runtime.site_ids]
    return {
        "loop": CAPACITY_EVENTS_POLLER,
        "dry_run": True,
        "sites": sites,
        "pending_count": sum(int(site["pending_count"]) for site in sites),
    }


async def publication_step() -> Mapping[str, Any]:
    # Resolving what the cycle reads is its compose stage, so a storefront with
    # no projection state composed fails there.
    enter_stage("compose")
    result = await run_publication_cycle_once(
        dry_run=False, site_projections=_site_projections()
    )
    logger.info("[ADMIN] Publication cycle advanced: %s", result["counts"])
    return result


async def publication_preview() -> Mapping[str, Any]:
    """Derive the next cycle's actions and apply none of them."""
    return await run_publication_cycle_once(
        dry_run=True, site_projections=_site_projections()
    )


def _introduction_retention() -> Any:
    composition = _container.resolved_contact_exchange
    return composition.retention() if composition is not None else None


async def introduction_retention_step() -> Mapping[str, Any]:
    """Run one retention sweep now; answers disabled while contact exchange is."""
    retention = _introduction_retention()
    if retention is None:
        return {"loop": INTRODUCTION_RETENTION, "enabled": False}
    report = await retention.sweep_once()
    if report.get("deleted"):
        logger.info(
            "[RETENTION] deleted payloads of %d introduction(s)", report["deleted"]
        )
    return report


async def introduction_retention_preview() -> Mapping[str, Any]:
    """Which introductions the next sweep would delete, deleting none."""
    retention = _introduction_retention()
    if retention is None:
        return {"loop": INTRODUCTION_RETENTION, "enabled": False}
    return await retention.preview()


def _fulfillment_resume_interval() -> float:
    return float(getattr(settings, "fulfillment_resume_sweep_interval", 30))


def register_vm_lifecycle_steps() -> None:
    """Register every loop's step, so each lifecycle route can run one."""
    register_step(NEGOTIATION_WATCHDOG, route="negotiation-watchdog", step=negotiation_watchdog_step)
    register_step(SETTLEMENT_SERVICING, route="settlement-servicing", step=settlement_servicing_step)
    register_step(FULFILLMENT_RESUME, route="fulfillment-resume", step=fulfillment_resume_step)
    register_step(
        SITE_PROJECTION_POLLER, route="site-projections", step=site_projections_step
    )
    register_step(
        CAPACITY_EVENTS_POLLER,
        route="capacity-events",
        step=capacity_events_step,
        preview=capacity_events_preview,
    )
    register_step(PUBLICATION, route="publication", step=publication_step, preview=publication_preview)
    register_step(
        INTRODUCTION_RETENTION,
        route=INTRODUCTION_RETENTION_ROUTE,
        step=introduction_retention_step,
        preview=introduction_retention_preview,
    )


async def capacity_events_fan_out() -> None:
    """The capacity-event aggregate loop's task: every site's poller."""
    await capacity_events_poller_loop(_container.resolved_sqlite_client)


def _capacity_site_names() -> tuple[str, ...]:
    """Each configured site's capacity-event poller name, declared up front.

    A storefront configured with no site refuses to start before any loop
    registers, so none here only means the fan-out declares its sites as it
    reaches them.
    """
    try:
        sites = configured_capacity_sites()
    except RuntimeError:
        return ()
    return tuple(capacity_site_loop_name(site) for site in sites)


def register_vm_loops(
    *, retention_interval_seconds: float | None = None
) -> dict[str, float]:
    """Register each loop's timer over its step, with its configured interval,
    and the capacity-event pollers' fan-out.

    Intervals are read when this runs, so startup registers what the running
    configuration states. Publication, the site-projection poller, and
    fulfillment resume run their first cycle as soon as their timers start;
    the watchdog, servicing, and retention sweeps run theirs one interval
    later. Those sweeps change durable deals and introductions, and holding the
    first one back gives an operator who holds the loops as the storefront
    starts a whole interval to do so. The retention sweep is registered only
    when ``retention_interval_seconds`` is given, which startup does while
    contact exchange is composed. Publication gets a fresh wake each time,
    bound to the event loop its timer runs on. Returns each registered loop's
    interval, by loop name.
    """
    intervals = {
        NEGOTIATION_WATCHDOG: negotiation_watchdog_policy().interval_seconds,
        SETTLEMENT_SERVICING: settlement_servicing_interval(),
        FULFILLMENT_RESUME: _fulfillment_resume_interval(),
        SITE_PROJECTION_POLLER: site_projection_poll_interval(),
        PUBLICATION: publication_interval_seconds(),
    }
    # Each site's poller waits the poll interval between its cycles.
    register_fan_out(
        CAPACITY_EVENTS_POLLER,
        route="capacity-events",
        step=capacity_events_step,
        preview=capacity_events_preview,
        run=capacity_events_fan_out,
        children=_capacity_site_names,
    )
    intervals[CAPACITY_EVENTS_POLLER] = intervals[SITE_PROJECTION_POLLER]
    register_loop(
        NEGOTIATION_WATCHDOG,
        route="negotiation-watchdog",
        step=negotiation_watchdog_step,
        interval_seconds=intervals[NEGOTIATION_WATCHDOG],
        initial_delay_seconds=intervals[NEGOTIATION_WATCHDOG],
    )
    register_loop(
        SETTLEMENT_SERVICING,
        route="settlement-servicing",
        step=settlement_servicing_step,
        interval_seconds=intervals[SETTLEMENT_SERVICING],
        initial_delay_seconds=intervals[SETTLEMENT_SERVICING],
    )
    register_loop(
        FULFILLMENT_RESUME,
        route="fulfillment-resume",
        step=fulfillment_resume_step,
        interval_seconds=intervals[FULFILLMENT_RESUME],
    )
    register_loop(
        SITE_PROJECTION_POLLER,
        route="site-projections",
        step=site_projections_step,
        interval_seconds=intervals[SITE_PROJECTION_POLLER],
    )
    register_loop(
        PUBLICATION,
        route="publication",
        step=publication_step,
        preview=publication_preview,
        interval_seconds=intervals[PUBLICATION],
        wake=new_publication_wake(),
    )
    if retention_interval_seconds is not None:
        intervals[INTRODUCTION_RETENTION] = retention_interval_seconds
        register_loop(
            INTRODUCTION_RETENTION,
            route=INTRODUCTION_RETENTION_ROUTE,
            step=introduction_retention_step,
            preview=introduction_retention_preview,
            interval_seconds=retention_interval_seconds,
            initial_delay_seconds=retention_interval_seconds,
        )
    return intervals


register_vm_lifecycle_steps()
