"""Prove ``FulfillmentConvergenceWatchdog`` can observe and progress rows
produced by the legacy VM lease backfill.

Migration ordering and schema shape are covered elsewhere
(``test_database.py``'s index/FK/schema-migrations-set assertions). This
file is the missing piece: it runs the real migration against a populated
pre-migration schema, producing one row in each non-terminal state the
backfill can emit, then drives the watchdog's claim/dispatch/converge
entry points against the resulting rows and asserts each progresses the
same way a natively-created row would -- proving recovery can actually
observe backfilled data, not just that the migration writes rows shaped
like it should.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import _apply_legacy_vm_lease_backfill
from compute_provisioning_service.services.fulfillment_convergence import (
    FulfillmentConvergenceWatchdog,
)
from market_fulfillment import (
    CredentialSet,
    FulfillmentProvider,
    FulfillmentResult,
    ProviderOperationState,
    ProviderRegistry,
    ProviderStatus,
    SettlementRecordState,
    SettlementRepository,
)

_PLAYBOOK_PATH = "/configured/playbook.yaml"
_INVENTORY_GROUP = "legacy_hosts"


class _StubAnsibleProvider(FulfillmentProvider):
    """Reports every in-flight operation as immediately successful."""

    def prepare_create(self, *, capacity_reservation_id, request, resource, pool_config):
        raise NotImplementedError

    async def dispatch_create(self, prepared):
        raise NotImplementedError

    def prepare_teardown(self, settlement_result, pool_config):
        raise NotImplementedError

    async def dispatch_teardown(self, prepared):
        return FulfillmentResult(provider_metadata={"current_job_id": "job-remove-dispatched"})

    async def get_status(self, capacity_reservation_id, resource, provider_metadata):
        return ProviderStatus(state=ProviderOperationState.succeeded)

    def resolve_provisioned_resources(self, provider_metadata):
        return (provider_metadata.get("vm_target") or "vm-resolved",)

    async def fetch_credentials(self, provider_metadata):
        return CredentialSet()


def _settings(**overrides):
    defaults = dict(
        fulfillment_convergence_batch_size=10,
        fulfillment_convergence_backoff_initial_seconds=1.0,
        fulfillment_convergence_backoff_multiplier=2.0,
        fulfillment_convergence_backoff_max_seconds=60.0,
        fulfillment_convergence_backoff_jitter_fraction=0.0,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture
def engine():
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
        connection.execute(text(
            """
            INSERT INTO hosts (name, kvm_host, ssh_user, ssh_key_type, ssh_key_value,
                                gpu_count, enabled, pool_id)
            VALUES ('kvm1', '10.0.0.1', 'root', 'path', '/keys/id_ed25519', 0, 1, 'default')
            """
        ))
        # One legacy lease per non-terminal backfill state.
        connection.execute(text(
            """
            INSERT INTO vm_leases (id, allocation_id, vm_host, vm_target, status,
                                    create_job_id, vm_remove_job_id)
            VALUES
                ('lease-provisioning', 'reservation-provisioning', 'kvm1', NULL,
                 'provisioning', 'job-create-1', NULL),
                ('lease-releasing-pending', 'reservation-releasing-pending', 'kvm1',
                 'vm-releasing-pending', 'releasing', 'job-create-2', NULL),
                ('lease-tearing-down', 'reservation-tearing-down', 'kvm1',
                 'vm-tearing-down', 'releasing', 'job-create-3', 'job-remove-3'),
                ('lease-teardown-failed', 'reservation-teardown-failed', 'kvm1',
                 'vm-teardown-failed', 'release_failed', 'job-create-4', 'job-remove-4')
            """
        ))
    with engine.begin() as connection:
        _apply_legacy_vm_lease_backfill(connection)
    return engine


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine)


@pytest.fixture
def repo():
    return SettlementRepository()


@pytest.fixture
def watchdog(session_factory, repo):
    return FulfillmentConvergenceWatchdog(
        session_factory=session_factory,
        repository=repo,
        provider_registry=ProviderRegistry({"ansible": _StubAnsibleProvider()}),
        settings=_settings(),
    )


def _state(repo, session_factory, reservation_id):
    with session_factory() as db:
        return repo.get(db, reservation_id).state


def test_backfill_produces_one_row_per_nonterminal_state(repo, session_factory):
    assert _state(repo, session_factory, "reservation-provisioning") == (
        SettlementRecordState.dispatching.value
    )
    assert _state(repo, session_factory, "reservation-releasing-pending") == (
        SettlementRecordState.teardown_dispatch_pending.value
    )
    assert _state(repo, session_factory, "reservation-tearing-down") == (
        SettlementRecordState.tearing_down.value
    )
    assert _state(repo, session_factory, "reservation-teardown-failed") == (
        SettlementRecordState.teardown_failed.value
    )


async def test_converge_creates_observes_backfilled_dispatching_row(
    watchdog, repo, session_factory
):
    await watchdog.converge_creates()

    assert _state(repo, session_factory, "reservation-provisioning") == (
        SettlementRecordState.active.value
    )
    with session_factory() as db:
        resources = repo.list_provisioned_resources(db, "reservation-provisioning")
    assert [r.domain_resource_ref for r in resources] == ["vm-resolved"]


async def test_dispatch_pending_teardowns_observes_backfilled_row(
    watchdog, repo, session_factory
):
    await watchdog.dispatch_pending_teardowns()

    assert _state(repo, session_factory, "reservation-releasing-pending") == (
        SettlementRecordState.tearing_down.value
    )


async def test_converge_teardowns_observes_backfilled_tearing_down_row(
    watchdog, repo, session_factory
):
    await watchdog.converge_teardowns()

    assert _state(repo, session_factory, "reservation-tearing-down") == (
        SettlementRecordState.torn_down.value
    )


async def test_requeue_teardown_failures_observes_backfilled_row(
    watchdog, repo, session_factory
):
    await watchdog.requeue_teardown_failures()

    assert _state(repo, session_factory, "reservation-teardown-failed") == (
        SettlementRecordState.teardown_dispatch_pending.value
    )


async def test_full_cycle_converges_every_backfilled_row_to_terminal_or_active(
    watchdog, repo, session_factory
):
    """A fresh watchdog instance resuming purely from durable state (no
    in-memory knowledge of which rows came from the legacy backfill)
    converges all of them within a couple of cycles, exactly as it would
    for natively-created rows."""
    await watchdog.run_cycle()
    await watchdog.run_cycle()

    assert _state(repo, session_factory, "reservation-provisioning") == (
        SettlementRecordState.active.value
    )
    assert _state(repo, session_factory, "reservation-releasing-pending") == (
        SettlementRecordState.torn_down.value
    )
    assert _state(repo, session_factory, "reservation-tearing-down") == (
        SettlementRecordState.torn_down.value
    )
    # teardown_failed -> teardown_dispatch_pending -> tearing_down -> torn_down
    assert _state(repo, session_factory, "reservation-teardown-failed") == (
        SettlementRecordState.torn_down.value
    )
