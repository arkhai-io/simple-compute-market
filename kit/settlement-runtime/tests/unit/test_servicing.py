"""The servicing worker's loop and one step, over mocked collaborators.

The loop's cycle ordering runs against a worker that sweeps nothing; the ready
step's scheduling and reporting run against a mocked runtime and repository.
Durable servicing against a real database is in
``tests/integration/test_servicing.py``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_identity import Identity, IdentityScheme

from market_settlement_runtime import (
    SettlementObligationRecord,
    SettlementServicingWorker,
)


class _CountingWorker(SettlementServicingWorker):
    """Counts sweeps; the loop's ordering is what these tests examine."""

    def __init__(self, *, interval_seconds: float) -> None:
        super().__init__(
            MagicMock(), MagicMock(), worker_id="counting", interval_seconds=interval_seconds
        )
        self.sweeps = 0

    async def run_once(self, limit: int = 50) -> int:
        self.sweeps += 1
        return 0


class _Control:
    """A gate and an interruptible wait, driven by the test.

    The wait returns only when the test ticks it or a pause is requested, so each
    tick lets the loop through one more cycle and nothing here waits on time.
    """

    def __init__(self) -> None:
        self.paused = False
        self.signal = asyncio.Event()
        self.tick = asyncio.Event()
        self.waiting = asyncio.Event()
        self.held_reads = 0
        self._held_read = asyncio.Event()

    def gate(self) -> bool:
        if self.paused:
            self.held_reads += 1
            self._held_read.set()
        return self.paused

    async def wait(self, seconds: float) -> None:
        self.waiting.set()
        tick = asyncio.ensure_future(self.tick.wait())
        pause = asyncio.ensure_future(self.signal.wait())
        try:
            await asyncio.wait({tick, pause}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            tick.cancel()
            pause.cancel()
        self.tick.clear()

    async def next_wait(self) -> None:
        self.waiting.clear()
        self.tick.set()
        await asyncio.wait_for(self.waiting.wait(), timeout=1)

    async def held_reads_reach(self, count: int) -> None:
        while self.held_reads < count:
            self._held_read.clear()
            await asyncio.wait_for(self._held_read.wait(), timeout=1)

    def pause(self) -> None:
        self.paused = True
        self.signal.set()

    def resume(self) -> None:
        self.paused = False
        self.signal.clear()


async def _stop(task: asyncio.Task) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_the_first_sweep_waits_one_interval():
    worker = _CountingWorker(interval_seconds=3600)
    control = _Control()
    task = asyncio.create_task(worker.run(paused=control.gate, wait=control.wait))
    try:
        await asyncio.wait_for(control.waiting.wait(), timeout=1)
        assert worker.sweeps == 0
    finally:
        await _stop(task)


async def test_a_pause_requested_during_the_wait_holds_the_next_sweep():
    # Due by the next cycle; the test, not the clock, decides when that is.
    worker = _CountingWorker(interval_seconds=1e-6)
    control = _Control()
    task = asyncio.create_task(worker.run(paused=control.gate, wait=control.wait))
    try:
        await asyncio.wait_for(control.waiting.wait(), timeout=1)
        await control.next_wait()
        swept = worker.sweeps
        assert swept >= 1

        control.pause()
        await control.held_reads_reach(3)
        assert worker.sweeps == swept, "a held servicing loop swept"

        control.resume()
        await control.next_wait()
        assert worker.sweeps > swept
    finally:
        await _stop(task)


async def test_a_gated_loop_without_an_interruptible_wait_is_refused():
    worker = _CountingWorker(interval_seconds=3600)
    with pytest.raises(TypeError):
        await worker.run(paused=lambda: False)


_PRINCIPAL = Identity(
    scheme=IdentityScheme.ED25519,
    identifier="ERERERERERERERERERERERERERERERERERERERERERE",
)


def _ready_without_fulfillment() -> dict:
    record = SettlementObligationRecord.from_obligation(
        agreement_ref="agreement",
        obligation_index=0,
        obligation={
            "payer": "buyer",
            "claimant": "seller",
            "payer_principal": _PRINCIPAL.model_dump(mode="json"),
            "claimant_principal": _PRINCIPAL.model_dump(mode="json"),
            "mechanism": "test.v1",
            "expiration_unix": 4_102_444_800,
        },
    )
    return {**record.model_dump(mode="json"), "mechanism_status": "ready"}


def _ready_step_worker(*, fulfill: dict, on_ready) -> tuple:
    """A worker whose one ready obligation leaves ``fulfill`` after its hook."""
    runtime = MagicMock()
    runtime.reconcile_status = AsyncMock(return_value=MagicMock(status="ready"))
    repository = MagicMock()
    repository.load_settlement_obligation = AsyncMock(
        return_value=_ready_without_fulfillment()
    )
    repository.load_settlement_operation = AsyncMock(return_value=fulfill)
    repository.schedule_settlement_retry = AsyncMock()
    worker = SettlementServicingWorker(
        runtime, repository, worker_id="w", interval_seconds=1, on_ready=on_ready
    )
    return worker, repository


async def _returns(_record, _worker_id) -> None:
    return None


async def test_a_ready_step_awaiting_delivery_keeps_the_due_time_it_wrote():
    """The mark is honoured once: rescheduled at its own due time, consuming it."""
    worker, repository = _ready_step_worker(
        fulfill={
            "state": "pending",
            "attempts": 0,
            "awaiting_delivery": True,
            "next_attempt_unix": 1234.0,
        },
        on_ready=_returns,
    )
    ref = _ready_without_fulfillment()["obligation_ref"]

    await worker.service_obligation(ref)

    repository.load_settlement_operation.assert_awaited_with(ref, "fulfill")
    repository.schedule_settlement_retry.assert_awaited_once_with(
        obligation_ref=ref, operation="fulfill", next_attempt_unix=1234.0
    )


async def test_a_ready_step_returning_without_the_mark_takes_the_error_backoff(caplog):
    worker, repository = _ready_step_worker(
        fulfill={"state": "pending", "attempts": 1, "awaiting_delivery": False},
        on_ready=_returns,
    )
    ref = _ready_without_fulfillment()["obligation_ref"]
    before = time.time()

    with caplog.at_level(logging.WARNING, logger="market_settlement_runtime.servicing"):
        await worker.service_obligation(ref)

    scheduled = repository.schedule_settlement_retry.await_args.kwargs
    assert scheduled["operation"] == "fulfill"
    assert scheduled["next_attempt_unix"] >= before + 30
    [logged] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert ref in logged.getMessage() and "fulfill" in logged.getMessage()


async def test_a_failing_step_is_logged_without_an_event_callback(caplog):
    async def unavailable(_record, _worker_id):
        raise RuntimeError("site unavailable")

    worker, repository = _ready_step_worker(
        fulfill={"state": "pending", "attempts": 1, "awaiting_delivery": True},
        on_ready=unavailable,
    )
    ref = _ready_without_fulfillment()["obligation_ref"]

    with caplog.at_level(logging.WARNING, logger="market_settlement_runtime.servicing"):
        await worker.service_obligation(ref)

    # A hook that raised stays on the error path, whatever the journal says.
    assert repository.schedule_settlement_retry.await_args.kwargs["operation"] == "fulfill"
    [logged] = [r for r in caplog.records if r.levelno == logging.WARNING]
    message = logged.getMessage()
    assert ref in message
    assert "fulfill" in message
    assert "RuntimeError: site unavailable" in message
