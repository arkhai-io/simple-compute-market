"""The lease lifecycle over the real site ledger, fulfillment aggregate, and sink.

Release follows the reservation's fulfillment aggregate for every offering
mode: teardown is begun or adopted, capacity is freed directly when the
fulfillment proves nothing was delivered, a create in flight is waited on, and
a failed create is left for an operator. The ledger carries the production
release guard, so every direct release here is held to the same proof the
service applies. Capacity returns in the ledger's local transaction and the
owning storefront gets a point-to-point capacity-released event.
Fulfillment convergence is not run: tests set the aggregate's state as
convergence would leave it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from compute_provisioning.jobs.db import Base as JobsBase
from compute_provisioning.lease_lifecycle import LeaseLifecycleService
from compute_provisioning.release import (
    FulfillmentReleaseExecutor,
    FulfillmentReleaseGuard,
    FulfillmentReleaseStatusPort,
    FulfillmentServiceTeardownPort,
)
from compute_provisioning_contracts import LeaseForceRelease
from market_fulfillment import (
    FulfillmentBase,
    FulfillmentOrchestrator,
    ProviderRegistry,
    SettlementRecord,
    SettlementRecordState,
    SettlementRepository,
    SqlAlchemyFulfillmentUnitOfWork,
)
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_resource_pools import DEFAULT_POOL_ID, ResourcePool, ResourcePoolService
from market_resource_pools.db import Base as PoolsBase
from market_site.authority import LedgerSiteAuthority
from market_site.db import Base as SiteBase
from market_site.ledger import CapacityLedgerService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.models import Base
from compute_provisioning_service.identity import ProvisioningIdentityContext
from compute_provisioning_service.services.deal_event_sink import (
    StorefrontLifecycleEventSink,
    notify_storefront_capacity_released,
)

VM_OFFERING_MODE = "vm"
BARE_METAL_OFFERING_MODE = "bare_metal"
_State = SettlementRecordState

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
    # Job rows ride the family kit's own metadata: the release guard reads
    # them for a reservation's dispatch provenance.
    JobsBase.metadata.create_all(bind=engine)
    # Site-ledger tables ride market_site's own metadata.
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
                    "deliverable_modes": [BARE_METAL_OFFERING_MODE, VM_OFFERING_MODE]
                },
            )
        )
    return sessionmaker(bind=engine)


@pytest.fixture
def ledger(session_factory) -> CapacityLedgerService:
    svc = CapacityLedgerService(
        session_factory,
        unit_claim_keys=("units", "gpu_count"),
        mirror_dimension="gpu_count",
        release_guard=FulfillmentReleaseGuard(SettlementRepository()),
    )
    svc.register_resource(
        resource_id="compute-kvm1-001",
        total_units=8,
        host_id="kvm1", attributes={},
        pool_id="default",
    )
    return svc


class _ProviderMock(MagicMock):
    """A mock provider that, like every real one, declares its host need."""

    needs_host = True


def _fulfillment_service(session_factory, *, provider=None) -> FulfillmentOrchestrator:
    resource_pool_service = ResourcePoolService(session_factory=session_factory, handlers={})
    return FulfillmentOrchestrator(
        provider_registry=ProviderRegistry({"ansible": provider or _ProviderMock()}),
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
    offering_mode: str,
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
                    "offering_mode": offering_mode,
                    "resource_kind": "vm",
                },
                settlement_resource_id="kvm1",
                pool_id="pool-1",
                provider="ansible",
                resource_host_id="kvm1", resource_attributes={},
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


def _lifecycle(session_factory, ledger, *, fulfillment_service=None, **settings_overrides):
    """The lifecycle as the service composes it, over these tables."""
    fulfillment_service = fulfillment_service or _fulfillment_service(session_factory)
    teardown_port = FulfillmentServiceTeardownPort(lambda: fulfillment_service)
    settings = _settings(**settings_overrides)
    principal_authority = MagicMock()
    principal_authority.active_principals.return_value = TrustedIdentitySet(
        identities=(_STOREFRONT_SIGNER.identity,)
    )
    event_sink = StorefrontLifecycleEventSink(settings, _IDENTITY, principal_authority)
    return LeaseLifecycleService(
        settings=settings,
        site_authority=LedgerSiteAuthority(ledger),
        release_executor=FulfillmentReleaseExecutor(
            settlement_repository=SettlementRepository(),
            session_factory=session_factory,
            teardown_port=teardown_port,
        ),
        release_status=FulfillmentReleaseStatusPort(teardown_port),
        capacity_released_notifier=(
            lambda reservation: notify_storefront_capacity_released(
                settings, reservation, sink=event_sink
            )
        ),
    )


def _leased(
    ledger: CapacityLedgerService,
    escrow: str = "0xe",
    *,
    offering_mode: str = VM_OFFERING_MODE,
    ended: timedelta = timedelta(seconds=1),
) -> str:
    """A registered lease whose end passed ``ended`` ago."""
    reserved = ledger.reserve(
        claim={"offering_mode": offering_mode, "gpu_count": 2, "host_id": "kvm1"},
        deal_ref={"escrow_uid": escrow},
    )
    end = datetime.now(timezone.utc) - ended
    ledger.commit(
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_start_utc=(end - timedelta(hours=1)).isoformat(),
        lease_end_utc=end.isoformat(),
    )
    with ledger._session_factory() as db:
        ledger.record_executor_target_in_session(
            db, reserved["capacity_reservation_id"], "tenant-x"
        )
        db.commit()
    return reserved["capacity_reservation_id"]


def _storefront():
    sf = MagicMock()
    sf.__aenter__ = AsyncMock(return_value=sf)
    sf.__aexit__ = AsyncMock(return_value=False)
    sf.notify_capacity_released = AsyncMock(return_value={})
    sf.patch_resource = AsyncMock()
    return sf


def _aggregate_state(session_factory, capacity_reservation_id: str) -> str:
    with session_factory() as db:
        return db.get(SettlementRecord, capacity_reservation_id).state


@pytest.mark.asyncio
async def test_an_expired_lease_is_torn_down_then_released_and_notified(session_factory, ledger):
    """Submission begins teardown this cycle; once convergence reports the
    aggregate torn down, the next cycle releases and notifies the storefront."""
    capacity_reservation_id = _leased(ledger)
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        offering_mode=VM_OFFERING_MODE,
    )
    svc = _lifecycle(session_factory, ledger)

    first = await svc.force_check_leases()
    assert first["checked"] == 1
    releasing = ledger.get_reservation(capacity_reservation_id)
    assert (releasing["state"], releasing["release_job_id"]) == ("releasing", "fulfillment-1")
    assert _aggregate_state(session_factory, capacity_reservation_id) == (
        _State.teardown_dispatch_pending.value
    )

    _set_fulfillment_state(session_factory, capacity_reservation_id, _State.torn_down.value)
    sf = _storefront()
    with patch("storefront_client.StorefrontClient", return_value=sf) as client_cls:
        summary = await svc.force_check_leases()

    assert summary["released"] == 1
    assert ledger.get_reservation(capacity_reservation_id)["state"] == "released"
    assert ledger.snapshot()[0]["available_units"] == 8
    client_cls.assert_called_once_with(
        base_url="http://storefront:8001",
        signer=_SERVICE_SIGNER,
        caller_role="service",
        expected_publishers=TrustedIdentitySet(identities=(_STOREFRONT_SIGNER.identity,)),
    )
    args, kwargs = sf.notify_capacity_released.await_args
    assert args == (capacity_reservation_id,)
    assert kwargs["site_id"] == "default"
    assert kwargs["request_id"].startswith("capacity-release-")
    assert "resource_id" not in kwargs
    sf.patch_resource.assert_not_awaited()
    events, _ = ledger.events_after(0)
    assert events[-1]["kind"] == "released"


@pytest.mark.asyncio
async def test_a_bare_metal_lease_is_released_through_its_fulfillment_as_a_vm_s_is(
    session_factory, ledger
):
    capacity_reservation_id = _leased(ledger, offering_mode=BARE_METAL_OFFERING_MODE)
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        offering_mode=BARE_METAL_OFFERING_MODE,
    )
    svc = _lifecycle(session_factory, ledger)

    await svc.force_check_leases()

    assert ledger.get_reservation(capacity_reservation_id)["release_job_id"] == "fulfillment-1"
    assert _aggregate_state(session_factory, capacity_reservation_id) == (
        _State.teardown_dispatch_pending.value
    )


@pytest.mark.asyncio
async def test_release_survives_an_unreachable_storefront(session_factory, ledger):
    """The local transaction is authoritative; notification is best-effort
    (the storefront converges through the capacity-event feed)."""
    capacity_reservation_id = _leased(ledger)
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        offering_mode=VM_OFFERING_MODE,
    )
    svc = _lifecycle(session_factory, ledger)
    await svc.force_check_leases()
    _set_fulfillment_state(session_factory, capacity_reservation_id, _State.torn_down.value)

    with patch("storefront_client.StorefrontClient", side_effect=ConnectionError("down")):
        summary = await svc.force_check_leases()

    assert summary["released"] == 1
    assert ledger.get_reservation(capacity_reservation_id)["state"] == "released"


@pytest.mark.asyncio
async def test_a_lease_nothing_was_dispatched_for_is_released_directly(session_factory, ledger):
    capacity_reservation_id = _leased(ledger)
    svc = _lifecycle(session_factory, ledger)

    sf = _storefront()
    with patch("storefront_client.StorefrontClient", return_value=sf):
        summary = await svc.force_check_leases()

    assert summary["released"] == 1
    assert ledger.get_reservation(capacity_reservation_id)["state"] == "released"
    sf.notify_capacity_released.assert_awaited_once()


@pytest.mark.asyncio
async def test_an_assigned_aggregate_is_abandoned_and_its_lease_released(session_factory, ledger):
    capacity_reservation_id = _leased(ledger)
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        offering_mode=VM_OFFERING_MODE,
    )
    _set_fulfillment_state(
        session_factory, capacity_reservation_id, _State.assigned.value, fulfillment_id=None
    )
    svc = _lifecycle(session_factory, ledger)

    with patch("storefront_client.StorefrontClient", return_value=_storefront()):
        await svc.force_check_leases()

    assert ledger.get_reservation(capacity_reservation_id)["state"] == "released"
    assert _aggregate_state(session_factory, capacity_reservation_id) == _State.abandoned.value


@pytest.mark.asyncio
async def test_a_lease_whose_create_is_in_flight_waits_then_tears_down(session_factory, ledger):
    """The release is remembered as ``releasing`` with the fulfillment as its
    handle; no grace timeout runs while the create is in flight; once it
    settles, teardown begins."""
    capacity_reservation_id = _leased(ledger, ended=timedelta(hours=2))
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        offering_mode=VM_OFFERING_MODE,
    )
    _set_fulfillment_state(session_factory, capacity_reservation_id, _State.dispatching.value)
    svc = _lifecycle(session_factory, ledger, lease_watchdog_grace_period_seconds=0)

    await svc.force_check_leases()
    await svc.force_check_leases()

    row = ledger.get_reservation(capacity_reservation_id)
    assert (row["state"], row["release_job_id"]) == ("releasing", "fulfillment-1")

    _set_fulfillment_state(session_factory, capacity_reservation_id, _State.active.value)
    await svc.force_check_leases()

    assert _aggregate_state(session_factory, capacity_reservation_id) == (
        _State.teardown_dispatch_pending.value
    )
    assert ledger.get_reservation(capacity_reservation_id)["state"] == "releasing"


@pytest.mark.asyncio
async def test_a_failed_create_leaves_the_lease_for_an_operator(session_factory, ledger):
    capacity_reservation_id = _leased(ledger)
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        offering_mode=VM_OFFERING_MODE,
    )
    _set_fulfillment_state(
        session_factory,
        capacity_reservation_id,
        _State.failed.value,
        failure_message="create reported failure",
    )
    svc = _lifecycle(session_factory, ledger)

    summary = await svc.force_check_leases()

    row = ledger.get_reservation(capacity_reservation_id)
    assert summary["release_failed"] == 1
    assert (row["state"], row["failure_reason"], row["failure_message"]) == (
        "release_failed",
        "fulfillment_failed",
        "create reported failure",
    )
    assert ledger.snapshot()[0]["available_units"] == 6


def _release_began(session_factory, capacity_reservation_id: str, ago: timedelta) -> None:
    """Move the release's recorded start back, as if it began ``ago``."""
    from market_site.db import CapacityReservation

    with session_factory() as db, db.begin():
        db.get(CapacityReservation, capacity_reservation_id).release_requested_at = (
            datetime.now(timezone.utc) - ago
        ).isoformat()


