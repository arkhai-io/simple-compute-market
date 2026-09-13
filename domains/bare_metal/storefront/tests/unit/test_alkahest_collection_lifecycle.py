from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from arkhai_bare_metal import (
    BareMetalAccessResult,
    BareMetalMaterialization,
    BareMetalReceipt,
    bare_metal_digest,
)
from market_identity import Ed25519Signer
from market_settlement_runtime import (
    ConditionOutcome,
    EffectOutcome,
    SettlementObligationRecord,
    StatusOutcome,
)

from arkhai_bare_metal_storefront.alkahest_lifecycle import (
    BareMetalAlkahestLifecycleCallbacks,
    BareMetalAlkahestLifecycleError,
)

BUYER = Ed25519Signer(bytes.fromhex("11" * 32)).identity
SELLER = Ed25519Signer(bytes.fromhex("22" * 32)).identity
SELLER_ADDRESS = "0x" + "33" * 20
ESCROW = "0x" + "44" * 32
FULFILLMENT = "0x" + "55" * 32
NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _record() -> SettlementObligationRecord:
    obligation = {
        "mechanism": "alkahest.v1",
        "payer": "buyer",
        "claimant": "seller",
        "payer_principal": BUYER.model_dump(mode="json"),
        "claimant_principal": SELLER.model_dump(mode="json"),
        "amount": 100,
        "asset": "erc20:token",
        "expiration_unix": 2_000_000_000,
        "params": {
            "chain_name": "chain-a",
            "escrow_contract": "0x" + "66" * 20,
            "obligation_data": {
                "token": "0x" + "77" * 20,
                "amount": 100,
                "arbiter": "0x" + "88" * 20,
                "demand": "0x" + "00" * 32,
            },
        },
    }
    return SettlementObligationRecord(
        obligation_ref="a" * 64,
        agreement_ref="agreement-a",
        obligation_index=0,
        obligation_hash="b" * 64,
        obligation=obligation,
        payer_principal=BUYER,
        claimant_principal=SELLER,
        mechanism_ref=ESCROW,
        mechanism_status="ready",
        materialization_state="materialized",
    )


class FakeRuntime:
    def __init__(self) -> None:
        self.completed: list[str] = []
        self.deferred = 0
        self.retried = 0
        self.fenced = 0
        self.fence_error: Exception | None = None

    async def reserve_fulfillment(self, *_args, **_kwargs):
        return SimpleNamespace(status="pending")

    async def complete_fulfillment(self, _ref, uid, **_kwargs):
        self.completed.append(uid)
        return _record().model_copy(update={"fulfillment_ref": uid})

    async def fence_fulfillment_publication(self, *_args, **_kwargs):
        self.fenced += 1
        if self.fence_error is not None:
            raise self.fence_error

    async def defer_fulfillment(self, *_args, **_kwargs):
        self.deferred += 1

    async def retry_fulfillment(self, *_args, **_kwargs):
        self.retried += 1


class FakeSettlementRepository:
    def __init__(self, collect_operation=None) -> None:
        self.collect_operation = collect_operation

    async def load_settlement_operation(self, _obligation_ref, operation):
        assert operation == "collect"
        return self.collect_operation


class FakePhysical:
    def __init__(self, state: str = "active", *, machine_id: str = "machine-a") -> None:
        self.state = state
        self.machine_id = machine_id
        self.begin_calls = 0

    async def begin(self, **_kwargs):
        self.begin_calls += 1
        return {"state": self.state}

    async def status(self, **_kwargs):
        return {
            "state": self.state,
            "site_id": "site-a",
            "physical_resource_id": "resource-a",
            "capacity_reservation_id": "reservation-a",
            "settlement_resource_id": "settlement-resource-a",
            "fulfillment_id": "provisioning-a",
        }

    async def lease_ready_evidence_inputs(self, **_kwargs):
        lifecycle = await self.status(**_kwargs)
        if lifecycle["state"] != "active":
            return {"lifecycle": lifecycle}
        materialization = BareMetalMaterialization(
            escrow_uid=ESCROW,
            machine_id="machine-a",
            physical_host_id="host-a",
            lease_start_utc=NOW,
            lease_end_utc=NOW + timedelta(hours=1),
            access_method="ssh",
            ssh_public_key="ssh-ed25519 AAAA",
        )
        return {
            "lifecycle": lifecycle,
            "materialization": materialization,
            "result": BareMetalAccessResult(
                action="node_grant_access",
                machine_id=self.machine_id,
                physical_host_id="host-a",
                ssh_user="lease-user",
                host="buyer.example.test",
                port=22,
                escrow_uid=ESCROW,
                access_grant_ref="grant-a",
                lease_expires_at=NOW + timedelta(hours=1),
                timestamp=NOW.isoformat(),
                status="success",
            ),
            "receipt": BareMetalReceipt(
                escrow_uid=ESCROW,
                machine_id="machine-a",
                physical_host_id="host-a",
                lease_start_utc=NOW,
                lease_end_utc=NOW + timedelta(hours=1),
                status="ready",
                access_ref={"fulfillment_id": "provisioning-a"},
            ),
        }


