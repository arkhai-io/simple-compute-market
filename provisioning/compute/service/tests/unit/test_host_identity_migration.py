"""The host-identity migration: one name for the host on every persisted surface.

Every test starts from the schema the preceding migration chain actually
leaves (``fixtures/schema_through_20260911_001.sql``), writes rows in the
shapes that schema held, and runs the pending migrations. Starting from the
real previous schema is what lets a failure be checked against the whole
database — its schema objects as well as its rows.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.migrations import (
    HostIdentityMigrationError,
    apply_schema_migrations,
    count_rows_carrying_retired_host_keys,
)

_PREVIOUS_SCHEMA = Path(__file__).parent / "fixtures" / "schema_through_20260911_001.sql"


def _previous_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    raw = engine.raw_connection()
    try:
        raw.driver_connection.executescript(_PREVIOUS_SCHEMA.read_text())
    finally:
        raw.close()
    return engine


def _snapshot(engine):
    """Every schema object and every row, for before/after comparison."""
    with engine.begin() as connection:
        schema = connection.execute(text(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        )).all()
        tables = [row[1] for row in schema if row[0] == "table"]
        rows = {
            table: connection.execute(text(f'SELECT * FROM "{table}"')).all()
            for table in tables
        }
    return schema, rows


def _execute(engine, sql, **params):
    with engine.begin() as connection:
        connection.execute(text(sql), params)


def _json(engine, sql):
    with engine.begin() as connection:
        value = connection.execute(text(sql)).scalar_one()
    return json.loads(value) if isinstance(value, str) else value


def _bucket(engine, bucket_id, resource_id, attributes):
    _execute(
        engine,
        "INSERT INTO capacity_buckets (capacity_bucket_id, backing_resource_id, "
        "pool_id, resource_type, total_units, capacity, attributes, enabled, "
        "created_at, updated_at) VALUES (:id, :rid, 'default', 'compute.gpu', 1, "
        "'{\"gpu_count\": 1}', :attributes, 1, '2026-01-01', '2026-01-01')",
        id=bucket_id, rid=resource_id, attributes=json.dumps(attributes),
    )


def _populate(engine):
    # The chain seeds the system-owned default pool; the schema dump carries
    # no rows, so the fixture does.
    _execute(
        engine,
        "INSERT INTO resource_pools (id, label, provider, enabled, policy_tags) "
        "VALUES ('default', 'Default Pool', 'ansible', 1, "
        "'{\"deliverable_modes\": [\"vm\"]}')",
    )
    _execute(
        engine,
        "INSERT INTO hosts (name, kvm_host, ssh_user, ssh_key_type, ssh_key_value, "
        "gpu_count, enabled, pool_id, created_at, updated_at) VALUES ('kvm1', "
        "'10.0.0.1', 'root', 'path', '/keys/id', 1, 1, 'default', '2026-01-01', "
        "'2026-01-01')",
    )
    _bucket(engine, "b1", "vm-slice-1", {"vm_host": "kvm1", "gpu_model": "H200"})
    _bucket(engine, "b2", "bm-node-1", {
        "bare_metal_publication": {
            "enabled": True,
            "machine_id": "bm1",
            "physical_host_id": "physical-1",
            "allocation_mode": "exclusive",
            "access_methods": ["ssh"],
        },
    })
    _execute(
        engine,
        "INSERT INTO capacity_reservations (capacity_reservation_id, units, state, "
        "executor_ref, claim_attributes, created_at, updated_at) VALUES "
        "('reservation-1', 1, 'leased', :ref, :claim, '2026-01-01', '2026-01-01')",
        ref=json.dumps({"vm_host": "kvm1"}),
        claim=json.dumps({"vm_host": "kvm1", "region": "eu"}),
    )
    _execute(
        engine,
        "INSERT INTO settlement_records (capacity_reservation_id, market, "
        "scheduling_requirements, settlement_resource_id, pool_id, provider, "
        "resource_attributes, prepared_create_operation, provider_metadata, "
        "state, attempt_count, created_at, updated_at) VALUES ('reservation-1', "
        "'vms', '{\"offering_mode\": \"vm\"}', 'kvm1', 'default', 'ansible', "
        ":attributes, :prepared, :metadata, 'active', 0, '2026-01-01', '2026-01-01')",
        attributes=json.dumps({"vm_host": "kvm1"}),
        prepared=json.dumps({
            "kind": "vm.ansible.create.v1",
            "schema_version": 1,
            "payload": {"parameters": {
                "vm_host": "kvm1",
                "vm_target": "t1",
                # Operator-supplied variables are never rewritten, whatever
                # their names.
                "provider_extra_vars": {"machine_id": "operator-value"},
            }},
        }),
        metadata=json.dumps({"vm_host": "kvm1", "vm_target": "t1"}),
    )
    _execute(
        engine,
        "INSERT INTO ansible_jobs (id, status, params, result, retry_count, "
        "max_retries, created_at, updated_at) VALUES ('job-1', 'succeeded', "
        ":params, :result, 0, 3, '2026-01-01', '2026-01-01')",
        params=json.dumps({"vm_host": "kvm1"}),
        result=json.dumps({"vm_host_ip": "203.0.113.9"}),
    )


def test_the_previous_schema_is_migrated_on_every_surface():
    engine = _previous_engine()
    _populate(engine)
    indexes_before = {
        index["name"] for index in inspect(engine).get_indexes("hosts")
    }

    apply_schema_migrations(engine)

    host_columns = {c["name"] for c in inspect(engine).get_columns("hosts")}
    assert {"host_id", "ssh_host"} <= host_columns
    assert not {"name", "kvm_host"} & host_columns
    # A column rename keeps the table's indexes.
    assert {i["name"] for i in inspect(engine).get_indexes("hosts")} == indexes_before
    assert "host_id" in {
        c["name"] for c in inspect(engine).get_columns("relay_port_leases")
    }
    assert count_rows_carrying_retired_host_keys(engine) == 0

    with engine.begin() as connection:
        buckets = {
            row[0]: (row[1], json.loads(row[2]))
            for row in connection.execute(text(
                "SELECT backing_resource_id, host_id, attributes FROM capacity_buckets"
            ))
        }
    assert buckets["vm-slice-1"] == ("kvm1", {"gpu_model": "H200"})
    assert buckets["bm-node-1"] == ("bm1", {
        "physical_host_id": "physical-1",
        "allocation_mode": "exclusive",
        "bare_metal_publication": {"enabled": True, "access_methods": ["ssh"]},
    })
    assert _json(engine, "SELECT executor_ref FROM capacity_reservations") == {
        "host_id": "kvm1"
    }
    assert _json(engine, "SELECT claim_attributes FROM capacity_reservations") == {
        "host_id": "kvm1", "region": "eu",
    }
    prepared = _json(engine, "SELECT prepared_create_operation FROM settlement_records")
    assert prepared["schema_version"] == 2
    assert prepared["payload"]["parameters"] == {
        "host_id": "kvm1",
        "vm_target": "t1",
        "provider_extra_vars": {"machine_id": "operator-value"},
    }
    assert _json(engine, "SELECT provider_metadata FROM settlement_records") == {
        "host_id": "kvm1", "vm_target": "t1",
    }
    with engine.begin() as connection:
        assert connection.execute(text(
            "SELECT resource_host_id, resource_attributes FROM settlement_records"
        )).one() == ("kvm1", "{}")
    assert _json(engine, "SELECT params FROM ansible_jobs") == {"host_id": "kvm1"}
    assert _json(engine, "SELECT result FROM ansible_jobs") == {"host_ip": "203.0.113.9"}


def test_the_retired_key_count_sees_every_unmigrated_row():
    engine = _previous_engine()
    _populate(engine)
    # Two declarations, one reservation, one settlement record, one job.
    assert count_rows_carrying_retired_host_keys(engine) == 5


@pytest.mark.parametrize(
    "attributes",
    [
        # The VM spelling and the bare-metal spelling name different hosts.
        {
            "vm_host": "kvm1",
            "bare_metal_publication": {"enabled": True, "machine_id": "bm1"},
        },
        # The cross-mode field disagrees between its two locations.
        {
            "physical_host_id": "physical-1",
            "bare_metal_publication": {
                "enabled": True,
                "machine_id": "bm1",
                "physical_host_id": "physical-2",
            },
        },
    ],
)
def test_an_inconsistent_row_leaves_the_database_exactly_as_it_was(attributes):
    engine = _previous_engine()
    _populate(engine)
    _bucket(engine, "b9", "conflicted", attributes)
    before = _snapshot(engine)

    with pytest.raises(HostIdentityMigrationError, match="conflicted"):
        apply_schema_migrations(engine)

    # Schema and rows alike: no column added, none renamed, nothing rewritten,
    # and the migration is not recorded, so the next attempt runs it again.
    assert _snapshot(engine) == before


def test_two_declarations_naming_one_host_leave_the_database_unchanged():
    engine = _previous_engine()
    _populate(engine)
    _bucket(engine, "b9", "second", {"vm_host": "kvm1"})
    before = _snapshot(engine)

    with pytest.raises(HostIdentityMigrationError, match="both name host 'kvm1'"):
        apply_schema_migrations(engine)

    assert _snapshot(engine) == before


def test_rerunning_the_migration_chain_changes_nothing():
    engine = _previous_engine()
    _populate(engine)
    apply_schema_migrations(engine)
    before = _snapshot(engine)

    apply_schema_migrations(engine)

    assert _snapshot(engine) == before
