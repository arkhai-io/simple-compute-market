"""The VM storefront's timer loops, bound to one kit loop controller.

The controller in `market_storefront_kit.lifecycle` owns registration, the
pause, acknowledgement, quiescence, loop state, and steps; see the storefront
loop requirements in openspec/specs/market-composition/spec.md. This module
names the VM storefront's loops and binds one controller for the process, so
the loop bodies, startup, and admin routes share it through stable names.

A loop body consults `gate` once per cycle, before any work, and waits between
cycles through `idle`, so a pause holds it at a cycle boundary without
cancelling it. Two loop bodies live in kit runners and take a `paused`
predicate and a `wait`; composition supplies `loop_gate(name)` and `idle`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from core_storefront.app_startup import StorefrontBackgroundTask
from market_storefront_kit import (
    LoopStep,
    QUIESCENCE_TIMEOUT_SECONDS,
    StorefrontLoopController,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Loop names.
#
# One definition per loop, used both by the registration in `startup.py` and by
# the loop body's own gate call. A name spelled independently in those two
# places can drift, and a loop acknowledging a name nobody waits on is
# indistinguishable from a loop that never gates at all.
# ---------------------------------------------------------------------------

NEGOTIATION_WATCHDOG = "negotiation_watchdog"
SETTLEMENT_SERVICING = "settlement_servicing"
FULFILLMENT_RESUME = "fulfillment_resume"
CAPACITY_EVENTS_POLLER = "capacity_events_poller"
SITE_PROJECTION_POLLER = "site_projection_poller"
PUBLICATION = "publication"


def capacity_site_loop_name(site: str) -> str:
    """The registered name of one site's capacity-event poller.

    Capacity polling fans out one poller per configured site, and each gates
    under its own name rather than sharing the aggregate's. A shared
    acknowledgement would let whichever site reached its gate first answer for
    the others, so a pause could report `paused` while another site's cycle was
    still writing.
    """
    return f"{CAPACITY_EVENTS_POLLER}:{site}"


_CONTROLLER = StorefrontLoopController(logger=logger)


def controller() -> StorefrontLoopController:
    """The process's one loop controller."""
    return _CONTROLLER


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


def reset_for_tests() -> None:
    """Drop all loop registrations, keeping steps. Test-only."""
    _CONTROLLER.clear_loops()


__all__ = [
    "CAPACITY_EVENTS_POLLER",
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
    "failed_loop_names",
    "gate",
    "idle",
    "loop_gate",
    "loop_states",
    "loops_check",
    "register_step",
    "registered_loop_names",
    "reset_for_tests",
    "start_registered_loop",
    "starting_loop_names",
]