@pytest.mark.asyncio
async def test_a_teardown_stalled_past_the_grace_period_from_its_release_times_out(
    session_factory, ledger
):
    """The grace period runs from when the release began, so a lease that
    ended long ago is not timed out in the cycle its teardown begins, and a
    teardown stalled past the grace period from its release is."""
    capacity_reservation_id = _leased(ledger, ended=timedelta(days=2))
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        offering_mode=VM_OFFERING_MODE,
    )
    svc = _lifecycle(session_factory, ledger)

    first = await svc.force_check_leases()

    assert first["release_failed"] == 0
    assert ledger.get_reservation(capacity_reservation_id)["release_requested_at"]

    _set_fulfillment_state(session_factory, capacity_reservation_id, _State.tearing_down.value)
    _release_began(session_factory, capacity_reservation_id, timedelta(minutes=10))
    stalled = await svc.force_check_leases()

    row = ledger.get_reservation(capacity_reservation_id)
    assert stalled["release_failed"] == 1
    assert (row["state"], row["failure_reason"]) == ("release_failed", "teardown_timeout")


@pytest.mark.asyncio
async def test_a_teardown_within_its_grace_period_is_left_running(session_factory, ledger):
    capacity_reservation_id = _leased(ledger)
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        offering_mode=VM_OFFERING_MODE,
    )
    svc = _lifecycle(session_factory, ledger)
    await svc.force_check_leases()
    _set_fulfillment_state(session_factory, capacity_reservation_id, _State.tearing_down.value)

    summary = await svc.force_check_leases()

    assert summary["skipped"] == 1
    assert ledger.get_reservation(capacity_reservation_id)["state"] == "releasing"


