"""Watchdog over ledger reservations: local release + deal event, no PATCH.

These cover the CapacityReservation-backed lease lifecycle: release happens in
the ledger's local transaction, the owning storefront gets a
point-to-point capacity-released event, and the resource PATCH callback
never fires. There is no separate `vm_leases` table or model in this
codebase; a lease is a state on the reservation row itself.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from market_identity import Ed25519Signer, TrustedIdentitySet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.models import Base
from compute_provisioning_service.identity import ProvisioningIdentityContext
from compute_provisioning.release import ExecutorReleaseDispatcher, ReleaseJobDispatcher
from market_site.authority import LedgerSiteAuthority
from market_site.ledger import CapacityLedgerService
from compute_provisioning.lease_lifecycle import LeaseLifecycleService
from compute_provisioning_service.services.deal_event_sink import (
    StorefrontLifecycleEventSink,
    notify_storefront_capacity_released,
)
from market_fulfillment import (
    FulfillmentBase,
    FulfillmentOrchestrator,
    ProviderRegistry,
    SettlementRecord,
    SettlementRecordState,
    SettlementRepository,
    SqlAlchemyFulfillmentUnitOfWork,
)
from market_resource_pools import DEFAULT_POOL_ID, ResourcePool, ResourcePoolService
from market_resource_pools.db import Base as PoolsBase
from vm_provisioning_adapter.release import (
    FulfillmentServiceTeardownPort,
    VM_EXECUTOR_KIND,
    VmFulfillmentReleaseJobPort,
    VmReleaseExecutor,
)
from bare_metal_provisioning_adapter.release import (
    BARE_METAL_EXECUTOR_KIND,
    BareMetalReleaseExecutor,
    bare_metal_executor_ref,
)

_SERVICE_SIGNER = Ed25519Signer(b"\x11" * 32)
_STOREFRONT_SIGNER = Ed25519Signer(b"\x12" * 32)
_IDENTITY = ProvisioningIdentityContext(
    signer=_SERVICE_SIGNER,
    storefront_principal=_STOREFRONT_SIGNER.identity,
    admin_principal=Ed25519Signer(b"\x13" * 32).identity,
    storefront_site_id="default",
)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # resource_pools must exist before Base's ansible_pool_configs FK resolves.
    PoolsBase.metadata.create_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # Site-ledger tables ride market_site's own metadata.
    from market_site.db import Base as SiteBase
    SiteBase.metadata.create_all(bind=engine)
    # Fulfillment aggregate tables — needed by tests exercising VM release,
    # which now begins durable fulfillment teardown rather than submitting
    # an Ansible job directly.
    FulfillmentBase.metadata.create_all(bind=engine)
    with sessionmaker(bind=engine)() as db, db.begin():
        db.add(
            ResourcePool(
                id=DEFAULT_POOL_ID,
                label="Default Pool",
                provider="ansible",
                enabled=True,
                policy_tags={
                    "deliverable_modes": [
                        BARE_METAL_EXECUTOR_KIND,
                        "custom_executor",
                        VM_EXECUTOR_KIND,
                    ]
                },
            )
        )
    return sessionmaker(bind=engine)


@pytest.fixture
def ledger(session_factory) -> CapacityLedgerService:
    svc = CapacityLedgerService(
        session_factory, unit_claim_keys=("units", "gpu_count")
    )
    svc.register_resource(
        resource_id="compute-kvm1-001",
        total_units=8,
        attributes={"vm_host": "kvm1"},
    )
    return svc


def _fulfillment_service(session_factory, *, provider=None) -> FulfillmentOrchestrator:
    resource_pool_service = ResourcePoolService(session_factory=session_factory, handlers={})
    return FulfillmentOrchestrator(
        provider_registry=ProviderRegistry({"ansible": provider or MagicMock()}),
        unit_of_work=SqlAlchemyFulfillmentUnitOfWork(
            session_factory=session_factory,
            pool_service=resource_pool_service,
            repository=SettlementRepository(),
        ),
    )


def _create_active_fulfillment(
    session_factory,
    *,
    capacity_reservation_id: str,
    executor_kind: str,
    fulfillment_id: str = "fulfillment-1",
) -> None:
    """Persist a `SettlementRecord` in `active` state, already carrying a
    prepared teardown envelope so `begin_fulfillment_teardown` needs no
    real pool configuration or provider call to queue teardown -- these
    tests exercise `LeaseLifecycleService`'s submission/polling behavior,
    not `FulfillmentOrchestrator`'s own preparation logic (covered in
    `kit/fulfillment`'s own test suite).
    """

    with session_factory() as db:
        db.add(
            SettlementRecord(
                capacity_reservation_id=capacity_reservation_id,
                fulfillment_id=fulfillment_id,
                market="vms",
                scheduling_requirements={
                    "executor_kind": executor_kind,
                    "resource_kind": "vm",
                },
                settlement_resource_id="kvm1",
                pool_id="pool-1",
                provider="ansible",
                resource_attributes={"vm_host": "kvm1"},
                fulfillment_request={
                    "kind": "vm.fulfillment.request",
                    "schema_version": 1,
                    "payload": {},
                },
                prepared_teardown_operation={
                    "kind": "vm.ansible.teardown.v1",
                    "schema_version": 1,
                    "payload": {},
                },
                provider_metadata={"current_job_id": "job-1"},
                state=SettlementRecordState.active.value,
            )
        )
        db.commit()


def _set_fulfillment_state(
    session_factory, capacity_reservation_id: str, state: str, **fields,
) -> None:
    """Simulate `FulfillmentConvergenceWatchdog` having already converged
    a teardown to a terminal (or in-flight) state, without running the
    watchdog itself -- that worker has its own test suite."""

    with session_factory() as db:
        record = db.get(SettlementRecord, capacity_reservation_id)
        record.state = state
        for key, value in fields.items():
            setattr(record, key, value)
        db.commit()


def _settings(**overrides):
    s = MagicMock()
    s.lease_watchdog_grace_period_seconds = 300
    s.storefront_url = "http://storefront:8001"
    s.storefront_site_id = "default"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


class DelegateReleaseExecutor:
    def __init__(self, delegate):
        self._delegate = delegate

    async def submit_release(self, reservation):
        result = self._delegate(reservation)
        if inspect.isawaitable(result):
            return await result
        return result


def _lifecycle(
    session_factory,
    ledger,
    *,
    executor_release=None,
    release_delegate=None,
    fulfillment_service=None,
    **settings_overrides,
):
    fulfillment_service = fulfillment_service or _fulfillment_service(session_factory)
    if executor_release is None:
        executors = {
            BARE_METAL_EXECUTOR_KIND: BareMetalReleaseExecutor(),
            VM_EXECUTOR_KIND: VmReleaseExecutor(
                settlement_repository=SettlementRepository(),
                session_factory=session_factory,
                teardown_port=FulfillmentServiceTeardownPort(lambda: fulfillment_service),
            ),
        }
        if release_delegate is not None:
            executors[VM_EXECUTOR_KIND] = DelegateReleaseExecutor(release_delegate)
        executor_release = ExecutorReleaseDispatcher(executors)
    release_jobs = ReleaseJobDispatcher({
        VM_EXECUTOR_KIND: VmFulfillmentReleaseJobPort(
            teardown_port=FulfillmentServiceTeardownPort(lambda: fulfillment_service),
        ),
    })
    settings = _settings(**settings_overrides)
    principal_authority = MagicMock()
    principal_authority.active_principals.return_value = TrustedIdentitySet(
        identities=(_STOREFRONT_SIGNER.identity,)
    )
    event_sink = StorefrontLifecycleEventSink(
        settings,
        _IDENTITY,
        principal_authority,
    )
    return LeaseLifecycleService(
        settings=settings,
        site_authority=LedgerSiteAuthority(ledger),
        executor_release=executor_release,
        release_jobs=release_jobs,
        capacity_released_notifier=(
            lambda reservation: notify_storefront_capacity_released(
                settings,
                reservation,
                sink=event_sink,
            )
        ),
    )


def _expired_reservation(ledger: CapacityLedgerService, escrow: str = "0xe") -> dict:
    reserved = ledger.reserve(
        claim={
            "executor_kind": VM_EXECUTOR_KIND,
            "gpu_count": 2,
            "vm_host": "kvm1",
        },
        deal_ref={"escrow_uid": escrow},
    )
    ledger.commit(
        resource_id="compute-kvm1-001",
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_start_utc="2020-01-01T00:00:00Z",
        lease_end_utc="2020-01-01 00:00",
    )
    ledger.attach_lease(
        capacity_reservation_id=reserved["capacity_reservation_id"],
        executor_target="tenant-x",
        lease_end_utc="2020-01-01 00:00",
    )
    return reserved


def _just_expired_reservation(
    ledger: CapacityLedgerService,
    escrow: str = "0xe",
    *,
    executor_kind: str,
) -> dict:
    reserved = ledger.reserve(
        claim={
            "executor_kind": executor_kind,
            "gpu_count": 2,
            "vm_host": "kvm1",
        },
        deal_ref={"escrow_uid": escrow},
    )
    just_expired_dt = datetime.now(timezone.utc) - timedelta(seconds=1)
    just_expired = just_expired_dt.isoformat()
    ledger.commit(
        resource_id="compute-kvm1-001",
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_start_utc=(just_expired_dt - timedelta(seconds=3600)).isoformat(),
        lease_end_utc=just_expired,
    )
    ledger.attach_lease(
        capacity_reservation_id=reserved["capacity_reservation_id"],
        executor_target="tenant-x",
        lease_end_utc=just_expired,
    )
    return reserved


@pytest.mark.asyncio
async def test_expired_ledger_lease_releases_locally_and_notifies(
    session_factory, ledger,
):
    """Full lifecycle: submission (this cycle) through confirmed teardown
    (simulated, since FulfillmentConvergenceWatchdog is tested separately)
    to local release + notification (next cycle)."""

    reservation = _just_expired_reservation(
        ledger,
        executor_kind=VM_EXECUTOR_KIND,
    )
    capacity_reservation_id = reservation["capacity_reservation_id"]
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        executor_kind=VM_EXECUTOR_KIND,
    )
    svc = _lifecycle(session_factory, ledger)

    first = await svc.force_check_leases()
    assert first["checked"] == 1
    releasing = ledger.get_reservation(capacity_reservation_id)
    assert releasing["state"] == "releasing"
    assert releasing["release_job_id"] == "fulfillment-1"

    # Convergence (FulfillmentConvergenceWatchdog, tested separately) has
    # confirmed the VM torn down.
    _set_fulfillment_state(
        session_factory, capacity_reservation_id, SettlementRecordState.torn_down.value,
    )

    sf = MagicMock()
    sf.__aenter__ = AsyncMock(return_value=sf)
    sf.__aexit__ = AsyncMock(return_value=False)
    sf.notify_capacity_released = AsyncMock(return_value={})
    sf.patch_resource = AsyncMock()

    with patch(
        "storefront_client.StorefrontClient", return_value=sf,
    ) as client_cls:
        summary = await svc.force_check_leases()

    assert summary["released"] == 1
    released = ledger.get_reservation(capacity_reservation_id)
    assert released["state"] == "released"
    assert ledger.snapshot()[0]["available_units"] == 8

    client_cls.assert_called_once_with(
        base_url="http://storefront:8001",
        signer=_SERVICE_SIGNER,
        caller_role="service",
        expected_publishers=TrustedIdentitySet(
            identities=(_STOREFRONT_SIGNER.identity,)
        ),
    )
    sf.notify_capacity_released.assert_awaited_once()
    args, kwargs = sf.notify_capacity_released.await_args
    assert args == (capacity_reservation_id,)
    assert kwargs["site_id"] == "default"
    assert kwargs["request_id"].startswith("capacity-release-")
    assert "resource_id" not in kwargs
    sf.patch_resource.assert_not_awaited()

    # The anonymous capacity feed carries the release for subscribers.
    events, _ = ledger.events_after(0)
    assert events[-1]["kind"] == "released"


@pytest.mark.asyncio
async def test_release_survives_unreachable_storefront(session_factory, ledger):
    """The local transaction is authoritative; notification is best-effort
    (the storefront converges through the capacity-event feed)."""
    reservation = _just_expired_reservation(
        ledger,
        executor_kind=VM_EXECUTOR_KIND,
    )
    capacity_reservation_id = reservation["capacity_reservation_id"]
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        executor_kind=VM_EXECUTOR_KIND,
    )
    svc = _lifecycle(session_factory, ledger)

    await svc.force_check_leases()
    _set_fulfillment_state(
        session_factory, capacity_reservation_id, SettlementRecordState.torn_down.value,
    )

    with patch(
        "storefront_client.StorefrontClient",
        side_effect=ConnectionError("storefront down"),
    ):
        summary = await svc.force_check_leases()

    assert summary["released"] == 1
    assert ledger.get_reservation(capacity_reservation_id)["state"] == "released"


@pytest.mark.asyncio
async def test_releasing_reservation_past_grace_marks_release_failed(
    session_factory, ledger,
):
    reservation = _expired_reservation(ledger)
    capacity_reservation_id = reservation["capacity_reservation_id"]
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        executor_kind=VM_EXECUTOR_KIND,
    )
    ledger.begin_releasing(capacity_reservation_id, vm_remove_job_id="fulfillment-1")
    _set_fulfillment_state(
        session_factory,
        capacity_reservation_id,
        SettlementRecordState.tearing_down.value,
    )

    svc = _lifecycle(session_factory, ledger)

    sf = MagicMock()
    sf.__aenter__ = AsyncMock(return_value=sf)
    sf.__aexit__ = AsyncMock(return_value=False)
    sf.notify_capacity_released = AsyncMock(return_value={})

    with patch("storefront_client.StorefrontClient", return_value=sf):
        # lease ended 2020 + 300s grace — long past: still-in-progress
        # teardown is marked failed; capacity remains held.
        summary = await svc.force_check_leases()

    assert summary["release_failed"] == 1
    assert ledger.get_reservation(capacity_reservation_id)["state"] == "release_failed"
    assert ledger.snapshot()[0]["available_units"] < 8
    sf.notify_capacity_released.assert_not_awaited()


@pytest.mark.asyncio
async def test_releasing_reservation_within_grace_skips(session_factory, ledger):
    reserved = ledger.reserve(claim={"executor_kind": "vm"}, deal_ref={})
    capacity_reservation_id = reserved["capacity_reservation_id"]
    soon_dt = datetime.now(timezone.utc) - timedelta(seconds=1)
    soon = soon_dt.isoformat()
    ledger.commit(
        resource_id="compute-kvm1-001",
        capacity_reservation_id=capacity_reservation_id,
        lease_start_utc=(soon_dt - timedelta(seconds=3600)).isoformat(),
        lease_end_utc=soon,
    )
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        executor_kind=VM_EXECUTOR_KIND,
    )
    ledger.begin_releasing(capacity_reservation_id, vm_remove_job_id="fulfillment-1")
    _set_fulfillment_state(
        session_factory,
        capacity_reservation_id,
        SettlementRecordState.tearing_down.value,
    )

    svc = _lifecycle(session_factory, ledger)
    summary = await svc.force_check_leases()
    assert summary["skipped"] == 1
    assert ledger.get_reservation(capacity_reservation_id)["state"] == "releasing"


@pytest.mark.asyncio
async def test_succeeded_vm_remove_releases_normally(session_factory, ledger):
    reservation = _expired_reservation(ledger)
    capacity_reservation_id = reservation["capacity_reservation_id"]
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        executor_kind=VM_EXECUTOR_KIND,
    )
    ledger.begin_releasing(capacity_reservation_id, vm_remove_job_id="fulfillment-1")
    _set_fulfillment_state(
        session_factory, capacity_reservation_id, SettlementRecordState.torn_down.value,
    )

    svc = _lifecycle(session_factory, ledger)

    sf = MagicMock()
    sf.__aenter__ = AsyncMock(return_value=sf)
    sf.__aexit__ = AsyncMock(return_value=False)
    sf.notify_capacity_released = AsyncMock(return_value={})

    with patch("storefront_client.StorefrontClient", return_value=sf):
        summary = await svc.force_check_leases()

    assert summary["released"] == 1
    assert ledger.get_reservation(capacity_reservation_id)["state"] == "released"


@pytest.mark.asyncio
async def test_failed_vm_remove_marks_release_failed_without_notification(session_factory, ledger):
    reservation = _expired_reservation(ledger)
    capacity_reservation_id = reservation["capacity_reservation_id"]
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        executor_kind=VM_EXECUTOR_KIND,
    )
    ledger.begin_releasing(capacity_reservation_id, vm_remove_job_id="fulfillment-1")
    _set_fulfillment_state(
        session_factory,
        capacity_reservation_id,
        SettlementRecordState.teardown_failed.value,
        failure_reason="provider_reported_failure",
        failure_message="cleanup script missing",
    )

    svc = _lifecycle(session_factory, ledger)

    sf = MagicMock()
    sf.__aenter__ = AsyncMock(return_value=sf)
    sf.__aexit__ = AsyncMock(return_value=False)
    sf.notify_capacity_released = AsyncMock(return_value={})

    with patch("storefront_client.StorefrontClient", return_value=sf):
        summary = await svc.force_check_leases()

    assert summary["release_failed"] == 1
    assert ledger.get_reservation(capacity_reservation_id)["state"] == "release_failed"
    assert ledger.snapshot()[0]["available_units"] < 8
    sf.notify_capacity_released.assert_not_awaited()


@pytest.mark.asyncio
async def test_due_leased_reservation_begins_fulfillment_teardown(session_factory, ledger):
    # Lease ended seconds ago — within grace, so the same cycle that
    # begins teardown must NOT force-release it.
    reservation = _just_expired_reservation(
        ledger,
        executor_kind=VM_EXECUTOR_KIND,
    )
    capacity_reservation_id = reservation["capacity_reservation_id"]
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        executor_kind=VM_EXECUTOR_KIND,
    )

    svc = _lifecycle(session_factory, ledger)

    summary = await svc.force_check_leases()

    assert summary["checked"] == 1
    row = ledger.get_reservation(capacity_reservation_id)
    assert row["state"] == "releasing"
    assert row["vm_remove_job_id"] == "fulfillment-1"
    assert row["release_job_id"] == "fulfillment-1"
    assert row["executor_kind"] == "vm"

    with session_factory() as db:
        record = db.get(SettlementRecord, capacity_reservation_id)
        assert record.state == SettlementRecordState.teardown_dispatch_pending.value


@pytest.mark.asyncio
async def test_missing_executor_kind_stays_held_and_retryable(session_factory, ledger):
    reservation = _just_expired_reservation(
        ledger,
        executor_kind=VM_EXECUTOR_KIND,
    )
    capacity_reservation_id = reservation["capacity_reservation_id"]
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        executor_kind=VM_EXECUTOR_KIND,
    )

    from market_site.db import CapacityReservation

    with session_factory() as db:
        row = db.get(CapacityReservation, capacity_reservation_id)
        row.executor_kind = None
        row.executor_target = None
        db.commit()

    svc = _lifecycle(session_factory, ledger)

    summary = await svc.force_check_leases()

    assert summary["checked"] == 0
    assert summary["release_failed"] == 1
    row = ledger.get_reservation(capacity_reservation_id)
    assert row["state"] == "release_failed"
    assert row["executor_kind"] is None
    assert row["release_job_id"] is None
    assert row["failure_reason"] == "release_submit_failed"
    assert ledger.snapshot()[0]["available_units"] < 8

    with session_factory() as db:
        record = db.get(SettlementRecord, capacity_reservation_id)
        assert record.state == SettlementRecordState.active.value


@pytest.mark.asyncio
async def test_missing_fulfillment_aggregate_stays_held_and_retryable(session_factory, ledger):
    """No `SettlementRecord` was ever created for this reservation (e.g. a
    lease registered without ever going through `begin_fulfillment`).
    `VmReleaseExecutor._resolve_fulfillment_id` returns `None` for this --
    a known, expected outcome, not a raised exception -- so it surfaces as
    `release_submit_failed`, distinct from an unexpected failure."""

    reservation = _just_expired_reservation(
        ledger,
        executor_kind=VM_EXECUTOR_KIND,
    )
    capacity_reservation_id = reservation["capacity_reservation_id"]
    # Deliberately no _create_active_fulfillment call.

    svc = _lifecycle(session_factory, ledger)
    summary = await svc.force_check_leases()

    assert summary["release_failed"] == 1
    row = ledger.get_reservation(capacity_reservation_id)
    assert row["state"] == "release_failed"
    assert row["failure_reason"] == "release_submit_failed"


@pytest.mark.asyncio
async def test_invalid_aggregate_state_propagates_as_release_submit_error(
    session_factory, ledger,
):
    """The fulfillment aggregate exists but is not `active` (e.g. it never
    dispatched, or already failed create-side) -- `begin_fulfillment_teardown`
    raises `FulfillmentConflictError`. `VmReleaseExecutor.submit_release`
    must not swallow this into a generic `None`; it must propagate so
    `LeaseLifecycleService`'s existing `release_submit_error` handling
    records the real reason, distinguishable from the "no aggregate at
    all" case above by both `failure_reason` and message content."""

    reservation = _just_expired_reservation(
        ledger,
        executor_kind=VM_EXECUTOR_KIND,
    )
    capacity_reservation_id = reservation["capacity_reservation_id"]
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        executor_kind=VM_EXECUTOR_KIND,
    )
    _set_fulfillment_state(
        session_factory, capacity_reservation_id, SettlementRecordState.failed.value,
    )

    svc = _lifecycle(session_factory, ledger)
    summary = await svc.force_check_leases()

    assert summary["release_failed"] == 1
    row = ledger.get_reservation(capacity_reservation_id)
    assert row["state"] == "release_failed"
    assert row["failure_reason"] == "release_submit_error"

    from market_site.db import CapacityReservation

    with session_factory() as db:
        raw = db.get(CapacityReservation, capacity_reservation_id)
        assert "only an active fulfillment can begin teardown" in raw.failure_message


