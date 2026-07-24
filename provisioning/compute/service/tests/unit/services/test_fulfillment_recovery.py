from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from market_fulfillment import (
    FulfillmentBase,
    FulfillmentProvider,
    FulfillmentResult,
    ProviderOperationState,
    ProviderRegistry,
    ProviderStatus,
    SettlementRecord,
    SettlementRecordState,
    SettlementRepository,
    VersionedEnvelope,
)
from compute_provisioning_service.services.fulfillment_recovery import (
    FulfillmentRecoveryService,
)


class _Provider(FulfillmentProvider):
    def __init__(self) -> None:
        self.dispatches = 0
        self.status = ProviderStatus(state=ProviderOperationState.pending)
        self.fail_dispatch = False

    def prepare_create(self, capacity_reservation_id, fulfillment_request, resource):
        raise NotImplementedError

    async def dispatch_create(self, prepared):
        self.dispatches += 1
        if self.fail_dispatch:
            raise RuntimeError("offline")
        return FulfillmentResult(
            provider_metadata={"job_id": "job-1"},
            provisioned_resource_refs=("resource-output-1",),
        )

    def prepare_teardown(self, capacity_reservation_id, resource, provider_metadata):
        raise NotImplementedError

    async def dispatch_teardown(self, prepared):
        self.dispatches += 1
        return FulfillmentResult(provider_metadata={"job_id": "teardown-job"})

    async def get_status(self, capacity_reservation_id, resource, provider_metadata):
        return self.status


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    FulfillmentBase.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def provider() -> _Provider:
    return _Provider()


@pytest.fixture
def recovery(session_factory, provider) -> FulfillmentRecoveryService:
    with session_factory() as db:
        db.add(
            SettlementRecord(
                capacity_reservation_id="reservation-1",
                fulfillment_id="fulfillment-1",
                owner_principal="seller-a",
                market="vms",
                scheduling_requirements={
                    "resource_kind": "vm",
                    "dimensions": {"units": 1},
                    "attributes": {},
                },
                settlement_resource_id="resource-1",
                pool_id="pool-1",
                provider="ansible",
                resource_attributes={"vm_host": "host-1"},
                fulfillment_request={
                    "kind": "vms.fulfillment",
                    "schema_version": 1,
                    "payload": {},
                },
                prepared_create_operation={
                    "kind": "fake.create",
                    "schema_version": 1,
                    "payload": {},
                },
                state=SettlementRecordState.dispatch_pending.value,
            )
        )
        db.commit()
    return FulfillmentRecoveryService(
        session_factory=session_factory,
        repository=SettlementRepository(),
        provider_registry=ProviderRegistry({("ansible", "vm"): provider}),
        worker_id="worker-a",
        jitter=lambda low, high: low,
    )


@pytest.mark.asyncio
async def test_recovery_dispatches_then_converges_success(
    recovery, provider, session_factory
):
    assert await recovery.run_once() == 1
    with session_factory() as db:
        record = db.get(SettlementRecord, "reservation-1")
        assert record.state == SettlementRecordState.dispatching.value
        assert record.provider_metadata["job_id"] == "job-1"
        assert record.claimed_by is None

    provider.status = ProviderStatus(state=ProviderOperationState.succeeded)
    restarted = FulfillmentRecoveryService(
        session_factory=session_factory,
        repository=SettlementRepository(),
        provider_registry=ProviderRegistry({("ansible", "vm"): provider}),
        worker_id="worker-after-restart",
        jitter=lambda low, high: low,
    )
    assert await restarted.run_once() == 1
    with session_factory() as db:
        record = db.get(SettlementRecord, "reservation-1")
        assert record.state == SettlementRecordState.active.value
        outputs = SettlementRepository().list_provisioned_resources(
            db,
            "reservation-1",
        )
        assert [item.domain_resource_ref for item in outputs] == [
            "resource-output-1"
        ]


@pytest.mark.asyncio
async def test_dispatch_failure_releases_claim_with_backoff(
    recovery, provider, session_factory
):
    provider.fail_dispatch = True
    assert await recovery.run_once() == 1

    with session_factory() as db:
        record = db.get(SettlementRecord, "reservation-1")
        assert record.state == SettlementRecordState.dispatch_pending.value
        assert record.claimed_by is None
        assert record.claim_expires_at is not None
        assert record.attempt_count == 1

    assert await recovery.run_once() == 0


