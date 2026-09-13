"""Pause gates and per-loop state for the storefront's timer loops.

A scenario that asserts on reconciliation has to be able to stop it. While the
timer loops run, an observation races them: a listing reconciled a second later
reads differently than one reconciled a second earlier, and a defect that
reorders two writes shows up as an intermittent failure rather than a
reproducible one. Waiting for the system to settle instead is what
`docs/development/TESTING.md` forbids, and it cannot establish ordering even
when it passes.

Two controls, deliberately separate:

- This module holds the **timer loops** idle. Trading is unaffected -- new
  negotiations are still accepted -- because a scenario needs deterministic
  reconciliation *and* a deal to agree. Overloading one flag with both meanings
  leaves no way to have one without the other.
- The storefront's global trading pause is a different flag with a different
  purpose, and neither implies the other.

Loops are held, not stopped: nothing is torn down, no cycle is cut part-way,
and a poller keeps its feed position. Each loop's work stays reachable through
its own admin run-cycle route, which is how an operator or a scenario advances
one step at a time while paused.

`LOOP_STATES` is reported so a caller can assert the loop it depends on
actually reached its gate. `running` means the loop completed a gate call and
will therefore observe a pause requested after it; `paused` means it is held at
the gate; `starting` means it has a task but has not yet cycled. Pausing on the
strength of `starting` reports a loop stopped that never started.
"""

from __future__ import annotations

import asyncio
from typing import Any

_PAUSED = False
_STATES: dict[str, str] = {}


def register_loop(name: str) -> None:
    """Declare a loop before it cycles, so status can report it as starting."""

    _STATES.setdefault(name, "starting")


def loop_states() -> dict[str, str]:
    """Per-loop gate state, for operator status and scenario assertions."""

    return dict(_STATES)


def loops_paused() -> bool:
    return _PAUSED


def set_loops_paused(value: bool) -> dict[str, str]:
    """Request the pause, and report what each loop is doing right now.

    The returned states are a snapshot, not a guarantee: a loop mid-cycle when
    the request arrives is still `running` and reaches its gate at the end of
    that cycle. A caller that needs the stronger property waits for the state
    to become `paused` rather than assuming the request implies it.
    """

    global _PAUSED
    _PAUSED = bool(value)
    if not _PAUSED:
        for name, state in list(_STATES.items()):
            if state == "paused":
                _STATES[name] = "running"
    return loop_states()


async def gate(name: str, *, poll_seconds: float = 0.05) -> None:
    """Hold one loop at the top of its cycle while loops are paused.

    Called by the loop itself rather than imposed by the scheduler: only the
    loop knows where its cycle boundary is, and a gate applied anywhere else
    would cut a cycle in half.
    """

    if not _PAUSED:
        _STATES[name] = "running"
        return
    _STATES[name] = "paused"
    while _PAUSED:
        await asyncio.sleep(poll_seconds)
    _STATES[name] = "running"


async def maybe_gate(name: str, paused: Any = None) -> None:
    """Gate on this module unless a caller supplied its own predicate.

    Lets a kit-level worker accept an injected `paused` callable -- keeping it
    independent of this module -- while storefront loops share one registry.
    """

    if paused is not None:
        if paused():
            _STATES[name] = "paused"
            while paused():
                await asyncio.sleep(0.05)
        _STATES[name] = "running"
        return
    await gate(name)