@pytest.mark.asyncio
async def test_a_failed_teardown_waits_for_retry_which_adopts_the_finished_one(
    session_factory, ledger
):
    capacity_reservation_id = _leased(ledger)
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        offering_mode=VM_OFFERING_MODE,
    )
    svc = _lifecycle(session_factory, ledger)
    await svc.force_check_leases()
    _set_fulfillment_state(
        session_factory, capacity_reservation_id, _State.teardown_failed.value,
        failure_message="host unreachable",
    )

    with patch("storefront_client.StorefrontClient", return_value=_storefront()):
        await svc.force_check_leases()
        assert ledger.get_reservation(capacity_reservation_id)["failure_reason"] == (
            "teardown_failed"
        )
        _set_fulfillment_state(session_factory, capacity_reservation_id, _State.torn_down.value)
        retried = await svc.retry_release(capacity_reservation_id)

    assert retried["state"] == "released"


@pytest.mark.asyncio
async def test_an_unexpected_repository_failure_is_recorded_as_release_submit_error(
    session_factory, ledger
):
    capacity_reservation_id = _leased(ledger)
    svc = _lifecycle(session_factory, ledger)

    with patch.object(SettlementRepository, "get", side_effect=RuntimeError("db gone")):
        summary = await svc.force_check_leases()

    row = ledger.get_reservation(capacity_reservation_id)
    assert summary["release_failed"] == 1
    assert (row["state"], row["failure_reason"]) == ("release_failed", "release_submit_error")


@pytest.mark.asyncio
async def test_an_operator_force_release_frees_an_unmanaged_lease_and_notifies(
    session_factory, ledger
):
    capacity_reservation_id = _leased(ledger)
    _create_active_fulfillment(
        session_factory,
        capacity_reservation_id=capacity_reservation_id,
        offering_mode=VM_OFFERING_MODE,
    )
    ledger.update_reservation_state(
        capacity_reservation_id,
        state="unmanaged",
        failure_reason="oversight_released",
        failure_message="manual ops",
    )
    svc = _lifecycle(session_factory, ledger)
    sf = _storefront()

    with patch("storefront_client.StorefrontClient", return_value=sf):
        released = await svc.force_release(
            capacity_reservation_id,
            LeaseForceRelease(reason="host inspected", evidence="VM absent"),
        )

    assert (released["state"], released["failure_reason"]) == (
        "force_released",
        "admin_force_release",
    )
    assert ledger.snapshot()[0]["available_units"] == 8
    sf.notify_capacity_released.assert_awaited_once()