class FakePublisher:
    def __init__(
        self,
        *,
        submit_error: Exception | None = None,
        confirm_errors: list[Exception] | None = None,
    ) -> None:
        self.submit_error = submit_error
        self.confirm_errors = list(confirm_errors or [])
        self.submissions: list[tuple[str, str]] = []
        self.confirmations: list[str] = []

    @property
    def publisher_address(self) -> str:
        return SELLER_ADDRESS

    async def submit_fulfillment(self, *, condition_anchor, evidence):
        self.submissions.append((condition_anchor, evidence))
        if self.submit_error:
            raise self.submit_error
        return FULFILLMENT

    async def confirm_fulfillment(
        self, *, fulfillment_uid, condition_anchor, evidence
    ):
        assert condition_anchor == ESCROW
        assert "bare_metal.alkahest-lease-ready-evidence.v1" in evidence
        self.confirmations.append(fulfillment_uid)
        if self.confirm_errors:
            raise self.confirm_errors.pop(0)
        return fulfillment_uid


class FakeDb:
    def __init__(self, record: SettlementObligationRecord) -> None:
        plan = {"obligations": [record.obligation]}
        self.binding = {
            "obligation_ref": record.obligation_ref,
            "agreement_ref": record.agreement_ref,
            "escrow_uid": ESCROW,
            "accepted_plan_digest": bare_metal_digest(plan),
            "seller_recipient": SELLER_ADDRESS,
            "evidence_json": None,
            "evidence_digest": None,
            "publication_state": "pending",
            "publication_owner": None,
            "fulfillment_uid": None,
            "terminal_state": "pending",
        }
        self.thread = {
            "settlement_plan": plan,
            "buyer_principal": BUYER.model_dump(mode="json"),
            "seller_principal": SELLER.model_dump(mode="json"),
        }
        self.lifecycle = {
            "site_id": "site-a",
            "physical_resource_id": "resource-a",
            "capacity_reservation_id": "reservation-a",
            "settlement_resource_id": "settlement-resource-a",
            "fulfillment_id": "provisioning-a",
            "state": "active",
        }
        self.materialization = BareMetalMaterialization(
            escrow_uid=ESCROW,
            machine_id="machine-a",
            physical_host_id="host-a",
            lease_start_utc=NOW,
            lease_end_utc=NOW + timedelta(hours=1),
            access_method="ssh",
            ssh_public_key="ssh-ed25519 AAAA",
        )
        self.result = BareMetalAccessResult(
            action="node_grant_access",
            machine_id="machine-a",
            physical_host_id="host-a",
            ssh_user="lease-user",
            escrow_uid=ESCROW,
            access_grant_ref="grant-a",
            lease_expires_at=NOW + timedelta(hours=1),
            timestamp=NOW.isoformat(),
            status="success",
        )
        self.receipt = BareMetalReceipt(
            escrow_uid=ESCROW,
            machine_id="machine-a",
            physical_host_id="host-a",
            lease_start_utc=NOW,
            lease_end_utc=NOW + timedelta(hours=1),
            status="ready",
            access_ref={"fulfillment_id": "provisioning-a"},
        )
        self.fail_uid_saves = 0
        self.submission_claims = 0

    async def load_bare_metal_alkahest_evidence(self, **_kwargs):
        return dict(self.binding)

    async def load_negotiation_thread_row(self, **_kwargs):
        return dict(self.thread)

    async def load_bare_metal_fulfillment_lifecycle(self, **_kwargs):
        return dict(self.lifecycle)

    async def load_bare_metal_materialization(self, **_kwargs):
        return self.materialization

    async def load_bare_metal_result(self, **_kwargs):
        return self.result

    async def load_bare_metal_receipt(self, **_kwargs):
        return self.receipt

    async def record_bare_metal_alkahest_evidence_intent(
        self, *, evidence, **_kwargs
    ):
        evidence_json = evidence.canonical_json()
        if self.binding["evidence_json"] not in (None, evidence_json):
            raise RuntimeError("changed evidence")
        self.binding.update(
            evidence_json=evidence_json,
            evidence_digest=evidence.evidence_digest,
            publication_state=(
                "intent_recorded"
                if self.binding["publication_state"] == "pending"
                else self.binding["publication_state"]
            ),
        )
        return dict(self.binding)

    async def advance_bare_metal_alkahest_evidence(self, **fields):
        fields.pop("obligation_ref")
        owner = fields.pop("publication_owner", None)
        if owner is not None and self.binding["publication_owner"] != owner:
            raise RuntimeError("publication ownership was lost")
        if fields.get("publication_state") == "uid_recorded" and self.fail_uid_saves:
            self.fail_uid_saves -= 1
            raise RuntimeError("receipt persistence failed")
        self.binding.update({k: v for k, v in fields.items() if v is not None})
        return dict(self.binding)

    async def claim_bare_metal_alkahest_evidence_submission(
        self, *, obligation_ref, evidence_digest, worker_id
    ):
        self.submission_claims += 1
        assert obligation_ref == self.binding["obligation_ref"]
        if (
            self.binding["publication_state"] != "intent_recorded"
            or self.binding["evidence_digest"] != evidence_digest
            or self.binding["publication_owner"] is not None
        ):
            return None
        self.binding.update(
            publication_state="submitting",
            publication_owner=worker_id,
        )
        return dict(self.binding)


