"""DB-level tests for the legacy VM lease -> fulfillment migration.

Per-candidate derivation scenarios (state mapping, per-row validation) are
covered without a database in
``tests/unit/services/test_legacy_vm_fulfillment_backfill.py`` against the
pure compiler. This file covers the population-level concerns that only
make sense against a real connection: cross-candidate enumeration,
comparison against already-persisted rows, and whole-transaction
atomicity. ``_apply_legacy_vm_lease_backfill`` is called directly (rather
than through ``run_migrations``) so equivalent-rerun and
conflicting-duplicate can be exercised at all -- ``apply_schema_migrations``
tracks migration ids and never re-invokes an applied migration, and the
next migration in sequence drops ``vm_leases`` outright.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import (
    SchemaDriftError,
    _apply_legacy_vm_lease_backfill,
)

_PLAYBOOK_PATH = "/configured/playbook.yaml"
_INVENTORY_GROUP = "legacy_hosts"


def _sqlite_memory_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _bootstrap_engine():
    """Build a fresh current-schema engine, then re-add a fresh ``vm_leases``
    table for tests to seed directly (``run_migrations`` drops it as its
    final step, matching production's one-shot cutover)."""
    engine = _sqlite_memory_engine()
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


def _insert_host(engine, *, name="kvm1", pool_id="default"):
    with engine.begin() as connection:
        connection.execute(text(
            """
            INSERT INTO hosts (name, kvm_host, ssh_user, ssh_key_type, ssh_key_value,
                                gpu_count, enabled, pool_id)
            VALUES (:name, '10.0.0.1', 'root', 'path', '/keys/id_ed25519', 0, 1, :pool_id)
            """
        ), {"name": name, "pool_id": pool_id})


def _insert_capacity_reservation(engine, *, reservation_id, state="reserved"):
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO capacity_reservations (capacity_reservation_id, units, state) "
            "VALUES (:id, 1, :state)"
        ), {"id": reservation_id, "state": state})


def _insert_vm_lease(
    engine,
    *,
    lease_id,
    allocation_id,
    status,
    vm_host="kvm1",
    vm_target=None,
    create_job_id=None,
    vm_remove_job_id=None,
):
    with engine.begin() as connection:
        connection.execute(text(
            """
            INSERT INTO vm_leases (id, allocation_id, vm_host, vm_target, status,
                                    create_job_id, vm_remove_job_id)
            VALUES (:id, :allocation_id, :vm_host, :vm_target, :status,
                    :create_job_id, :vm_remove_job_id)
            """
        ), {
            "id": lease_id, "allocation_id": allocation_id, "vm_host": vm_host,
            "vm_target": vm_target, "status": status,
            "create_job_id": create_job_id, "vm_remove_job_id": vm_remove_job_id,
        })


def _apply_backfill(engine):
    with engine.begin() as connection:
        _apply_legacy_vm_lease_backfill(connection)


def _settlement_state(engine, reservation_id):
    with engine.begin() as connection:
        row = connection.execute(text(
            "SELECT state FROM settlement_records WHERE capacity_reservation_id=:id"
        ), {"id": reservation_id}).mappings().one_or_none()
    return row["state"] if row else None


def _count(engine, table):
    with engine.begin() as connection:
        return connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()


def test_terminal_and_expired_leases_are_skipped():
    engine = _bootstrap_engine()
    _insert_host(engine)
    for status in ("completed", "expired", "cancelled"):
        _insert_vm_lease(
            engine, lease_id=f"lease-{status}", allocation_id=f"reservation-{status}",
            status=status, vm_target=f"vm-{status}",
        )

    _apply_backfill(engine)

    assert _count(engine, "settlement_records") == 0
    assert _count(engine, "provisioned_resources") == 0


