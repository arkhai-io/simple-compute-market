"""Durable acceptance tests for the fulfillment service boundary."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from market_fulfillment import (
    FulfillmentBase,
    FulfillmentConflictError,
    FulfillmentProvider,
    FulfillmentResult,
    LiveCredential,
    LiveCredentialResult,
    ProviderOperationState,
    ProviderRegistry,
    ProviderStatus,
    SettlementEntityNotFoundError,
    SettlementRecord,
    SettlementRecordState,
    SettlementRepository,
    VersionedEnvelope,
)
from compute_provisioning_service.services.fulfillment_service import FulfillmentService


class _FakeProvider(FulfillmentProvider):
    def __init__(self) -> None:
        self.prepare_calls = 0
        self.dispatch_calls = 0
        self.fail_dispatch = False
        self.on_dispatch: Callable[[], None] | None = None
        self.credential_reads = 0
        self.fail_credentials = False

    def prepare_create(self, capacity_reservation_id, fulfillment_request, resource):
        self.prepare_calls += 1
        return VersionedEnvelope(
            kind="fake.create",
            schema_version=1,
            payload={
                "resource_id": resource.settlement_resource_id,
                "resource_kind": resource.resource_kind,
                "requirements": fulfillment_request.payload,
            },
        )

    async def dispatch_create(self, prepared):
        self.dispatch_calls += 1
        if self.on_dispatch is not None:
            self.on_dispatch()
        if self.fail_dispatch:
            raise RuntimeError("provider unavailable")
        return FulfillmentResult(provider_metadata={"job_id": "job-1"})

    def prepare_teardown(self, capacity_reservation_id, resource, provider_metadata):
        return VersionedEnvelope(kind="fake.teardown", schema_version=1, payload={})

    async def dispatch_teardown(self, prepared):
        return FulfillmentResult(provider_metadata={})

    async def get_status(self, capacity_reservation_id, resource, provider_metadata):
        return ProviderStatus(state=ProviderOperationState.succeeded)

    async def get_live_credentials(
        self,
        capacity_reservation_id,
        resource,
        provider_metadata,
        *,
        credential_generation,
    ):
        self.credential_reads += 1
        if self.fail_credentials:
            raise RuntimeError("rotation failed")
        return LiveCredentialResult(
            credentials=(
                LiveCredential(
                    kind="vm.password.v1",
                    schema_version=1,
                    payload={"password": f"password-{credential_generation}"},
                ),
            ),
            rotated=True,
        )


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
def provider() -> _FakeProvider:
    return _FakeProvider()


@pytest.fixture
def service(session_factory, provider) -> FulfillmentService:
    with session_factory() as db:
        db.add(
            SettlementRecord(
                capacity_reservation_id="reservation-1",
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
                state=SettlementRecordState.assigned.value,
            )
        )
        db.commit()
    return FulfillmentService(
        provider_registry=ProviderRegistry({("ansible", "vm"): provider}),
        session_factory=session_factory,
        repository=SettlementRepository(),
    )


def _request(payload: dict | None = None) -> VersionedEnvelope:
    return VersionedEnvelope(
        kind="vms.fulfillment",
        schema_version=1,
        payload=payload or {"units": 1},
    )


@pytest.mark.asyncio
async def test_acceptance_commits_prepared_input_before_dispatch(
    service, provider, session_factory
):
    def assert_pending_is_visible() -> None:
        with session_factory() as db:
            record = db.get(SettlementRecord, "reservation-1")
            assert record is not None
            assert record.fulfillment_id is not None
            assert record.state == SettlementRecordState.dispatch_pending.value
            assert record.prepared_create_operation["kind"] == "fake.create"

    provider.on_dispatch = assert_pending_is_visible
    accepted = await service.begin_fulfillment(
        capacity_reservation_id="reservation-1",
        market="vms",
        fulfillment_request=_request(),
        owner_principal="seller-a",
    )

    assert accepted.state == SettlementRecordState.dispatching.value
    assert provider.prepare_calls == 1
    assert provider.dispatch_calls == 1
    with session_factory() as db:
        record = db.get(SettlementRecord, "reservation-1")
        assert record.provider_metadata == {"job_id": "job-1"}


@pytest.mark.asyncio
async def test_equivalent_retry_reuses_identity_without_repreparing_or_redispatching(
    service, provider
):
    first = await service.begin_fulfillment(
        capacity_reservation_id="reservation-1",
        market="vms",
        fulfillment_request=_request(),
        owner_principal="seller-a",
    )
    second = await service.begin_fulfillment(
        capacity_reservation_id="reservation-1",
        market="vms",
        fulfillment_request=_request(),
        owner_principal="seller-a",
    )

    assert second.fulfillment_id == first.fulfillment_id
    assert provider.prepare_calls == 1
    assert provider.dispatch_calls == 1


@pytest.mark.asyncio
async def test_conflicting_retry_is_rejected_before_provider_dispatch(service, provider):
    await service.begin_fulfillment(
        capacity_reservation_id="reservation-1",
        market="vms",
        fulfillment_request=_request(),
        owner_principal="seller-a",
    )

    with pytest.raises(FulfillmentConflictError):
        await service.begin_fulfillment(
            capacity_reservation_id="reservation-1",
            market="vms",
            fulfillment_request=_request({"units": 2}),
            owner_principal="seller-a",
        )
    assert provider.prepare_calls == 1
    assert provider.dispatch_calls == 1


@pytest.mark.asyncio
async def test_dispatch_failure_leaves_durable_pending_command(
    service, provider, session_factory
):
    provider.fail_dispatch = True
    accepted = await service.begin_fulfillment(
        capacity_reservation_id="reservation-1",
        market="vms",
        fulfillment_request=_request(),
        owner_principal="seller-a",
    )

    assert accepted.state == SettlementRecordState.dispatch_pending.value
    with session_factory() as db:
        record = db.get(SettlementRecord, "reservation-1")
        assert record.state == SettlementRecordState.dispatch_pending.value
        assert record.prepared_create_operation is not None


@pytest.mark.asyncio
async def test_owner_isolation_hides_assignment_before_preparation(service, provider):
    with pytest.raises(SettlementEntityNotFoundError):
        await service.begin_fulfillment(
            capacity_reservation_id="reservation-1",
            market="vms",
            fulfillment_request=_request(),
            owner_principal="seller-b",
        )
    assert provider.prepare_calls == 0
    assert provider.dispatch_calls == 0


@pytest.mark.asyncio
async def test_equivalent_retry_survives_service_reconstruction(
    service, provider, session_factory
):
    first = await service.begin_fulfillment(
        capacity_reservation_id="reservation-1",
        market="vms",
        fulfillment_request=_request(),
        owner_principal="seller-a",
    )
    reconstructed = FulfillmentService(
        provider_registry=ProviderRegistry({("ansible", "vm"): provider}),
        session_factory=session_factory,
        repository=SettlementRepository(),
    )
    second = await reconstructed.begin_fulfillment(
        capacity_reservation_id="reservation-1",
        market="vms",
        fulfillment_request=_request(),
        owner_principal="seller-a",
    )
    assert second.fulfillment_id == first.fulfillment_id
    assert provider.dispatch_calls == 1


@pytest.mark.asyncio
async def test_status_reads_durable_state_and_hides_other_owner(
    service, provider, session_factory
):
    accepted = await service.begin_fulfillment(
        capacity_reservation_id="reservation-1",
        market="vms",
        fulfillment_request=_request(),
        owner_principal="seller-a",
    )
    reconstructed = FulfillmentService(
        provider_registry=ProviderRegistry({("ansible", "vm"): provider}),
        session_factory=session_factory,
        repository=SettlementRepository(),
    )

    status = reconstructed.get_status(
        fulfillment_id=accepted.fulfillment_id,
        owner_principal="seller-a",
    )
    assert status.state == SettlementRecordState.dispatching.value
    with pytest.raises(SettlementEntityNotFoundError):
        reconstructed.get_status(
            fulfillment_id=accepted.fulfillment_id,
            owner_principal="seller-b",
        )


def test_dry_run_uses_preparation_without_persisting(service, provider, session_factory):
    validation = service.validate_create(
        capacity_reservation_id="reservation-1",
        market="vms",
        fulfillment_request=_request(),
        owner_principal="seller-a",
    )

    assert validation.valid
    assert provider.prepare_calls == 1
    assert provider.dispatch_calls == 0
    with session_factory() as db:
        record = db.get(SettlementRecord, "reservation-1")
        assert record.fulfillment_id is None
        assert record.prepared_create_operation is None


@pytest.mark.asyncio
async def test_result_rotates_live_credentials_and_persists_only_generation(
    service, provider, session_factory
):
    accepted = await service.begin_fulfillment(
        capacity_reservation_id="reservation-1",
        market="vms",
        fulfillment_request=_request(),
        owner_principal="seller-a",
    )
    with session_factory() as db:
        SettlementRepository().transition(
            db,
            "reservation-1",
            SettlementRecordState.active.value,
        )
        SettlementRepository().add_provisioned_resource(
            db,
            capacity_reservation_id="reservation-1",
            domain_resource_ref="vm-1",
        )
        db.commit()

    restarted = FulfillmentService(
        provider_registry=ProviderRegistry({("ansible", "vm"): provider}),
        session_factory=session_factory,
        repository=SettlementRepository(),
    )
    first = await restarted.get_result(
        fulfillment_id=accepted.fulfillment_id,
        owner_principal="seller-a",
    )
    second = await restarted.get_result(
        fulfillment_id=accepted.fulfillment_id,
        owner_principal="seller-a",
    )

    assert first.credential_generation == 1
    assert second.credential_generation == 2
    assert first.credentials[0].payload["password"] == "password-1"
    assert second.credentials[0].payload["password"] == "password-2"
    assert first.provisioned_resources[0].domain_resource_ref == "vm-1"
    with session_factory() as db:
        record = db.get(SettlementRecord, "reservation-1")
        assert record.credential_generation == 2
        assert "password" not in str(record.provider_metadata)
        assert record.claimed_by is None


@pytest.mark.asyncio
async def test_nonterminal_and_foreign_result_reads_do_not_fetch_credentials(
    service, provider
):
    accepted = await service.begin_fulfillment(
        capacity_reservation_id="reservation-1",
        market="vms",
        fulfillment_request=_request(),
        owner_principal="seller-a",
    )

    pending = await service.get_result(
        fulfillment_id=accepted.fulfillment_id,
        owner_principal="seller-a",
    )
    assert pending.credentials == ()
    assert pending.credential_generation == 0
    assert provider.credential_reads == 0

    with pytest.raises(SettlementEntityNotFoundError):
        await service.get_result(
            fulfillment_id=accepted.fulfillment_id,
            owner_principal="seller-b",
        )
    assert provider.credential_reads == 0

@pytest.mark.asyncio
async def test_failed_credential_rotation_does_not_advance_generation(
    service, provider, session_factory
):
    accepted = await service.begin_fulfillment(
        capacity_reservation_id="reservation-1",
        market="vms",
        fulfillment_request=_request(),
        owner_principal="seller-a",
    )
    with session_factory() as db:
        SettlementRepository().transition(
            db, "reservation-1", SettlementRecordState.active.value
        )
        db.commit()
    provider.fail_credentials = True

    with pytest.raises(RuntimeError, match="rotation failed"):
        await service.get_result(
            fulfillment_id=accepted.fulfillment_id,
            owner_principal="seller-a",
        )

    with session_factory() as db:
        record = db.get(SettlementRecord, "reservation-1")
        assert record.credential_generation == 0
        assert record.claimed_by is None