@pytest.mark.asyncio
async def test_unavailable_teardown_port_propagates_as_release_submit_error(
    session_factory, ledger,
):
    """The composition root never bound the teardown port (e.g. a startup
    ordering bug) -- `DeferredFulfillmentTeardownPort.begin_teardown` raises
    `RuntimeError`. This must reach the operator, not be swallowed."""

    reservation = _just_expired_reservation(
        ledger,
        executor_kind=VM_EXECUTOR_KIND,
    )
    capacity_reservation_id = reservation["capacity_reservation_id"]
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        executor_kind=VM_EXECUTOR_KIND,
    )

    class _UnboundTeardownPort:
        async def begin_teardown(self, fulfillment_id: str) -> str:
            raise RuntimeError("fulfillment teardown port is not bound")

        def get_status(self, fulfillment_id: str):
            raise RuntimeError("fulfillment teardown port is not bound")

    executor_release = ExecutorReleaseDispatcher({
        BARE_METAL_EXECUTOR_KIND: BareMetalReleaseExecutor(),
        VM_EXECUTOR_KIND: VmReleaseExecutor(
            settlement_repository=SettlementRepository(),
            session_factory=session_factory,
            teardown_port=_UnboundTeardownPort(),
        ),
    })
    svc = _lifecycle(session_factory, ledger, executor_release=executor_release)
    summary = await svc.force_check_leases()

    assert summary["release_failed"] == 1
    row = ledger.get_reservation(capacity_reservation_id)
    assert row["state"] == "release_failed"
    assert row["failure_reason"] == "release_submit_error"

    from market_site.db import CapacityReservation

    with session_factory() as db:
        raw = db.get(CapacityReservation, capacity_reservation_id)
        assert "not bound" in raw.failure_message


