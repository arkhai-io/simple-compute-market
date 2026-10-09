"""One cycle of each bare-metal storefront loop, registered as that loop's step.

Each step calls the operation the loop's timer invokes and returns what it
returns, so an operator advancing a held loop exercises production behaviour.
Publication has no timer: it is stepped, never held, and each step is one
operator-invoked pass, the same pass the publication command runs.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from core_storefront.stage_log import stage_event
from market_contact_exchange import (
    INTRODUCTION_RETENTION_LOOP,
    INTRODUCTION_RETENTION_ROUTE,
)
from market_storefront_kit import LifecycleRouteError, sweep_stale_negotiations
from pydantic_core import to_jsonable_python

if TYPE_CHECKING:
    from .runtime import BareMetalStorefrontRuntime

logger = logging.getLogger(__name__)

NEGOTIATION_WATCHDOG = "negotiation_watchdog"
SETTLEMENT_SERVICING = "settlement_servicing"
PUBLICATION = "publication"
INTRODUCTION_RETENTION = INTRODUCTION_RETENTION_LOOP
PAYMENT_RECONCILIATION = "payment_reconciliation"


def register_bare_metal_lifecycle_steps(runtime: BareMetalStorefrontRuntime) -> None:
    """Register every loop's step on the runtime's loop controller."""

    loops = runtime.loops

    async def negotiation_watchdog_step() -> Mapping[str, Any]:
        # Imported when the step runs: the composition root imports this
        # module, and owns the watchdog's environment schedule.
        from .server import _negotiation_watchdog_policy

        abandoned = await sweep_stale_negotiations(
            runtime.db,
            _negotiation_watchdog_policy(),
            emit_stage_event=stage_event,
            logger=logger,
        )
        return {"loop": NEGOTIATION_WATCHDOG, "abandoned": int(abandoned)}

    async def publication_step() -> Mapping[str, Any]:
        # Imported when the step runs: publication composition imports the
        # runtime module, which registers these steps.
        from .publication_composition import compose_publication_cycle

        factory = runtime.publication_cycle_factory or compose_publication_cycle
        # One publication pass at a time within this process.
        async with runtime.publication_lock:
            try:
                cycle = factory(runtime)
            except RuntimeError as exc:
                raise LifecycleRouteError(503, str(exc)) from exc
            report = await cycle.run()
        return to_jsonable_python(report)

    async def publication_preview() -> Mapping[str, Any]:
        """What one publication pass would open, close, refresh, reopen, or hold."""
        from .publication_composition import compose_publication_cycle

        factory = runtime.publication_cycle_factory or compose_publication_cycle
        async with runtime.publication_lock:
            try:
                cycle = factory(runtime)
            except RuntimeError as exc:
                raise LifecycleRouteError(503, str(exc)) from exc
            report = await cycle.run(dry_run=True)
        return to_jsonable_python(report)

    loops.register_step(
        NEGOTIATION_WATCHDOG, route="negotiation-watchdog", step=negotiation_watchdog_step
    )
    loops.register_step(
        PUBLICATION,
        route="publication",
        step=publication_step,
        preview=publication_preview,
    )

    if runtime.payments_reconciliation_enabled():

        async def payment_reconciliation_step() -> Mapping[str, Any]:
            done = await runtime.settlement_service().reconcile_payments_once()
            return {
                "loop": PAYMENT_RECONCILIATION,
                "attempted": done.attempted,
                "failed": done.failed,
            }

        loops.register_step(
            PAYMENT_RECONCILIATION,
            route="payment-reconciliation",
            step=payment_reconciliation_step,
        )

    worker = runtime.settlement_worker
    if worker is not None:

        async def settlement_servicing_step() -> Mapping[str, Any]:
            processed = await worker.run_once()
            return {"loop": SETTLEMENT_SERVICING, "processed": int(processed)}

        loops.register_step(
            SETTLEMENT_SERVICING, route="settlement-servicing", step=settlement_servicing_step
        )

    retention = runtime.introduction_retention()
    if retention is not None:
        # Registered with its preview, so an operator holding the loops can
        # see which introductions the next sweep would delete before running it.
        loops.register_step(
            INTRODUCTION_RETENTION,
            route=INTRODUCTION_RETENTION_ROUTE,
            step=retention.sweep_once,
            preview=retention.preview,
        )


__all__ = [
    "INTRODUCTION_RETENTION",
    "NEGOTIATION_WATCHDOG",
    "PUBLICATION",
    "SETTLEMENT_SERVICING",
    "register_bare_metal_lifecycle_steps",
]
