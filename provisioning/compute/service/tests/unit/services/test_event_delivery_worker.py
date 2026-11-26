"""The event delivery worker's cycles: one at a time per consumer, a delivery
asked for waiting only for its own consumers' running cycle.

Stand-in consumers whose cycle can be held at a gate, so a test controls which
cycle is running; every wait is bounded.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from eventing import CycleReport

from compute_provisioning_service.services.operator_events import EventDeliveryWorker

BOUND = 5.0


@dataclass
class _Consumer:
    """A consumer whose cycles record their start and end; while ``gate`` is an
    unset event, a cycle announces itself on ``entered`` and waits for it."""

    name: str
    cycles: list[tuple[str, int]] = field(default_factory=list)
    gate: threading.Event | None = None
    entered: threading.Event = field(default_factory=threading.Event)

    def run_cycle(self) -> CycleReport:
        number = sum(1 for step in self.cycles if step[0] == "start") + 1
        self.cycles.append(("start", number))
        gate = self.gate
        self.entered.set()
        if gate is not None:
            assert gate.wait(BOUND), "the held cycle was never released"
        self.cycles.append(("end", number))
        return CycleReport(delivered=1)


class _Pruner:
    def prune(self):
        return SimpleNamespace(removed={})


def _worker(*consumers: _Consumer) -> EventDeliveryWorker:
    return EventDeliveryWorker(consumers, _Pruner(), interval_seconds=3600)


async def test_a_delivery_waits_for_its_consumer_s_running_cycle_then_runs_its_own():
    held = threading.Event()
    reports = _Consumer("lease-end-reports", gate=held)
    worker = _worker(reports)
    timer = asyncio.create_task(worker.run_cycle())
    assert await asyncio.to_thread(reports.entered.wait, BOUND)
    reports.gate = None

    asked = asyncio.create_task(worker.deliver("lease-end-reports"))
    held.set()
    report = await asyncio.wait_for(asked, BOUND)
    await asyncio.wait_for(timer, BOUND)

    # The asked cycle began only once the running one had ended.
    assert reports.cycles == [("start", 1), ("end", 1), ("start", 2), ("end", 2)]
    assert report["lease-end-reports"]["delivered"] == 1


async def test_a_delivery_never_waits_for_another_consumer_s_cycle():
    held = threading.Event()
    sinks = _Consumer("event-sinks", gate=held)
    callbacks = _Consumer("capacity-released")
    worker = _worker(sinks, callbacks)
    timer = asyncio.create_task(worker.run_cycle())
    assert await asyncio.to_thread(sinks.entered.wait, BOUND)

    report = await asyncio.wait_for(worker.deliver("capacity-released"), BOUND)

    assert (callbacks.cycles, sinks.cycles) == ([("start", 1), ("end", 1)], [("start", 1)])
    assert set(report) == {"capacity-released"}
    held.set()
    await asyncio.wait_for(timer, BOUND)


async def test_a_delivery_for_a_consumer_the_worker_does_not_run_is_refused():
    worker = _worker(_Consumer("event-sinks"))

    with pytest.raises(LookupError, match="lease-end-reports"):
        await worker.deliver("lease-end-reports")