@pytest.mark.asyncio
async def test_unexpected_repository_failure_propagates_as_release_submit_error(
    session_factory, ledger,
):
    """A database-level failure resolving the fulfillment_id (not a domain
    outcome at all) must not be silently downgraded to "no aggregate
    found" -- the operator needs to know this is an infrastructure
    problem, not a registration gap."""

    reservation = _just_expired_reservation(
        ledger,
        executor_kind=VM_EXECUTOR_KIND,
    )
    capacity_reservation_id = reservation["capacity_reservation_id"]
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        executor_kind=VM_EXECUTOR_KIND,
    )

    class _BrokenSettlementRepository:
        def get(self, db, capacity_reservation_id):
            raise RuntimeError("settlement database unavailable")

    executor_release = ExecutorReleaseDispatcher({
        BARE_METAL_EXECUTOR_KIND: BareMetalReleaseExecutor(),
        VM_EXECUTOR_KIND: VmReleaseExecutor(
            settlement_repository=_BrokenSettlementRepository(),
            session_factory=session_factory,
            teardown_port=FulfillmentServiceTeardownPort(
                lambda: _fulfillment_service(session_factory)
            ),
        ),
    })
    svc = _lifecycle(session_factory, ledger, executor_release=executor_release)
    summary = await svc.force_check_leases()

    assert summary["release_failed"] == 1
    row = ledger.get_reservation(capacity_reservation_id)
    assert row["state"] == "release_failed"
    assert row["failure_reason"] == "release_submit_error"

    from market_site.db import CapacityReservation

    with session_factory() as db:
        raw = db.get(CapacityReservation, capacity_reservation_id)
        assert "settlement database unavailable" in raw.failure_message


