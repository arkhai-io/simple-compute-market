"""One cycle of each API-credit storefront loop, registered as that loop's step.

Each step calls the operation the loop's timer invokes and returns what it
returns, so an operator advancing a held loop exercises production behaviour.
Steps resolve their collaborators from the container when they run.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from core_storefront.stage_log import stage_event
from market_storefront_kit import (
    LifecycleRouteError,
    StorefrontLoopController,
    sweep_stale_negotiations,
)

import apicredits_storefront.container as _container
from apicredits_storefront.services.capacity_client import build_capacity_runtime

logger = logging.getLogger(__name__)

NEGOTIATION_WATCHDOG = "negotiation_watchdog"
SETTLEMENT_SERVICING = "settlement_servicing"
CAPACITY_EVENTS_POLLER = "capacity_events_poller"


def capacity_site_loop_name(site: str) -> str:
    """The gated name of one site's capacity-event poller.

    Each site acknowledges under its own name, so one site reaching its gate
    cannot answer for another still writing.
    """
    return f"{CAPACITY_EVENTS_POLLER}:{site}"


def _sqlite_client() -> Any:
    if _container.resolved_sqlite_client is None:
        raise LifecycleRouteError(503, "storefront persistence is not initialized")
    return _container.resolved_sqlite_client


async def negotiation_watchdog_step() -> Mapping[str, Any]:
    # Imported when the step runs: startup imports this module for the loop names.
    from apicredits_storefront.startup import _negotiation_watchdog_policy

    abandoned = await sweep_stale_negotiations(
        _sqlite_client(),
        _negotiation_watchdog_policy(),
        emit_stage_event=stage_event,
        logger=logger,
    )
    return {"loop": NEGOTIATION_WATCHDOG, "abandoned": int(abandoned)}


async def settlement_servicing_step() -> Mapping[str, Any]:
    worker = _container.resolved_settlement_worker
    if worker is None:
        raise LifecycleRouteError(503, "settlement servicing worker is not initialized")
    processed = await worker.run_once()
    return {"loop": SETTLEMENT_SERVICING, "processed": int(processed)}


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
    loops.register_step(
        NEGOTIATION_WATCHDOG, route="negotiation-watchdog", step=negotiation_watchdog_step
    )
    loops.register_step(
        SETTLEMENT_SERVICING, route="settlement-servicing", step=settlement_servicing_step
    )
    loops.register_step(
        CAPACITY_EVENTS_POLLER,
        route="capacity-events",
        step=capacity_events_step,
        preview=capacity_events_preview,
    )


__all__ = [
    "CAPACITY_EVENTS_POLLER",
    "NEGOTIATION_WATCHDOG",
    "SETTLEMENT_SERVICING",
    "capacity_site_loop_name",
    "register_api_credit_lifecycle_steps",
]