class RecordingConditionalEscrow:
    def __init__(
        self,
        *,
        collect_error: Exception | None = None,
        status: str = "ready",
    ) -> None:
        self.collect_calls: list[dict] = []
        self.collect_error = collect_error
        self.status = status

    async def get_status(
        self, obligation, *, mechanism_ref, operation_ref, mechanism_state
    ):
        assert obligation["params"]["obligation_data"]["amount"] == 100
        return StatusOutcome(
            status=self.status,
            mechanism_ref=mechanism_ref,
            condition_anchor=mechanism_ref,
            mechanism_state=mechanism_state,
            last_error=(
                "chain state cannot distinguish collection from reclaim"
                if self.status == "manual_required"
                else None
            ),
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
        assert mechanism_ref == ESCROW
        assert fulfillment_ref == FULFILLMENT
        return ConditionOutcome(decision="ready", mechanism_state=mechanism_state)

    async def collect(
        self,
        obligation,
        *,
        mechanism_ref,
        fulfillment_ref,
        operation_ref,
        mechanism_state,
    ):
        self.collect_calls.append(
            {
                "obligation": obligation,
                "mechanism_ref": mechanism_ref,
                "fulfillment_ref": fulfillment_ref,
                "operation_ref": operation_ref,
            }
        )
        if self.collect_error is not None:
            raise self.collect_error
        return EffectOutcome(
            receipt={"receipt": "0xcollection"},
            mechanism_state=mechanism_state,
        )

    async def materialize(self, *_args, **_kwargs):
        raise AssertionError("settlement was already materialized")

    async def reclaim_expired(self, *_args, **_kwargs):
        raise AssertionError("seller collection must not reclaim")


def _callbacks(
    *,
    db=None,
    runtime=None,
    repository=None,
    physical=None,
    publisher=None,
):
    record = _record()
    return record, BareMetalAlkahestLifecycleCallbacks(
        db=db or FakeDb(record),
        runtime=runtime or FakeRuntime(),
        settlement_repository=repository or FakeSettlementRepository(),
        local_principal=SELLER,
        fulfillment_service=physical or FakePhysical(),
        publishers={"chain-a": publisher or FakePublisher()},
    )


@pytest.mark.asyncio
async def test_active_delivery_publishes_confirms_and_binds_fulfillment() -> None:
    runtime = FakeRuntime()
    publisher = FakePublisher()
    record, callbacks = _callbacks(runtime=runtime, publisher=publisher)

    await callbacks.fulfill(record, "worker-a")

    assert len(publisher.submissions) == 1
    assert runtime.fenced == 1
    assert publisher.confirmations == [FULFILLMENT]
    assert runtime.completed == [FULFILLMENT]


@pytest.mark.asyncio
async def test_pending_delivery_defers_without_publication_or_collection() -> None:
    runtime = FakeRuntime()
    publisher = FakePublisher()
    record, callbacks = _callbacks(
        runtime=runtime,
        physical=FakePhysical("provisioning"),
        publisher=publisher,
    )

    await callbacks.fulfill(record, "worker-a")

    assert runtime.deferred == 1
    assert publisher.submissions == []
    assert runtime.completed == []


@pytest.mark.asyncio
async def test_submission_ambiguity_never_blindly_republishes() -> None:
    runtime = FakeRuntime()
    publisher = FakePublisher(submit_error=RuntimeError("ambiguous"))
    record = _record()
    db = FakeDb(record)
    _, callbacks = _callbacks(db=db, runtime=runtime, publisher=publisher)

    with pytest.raises(RuntimeError, match="ambiguous"):
        await callbacks.fulfill(record, "worker-a")
    assert db.binding["publication_state"] == "submission_unknown"
    with pytest.raises(BareMetalAlkahestLifecycleError, match="manual"):
        await callbacks.fulfill(record, "worker-a")

    assert len(publisher.submissions) == 1
    assert runtime.retried == 2


@pytest.mark.asyncio
async def test_cancellation_after_publication_fence_never_reaches_retry_handler() -> (
    None
):
    runtime = FakeRuntime()

    class CancelledPublisher(FakePublisher):
        async def submit_fulfillment(self, *, condition_anchor, evidence):
            assert runtime.fenced == 1
            return await super().submit_fulfillment(
                condition_anchor=condition_anchor,
                evidence=evidence,
            )

    publisher = CancelledPublisher(submit_error=asyncio.CancelledError())
    record = _record()
    db = FakeDb(record)
    _, callbacks = _callbacks(db=db, runtime=runtime, publisher=publisher)

    with pytest.raises(asyncio.CancelledError):
        await callbacks.fulfill(record, "worker-a")

    assert runtime.fenced == 1
    assert runtime.retried == 0
    assert db.binding["publication_state"] == "submitting"
    assert len(publisher.submissions) == 1


@pytest.mark.asyncio
async def test_rejected_publication_fence_prevents_claim_and_external_write() -> None:
    runtime = FakeRuntime()
    runtime.fence_error = RuntimeError("settlement operation lease was lost")
    publisher = FakePublisher()
    record = _record()
    db = FakeDb(record)
    _, callbacks = _callbacks(db=db, runtime=runtime, publisher=publisher)

    with pytest.raises(RuntimeError, match="lease was lost"):
        await callbacks.fulfill(record, "stale-seller")

    assert runtime.fenced == 1
    assert runtime.retried == 1
    assert db.submission_claims == 0
    assert db.binding["publication_state"] == "intent_recorded"
    assert publisher.submissions == []


@pytest.mark.asyncio
async def test_recorded_uid_retries_readback_without_republication() -> None:
    runtime = FakeRuntime()
    publisher = FakePublisher()
    record = _record()
    db = FakeDb(record)
    db.binding.update(
        publication_state="uid_recorded",
        fulfillment_uid=FULFILLMENT,
    )
    _, callbacks = _callbacks(db=db, runtime=runtime, publisher=publisher)

    await callbacks.fulfill(record, "worker-a")

    assert publisher.submissions == []
    assert publisher.confirmations == [FULFILLMENT]
    assert runtime.completed == [FULFILLMENT]


@pytest.mark.asyncio
async def test_readback_unknown_retries_same_uid_without_republication() -> None:
    runtime = FakeRuntime()
    publisher = FakePublisher(confirm_errors=[ConnectionError("read unavailable")])
    record = _record()
    db = FakeDb(record)
    _, callbacks = _callbacks(db=db, runtime=runtime, publisher=publisher)

    with pytest.raises(ConnectionError, match="read unavailable"):
        await callbacks.fulfill(record, "worker-a")
    assert db.binding["publication_state"] == "readback_unknown"
    assert db.binding["failure_reason"] == (
        "fulfillment attestation readback failed: ConnectionError"
    )
    await callbacks.fulfill(record, "worker-a")

    assert len(publisher.submissions) == 1
    assert publisher.confirmations == [FULFILLMENT, FULFILLMENT]
    assert runtime.completed == [FULFILLMENT]


@pytest.mark.asyncio
async def test_uid_persistence_failure_leaves_no_blind_retry_path() -> None:
    runtime = FakeRuntime()
    publisher = FakePublisher()
    record = _record()
    db = FakeDb(record)
    db.fail_uid_saves = 1
    _, callbacks = _callbacks(db=db, runtime=runtime, publisher=publisher)

    with pytest.raises(RuntimeError, match="receipt persistence failed"):
        await callbacks.fulfill(record, "worker-a")
    with pytest.raises(BareMetalAlkahestLifecycleError, match="manual"):
        await callbacks.fulfill(record, "worker-a")

    assert len(publisher.submissions) == 1
    assert runtime.completed == []


@pytest.mark.asyncio
async def test_stale_worker_loses_atomic_publication_claim() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingPublisher(FakePublisher):
        async def submit_fulfillment(self, *, condition_anchor, evidence):
            self.submissions.append((condition_anchor, evidence))
            entered.set()
            await release.wait()
            return FULFILLMENT

    runtime = FakeRuntime()
    publisher = BlockingPublisher()
    record = _record()
    db = FakeDb(record)
    _, callbacks = _callbacks(db=db, runtime=runtime, publisher=publisher)

    evidence = callbacks._evidence(
        record,
        db.binding,
        await FakePhysical().lease_ready_evidence_inputs(),
    )
    binding = await db.record_bare_metal_alkahest_evidence_intent(
        obligation_ref=record.obligation_ref,
        evidence=evidence,
    )
    winner = asyncio.create_task(
        callbacks._publish_or_recover(
            record=record,
            worker_id="worker-a",
            binding=binding,
            evidence=evidence.canonical_json(),
            publisher=publisher,
        )
    )
    await entered.wait()
    with pytest.raises(BareMetalAlkahestLifecycleError, match="already claimed"):
        await callbacks._publish_or_recover(
            record=record,
            worker_id="worker-b",
            binding=binding,
            evidence=evidence.canonical_json(),
            publisher=publisher,
        )
    release.set()
    await winner

    assert len(publisher.submissions) == 1
    assert await winner == FULFILLMENT


@pytest.mark.asyncio
async def test_changed_plan_or_wrong_physical_result_fails_before_publication() -> None:
    publisher = FakePublisher()
    record = _record()
    db = FakeDb(record)
    db.thread["settlement_plan"] = {"obligations": []}
    _, callbacks = _callbacks(db=db, publisher=publisher)
    with pytest.raises(BareMetalAlkahestLifecycleError, match="accepted plan"):
        await callbacks.fulfill(record, "worker-a")
    assert publisher.submissions == []

    db = FakeDb(record)
    _, callbacks = _callbacks(
        db=db,
        physical=FakePhysical(machine_id="machine-b"),
        publisher=publisher,
    )
    with pytest.raises(BareMetalAlkahestLifecycleError, match="physical result"):
        await callbacks.fulfill(record, "worker-a")
    assert publisher.submissions == []


@pytest.mark.asyncio
async def test_wrong_seller_binding_fails_before_physical_or_chain_io() -> None:
    publisher = FakePublisher()
    physical = FakePhysical()
    record = _record()
    db = FakeDb(record)
    db.binding["seller_recipient"] = "0x" + "99" * 20
    _, callbacks = _callbacks(
        db=db,
        physical=physical,
        publisher=publisher,
    )

    with pytest.raises(BareMetalAlkahestLifecycleError, match="identity"):
        await callbacks.fulfill(record, "worker-a")

    assert physical.begin_calls == 0
    assert publisher.submissions == []


@pytest.mark.asyncio
async def test_terminal_collection_is_persisted_without_new_chain_effect() -> None:
    record = _record().model_copy(
        update={
            "fulfillment_ref": FULFILLMENT,
            "condition_state": "ready",
            "collection_state": "succeeded",
            "collection_receipt": {"receipt": "0xcollection"},
        }
    )
    db = FakeDb(record)
    _, callbacks = _callbacks(db=db)

    await callbacks.reconcile_terminal(record, "collected", None)

    assert db.binding["terminal_state"] == "collected"


@pytest.mark.asyncio
async def test_uncertain_collection_receipt_is_persisted_as_unknown() -> None:
    record = _record().model_copy(
        update={
            "fulfillment_ref": FULFILLMENT,
            "condition_state": "ready",
            "collection_state": "pending",
            "mechanism_status": "manual_required",
        }
    )
    db = FakeDb(record)
    repository = FakeSettlementRepository(
        {
            "state": "pending",
            "uncertain_acknowledgement": True,
        }
    )
    _, callbacks = _callbacks(db=db, repository=repository)

    await callbacks.reconcile_terminal(record, "manual_required", "chain revoked")

    assert db.binding["terminal_state"] == "collection_unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("persisted_terminal", [None, "manual_required"])
async def test_invalid_collection_projects_manual_required_without_ready_fallback(
    persisted_terminal,
) -> None:
    record = _record().model_copy(
        update={
            "fulfillment_ref": FULFILLMENT,
            "condition_state": "ready",
            "collection_state": "manual_required",
            "mechanism_status": "ready",
        }
    )
    db = FakeDb(record)
    db.binding["terminal_state"] = persisted_terminal or "pending"
    _, callbacks = _callbacks(db=db)

    await callbacks.reconcile_terminal(record, "ready", "invalid receipt")

    assert db.binding["terminal_state"] == "manual_required"