@pytest.mark.asyncio
async def test_bare_metal_executor_releases_locally_and_notifies(session_factory, ledger):
    reservation = _just_expired_reservation(
        ledger,
        executor_kind=BARE_METAL_EXECUTOR_KIND,
    )
    ledger.update_lease_fields(
        reservation["capacity_reservation_id"],
        executor_target="node-1",
        executor_ref=bare_metal_executor_ref(
            "host-kvm1",
            access_ref={"ssh_user": "tenant-x"},
        ),
    )

    svc = _lifecycle(session_factory, ledger)

    sf = MagicMock()
    sf.__aenter__ = AsyncMock(return_value=sf)
    sf.__aexit__ = AsyncMock(return_value=False)
    sf.notify_capacity_released = AsyncMock(return_value={})

    with patch("storefront_client.StorefrontClient", return_value=sf):
        summary = await svc.force_check_leases()

    assert summary["checked"] == 1
    assert summary["released"] == 1
    row = ledger.get_reservation(reservation["capacity_reservation_id"])
    assert row["state"] == "released"
    assert row["release_job_id"] == "direct-release"
    assert row["vm_remove_job_id"] is None
    assert row["executor_target"] == "node-1"
    assert row["executor_ref"] == {
        "physical_host_id": "host-kvm1",
        "ssh_user": "tenant-x",
    }
    assert ledger.snapshot()[0]["available_units"] == 8
    sf.notify_capacity_released.assert_awaited_once()


