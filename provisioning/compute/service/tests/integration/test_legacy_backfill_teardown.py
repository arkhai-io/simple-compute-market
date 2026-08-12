"""Migration-produced backfill through the current teardown path end to end.

Every other teardown test in this suite
hand-constructs a `SettlementRecord` row directly (`_create_active_fulfillment`
and its siblings in `test_ledger_lease_lifecycle.py`/`test_compute_contract_api.py`),
which is the right choice for tests whose subject is teardown submission or
polling -- but none of them prove the actual legacy backfill migration
(`_apply_legacy_vm_lease_backfill`) produces a row the new teardown path can
consume. This file runs the real migration entrypoint against a real
connection, then drives its output through `begin_fulfillment_teardown`,
simulated convergence (`FulfillmentConvergenceWatchdog` has its own test
suite; this file only needs its end state), and `LeaseLifecycleService`,
proving a pre-cutover VM lease reaches `released` with capacity returned.
"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning.lease_lifecycle import LeaseLifecycleService
from compute_provisioning.release import ExecutorReleaseDispatcher, ReleaseJobDispatcher
from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import _apply_legacy_vm_lease_backfill
from market_fulfillment import (
    FulfillmentOrchestrator,
    ProviderRegistry,
    SettlementRecord,
    SettlementRecordState,
    SettlementRepository,
    SqlAlchemyFulfillmentUnitOfWork,
)
from market_resource_pools import ResourcePoolService
from market_site.authority import LedgerSiteAuthority
from market_site.ledger import CapacityLedgerService
from vm_provisioning_adapter.release import (
    VM_EXECUTOR_KIND,
    FulfillmentServiceTeardownPort,
    VmFulfillmentReleaseJobPort,
    VmReleaseExecutor,
)
from vm_provisioning_adapter.services.ansible_fulfillment_provider import (
    AnsibleFulfillmentProvider,
)

_PLAYBOOK_PATH = "/configured/playbook.yaml"
_INVENTORY_GROUP = "legacy_hosts"


def _bootstrap_engine():
    """Current-schema engine, then a fresh `vm_leases` table re-added for the
    test to seed -- `run_migrations` drops it as its final step, matching
    production's one-shot cutover, same pattern as
    `test_legacy_vm_lease_migration.py`."""

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(
        engine,
        default_playbook_path=_PLAYBOOK_PATH,
        default_inventory_group=_INVENTORY_GROUP,
    )
    with engine.begin() as connection:
        connection.execute(text(
            """
            CREATE TABLE vm_leases (
                id VARCHAR PRIMARY KEY,
                allocation_id VARCHAR,
                escrow_uid VARCHAR,
                vm_host VARCHAR NOT NULL,
                vm_target VARCHAR,
                status VARCHAR NOT NULL,
                create_job_id VARCHAR,
                vm_remove_job_id VARCHAR
            )
            """
        ))
    return engine


def _settings(**overrides):
    from unittest.mock import MagicMock

    s = MagicMock()
    s.lease_watchdog_grace_period_seconds = 300
    s.storefront_url = "http://storefront:8001"
    s.storefront_site_id = "default"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s

async def _successful_notification(_reservation):
    return True


def test_pre_cutover_vm_lease_backfills_and_tears_down_to_release():
    engine = _bootstrap_engine()

    # Representative pre-POOLS data: a VM lease still active (not yet
    # released) when the cutover migration ran, exactly the common case a
    # migration must carry forward correctly, not an already-failed edge
    # case that happens to skip the "initiate teardown" step.
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO hosts (name, kvm_host, ssh_user, ssh_key_type, ssh_key_value, "
            "gpu_count, enabled, pool_id) "
            "VALUES ('kvm1', '10.0.0.1', 'root', 'path', '/keys/id_ed25519', 0, 1, 'default')"
        ))
        connection.execute(text(
            "INSERT INTO capacity_reservations (capacity_reservation_id, units, state) "
            "VALUES ('reservation-legacy-1', 1, 'leased')"
        ))
        connection.execute(text(
            """
            INSERT INTO vm_leases (id, allocation_id, vm_host, vm_target, status,
                                    create_job_id, vm_remove_job_id)
            VALUES ('lease-legacy-1', 'reservation-legacy-1', 'kvm1', 'tenant-legacy-1',
                    'leased', 'job-create-legacy-1', NULL)
            """
        ))

    # The real migration entrypoint -- not a hand-constructed SettlementRecord.
    with engine.begin() as connection:
        _apply_legacy_vm_lease_backfill(connection)

    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        record = db.get(SettlementRecord, "reservation-legacy-1")
        assert record is not None
        assert record.state == SettlementRecordState.active.value
        assert record.prepared_teardown_operation is not None
        fulfillment_id = record.fulfillment_id

    # Wire the real components the running service composes, against the
    # same engine the migration just wrote to.
    resource_pool_service = ResourcePoolService(session_factory=session_factory, handlers={})
    settlement_repository = SettlementRepository()
    fulfillment_service = FulfillmentOrchestrator(
        provider_registry=ProviderRegistry({
            "ansible": AnsibleFulfillmentProvider(
                job_service=None, job_queue_provider=lambda: None,
            ),
        }),
        unit_of_work=SqlAlchemyFulfillmentUnitOfWork(
            session_factory=session_factory,
            pool_service=resource_pool_service,
            repository=settlement_repository,
        ),
    )
    ledger = CapacityLedgerService(session_factory=session_factory)
    executor_release = ExecutorReleaseDispatcher(
        {
            VM_EXECUTOR_KIND: VmReleaseExecutor(
                settlement_repository=settlement_repository,
                session_factory=session_factory,
                teardown_port=FulfillmentServiceTeardownPort(lambda: fulfillment_service),
            ),
        },
        default_executor_kind=VM_EXECUTOR_KIND,
    )
    release_jobs = ReleaseJobDispatcher(
        {
            VM_EXECUTOR_KIND: VmFulfillmentReleaseJobPort(
                teardown_port=FulfillmentServiceTeardownPort(lambda: fulfillment_service),
            ),
        },
        default_executor_kind=VM_EXECUTOR_KIND,
    )
    settings = _settings()
    lease_lifecycle = LeaseLifecycleService(
        settings=settings,
        site_authority=LedgerSiteAuthority(ledger),
        executor_release=executor_release,
        release_jobs=release_jobs,
        capacity_released_notifier=_successful_notification,
    )

    # Give the reservation a lease_end_utc in the past so the watchdog
    # picks it up -- the migration itself does not carry lease timing
    # (that's site-ledger data, not fulfillment-aggregate data).
    from datetime import datetime, timedelta, timezone

    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE capacity_reservations SET lease_end_utc = :end WHERE "
            "capacity_reservation_id = 'reservation-legacy-1'"
        ), {"end": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()})

    import asyncio

    async def _drive():
        first = await lease_lifecycle.force_check_leases()
        assert first["checked"] == 1
        reservation = ledger.get_reservation("reservation-legacy-1")
        assert reservation["state"] == "releasing"
        assert reservation["release_job_id"] == fulfillment_id

        with session_factory() as db:
            record = db.get(SettlementRecord, "reservation-legacy-1")
            assert record.state == SettlementRecordState.teardown_dispatch_pending.value
            # Convergence itself is FulfillmentConvergenceWatchdog's own concern.
            record.state = SettlementRecordState.torn_down.value
            db.commit()

        summary = await lease_lifecycle.force_check_leases()
        assert summary["released"] == 1
        released = ledger.get_reservation("reservation-legacy-1")
        assert released["state"] == "released"

    asyncio.run(_drive())