class _Ledger:
    def __init__(self) -> None:
        self.releases = []

    def release(self, **kwargs):
        self.releases.append(kwargs)
        return {"state": "released"}


@pytest.mark.asyncio
async def test_teardown_recovery_releases_capacity_only_after_provider_success(
    recovery, provider, session_factory
):
    await recovery.run_once()
    provider.status = ProviderStatus(state=ProviderOperationState.succeeded)
    await recovery.run_once()
    with session_factory() as db:
        SettlementRepository().transition(
            db,
            "reservation-1",
            SettlementRecordState.teardown_dispatch_pending.value,
            prepared_teardown_operation={
                "kind": "fake.teardown",
                "schema_version": 1,
                "payload": {},
            },
        )
        db.commit()

    ledger = _Ledger()
    teardown_recovery = FulfillmentRecoveryService(
        session_factory=session_factory,
        repository=SettlementRepository(),
        provider_registry=ProviderRegistry({("ansible", "vm"): provider}),
        capacity_ledger_service=ledger,
        worker_id="teardown-worker",
        jitter=lambda low, high: low,
    )
    provider.status = ProviderStatus(state=ProviderOperationState.pending)
    assert await teardown_recovery.run_once() == 1
    assert ledger.releases == []

    provider.status = ProviderStatus(state=ProviderOperationState.succeeded)
    assert await teardown_recovery.run_once() == 1
    assert ledger.releases == [
        {
            "capacity_reservation_id": "reservation-1",
            "owner_principal": "seller-a",
        }
    ]
    with session_factory() as db:
        record = db.get(SettlementRecord, "reservation-1")
        assert record.state == SettlementRecordState.torn_down.value
        resources = SettlementRepository().list_provisioned_resources(
            db, "reservation-1"
        )
        assert {item.status for item in resources} == {"torn_down"}


def test_recovery_diagnostics_report_safe_claim_and_lifecycle_metrics(
    recovery, session_factory
):
    with session_factory() as db:
        record = db.get(SettlementRecord, "reservation-1")
        record.claimed_by = "dead-worker"
        record.claim_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        record.attempt_count = 3
        db.commit()

    diagnostics = recovery.diagnostics()

    assert diagnostics["stuck_claims"] == 1
    assert diagnostics["live_claims"] == 0
    assert diagnostics["nonterminal"] == 1
    assert diagnostics["oldest_nonterminal_seconds"] >= 0
    assert "owner_principal" not in diagnostics
    assert "provider_metadata" not in diagnostics


@pytest.mark.asyncio
async def test_failed_teardown_restarts_retries_and_releases_capacity_once(
    recovery, provider, session_factory
):
    await recovery.run_once()
    provider.status = ProviderStatus(state=ProviderOperationState.succeeded)
    await recovery.run_once()
    with session_factory() as db:
        SettlementRepository().transition(
            db,
            "reservation-1",
            SettlementRecordState.teardown_dispatch_pending.value,
            prepared_teardown_operation={
                "kind": "fake.teardown",
                "schema_version": 1,
                "payload": {},
            },
        )
        db.commit()

    ledger = _Ledger()
    first_worker = FulfillmentRecoveryService(
        session_factory=session_factory,
        repository=SettlementRepository(),
        provider_registry=ProviderRegistry({("ansible", "vm"): provider}),
        capacity_ledger_service=ledger,
        worker_id="first-teardown-worker",
        jitter=lambda low, high: low,
    )
    await first_worker.run_once()
    provider.status = ProviderStatus(
        state=ProviderOperationState.failed, detail="temporary teardown failure"
    )
    await first_worker.run_once()
    with session_factory() as db:
        assert db.get(SettlementRecord, "reservation-1").state == (
            SettlementRecordState.teardown_failed.value
        )
    assert ledger.releases == []

    restarted = FulfillmentRecoveryService(
        session_factory=session_factory,
        repository=SettlementRepository(),
        provider_registry=ProviderRegistry({("ansible", "vm"): provider}),
        capacity_ledger_service=ledger,
        worker_id="restarted-teardown-worker",
        jitter=lambda low, high: low,
    )
    await restarted.run_once()
    provider.status = ProviderStatus(state=ProviderOperationState.succeeded)
    await restarted.run_once()

    assert len(ledger.releases) == 1
    with session_factory() as db:
        assert db.get(SettlementRecord, "reservation-1").state == (
            SettlementRecordState.torn_down.value
        )