@pytest.mark.asyncio
async def test_bare_metal_executor_submits_reclaim_job_when_delegate_configured(
    session_factory, ledger,
):
    reservation = _just_expired_reservation(
        ledger,
        executor_kind=BARE_METAL_EXECUTOR_KIND,
    )
    ledger.update_lease_fields(
        reservation["capacity_reservation_id"],
        executor_target="node-1",
        executor_ref=bare_metal_executor_ref(
            "host-kvm1",
            access_ref={"ssh_user": "tenant-x"},
        ),
    )
    release_delegate = AsyncMock(return_value="reclaim-42")
    dispatcher = ExecutorReleaseDispatcher({
        BARE_METAL_EXECUTOR_KIND: BareMetalReleaseExecutor(
            release_delegate=release_delegate,
        ),
    })
    svc = _lifecycle(session_factory, ledger, executor_release=dispatcher)

    summary = await svc.force_check_leases()

    assert summary["checked"] == 1
    row = ledger.get_reservation(reservation["capacity_reservation_id"])
    assert row["state"] == "releasing"
    assert row["release_job_id"] == "reclaim-42"
    release_delegate.assert_awaited_once()


@pytest.mark.asyncio
async def test_bare_metal_release_submission_failure_stays_held(session_factory, ledger):
    reservation = _just_expired_reservation(
        ledger,
        executor_kind=BARE_METAL_EXECUTOR_KIND,
    )
    ledger.update_lease_fields(
        reservation["capacity_reservation_id"],
        executor_target="node-1",
    )

    release_delegate = AsyncMock(return_value=None)
    dispatcher = ExecutorReleaseDispatcher({
        BARE_METAL_EXECUTOR_KIND: BareMetalReleaseExecutor(
            release_delegate=release_delegate,
        ),
    })
    svc = _lifecycle(session_factory, ledger, executor_release=dispatcher)

    summary = await svc.force_check_leases()

    assert summary["release_failed"] == 1
    row = ledger.get_reservation(reservation["capacity_reservation_id"])
    assert row["state"] == "release_failed"
    assert row["failure_reason"] == "release_submit_failed"
    assert ledger.snapshot()[0]["available_units"] < 8
    release_delegate.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_executor_kind_stays_held_and_retryable(session_factory, ledger):
    reservation = _just_expired_reservation(
        ledger,
        executor_kind="custom_executor",
    )
    ledger.update_lease_fields(
        reservation["capacity_reservation_id"],
        executor_target="target-1",
    )

    svc = _lifecycle(session_factory, ledger)

    summary = await svc.force_check_leases()

    assert summary["release_failed"] == 1
    row = ledger.get_reservation(reservation["capacity_reservation_id"])
    assert row["state"] == "release_failed"
    assert row["executor_kind"] == "custom_executor"
    assert row["failure_reason"] == "release_submit_failed"
    assert ledger.snapshot()[0]["available_units"] < 8