def test_unmatched_reservation_does_not_obscure_a_real_lease():
    engine = _bootstrap_engine()
    _insert_host(engine)
    # A pre-release reservation with no corresponding lease -- must be
    # tolerated (ignored), not treated as a migration candidate.
    _insert_capacity_reservation(engine, reservation_id="orphan-reservation")
    _insert_vm_lease(
        engine, lease_id="lease-active", allocation_id="reservation-active",
        status="leased", vm_target="vm-active", create_job_id="job-1",
    )

    _apply_backfill(engine)

    assert _settlement_state(engine, "reservation-active") == "active"
    assert _settlement_state(engine, "orphan-reservation") is None
    assert _count(engine, "settlement_records") == 1


def test_equivalent_rerun_is_idempotent_and_writes_nothing_new():
    engine = _bootstrap_engine()
    _insert_host(engine)
    _insert_vm_lease(
        engine, lease_id="lease-active", allocation_id="reservation-active",
        status="leased", vm_target="vm-active", create_job_id="job-1",
    )

    _apply_backfill(engine)
    first_provisioned_count = _count(engine, "provisioned_resources")

    # Rerun directly against the same still-populated vm_leases table --
    # not reachable through run_migrations, which tracks this migration id
    # and never re-invokes it, and whose next step drops vm_leases outright.
    _apply_backfill(engine)

    assert _settlement_state(engine, "reservation-active") == "active"
    assert _count(engine, "settlement_records") == 1
    assert _count(engine, "provisioned_resources") == first_provisioned_count


def test_conflicting_duplicate_is_rejected_not_overwritten():
    engine = _bootstrap_engine()
    _insert_host(engine)
    _insert_vm_lease(
        engine, lease_id="lease-active", allocation_id="reservation-1",
        status="leased", vm_target="vm-active", create_job_id="job-1",
    )
    _apply_backfill(engine)
    assert _settlement_state(engine, "reservation-1") == "active"

    # Mutate the lease so a rerun would derive a *different* state for the
    # same reservation identity -- this must be rejected, not silently
    # overwrite the already-persisted aggregate.
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE vm_leases SET status='release_failed', vm_remove_job_id='job-remove-1' "
            "WHERE id='lease-active'"
        ))

    with pytest.raises(SchemaDriftError, match="conflicting settlement aggregate"):
        _apply_backfill(engine)

    # The original row must be untouched by the rejected rerun.
    assert _settlement_state(engine, "reservation-1") == "active"


def test_whole_migration_rolls_back_on_any_candidate_failure():
    engine = _bootstrap_engine()
    _insert_host(engine)
    _insert_vm_lease(
        engine, lease_id="lease-valid", allocation_id="reservation-valid",
        status="leased", vm_target="vm-valid", create_job_id="job-1",
    )
    # Second candidate has no create_job_id and no target for a
    # non-provisioning status -- the compiler rejects it.
    _insert_vm_lease(
        engine, lease_id="lease-invalid", allocation_id="reservation-invalid",
        status="leased", vm_target=None, create_job_id=None,
    )

    with pytest.raises(SchemaDriftError):
        _apply_backfill(engine)

    # Neither candidate's rows were committed -- including the otherwise
    # valid one enumerated before the failing candidate.
    assert _count(engine, "settlement_records") == 0
    assert _count(engine, "provisioned_resources") == 0


def test_conflicting_duplicate_rejects_different_create_job_id():
    """Same derived state/resource/pool/provider, but the tracked create
    job identity itself differs -- accepting this would silently lose or
    swap which provider job a reservation is actually attached to."""
    engine = _bootstrap_engine()
    _insert_host(engine)
    _insert_vm_lease(
        engine, lease_id="lease-active", allocation_id="reservation-1",
        status="leased", vm_target="vm-active", create_job_id="job-1",
    )
    _apply_backfill(engine)
    assert _settlement_state(engine, "reservation-1") == "active"

    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE vm_leases SET create_job_id='job-2' WHERE id='lease-active'"
        ))

    with pytest.raises(SchemaDriftError, match="conflicting settlement aggregate"):
        _apply_backfill(engine)


