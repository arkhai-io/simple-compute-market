"""The VM storefront's timer loops, bound to one kit loop controller.

The controller in `market_storefront_kit.lifecycle` owns registration, the
pause, acknowledgement, quiescence, loop state, and steps; see the storefront
loop requirements in openspec/specs/market-composition/spec.md. This module
names the VM storefront's loops and binds one controller for the process, so
the loop bodies, startup, and admin routes share it through stable names.

A loop body consults `gate` once per cycle, before any work, and waits between
cycles through `idle`, so a pause holds it at a cycle boundary without
cancelling it. Every loop but the capacity-event pollers is registered with
`register_loop` and has no body of its own: the controller's timer gates, runs
the loop's step through the one cycle boundary an operator's step also takes,
and waits. The capacity-event pollers fan out one cycle per site inside the
capacity-publication kit, which takes `loop_gate(name)` and `idle` and
serializes each site's cycle with that site's step itself.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from core_storefront.app_startup import StorefrontBackgroundTask
from core_storefront.domain_registry import (
    StorefrontDomainBindingError,
    StorefrontDomainRegistryError,
)
from market_capacity_publication import CapacityBindingError, CapacityConfigurationError
from market_storefront_kit import (
    LoopSnapshot,
    LoopStep,
    QUIESCENCE_TIMEOUT_SECONDS,
    StorefrontLoopController,
    TradingPause,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Loop names.
#
# One definition per loop, used by its registration in `lifecycle_steps.py`,
# which the controller's timer gates under, and by what its step reports. A
# name spelled independently in those places can drift, and a loop
# acknowledging a name nobody waits on is indistinguishable from a loop that
# never gates at all.
# ---------------------------------------------------------------------------

NEGOTIATION_WATCHDOG = "negotiation_watchdog"
SETTLEMENT_SERVICING = "settlement_servicing"
FULFILLMENT_RESUME = "fulfillment_resume"
CAPACITY_EVENTS_POLLER = "capacity_events_poller"
SITE_PROJECTION_POLLER = "site_projection_poller"
PUBLICATION = "publication"
INTRODUCTION_RETENTION = "introduction_retention"


def capacity_site_loop_name(site: str) -> str:
    """The registered name of one site's capacity-event poller.

    Capacity polling fans out one poller per configured site, and each gates
    under its own name rather than sharing the aggregate's. A shared
    acknowledgement would let whichever site reached its gate first answer for
    the others, so a pause could report `paused` while another site's cycle was
    still writing.
    """
    return f"{CAPACITY_EVENTS_POLLER}:{site}"


#: The errors whose messages a recorded cycle outcome may carry. These are the
#: configuration and binding refusals the storefront's cycles raise -- a
#: capacity site or binding that does not resolve, a domain registration that
#: is incomplete or does not match durable state. Their text names keys,
#: configured site, listing, and domain identifiers and versions, and reasons,
#: all public configuration; none carries a secret or a credential. The check
#: is `isinstance`, so a subclass of one of these is disclosed too. Every other
#: exception reaches status by type alone.
DISCLOSED_CYCLE_ERRORS: tuple[type[BaseException], ...] = (
    CapacityBindingError,
    CapacityConfigurationError,
    StorefrontDomainBindingError,
    StorefrontDomainRegistryError,
)

_CONTROLLER = StorefrontLoopController(
    logger=logger, disclosed_errors=DISCLOSED_CYCLE_ERRORS
)


def controller() -> StorefrontLoopController:
    """The process's one loop controller."""
    return _CONTROLLER


# Whether this process opens new negotiations; separate from the loops' pause.
_TRADING_PAUSE = TradingPause()


def trading_pause() -> TradingPause:
    """The process's one trading pause."""
    return _TRADING_PAUSE


def start_registered_loop(
    task: StorefrontBackgroundTask,
    *,
    task_logger: Any = None,
) -> asyncio.Task[Any]:
    """Start one background loop under the controller."""
    return _CONTROLLER.start_loop(task, task_logger=task_logger or logger)


