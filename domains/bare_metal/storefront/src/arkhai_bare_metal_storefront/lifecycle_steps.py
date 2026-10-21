"""The bare-metal storefront's loops: one cycle of each, and each loop's timer.

Each step calls the operation the loop's timer invokes and returns what it
returns, so an operator advancing a held loop exercises production behaviour.
Every loop is registered on the runtime's one loop controller twice over: its
step when the runtime is built, so every lifecycle route can run one, and its
timer when the server starts (``register_bare_metal_loops``), so the
controller's timer runs the step through the same cycle boundary an operator's
step takes, one cycle at a time. See openspec/specs/market-composition/spec.md,
"Storefront timer loops are held and stepped through one kit controller".

Publication runs on its timer like every other loop, and the site-projection
poller's cycle wakes it when a site's resource-pool generation changes, as an
accepted pool-override write does. See
openspec/specs/storefront-publication/spec.md, "Publication runs as a
controllable storefront lifecycle loop".
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core_storefront.domain_registry import (
    StorefrontDomainBindingError,
    StorefrontDomainRegistryError,
)
from core_storefront.stage_log import stage_event
from market_alkahest import ALKAHEST_CHAIN_PROBE_LOOP, ALKAHEST_CHAIN_PROBE_ROUTE
from market_capacity_publication import (
    CapacityBindingError,
    CapacityConfigurationError,
    SiteProjectionState,
)
from market_contact_exchange import (
    INTRODUCTION_RETENTION_LOOP,
    INTRODUCTION_RETENTION_ROUTE,
)
from market_storefront_kit import (
    LifecycleRouteError,
    StorefrontLoopController,
    sweep_stale_negotiations,
)
from pydantic_core import to_jsonable_python

from .config import BareMetalConfigurationError
from .publication import BareMetalPublicationError

if TYPE_CHECKING:
    from .runtime import BareMetalStorefrontRuntime

logger = logging.getLogger(__name__)

NEGOTIATION_WATCHDOG = "negotiation_watchdog"
SETTLEMENT_SERVICING = "settlement_servicing"
SITE_PROJECTION_POLLER = "site_projection_poller"
PUBLICATION = "publication"
INTRODUCTION_RETENTION = INTRODUCTION_RETENTION_LOOP
PAYMENT_RECONCILIATION = "payment_reconciliation"

#: The errors whose messages a recorded cycle outcome may carry: the
#: storefront's own configuration and publication errors, and the capacity and
#: domain-registration refusals its cycles raise for an unconfigured site or a
#: registration that does not resolve. Their text names keys, configured site
#: and domain identifiers, and reasons, all public configuration; none carries
#: a secret, a credential, or a site's URL. The check is `isinstance`, so a
#: subclass of one is disclosed too; every other exception reaches status by
#: its type alone.
DISCLOSED_CYCLE_ERRORS: tuple[type[BaseException], ...] = (
    BareMetalConfigurationError,
    BareMetalPublicationError,
    CapacityBindingError,
    CapacityConfigurationError,
    StorefrontDomainBindingError,
    StorefrontDomainRegistryError,
)


def bare_metal_loop_controller(**options: Any) -> StorefrontLoopController:
    """The loop controller for one bare-metal storefront process.

    ``options`` are the controller's own seams (a clock, a cycle-lock factory, a
    logger in place of this module's); the disclosed error types are always this
    storefront's.
    """
    options.setdefault("logger", logger)
    return StorefrontLoopController(disclosed_errors=DISCLOSED_CYCLE_ERRORS, **options)


class PublicationWake:
    """What runs the publication loop without waiting out its interval.

    A resource-pool generation change a projection poll observes sets it, and
    so does an accepted pool-override write; a held loop stays held, and runs
    promptly once resumed. An ``asyncio.Event`` binds to the event loop that
    first waits on it, so each registration of the publication timer takes a
    fresh one (``renew``), and setting the wake sets whichever is current.
    """

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def renew(self) -> asyncio.Event:
        """A fresh event for a new publication timer, which this wake now sets."""
        self._event = asyncio.Event()
        return self._event

    def __call__(self) -> None:
        self._event.set()


def site_projection_status(state: SiteProjectionState) -> dict[str, dict[str, Any]]:
    """Each site's per-family load state, as status and the poller's step report it."""
    return {
        site_id: {family: status.model_dump(mode="json") for family, status in families.items()}
        for site_id, families in state.status().items()
    }


@dataclass(frozen=True)
class _Loop:
    """One loop: its name, route, step, and the timer the server registers."""

    name: str
    route: str
    step: Callable[[], Awaitable[Mapping[str, Any]]]
    interval_seconds: float
    #: The first timer cycle is due this long after the timer starts.
    initial_delay_seconds: float = 0.0
    preview: Callable[[], Awaitable[Mapping[str, Any]]] | None = None
    #: Whether a wake runs the loop before its interval ends.
    woken: bool = False


def _loops(runtime: BareMetalStorefrontRuntime) -> tuple[_Loop, ...]:
    """Every loop the runtime composes, each bound to its step.

    Publication and the site-projection poller run their first cycle as soon as
    their timers start, after startup's first projection load. The sweeps --
    the watchdog, settlement servicing, payment reconciliation, and introduction
    retention -- change durable deals and introductions, so their first cycle
    is due one interval later, giving an operator who holds the loops as the
    storefront starts a whole interval to do so.
    """

    loops = runtime.loops

    async def negotiation_watchdog_step() -> Mapping[str, Any]:
        policy = runtime.negotiation_watchdog
        abandoned = await sweep_stale_negotiations(
            runtime.db,
            policy,
            emit_stage_event=stage_event,
            logger=logger,
        )
        if abandoned:
            logger.info(
                "[WATCHDOG] marked %d stale thread(s) as %s",
                abandoned,
                policy.terminal_state,
            )
        return {"loop": NEGOTIATION_WATCHDOG, "abandoned": int(abandoned)}

    def site_projections() -> SiteProjectionState:
        if runtime.site_projections is None:
            raise LifecycleRouteError(503, "site projection state is unavailable")
        return runtime.site_projections

    async def site_projections_step() -> Mapping[str, Any]:
        """The poller's cycle: poll every site's families in place.

        A site that cannot be reached keeps its last generation as ``stale``,
        and a resource-pool change wakes publication.
        """
        state = site_projections()
        await state.poll_once()
        return {"loop": SITE_PROJECTION_POLLER, "sites": site_projection_status(state)}

    def compose_publication() -> Any:
        # Imported when a cycle is composed: publication composition imports
        # the runtime module, which registers these steps.
        from .publication_composition import compose_publication_cycle

        factory = runtime.publication_cycle_factory or compose_publication_cycle
        try:
            return factory(runtime)
        except BareMetalPublicationError:
            raise
        except RuntimeError as exc:
            raise LifecycleRouteError(503, str(exc)) from exc

    async def publication_step() -> Mapping[str, Any]:
        # Composing the cycle is its compose stage, so a storefront that
        # cannot compose one fails there; the cycle names the stages after it.
        # The previous cycle's derivation goes as this one starts, so status
        # never pairs this cycle's outcome with another cycle's derivation.
        loops.enter_stage("compose")
        runtime.publication_derivation.clear()
        cycle = compose_publication()
        return to_jsonable_python(await cycle.run())

    async def publication_preview() -> Mapping[str, Any]:
        """What one publication cycle would open, close, refresh, reopen, or hold."""
        cycle = compose_publication()
        return to_jsonable_python(await cycle.run(dry_run=True))

    composed = [
        _Loop(
            NEGOTIATION_WATCHDOG,
            "negotiation-watchdog",
            negotiation_watchdog_step,
            interval_seconds=runtime.negotiation_watchdog.interval_seconds,
            initial_delay_seconds=runtime.negotiation_watchdog.interval_seconds,
        ),
    ]
    if runtime.site_projections is not None:
        composed.append(
            _Loop(
                SITE_PROJECTION_POLLER,
                "site-projections",
                site_projections_step,
                interval_seconds=runtime.site_projection_poll_interval_seconds,
            )
        )
    composed.append(
        _Loop(
            PUBLICATION,
            "publication",
            publication_step,
            interval_seconds=runtime.publication_interval_seconds,
            preview=publication_preview,
            woken=True,
        )
    )

    probe = runtime.alkahest_chain_probe
    if probe is not None:

        async def alkahest_chain_probe_step() -> Mapping[str, Any]:
            return {"loop": ALKAHEST_CHAIN_PROBE_LOOP, **(await probe.step())}

        # Its first cycle runs as its timer starts: readiness reads every chain
        # unprobed until it has.
        composed.append(
            _Loop(
                ALKAHEST_CHAIN_PROBE_LOOP,
                ALKAHEST_CHAIN_PROBE_ROUTE,
                alkahest_chain_probe_step,
                interval_seconds=probe.interval_seconds,
            )
        )

    if runtime.payments_reconciliation_enabled():

        async def payment_reconciliation_step() -> Mapping[str, Any]:
            done = await runtime.settlement_service().reconcile_payments_once()
            return {
                "loop": PAYMENT_RECONCILIATION,
                "attempted": done.attempted,
                "failed": done.failed,
            }

        composed.append(
            _Loop(
                PAYMENT_RECONCILIATION,
                "payment-reconciliation",
                payment_reconciliation_step,
                interval_seconds=runtime.payment_reconciliation_interval_seconds,
                initial_delay_seconds=runtime.payment_reconciliation_interval_seconds,
            )
        )

    worker = runtime.settlement_worker
    if worker is not None:

        async def settlement_servicing_step() -> Mapping[str, Any]:
            processed = await worker.run_once()
            return {"loop": SETTLEMENT_SERVICING, "processed": int(processed)}

        composed.append(
            _Loop(
                SETTLEMENT_SERVICING,
                "settlement-servicing",
                settlement_servicing_step,
                interval_seconds=runtime.settlement_servicing_interval_seconds,
                initial_delay_seconds=runtime.settlement_servicing_interval_seconds,
            )
        )

    retention = runtime.introduction_retention()
    if retention is not None:

        async def introduction_retention_step() -> Mapping[str, Any]:
            report = await retention.sweep_once()
            if report.get("deleted"):
                logger.info(
                    "[RETENTION] deleted payloads of %d introduction(s)", report["deleted"]
                )
            return report

        sweep_interval = float(retention.policy.sweep_interval_seconds)
        # Registered with its preview, so an operator holding the loops can
        # see which introductions the next sweep would delete before running it.
        composed.append(
            _Loop(
                INTRODUCTION_RETENTION,
                INTRODUCTION_RETENTION_ROUTE,
                introduction_retention_step,
                interval_seconds=sweep_interval,
                initial_delay_seconds=sweep_interval,
                preview=retention.preview,
            )
        )
    return tuple(composed)


def register_bare_metal_lifecycle_steps(runtime: BareMetalStorefrontRuntime) -> None:
    """Register every loop's step on the runtime's loop controller."""
    for loop in _loops(runtime):
        runtime.loops.register_step(
            loop.name, route=loop.route, step=loop.step, preview=loop.preview
        )


def register_bare_metal_loops(runtime: BareMetalStorefrontRuntime) -> dict[str, float]:
    """Register each loop's timer over its step; returns each one's interval.

    The publication timer takes a fresh wake from the runtime's publication
    wake, bound to the event loop the timer runs on. ``start_loops`` on the
    runtime's controller then starts them.
    """
    intervals: dict[str, float] = {}
    for loop in _loops(runtime):
        runtime.loops.register_loop(
            loop.name,
            route=loop.route,
            step=loop.step,
            preview=loop.preview,
            interval_seconds=loop.interval_seconds,
            initial_delay_seconds=loop.initial_delay_seconds,
            wake=runtime.publication_wake.renew() if loop.woken else None,
        )
        intervals[loop.name] = loop.interval_seconds
    return intervals


__all__ = [
    "DISCLOSED_CYCLE_ERRORS",
    "INTRODUCTION_RETENTION",
    "NEGOTIATION_WATCHDOG",
    "PAYMENT_RECONCILIATION",
    "PUBLICATION",
    "SETTLEMENT_SERVICING",
    "SITE_PROJECTION_POLLER",
    "PublicationWake",
    "bare_metal_loop_controller",
    "register_bare_metal_lifecycle_steps",
    "register_bare_metal_loops",
    "site_projection_status",
]