def test_conflicting_duplicate_rejects_different_teardown_job_id():
    """Same derived state, but the active teardown job identity differs."""
    engine = _bootstrap_engine()
    _insert_host(engine)
    _insert_vm_lease(
        engine, lease_id="lease-tearing", allocation_id="reservation-1",
        status="releasing", vm_target="vm-tearing", create_job_id="job-1",
        vm_remove_job_id="job-remove-1",
    )
    _apply_backfill(engine)
    assert _settlement_state(engine, "reservation-1") == "tearing_down"

    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE vm_leases SET vm_remove_job_id='job-remove-2' WHERE id='lease-tearing'"
        ))

    with pytest.raises(SchemaDriftError, match="conflicting settlement aggregate"):
        _apply_backfill(engine)


def test_conflicting_duplicate_rejects_missing_prepared_teardown_operation():
    """An already-persisted row with a live target but no prepared teardown
    envelope is not equivalent to a freshly-compiled draft, which always
    prepares one for a live target -- accepting it would leave a recovered
    reservation with no way to tear the resource down."""
    engine = _bootstrap_engine()
    _insert_host(engine)
    _insert_vm_lease(
        engine, lease_id="lease-active", allocation_id="reservation-1",
        status="leased", vm_target="vm-active", create_job_id="job-1",
    )
    _apply_backfill(engine)

    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE settlement_records SET prepared_teardown_operation=NULL "
            "WHERE capacity_reservation_id='reservation-1'"
        ))

    with pytest.raises(SchemaDriftError, match="conflicting settlement aggregate"):
        _apply_backfill(engine)


def test_conflicting_duplicate_rejects_missing_provisioned_resource_row():
    """A live-target candidate expects exactly one ProvisionedResource row;
    an already-persisted aggregate with none is a conflict, not something
    to silently leave as-is."""
    engine = _bootstrap_engine()
    _insert_host(engine)
    _insert_vm_lease(
        engine, lease_id="lease-active", allocation_id="reservation-1",
        status="leased", vm_target="vm-active", create_job_id="job-1",
    )
    _apply_backfill(engine)
    assert _count(engine, "provisioned_resources") == 1

    with engine.begin() as connection:
        connection.execute(text(
            "DELETE FROM provisioned_resources WHERE capacity_reservation_id='reservation-1'"
        ))

    with pytest.raises(SchemaDriftError, match="conflicting settlement aggregate"):
        _apply_backfill(engine)


def test_conflicting_duplicate_rejects_provisioned_resource_with_different_target():
    """An existing ProvisionedResource row pointing at a different VM target
    than the one the lease actually describes is a conflict."""
    engine = _bootstrap_engine()
    _insert_host(engine)
    _insert_vm_lease(
        engine, lease_id="lease-active", allocation_id="reservation-1",
        status="leased", vm_target="vm-active", create_job_id="job-1",
    )
    _apply_backfill(engine)

    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE provisioned_resources SET domain_resource_ref='vm-different' "
            "WHERE capacity_reservation_id='reservation-1'"
        ))

    with pytest.raises(SchemaDriftError, match="conflicting settlement aggregate"):
        _apply_backfill(engine)


def test_conflicting_duplicate_rejects_multiple_provisioned_resource_rows():
    """Exactly one ProvisionedResource row is expected for a live-target
    candidate; a second, differently-targeted row for the same reservation
    is a conflict, not something the rerun should tolerate or pick from."""
    engine = _bootstrap_engine()
    _insert_host(engine)
    _insert_vm_lease(
        engine, lease_id="lease-active", allocation_id="reservation-1",
        status="leased", vm_target="vm-active", create_job_id="job-1",
    )
    _apply_backfill(engine)

    with engine.begin() as connection:
        connection.execute(text(
            """INSERT INTO provisioned_resources
            (provisioned_resource_id, capacity_reservation_id, fulfillment_id,
             domain_resource_ref, status)
            SELECT 'extra-resource', capacity_reservation_id, fulfillment_id,
                   'vm-active-extra', 'active'
            FROM settlement_records WHERE capacity_reservation_id='reservation-1'"""
        ))

    with pytest.raises(SchemaDriftError, match="conflicting settlement aggregate"):
        _apply_backfill(engine)
