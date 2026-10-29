"""Durable settlement servicing against a real SQLite database.

The worker, runtime, and repository are the library's own; only the mechanism
client is a fake. Concurrency cases use separate repository instances, and so
separate connections, over one database file.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from market_identity import Identity, IdentityScheme

from market_settlement_runtime import (
    ConditionOutcome,
    EffectOutcome,
    MaterializationOutcome,
    SettlementRuntime,
    SettlementSQLiteRepository,
    SettlementServicingWorker,
    StatusOutcome,
)

BUYER = Identity(
    scheme=IdentityScheme.ED25519,
    identifier="ERERERERERERERERERERERERERERERERERERERERERE",
)
SELLER = Identity(
    scheme=IdentityScheme.ED25519,
    identifier="IiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiI",
)


class PollingClient:
    def __init__(self) -> None:
        self.decisions = ["pending", "ready"]
        self.states: list[dict] = []
        self.status_calls = 0
        self.collect_calls = 0

    async def materialize(self, obligation, *, operation_ref):
        return MaterializationOutcome(mechanism_ref="escrow", status="ready")

    async def get_status(
        self, obligation, *, mechanism_ref, operation_ref, mechanism_state
    ):
        self.status_calls += 1
        return StatusOutcome(
            status="ready",
            mechanism_ref=mechanism_ref,
            mechanism_state=mechanism_state,
        )

    async def check(
        self,
        obligation,
        *,
        mechanism_ref,
        fulfillment_ref,
        operation_ref,
        mechanism_state,
    ):
        self.states.append(dict(mechanism_state))
        decision = self.decisions.pop(0)
        return ConditionOutcome(
            decision=decision,
            mechanism_state={"requested": True}
            if decision == "pending"
            else mechanism_state,
        )

    async def collect(
        self,
        obligation,
        *,
        mechanism_ref,
        fulfillment_ref,
        operation_ref,
        mechanism_state,
    ):
        self.collect_calls += 1
        return EffectOutcome(receipt={"collected": True})

    async def reclaim_expired(
        self,
        obligation,
        *,
        mechanism_ref,
        operation_ref,
        mechanism_state,
        mechanism_options=None,
    ):
        return EffectOutcome(receipt={"reclaimed": True})


async def test_worker_restarts_from_durable_backoff_and_operation_state(
    tmp_path,
) -> None:
    repository = SettlementSQLiteRepository(str(tmp_path / "worker.db"))
    client = PollingClient()
    runtime = SettlementRuntime(repository, {"test.v1": client})
    record = (
        await runtime.register_plan(
            agreement_ref="agreement",
            obligations=[
                {
                    "payer": "buyer",
                    "claimant": "seller",
                    "payer_principal": BUYER.model_dump(mode="json"),
                    "claimant_principal": SELLER.model_dump(mode="json"),
                    "mechanism": "test.v1",
                    "expiration_unix": 4_102_444_800,
                }
            ],
        )
    )[0]
    await runtime.adopt(
        record.obligation_ref,
        local_principal=SELLER,
        mechanism_ref="escrow",
    )
    await runtime.bind_fulfillment(
        record.obligation_ref,
        "fulfillment",
        local_principal=SELLER,
    )
    events: list[tuple[str, dict]] = []
    terminals: list[str] = []
    first = SettlementServicingWorker(
        runtime,
        repository,
        worker_id="worker-one",
        interval_seconds=1,
        on_event=lambda event, fields: events.append((event, fields)),
        on_terminal=lambda record, outcome, reason: terminals.append(outcome),
    )
    assert await first.run_once() == 1
    pending = await repository.load_settlement_operation(record.obligation_ref, "check")
    assert pending is not None
    assert pending["state"] == "pending"
    assert pending["next_attempt_unix"] is not None
    await first.wake(record.obligation_ref)
    restarted = SettlementServicingWorker(
        SettlementRuntime(repository, {"test.v1": client}),
        repository,
        worker_id="worker-two",
        interval_seconds=1,
        on_terminal=lambda record, outcome, reason: terminals.append(outcome),
    )
    assert await restarted.run_once() == 1
    assert client.states == [{}, {"requested": True}]
    assert client.collect_calls == 1
    assert terminals == ["collected"]
    stored = await repository.load_settlement_obligation(record.obligation_ref)
    assert stored is not None
    assert stored["collection_state"] == "succeeded"
    assert any(event == "settlement_conditions_pending" for event, _ in events)


class ExpiredClient(PollingClient):
    async def get_status(
        self, obligation, *, mechanism_ref, operation_ref, mechanism_state
    ):
        return StatusOutcome(
            status="expired",
            mechanism_ref=mechanism_ref,
            mechanism_state=mechanism_state,
        )


async def test_expired_obligation_dispatches_terminal_outcome(tmp_path) -> None:
    repository = SettlementSQLiteRepository(str(tmp_path / "expired.db"))
    client = ExpiredClient()
    runtime = SettlementRuntime(repository, {"test.v1": client})
    record = (
        await runtime.register_plan(
            agreement_ref="expired-agreement",
            obligations=[
                {
                    "payer": "buyer",
                    "claimant": "seller",
                    "payer_principal": BUYER.model_dump(mode="json"),
                    "claimant_principal": SELLER.model_dump(mode="json"),
                    "mechanism": "test.v1",
                    "expiration_unix": 1,
                }
            ],
        )
    )[0]
    await runtime.adopt(
        record.obligation_ref,
        local_principal=SELLER,
        mechanism_ref="expired-escrow",
    )
    await runtime.bind_fulfillment(
        record.obligation_ref,
        "fulfillment",
        local_principal=SELLER,
    )
    terminals: list[str] = []
    worker = SettlementServicingWorker(
        runtime,
        repository,
        worker_id="expired-worker",
        interval_seconds=1,
        on_terminal=lambda record, outcome, reason: terminals.append(outcome),
    )
    assert await worker.run_once() == 1
    assert terminals == ["expired"]



class ReturnedClient(PollingClient):
    async def get_status(
        self, obligation, *, mechanism_ref, operation_ref, mechanism_state
    ):
        return StatusOutcome(
            status="failed",
            mechanism_ref=mechanism_ref,
            mechanism_state=mechanism_state,
            receipt={"funding_reason": "returned"},
        )


async def test_return_cleanup_retries_durably_after_restart(tmp_path) -> None:
    repository = SettlementSQLiteRepository(str(tmp_path / "returned.db"))
    client = ReturnedClient()
    runtime = SettlementRuntime(repository, {"test.v1": client})
    record = (
        await runtime.register_plan(
            agreement_ref="returned-agreement",
            obligations=[
                {
                    "payer": "buyer",
                    "claimant": "seller",
                    "payer_principal": BUYER.model_dump(mode="json"),
                    "claimant_principal": SELLER.model_dump(mode="json"),
                    "mechanism": "test.v1",
                    "expiration_unix": 4_102_444_800,
                }
            ],
        )
    )[0]
    await runtime.adopt(
        record.obligation_ref,
        local_principal=SELLER,
        mechanism_ref="returned-escrow",
    )
    await runtime.bind_fulfillment(
        record.obligation_ref,
        "durable-fulfillment-evidence",
        local_principal=SELLER,
    )
    attempts: list[str] = []

    async def cleanup(_record, _outcome, _reason):
        attempts.append("cleanup")
        if len(attempts) == 1:
            raise RuntimeError("capacity service unavailable")

    first = SettlementServicingWorker(
        runtime,
        repository,
        worker_id="cleanup-one",
        interval_seconds=1,
        on_terminal=cleanup,
    )
    assert await first.run_once() == 1
    pending = await repository.load_settlement_operation(
        record.obligation_ref,
        "cleanup",
    )
    assert pending is not None
    assert pending["state"] == "pending"
    assert pending["next_attempt_unix"] is not None

    await first.wake(record.obligation_ref)
    restarted = SettlementServicingWorker(
        SettlementRuntime(repository, {"test.v1": client}),
        repository,
        worker_id="cleanup-two",
        interval_seconds=1,
        on_terminal=cleanup,
    )
    assert await restarted.run_once() == 1

    completed = await repository.load_settlement_operation(
        record.obligation_ref,
        "cleanup",
    )
    stored = await repository.load_settlement_obligation(record.obligation_ref)
    assert completed is not None
    assert completed["state"] == "succeeded"
    assert attempts == ["cleanup", "cleanup"]
    assert stored is not None
    assert stored["fulfillment_ref"] == "durable-fulfillment-evidence"
    assert stored["collection_state"] == "pending"

async def _adopted_without_fulfillment(tmp_path, client):
    repository = SettlementSQLiteRepository(str(tmp_path / "one.db"))
    runtime = SettlementRuntime(repository, {"test.v1": client})
    record = (
        await runtime.register_plan(
            agreement_ref="agreement-one",
            obligations=[
                {
                    "payer": "buyer",
                    "claimant": "seller",
                    "payer_principal": BUYER.model_dump(mode="json"),
                    "claimant_principal": SELLER.model_dump(mode="json"),
                    "mechanism": "test.v1",
                    "expiration_unix": 4_102_444_800,
                }
            ],
        )
    )[0]
    await runtime.adopt(
        record.obligation_ref,
        local_principal=SELLER,
        mechanism_ref="escrow",
    )
    return repository, runtime, record


def _deferring(runtime: SettlementRuntime, calls: list[str]):
    """A ready hook whose delivery is never ready: it reserves, then defers."""

    async def on_ready(ready, worker_id):
        calls.append(worker_id)
        reserved = await runtime.reserve_fulfillment(
            ready.obligation_ref, local_principal=SELLER, worker_id=worker_id
        )
        if reserved.status == "pending":
            await runtime.defer_fulfillment(
                ready.obligation_ref, local_principal=SELLER, worker_id=worker_id
            )

    return on_ready


def _completing(runtime: SettlementRuntime):
    async def on_ready(ready, worker_id):
        reserved = await runtime.reserve_fulfillment(
            ready.obligation_ref, local_principal=SELLER, worker_id=worker_id
        )
        if reserved.status == "pending":
            await runtime.complete_fulfillment(
                ready.obligation_ref,
                "fulfillment-1",
                local_principal=SELLER,
                worker_id=worker_id,
            )

    return on_ready


async def _fulfill_operation(repository, record) -> dict:
    operation = await repository.load_settlement_operation(
        record.obligation_ref, "fulfill"
    )
    assert operation is not None
    return operation


async def test_a_ready_step_awaiting_delivery_is_due_every_cycle(tmp_path) -> None:
    """Several deferrals in a row: due each next cycle, no attempt counted."""
    repository, runtime, record = await _adopted_without_fulfillment(
        tmp_path, PollingClient()
    )
    calls: list[str] = []
    worker = SettlementServicingWorker(
        runtime,
        repository,
        worker_id="w",
        interval_seconds=1,
        on_ready=_deferring(runtime, calls),
    )

    for cycle in range(1, 4):
        assert await worker.run_once() == 1
        operation = await _fulfill_operation(repository, record)
        assert operation["state"] == "pending"
        assert operation["attempts"] == 0
        assert operation["lease_owner"] is None
        assert operation["next_attempt_unix"] <= time.time()
        # Honoured, so consumed: the next step writes its own.
        assert operation["awaiting_delivery"] is False
        assert len(calls) == cycle

    delivered = SettlementServicingWorker(
        runtime, repository, worker_id="w", interval_seconds=1,
        on_ready=_completing(runtime),
    )
    assert await delivered.run_once() == 1
    stored = await repository.load_settlement_obligation(record.obligation_ref)
    assert stored["fulfillment_ref"] == "fulfillment-1"


async def test_a_restarted_worker_finds_an_obligation_awaiting_delivery_due(
    tmp_path,
) -> None:
    """The mark is written and the process stops before scheduling anything."""
    repository, runtime, record = await _adopted_without_fulfillment(
        tmp_path, PollingClient()
    )
    await _deferring(runtime, [])(record, "stopped-worker")

    reopened = SettlementSQLiteRepository(str(tmp_path / "one.db"))
    due = await reopened.list_due_settlement_obligations(now_unix=time.time())
    assert [row["obligation_ref"] for row in due] == [record.obligation_ref]
    operation = await _fulfill_operation(reopened, record)
    assert operation["lease_owner"] is None
    assert operation["lease_until_unix"] is None
    assert operation["attempts"] == 0

    restarted_runtime = SettlementRuntime(reopened, {"test.v1": PollingClient()})
    restarted = SettlementServicingWorker(
        restarted_runtime,
        reopened,
        worker_id="restarted",
        interval_seconds=1,
        on_ready=_completing(restarted_runtime),
    )
    assert await restarted.run_once() == 1
    stored = await reopened.load_settlement_obligation(record.obligation_ref)
    assert stored["fulfillment_ref"] == "fulfillment-1"


async def test_a_lease_clears_the_awaiting_delivery_mark(tmp_path) -> None:
    repository, runtime, record = await _adopted_without_fulfillment(
        tmp_path, PollingClient()
    )
    await _deferring(runtime, [])(record, "w")

    reserved = await runtime.reserve_fulfillment(
        record.obligation_ref, local_principal=SELLER, worker_id="w"
    )

    assert reserved.status == "pending"
    operation = await _fulfill_operation(repository, record)
    assert operation["state"] == "in_progress"
    assert operation["awaiting_delivery"] is False
    assert operation["attempts"] == 1


async def test_retry_scheduling_and_wake_treat_an_awaiting_operation_as_pending(
    tmp_path,
) -> None:
    """Due query, retry schedule, and wake read no mark: what an older release reads."""
    repository, runtime, record = await _adopted_without_fulfillment(
        tmp_path, PollingClient()
    )
    await _deferring(runtime, [])(record, "w")
    now = time.time()

    await repository.schedule_settlement_retry(
        obligation_ref=record.obligation_ref,
        operation="fulfill",
        next_attempt_unix=now + 600,
    )
    assert await repository.list_due_settlement_obligations(now_unix=now) == []

    await repository.wake_settlement_obligation(record.obligation_ref)
    due = await repository.list_due_settlement_obligations(now_unix=now)
    assert [row["obligation_ref"] for row in due] == [record.obligation_ref]


async def test_a_ready_step_returning_without_the_mark_backs_off(tmp_path) -> None:
    repository, runtime, record = await _adopted_without_fulfillment(
        tmp_path, PollingClient()
    )

    async def released_unmarked(ready, worker_id):
        await runtime.reserve_fulfillment(
            ready.obligation_ref, local_principal=SELLER, worker_id=worker_id
        )
        await runtime.retry_fulfillment(
            ready.obligation_ref,
            RuntimeError("not started"),
            local_principal=SELLER,
            worker_id=worker_id,
        )

    worker = SettlementServicingWorker(
        runtime, repository, worker_id="w", interval_seconds=1,
        on_ready=released_unmarked,
    )
    before = time.time()
    assert await worker.run_once() == 1

    operation = await _fulfill_operation(repository, record)
    assert operation["awaiting_delivery"] is False
    assert operation["next_attempt_unix"] >= before + 30
    assert await repository.list_due_settlement_obligations(now_unix=time.time()) == []


async def test_a_mark_an_earlier_step_wrote_does_not_spare_a_later_one(
    tmp_path,
) -> None:
    """A step that neither starts nor waits backs off, after any earlier wait."""
    repository, runtime, record = await _adopted_without_fulfillment(
        tmp_path, PollingClient()
    )
    waiting = SettlementServicingWorker(
        runtime, repository, worker_id="w", interval_seconds=1,
        on_ready=_deferring(runtime, []),
    )
    assert await waiting.run_once() == 1

    async def neither(_ready, _worker_id):
        return None

    idle = SettlementServicingWorker(
        runtime, repository, worker_id="w", interval_seconds=1, on_ready=neither
    )
    before = time.time()
    assert await idle.run_once() == 1

    operation = await _fulfill_operation(repository, record)
    assert operation["next_attempt_unix"] >= before + 30


class _PredatesTheMark:
    """A repository read as a release that does not know the mark reads it."""

    def __init__(self, repository: SettlementSQLiteRepository) -> None:
        self._repository = repository

    def __getattr__(self, name):
        return getattr(self._repository, name)

    async def load_settlement_operation(self, obligation_ref, operation):
        row = await self._repository.load_settlement_operation(obligation_ref, operation)
        if row is not None:
            row.pop("awaiting_delivery")
        return row


async def test_a_worker_without_the_mark_backs_off_an_awaiting_operation(
    tmp_path,
) -> None:
    """Rollback degrades to the error backoff and never strands the obligation."""
    repository, runtime, record = await _adopted_without_fulfillment(
        tmp_path, PollingClient()
    )
    worker = SettlementServicingWorker(
        runtime,
        _PredatesTheMark(repository),
        worker_id="older",
        interval_seconds=1,
        on_ready=_deferring(runtime, []),
    )
    before = time.time()

    assert await worker.run_once() == 1

    operation = await _fulfill_operation(repository, record)
    assert operation["state"] == "pending"
    assert operation["next_attempt_unix"] >= before + 30
    later = await repository.list_due_settlement_obligations(
        now_unix=operation["next_attempt_unix"]
    )
    assert [row["obligation_ref"] for row in later] == [record.obligation_ref]


async def test_service_obligation_starts_fulfillment_through_the_ready_hook(
    tmp_path,
) -> None:
    repository, runtime, record = await _adopted_without_fulfillment(
        tmp_path, PollingClient()
    )
    started: list[str] = []

    async def on_ready(ready, _worker_id):
        started.append(ready.obligation_ref)
        await runtime.bind_fulfillment(
            ready.obligation_ref, "fulfillment-1", local_principal=SELLER
        )

    worker = SettlementServicingWorker(
        runtime, repository, worker_id="w", interval_seconds=1, on_ready=on_ready
    )

    await worker.service_obligation(record.obligation_ref)

    assert started == [record.obligation_ref]
    stored = await repository.load_settlement_obligation(record.obligation_ref)
    assert stored["fulfillment_ref"] == "fulfillment-1"


async def test_a_failed_start_is_left_to_the_workers_retry(tmp_path) -> None:
    repository, runtime, record = await _adopted_without_fulfillment(
        tmp_path, PollingClient()
    )
    attempts: list[int] = []
    events: list[str] = []

    async def on_ready(_ready, _worker_id):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("site unavailable")
        await runtime.bind_fulfillment(
            record.obligation_ref, "fulfillment-1", local_principal=SELLER
        )

    worker = SettlementServicingWorker(
        runtime,
        repository,
        worker_id="w",
        interval_seconds=1,
        on_ready=on_ready,
        on_event=lambda event, _fields: events.append(event),
    )

    await worker.service_obligation(record.obligation_ref)
    stored = await repository.load_settlement_obligation(record.obligation_ref)
    assert stored["fulfillment_ref"] is None
    assert "settlement_retry" in events

    await worker.wake(record.obligation_ref)
    assert await worker.run_once() == 1
    stored = await repository.load_settlement_obligation(record.obligation_ref)
    assert stored["fulfillment_ref"] == "fulfillment-1"
    assert len(attempts) == 2


async def test_service_obligation_refuses_an_unknown_obligation(tmp_path) -> None:
    repository = SettlementSQLiteRepository(str(tmp_path / "none.db"))
    worker = SettlementServicingWorker(
        SettlementRuntime(repository, {"test.v1": PollingClient()}),
        repository,
        worker_id="w",
        interval_seconds=1,
    )

    with pytest.raises(KeyError):
        await worker.service_obligation("missing")


async def test_an_unstarted_ready_obligation_is_due_until_an_attempt_holds_it(
    tmp_path,
) -> None:
    repository, runtime, record = await _adopted_without_fulfillment(
        tmp_path, PollingClient()
    )

    due = await repository.list_due_settlement_obligations(now_unix=10**10)
    assert [row["obligation_ref"] for row in due] == [record.obligation_ref]

    reserved = await runtime.reserve_fulfillment(
        record.obligation_ref, local_principal=SELLER, worker_id="w"
    )
    assert reserved.status == "pending"
    leased = await repository.list_due_settlement_obligations(now_unix=0)
    assert leased == []

    await runtime.retry_fulfillment(
        record.obligation_ref,
        RuntimeError("site unavailable"),
        local_principal=SELLER,
        worker_id="w",
    )
    operation = await repository.load_settlement_operation(
        record.obligation_ref, "fulfill"
    )
    assert operation["state"] == "pending"
    if operation["next_attempt_unix"] is not None:
        assert await repository.list_due_settlement_obligations(
            now_unix=operation["next_attempt_unix"] - 1
        ) == []
    retry_due = await repository.list_due_settlement_obligations(now_unix=10**10)
    assert [row["obligation_ref"] for row in retry_due] == [record.obligation_ref]


async def test_an_obligation_that_is_not_ready_is_not_due_for_fulfillment(
    tmp_path,
) -> None:
    repository = SettlementSQLiteRepository(str(tmp_path / "pending.db"))
    runtime = SettlementRuntime(repository, {"test.v1": PollingClient()})
    await runtime.register_plan(
        agreement_ref="agreement-pending",
        obligations=[
            {
                "payer": "buyer",
                "claimant": "seller",
                "payer_principal": BUYER.model_dump(mode="json"),
                "claimant_principal": SELLER.model_dump(mode="json"),
                "mechanism": "test.v1",
                "expiration_unix": 4_102_444_800,
            }
        ],
    )

    assert await repository.list_due_settlement_obligations(now_unix=10**10) == []


async def test_a_concurrent_pass_sees_an_obligation_being_serviced_as_busy(
    tmp_path,
) -> None:
    """While ``service_obligation`` holds the fulfillment lease, another worker's
    pass over the same database starts no second fulfillment.

    The ready hook reserves the attempt through the runtime, as every
    storefront's hook does; that reservation is the lease the second pass meets.
    """
    repository, runtime, record = await _adopted_without_fulfillment(
        tmp_path, PollingClient()
    )
    holding = asyncio.Event()
    release = asyncio.Event()
    starts: list[str] = []

    def ready_hook(hook_runtime: SettlementRuntime):
        async def on_ready(ready, worker_id):
            reserved = await hook_runtime.reserve_fulfillment(
                ready.obligation_ref, local_principal=SELLER, worker_id=worker_id
            )
            if reserved.status != "pending":
                return
            starts.append(worker_id)
            holding.set()
            await release.wait()
            await hook_runtime.complete_fulfillment(
                ready.obligation_ref,
                "fulfillment-1",
                local_principal=SELLER,
                worker_id=worker_id,
            )

        return on_ready

    first = SettlementServicingWorker(
        runtime,
        repository,
        worker_id="worker-one",
        interval_seconds=1,
        on_ready=ready_hook(runtime),
    )
    other_repository = SettlementSQLiteRepository(str(tmp_path / "one.db"))
    other_runtime = SettlementRuntime(other_repository, {"test.v1": PollingClient()})
    second = SettlementServicingWorker(
        other_runtime,
        other_repository,
        worker_id="worker-two",
        interval_seconds=1,
        on_ready=ready_hook(other_runtime),
    )

    servicing = asyncio.create_task(first.service_obligation(record.obligation_ref))
    try:
        await asyncio.wait_for(holding.wait(), timeout=5.0)

        assert await second.run_once() == 0
        busy = await other_runtime.reserve_fulfillment(
            record.obligation_ref, local_principal=SELLER, worker_id="worker-two"
        )
        assert busy.status == "busy"
    finally:
        release.set()
        await asyncio.wait_for(servicing, timeout=5.0)

    assert starts == ["worker-one"]
    stored = await other_repository.load_settlement_obligation(record.obligation_ref)
    assert stored["fulfillment_ref"] == "fulfillment-1"
    operation = await other_repository.load_settlement_operation(
        record.obligation_ref, "fulfill"
    )
    assert operation["state"] == "succeeded"