def register_step(
    name: str,
    *,
    route: str,
    step: LoopStep,
    preview: LoopStep | None = None,
) -> None:
    """Bind one loop's cycle, and optionally its preview, to a route name."""
    _CONTROLLER.register_step(name, route=route, step=step, preview=preview)


def register_loop(
    name: str,
    *,
    route: str,
    step: LoopStep,
    interval_seconds: float,
    preview: LoopStep | None = None,
    wake: asyncio.Event | None = None,
    initial_delay_seconds: float = 0.0,
) -> None:
    """Register a loop whose timer the controller runs over its step.

    The timer and an operator's step run the same operation, one at a time;
    `start_loops` starts the timer. `wake` ends the wait between cycles early,
    and the first cycle is due `initial_delay_seconds` after the timer starts.
    """
    _CONTROLLER.register_loop(
        name,
        route=route,
        step=step,
        preview=preview,
        interval_seconds=interval_seconds,
        wake=wake,
        initial_delay_seconds=initial_delay_seconds,
    )


def start_loops() -> dict[str, asyncio.Task[Any]]:
    """Start the timer of every registered loop not yet started."""
    return _CONTROLLER.start_loops(task_logger=logger)


def declare_and_gate(name: str) -> Callable[[], bool]:
    """Declare a gated name with no task handle here, and bind its gate."""
    return _CONTROLLER.declare(name)


def gate(name: str) -> bool:
    """The pause gate a named loop consults once per cycle, before any work."""
    return _CONTROLLER.gate(name)


def loop_gate(name: str) -> Callable[[], bool]:
    """A no-argument gate bound to one loop's name, for kit loop runners."""
    return _CONTROLLER.loop_gate(name)


async def idle(seconds: float, *, wake: asyncio.Event | None = None) -> None:
    """Wait between cycles: until the interval ends, `wake` is set, or a pause."""
    await _CONTROLLER.idle(seconds, wake=wake)


async def await_quiescence(timeout: float | None = None) -> None:
    await _CONTROLLER.await_quiescence(timeout)


def loop_states() -> dict[str, str]:
    return _CONTROLLER.states()


def loops_check() -> str:
    return _CONTROLLER.loops_check()


def failed_loop_names() -> list[str]:
    return _CONTROLLER.failed_loop_names()


def starting_loop_names() -> list[str]:
    return _CONTROLLER.starting_loop_names()


def registered_loop_names() -> list[str]:
    return _CONTROLLER.registered_loop_names()


def enter_stage(stage: str) -> None:
    """Name the stage the cycle running in this task has reached."""
    _CONTROLLER.enter_stage(stage)


def snapshot() -> dict[str, LoopSnapshot]:
    """Every loop's state and the last outcome its cycles recorded."""
    return _CONTROLLER.snapshot()


async def reset_for_tests() -> None:
    """Cancel every loop and wait for it to end, dropping its handles, outcomes,
    pause, and timer registration and keeping the registered steps, so no test
    starts a loop another registered. Test-only."""
    await _CONTROLLER.stop_loops(keep_registrations=False)


__all__ = [
    "CAPACITY_EVENTS_POLLER",
    "DISCLOSED_CYCLE_ERRORS",
    "FULFILLMENT_RESUME",
    "NEGOTIATION_WATCHDOG",
    "PUBLICATION",
    "QUIESCENCE_TIMEOUT_SECONDS",
    "SETTLEMENT_SERVICING",
    "SITE_PROJECTION_POLLER",
    "await_quiescence",
    "capacity_site_loop_name",
    "controller",
    "declare_and_gate",
    "enter_stage",
    "failed_loop_names",
    "gate",
    "idle",
    "loop_gate",
    "loop_states",
    "loops_check",
    "register_loop",
    "register_step",
    "registered_loop_names",
    "reset_for_tests",
    "snapshot",
    "start_loops",
    "start_registered_loop",
    "starting_loop_names",
]
