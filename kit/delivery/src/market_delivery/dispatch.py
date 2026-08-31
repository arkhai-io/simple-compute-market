"""Bounded, non-fatal dispatch.

Delivery is a convenience laid over a deal that has already completed, so
dispatch never raises to its caller and never reports what it was carrying.
A failure yields the sink's name, the obligation reference, and a failure
description the sink itself made safe; anything else that escapes a sink is
reported by exception class alone, because an arbitrary message may quote the
payload or a credential.

Sinks are synchronous and may block, so each runs in its own daemon thread
bounded by a join timeout. A sink that overruns is abandoned rather than
interrupted -- a thread cannot be killed -- which is why the seller side
dispatches off the request path instead of waiting, and why the threads are
daemons: an abandoned sink must not hold up the process it was helping.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .events import DeliveryEvent
from .sinks import ConfiguredSink, DeliveryError


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    """What happened for one sink, in a form that is safe to print."""

    sink: str
    obligation_ref: str
    delivered: bool
    failure: str | None = None

    def describe(self) -> str:
        if self.delivered:
            return f"delivered to {self.sink}"
        return f"delivery to {self.sink} failed: {self.failure}"


def _failure_description(exc: BaseException) -> str:
    if isinstance(exc, DeliveryError):
        return str(exc)
    return type(exc).__name__


def _run_sink(
    configured: ConfiguredSink,
    event: DeliveryEvent,
    box: list[BaseException | None],
) -> None:
    try:
        configured.sink(event)
    except BaseException as exc:  # noqa: BLE001 - a sink may raise anything
        box[0] = exc


def deliver(
    sinks: Sequence[ConfiguredSink],
    event: DeliveryEvent,
) -> tuple[DeliveryOutcome, ...]:
    """Run every sink under its own bound; never raise."""

    if not sinks:
        return ()
    running: list[tuple[ConfiguredSink, threading.Thread, list[BaseException | None]]] = []
    # Sinks run concurrently, so each one's bound is measured from the same
    # start: the whole dispatch costs the slowest sink, not the sum of them.
    started = time.monotonic()
    for configured in sinks:
        box: list[BaseException | None] = [None]
        thread = threading.Thread(
            target=_run_sink,
            args=(configured, event, box),
            name=f"delivery-{configured.name}",
            daemon=True,
        )
        thread.start()
        running.append((configured, thread, box))

    outcomes: list[DeliveryOutcome] = []
    for configured, thread, box in running:
        remaining = configured.timeout_seconds - (time.monotonic() - started)
        thread.join(timeout=max(remaining, 0.0))
        if thread.is_alive():
            outcomes.append(
                DeliveryOutcome(
                    sink=configured.name,
                    obligation_ref=event.obligation_ref,
                    delivered=False,
                    failure=f"timed out after {configured.timeout_seconds:g}s",
                )
            )
            continue
        failure = box[0]
        outcomes.append(
            DeliveryOutcome(
                sink=configured.name,
                obligation_ref=event.obligation_ref,
                delivered=failure is None,
                failure=None if failure is None else _failure_description(failure),
            )
        )
    return tuple(outcomes)


async def deliver_async(
    sinks: Sequence[ConfiguredSink],
    event: DeliveryEvent,
) -> tuple[DeliveryOutcome, ...]:
    """Await the same bounded dispatch without occupying the event loop."""

    if not sinks:
        return ()
    return await asyncio.to_thread(deliver, sinks, event)


def describe_outcomes(outcomes: Iterable[DeliveryOutcome]) -> tuple[str, ...]:
    """Render outcomes for a local operator, payload-free by construction."""

    return tuple(outcome.describe() for outcome in outcomes)


__all__ = [
    "DeliveryOutcome",
    "deliver",
    "deliver_async",
    "describe_outcomes",
]
