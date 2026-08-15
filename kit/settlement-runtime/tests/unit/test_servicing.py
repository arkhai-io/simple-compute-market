from __future__ import annotations

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
        self, obligation, *, mechanism_ref, operation_ref, mechanism_state
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