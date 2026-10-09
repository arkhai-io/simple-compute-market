"""One cycle of each VM storefront loop, registered as that loop's step.

Each step calls the operation the loop's timer already invokes and returns what
that operation returns, so an operator advancing a held loop exercises
production behaviour rather than a test path. None drives an iteration of the
loop itself, and none implements a transition the loop does not.

Steps resolve their collaborators from the container when they run, not when
they are registered, so they answer the same way whether or not startup has
started the loops.
Registration happens when this module is imported, which the admin routes do.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from core_storefront.stage_log import stage_event
from market_contact_exchange import INTRODUCTION_RETENTION_ROUTE
from market_storefront_kit import LifecycleRouteError, sweep_stale_negotiations

import market_storefront.container as _container
from market_storefront.lifecycle import (
    CAPACITY_EVENTS_POLLER,
    FULFILLMENT_RESUME,
    INTRODUCTION_RETENTION,
    NEGOTIATION_WATCHDOG,
    PUBLICATION,
    SETTLEMENT_SERVICING,
    SITE_PROJECTION_POLLER,
    register_step,
)
from market_storefront.services.fulfillment_resume_runtime import (
    resume_incomplete_fulfillments_once,
)
from market_storefront.services.publication_loop import run_publication_cycle_once
from market_storefront.services.site_projection_cache import (
    load_site_projections,
    projection_status_summary,
)
from market_storefront.startup import _negotiation_watchdog_policy

logger = logging.getLogger(__name__)


def _sqlite_client() -> Any:
    if _container.resolved_sqlite_client is None:
        raise LifecycleRouteError(503, "storefront persistence is not initialized")
    return _container.resolved_sqlite_client


def _capacity_runtime() -> Any:
    if _container.resolved_capacity_runtime is None:
        raise LifecycleRouteError(503, "capacity runtime is unavailable")
    return _container.resolved_capacity_runtime


async def negotiation_watchdog_step() -> Mapping[str, Any]:
    """One stale-negotiation sweep, under the watchdog's configured policy."""
    abandoned = await sweep_stale_negotiations(
        _sqlite_client(),
        _negotiation_watchdog_policy(),
        emit_stage_event=stage_event,
        logger=logger,
    )
    return {"loop": NEGOTIATION_WATCHDOG, "abandoned": int(abandoned)}


async def settlement_servicing_step() -> Mapping[str, Any]:
    composition = _container.resolved_settlement_composition
    if composition is None:
        raise LifecycleRouteError(503, "settlement composition is not initialized")
    processed = await composition.worker.run_once()
    return {"loop": SETTLEMENT_SERVICING, "processed": int(processed)}


async def fulfillment_resume_step() -> Mapping[str, Any]:
    await resume_incomplete_fulfillments_once(sqlite_client=_sqlite_client())
    return {"loop": FULFILLMENT_RESUME}


async def site_projections_step() -> Mapping[str, Any]:
    """The projection poller's own cycle: pull every site's projection now."""
    await load_site_projections(_sqlite_client())
    return {"loop": SITE_PROJECTION_POLLER, "sites": projection_status_summary()}


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
    result = await run_publication_cycle_once(dry_run=False)
    logger.info("[ADMIN] Publication cycle advanced: %s", result["counts"])
    return result


async def publication_preview() -> Mapping[str, Any]:
    """Derive the next cycle's actions and apply none of them."""
    return await run_publication_cycle_once(dry_run=True)


def _introduction_retention() -> Any:
    composition = _container.resolved_contact_exchange
    return composition.retention() if composition is not None else None


async def introduction_retention_step() -> Mapping[str, Any]:
    """Run one retention sweep now; answers disabled while contact exchange is."""
    retention = _introduction_retention()
    if retention is None:
        return {"loop": INTRODUCTION_RETENTION, "enabled": False}
    return await retention.sweep_once()


async def introduction_retention_preview() -> Mapping[str, Any]:
    """Which introductions the next sweep would delete, deleting none."""
    retention = _introduction_retention()
    if retention is None:
        return {"loop": INTRODUCTION_RETENTION, "enabled": False}
    return await retention.preview()


def register_vm_lifecycle_steps() -> None:
    register_step(NEGOTIATION_WATCHDOG, route="negotiation-watchdog", step=negotiation_watchdog_step)
    register_step(SETTLEMENT_SERVICING, route="settlement-servicing", step=settlement_servicing_step)
    register_step(FULFILLMENT_RESUME, route="fulfillment-resume", step=fulfillment_resume_step)
    register_step(SITE_PROJECTION_POLLER, route="site-projections", step=site_projections_step)
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


register_vm_lifecycle_steps()
