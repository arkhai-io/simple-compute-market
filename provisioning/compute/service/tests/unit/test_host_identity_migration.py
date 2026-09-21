"""The host-identity migration: one name for the host on every persisted surface.

Each test builds a database at the current schema, writes rows in the shapes
that existed before the host had one name, and runs the migration directly.
Starting from the current schema rather than replaying every historical
migration keeps each case about this migration's own rewrite.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import (
    HostIdentityMigrationError,
    _migrate_host_identity,
    count_rows_carrying_retired_host_keys,
)

_PLAYBOOK_PATH = "/opt/playbooks/vm-operations.yaml"
_INVENTORY_GROUP = "kvm_hosts"


def _engine():
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
    return engine


def _bucket(engine, resource_id, attributes, *, host_id=None):
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO capacity_buckets (capacity_bucket_id, backing_resource_id, "
                "pool_id, resource_type, total_units, capacity, attributes, enabled, "
                "host_id) VALUES (:id, :rid, 'default', 'compute.gpu', 1, "
                "'{\"gpu_count\": 1}', :attributes, 1, :host_id)"
            ),
            {
                "id": f"bucket-{resource_id}",
                "rid": resource_id,
                "attributes": json.dumps(attributes),
                "host_id": host_id,
            },
        )


def _reservation(engine, reservation_id, executor_ref, claim_attributes=None):
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO capacity_reservations (capacity_reservation_id, units, "
                "state, executor_ref, claim_attributes) "
                "VALUES (:id, 1, 'leased', :ref, :claim)"
            ),
            {
                "id": reservation_id,
                "ref": json.dumps(executor_ref),
                "claim": json.dumps(claim_attributes) if claim_attributes else None,
            },
        )


def _settlement_record(engine, reservation_id, *, attributes, prepared, metadata):
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO settlement_records (capacity_reservation_id, market, "
                "scheduling_requirements, settlement_resource_id, pool_id, provider, "
                "resource_attributes, prepared_create_operation, provider_metadata, "
                "state, attempt_count) VALUES (:id, 'vms', "
                "'{\"offering_mode\": \"vm\"}', 'kvm1', 'default', 'ansible', "
                ":attributes, :prepared, :metadata, 'active', 0)"
            ),
            {
                "id": reservation_id,
                "attributes": json.dumps(attributes),
                "prepared": json.dumps(prepared),
                "metadata": json.dumps(metadata),
            },
        )


def _job(engine, job_id, params, result):
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ansible_jobs (id, status, params, result, retry_count, "
                "max_retries) VALUES (:id, 'succeeded', :params, :result, 0, 3)"
            ),
            {"id": job_id, "params": json.dumps(params), "result": json.dumps(result)},
        )


def _json(engine, sql, **params):
    with engine.begin() as connection:
        value = connection.execute(text(sql), params).scalar_one()
    return json.loads(value) if isinstance(value, str) else value


def _populate_retired_shapes(engine):
    _bucket(engine, "vm-slice-1", {"vm_host": "kvm1", "gpu_model": "H200"})
    _bucket(
        engine,
        "bm-node-1",
        {
            "bare_metal_publication": {
                "enabled": True,
                "machine_id": "bm1",
                "physical_host_id": "physical-1",
                "allocation_mode": "exclusive",
                "access_methods": ["ssh"],
            },
        },
    )
    _reservation(
        engine,
        "reservation-1",
        {"vm_host": "kvm1"},
        claim_attributes={"vm_host": "kvm1", "region": "eu"},
    )
    _settlement_record(
        engine,
        "reservation-1",
        attributes={"vm_host": "kvm1"},
        prepared={
            "kind": "vm.ansible.create.v1",
            "schema_version": 1,
            "payload": {"parameters": {"vm_host": "kvm1", "vm_target": "t1"}},
        },
        metadata={"vm_host": "kvm1", "vm_target": "t1", "create_job_id": "job-1"},
    )
    _job(engine, "job-1", {"vm_host": "kvm1"}, {"vm_host_ip": "203.0.113.9"})


def test_every_surface_names_the_host_host_id():
    engine = _engine()
    _populate_retired_shapes(engine)
    assert count_rows_carrying_retired_host_keys(engine) == 5

    _migrate_host_identity(engine)

    assert count_rows_carrying_retired_host_keys(engine) == 0
    with engine.begin() as connection:
        buckets = {
            row[0]: (row[1], json.loads(row[2]))
            for row in connection.execute(text(
                "SELECT backing_resource_id, host_id, attributes FROM capacity_buckets"
            ))
        }
    assert buckets["vm-slice-1"] == ("kvm1", {"gpu_model": "H200"})
    bm_host, bm_attributes = buckets["bm-node-1"]
    assert bm_host == "bm1"
    # Cross-mode fields have one location: the top level the ledger reads.
    assert bm_attributes == {
        "physical_host_id": "physical-1",
        "allocation_mode": "exclusive",
        "bare_metal_publication": {"enabled": True, "access_methods": ["ssh"]},
    }

    assert _json(
        engine,
        "SELECT executor_ref FROM capacity_reservations WHERE capacity_reservation_id='reservation-1'",
    ) == {"host_id": "kvm1"}
    assert _json(
        engine,
        "SELECT claim_attributes FROM capacity_reservations WHERE capacity_reservation_id='reservation-1'",
    ) == {"host_id": "kvm1", "region": "eu"}

    prepared = _json(
        engine,
        "SELECT prepared_create_operation FROM settlement_records",
    )
    assert prepared["schema_version"] == 2
    assert prepared["payload"]["parameters"] == {"host_id": "kvm1", "vm_target": "t1"}
    assert _json(engine, "SELECT provider_metadata FROM settlement_records")["host_id"] == "kvm1"
    with engine.begin() as connection:
        record = connection.execute(text(
            "SELECT resource_host_id, resource_attributes FROM settlement_records"
        )).one()
    assert record[0] == "kvm1"
    assert json.loads(record[1]) == {}
    assert _json(engine, "SELECT params FROM ansible_jobs") == {"host_id": "kvm1"}
    assert _json(engine, "SELECT result FROM ansible_jobs") == {"host_ip": "203.0.113.9"}


def test_rerunning_changes_nothing():
    engine = _engine()
    _populate_retired_shapes(engine)
    _migrate_host_identity(engine)
    with engine.begin() as connection:
        before = connection.execute(text(
            "SELECT backing_resource_id, host_id, attributes FROM capacity_buckets "
            "ORDER BY backing_resource_id"
        )).all()

    _migrate_host_identity(engine)

    with engine.begin() as connection:
        after = connection.execute(text(
            "SELECT backing_resource_id, host_id, attributes FROM capacity_buckets "
            "ORDER BY backing_resource_id"
        )).all()
    assert after == before


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
def test_an_inconsistent_row_aborts_with_nothing_written(attributes):
    engine = _engine()
    _bucket(engine, "clean", {"vm_host": "kvm9"})
    _bucket(engine, "conflicted", attributes)

    with pytest.raises(HostIdentityMigrationError, match="conflicted"):
        _migrate_host_identity(engine)

    # The clean row is not half-migrated: the whole migration rolled back.
    assert _json(
        engine,
        "SELECT attributes FROM capacity_buckets WHERE backing_resource_id='clean'",
    ) == {"vm_host": "kvm9"}


def test_two_declarations_naming_one_host_abort():
    engine = _engine()
    _bucket(engine, "first", {"vm_host": "kvm1"})
    _bucket(engine, "second", {"vm_host": "kvm1"})

    with pytest.raises(HostIdentityMigrationError, match="both name host 'kvm1'"):
        _migrate_host_identity(engine)


def test_the_host_registry_columns_are_renamed_on_an_old_table():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE hosts (name VARCHAR PRIMARY KEY, kvm_host VARCHAR NOT NULL)"
        ))
        connection.execute(text(
            "INSERT INTO hosts (name, kvm_host) VALUES ('kvm1', '10.0.0.1')"
        ))

    _migrate_host_identity(engine)

    columns = {c["name"] for c in inspect(engine).get_columns("hosts")}
    assert {"host_id", "ssh_host"} <= columns
    assert not {"name", "kvm_host"} & columns
    with engine.begin() as connection:
        assert connection.execute(text(
            "SELECT host_id, ssh_host FROM hosts"
        )).one() == ("kvm1", "10.0.0.1")
