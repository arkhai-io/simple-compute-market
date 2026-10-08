"""Durable settlement servicing against a real SQLite database.

The worker, runtime, and repository are the library's own; only the mechanism
client is a fake. Concurrency cases use separate repository instances, and so
separate connections, over one database file.
"""

from __future__ import annotations

import asyncio

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
