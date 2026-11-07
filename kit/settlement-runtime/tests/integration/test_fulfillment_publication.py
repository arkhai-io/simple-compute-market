"""Recorded fulfillment submissions, parking, and the parked count.

These run against the real SQLite repository: what they prove is that the
journal keeps a submission and its reference across lease takeover and refuses
to rewrite either, which is a property of the stored rows rather than of the
runtime's control flow.
"""

from __future__ import annotations

import sqlite3

import pytest

from market_settlement_runtime import (
    FULFILLMENT_REFERENCE_KEY,
    FULFILLMENT_SUBMISSION_KEY,
    MANUAL_REASON_KEY,
    SettlementManualRequired,
    SettlementOperationConflict,
    SettlementRuntime,
    SettlementSQLiteRepository,
    StatusOutcome,
)

from .test_servicing import BUYER, SELLER, PollingClient


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


async def _adopted(tmp_path, *, agreement_ref: str = "agreement-one", clock=None):
    repository = SettlementSQLiteRepository(str(tmp_path / "journal.db"))
    runtime = SettlementRuntime(
        repository,
        {"test.v1": PollingClient()},
        clock=clock or Clock(),
        lease_seconds=30.0,
    )
    record = (
        await runtime.register_plan(
            agreement_ref=agreement_ref,
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
        record.obligation_ref, local_principal=SELLER, mechanism_ref="escrow"
    )
    return repository, runtime, record


async def _reserve(runtime, record, worker_id: str = "w1"):
    return await runtime.reserve_fulfillment(
        record.obligation_ref, local_principal=SELLER, worker_id=worker_id
    )


async def test_a_submission_and_its_reference_survive_a_lease_takeover(
    tmp_path,
) -> None:
    clock = Clock()
    _repository, runtime, record = await _adopted(tmp_path, clock=clock)
    first = await _reserve(runtime, record, "w1")
    assert first.status == "pending" and first.receipt is None
    assert first.attempts == 1

    await runtime.record_fulfillment_submission(
        record.obligation_ref,
        {"digest": "sha256:aa"},
        local_principal=SELLER,
        worker_id="w1",
    )
    await runtime.record_fulfillment_publication(
        record.obligation_ref, "0xuid", local_principal=SELLER, worker_id="w1"
    )

    # w1 stops without completing; its lease expires and w2 takes over.
    clock.now += 60
    resumed = await _reserve(runtime, record, "w2")

    assert resumed.status == "pending"
    assert resumed.receipt == {
        FULFILLMENT_SUBMISSION_KEY: {"digest": "sha256:aa"},
        FULFILLMENT_REFERENCE_KEY: "0xuid",
    }
    assert resumed.attempts == 2


async def test_recording_the_same_values_again_changes_nothing(tmp_path) -> None:
    repository, runtime, record = await _adopted(tmp_path)
    await _reserve(runtime, record)
    for _ in range(2):
        await runtime.record_fulfillment_submission(
            record.obligation_ref,
            {"digest": "sha256:aa"},
            local_principal=SELLER,
            worker_id="w1",
        )
        await runtime.record_fulfillment_publication(
            record.obligation_ref, "0xuid", local_principal=SELLER, worker_id="w1"
        )

    operation = await repository.load_settlement_operation(
        record.obligation_ref, "fulfill"
    )
    assert operation["receipt"] == {
        FULFILLMENT_SUBMISSION_KEY: {"digest": "sha256:aa"},
        FULFILLMENT_REFERENCE_KEY: "0xuid",
    }
    assert operation["uncertain_acknowledgement"] is True


async def test_a_different_submission_or_reference_is_refused(tmp_path) -> None:
    repository, runtime, record = await _adopted(tmp_path)
    await _reserve(runtime, record)
    await runtime.record_fulfillment_submission(
        record.obligation_ref,
        {"digest": "sha256:aa"},
        local_principal=SELLER,
        worker_id="w1",
    )
    await runtime.record_fulfillment_publication(
        record.obligation_ref, "0xuid", local_principal=SELLER, worker_id="w1"
    )

    with pytest.raises(SettlementOperationConflict):
        await runtime.record_fulfillment_submission(
            record.obligation_ref,
            {"digest": "sha256:bb"},
            local_principal=SELLER,
            worker_id="w1",
        )
    with pytest.raises(SettlementOperationConflict):
        await runtime.record_fulfillment_publication(
            record.obligation_ref, "0xother", local_principal=SELLER, worker_id="w1"
        )

    operation = await repository.load_settlement_operation(
        record.obligation_ref, "fulfill"
    )
    assert operation["receipt"] == {
        FULFILLMENT_SUBMISSION_KEY: {"digest": "sha256:aa"},
        FULFILLMENT_REFERENCE_KEY: "0xuid",
    }


async def test_a_cleared_submission_is_gone_but_a_published_one_stays(
    tmp_path,
) -> None:
    repository, runtime, record = await _adopted(tmp_path)
    await _reserve(runtime, record)
    await runtime.record_fulfillment_submission(
        record.obligation_ref,
        {"digest": "sha256:aa"},
        local_principal=SELLER,
        worker_id="w1",
    )
    await runtime.clear_fulfillment_submission(
        record.obligation_ref, local_principal=SELLER, worker_id="w1"
    )
    cleared = await repository.load_settlement_operation(
        record.obligation_ref, "fulfill"
    )
    assert cleared["receipt"] is None

    await runtime.record_fulfillment_submission(
        record.obligation_ref,
        {"digest": "sha256:bb"},
        local_principal=SELLER,
        worker_id="w1",
    )
    await runtime.record_fulfillment_publication(
        record.obligation_ref, "0xuid", local_principal=SELLER, worker_id="w1"
    )
    with pytest.raises(SettlementOperationConflict):
        await runtime.clear_fulfillment_submission(
            record.obligation_ref, local_principal=SELLER, worker_id="w1"
        )
    kept = await repository.load_settlement_operation(
        record.obligation_ref, "fulfill"
    )
    assert kept["receipt"][FULFILLMENT_SUBMISSION_KEY] == {"digest": "sha256:bb"}


async def test_only_the_lease_holder_records_or_clears(tmp_path) -> None:
    _repository, runtime, record = await _adopted(tmp_path)
    await _reserve(runtime, record, "w1")

    with pytest.raises(RuntimeError, match="lease was lost"):
        await runtime.record_fulfillment_submission(
            record.obligation_ref,
            {"digest": "sha256:aa"},
            local_principal=SELLER,
            worker_id="w2",
        )
    with pytest.raises(RuntimeError, match="lease was lost"):
        await runtime.clear_fulfillment_submission(
            record.obligation_ref, local_principal=SELLER, worker_id="w2"
        )
    with pytest.raises(PermissionError):
        await runtime.record_fulfillment_submission(
            record.obligation_ref,
            {"digest": "sha256:aa"},
            local_principal=BUYER,
            worker_id="w1",
        )


async def test_a_retry_keeps_the_recorded_submission(tmp_path) -> None:
    clock = Clock()
    _repository, runtime, record = await _adopted(tmp_path, clock=clock)
    await _reserve(runtime, record, "w1")
    await runtime.record_fulfillment_submission(
        record.obligation_ref,
        {"digest": "sha256:aa"},
        local_principal=SELLER,
        worker_id="w1",
    )
    await runtime.retry_fulfillment(
        record.obligation_ref,
        RuntimeError("chain unavailable"),
        local_principal=SELLER,
        worker_id="w1",
    )

    resumed = await _reserve(runtime, record, "w2")
    assert resumed.receipt == {FULFILLMENT_SUBMISSION_KEY: {"digest": "sha256:aa"}}


async def test_a_parked_fulfillment_waits_for_an_operator_and_is_counted(
    tmp_path,
) -> None:
    repository, runtime, record = await _adopted(tmp_path)
    await _reserve(runtime, record)

    outcome = await runtime.park_fulfillment(
        record.obligation_ref,
        SettlementManualRequired("outcome unknown", code="submission_unknown"),
        local_principal=SELLER,
        worker_id="w1",
    )

    assert outcome.status == "manual_required"
    operation = await repository.load_settlement_operation(
        record.obligation_ref, "fulfill"
    )
    assert operation["state"] == "manual_required"
    stored = await repository.load_settlement_obligation(record.obligation_ref)
    assert stored["mechanism_state"][MANUAL_REASON_KEY] == "submission_unknown"
    assert await repository.list_due_settlement_obligations(now_unix=10**10) == []
    assert await runtime.manual_required_count() == 1

    again = await _reserve(runtime, record, "w2")
    assert again.status == "manual_required"


async def test_the_count_includes_each_parked_obligation_once(tmp_path) -> None:
    repository, runtime, record = await _adopted(tmp_path)
    other = (
        await runtime.register_plan(
            agreement_ref="agreement-two",
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
    assert await runtime.manual_required_count() == 0

    await _reserve(runtime, record)
    await runtime.park_fulfillment(
        record.obligation_ref,
        SettlementManualRequired("parked", code="one"),
        local_principal=SELLER,
        worker_id="w1",
    )
    # The same obligation also parked by its mechanism counts once. A
    # mechanism parks through its status write; the row is set directly here
    # because no test client reports a park.
    conn = sqlite3.connect(str(tmp_path / "journal.db"))
    with conn:
        conn.execute(
            "UPDATE settlement_obligations SET mechanism_status='manual_required' "
            "WHERE obligation_ref=?",
            (record.obligation_ref,),
        )
    conn.close()
    assert await runtime.manual_required_count() == 1

    unparked = await repository.load_settlement_obligation(other.obligation_ref)
    assert unparked["mechanism_status"] != "manual_required"
    assert await runtime.manual_required_count() == 1


class FreshStateClient(PollingClient):
    """Reports its own current state on every poll, naming no park reason."""

    async def get_status(
        self, obligation, *, mechanism_ref, operation_ref, mechanism_state
    ):
        self.status_calls += 1
        return StatusOutcome(
            status="ready",
            mechanism_ref=mechanism_ref,
            mechanism_state={"polled": self.status_calls},
        )


async def test_a_parked_fulfillments_reason_survives_a_later_status_poll(
    tmp_path,
) -> None:
    repository = SettlementSQLiteRepository(str(tmp_path / "journal.db"))
    runtime = SettlementRuntime(repository, {"test.v1": FreshStateClient()})
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
        record.obligation_ref, local_principal=SELLER, mechanism_ref="escrow"
    )
    await _reserve(runtime, record)
    await runtime.park_fulfillment(
        record.obligation_ref,
        SettlementManualRequired("parked", code="submission_unknown"),
        local_principal=SELLER,
        worker_id="w1",
    )

    await runtime.reconcile_status(
        obligation_ref=record.obligation_ref, local_principal=SELLER, worker_id="w2"
    )

    stored = await repository.load_settlement_obligation(record.obligation_ref)
    assert stored["mechanism_state"]["polled"] == 1
    assert stored["mechanism_state"][MANUAL_REASON_KEY] == "submission_unknown"