@pytest.mark.asyncio
async def test_admin_retry_release_resubmits_delegate(session_factory, ledger):
    reservation = _expired_reservation(ledger)
    ledger.update_reservation_state(
        reservation["capacity_reservation_id"],
        state="release_failed",
        failure_reason="vm_remove_failed",
        failure_message="cleanup script missing",
    )

    delegate = AsyncMock(return_value="remove-retry-1")
    svc = _lifecycle(session_factory, ledger, release_delegate=delegate)

    from vm_provisioning_operator.models import LeaseRetryReleaseRequest

    updated = await svc.retry_release(
        reservation["capacity_reservation_id"],
        LeaseRetryReleaseRequest(reason="operator retry"),
    )

    assert updated["state"] == "releasing"
    assert updated["vm_remove_job_id"] == "remove-retry-1"
    assert updated["release_job_id"] == "remove-retry-1"
    assert ledger.snapshot()[0]["available_units"] < 8
    delegate.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_force_release_unmanaged_releases_capacity_and_notifies(session_factory, ledger):
    reservation = _expired_reservation(ledger)
    ledger.update_reservation_state(
        reservation["capacity_reservation_id"],
        state="unmanaged",
        failure_reason="oversight_released",
        failure_message="manual ops",
    )

    svc = _lifecycle(session_factory, ledger)

    sf = MagicMock()
    sf.__aenter__ = AsyncMock(return_value=sf)
    sf.__aexit__ = AsyncMock(return_value=False)
    sf.notify_capacity_released = AsyncMock(return_value={})

    from vm_provisioning_operator.models import LeaseForceReleaseRequest

    with patch("storefront_client.StorefrontClient", return_value=sf):
        released = await svc.force_release(
            reservation["capacity_reservation_id"],
            LeaseForceReleaseRequest(reason="host inspected", evidence="VM absent"),
        )

    assert released["state"] == "force_released"
    assert released["failure_reason"] == "admin_force_release"
    assert ledger.snapshot()[0]["available_units"] == 8
    events, _ = ledger.events_after(0)
    assert events[-1]["kind"] == "released"
    sf.notify_capacity_released.assert_awaited_once()
