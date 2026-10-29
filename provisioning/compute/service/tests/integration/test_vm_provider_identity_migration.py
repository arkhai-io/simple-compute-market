"""VM identity upgrades preserve pool configuration and accepted work in SQLite."""

from __future__ import annotations

import json

from sqlalchemy import create_engine, text

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import (
    _migrate_vm_provider_identity,
    check_schema_version,
)

from .legacy_default_pool import add_legacy_default_pool


def _rows(engine, table, key):
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(
            text(f"SELECT * FROM {table} ORDER BY {key}")
        ).mappings()]


def test_vm_identity_migration_changes_only_provider_names_and_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'provisioning.db'}")
    run_migrations(engine)
    add_legacy_default_pool(engine, playbook_path="/configured/vm.yaml")
    operation = json.dumps({
        "kind": "vm.ansible.create.v1", "version": 1,
        "payload": {"parameters": {"executor_target": "guest-1"}},
    }, separators=(",", ":"))
    with engine.begin() as connection:
        connection.execute(text("UPDATE resource_pools SET provider='ansible'"))
        connection.execute(text(
            "INSERT INTO resource_pools (id, label, provider, enabled, policy_tags) "
            "VALUES ('bare-metal', 'Bare metal', 'bare_metal.ansible', 1, '{}')"
        ))
        # The documentation address is deterministic test data, never a host
        # to contact on a public network.
        connection.execute(text(
            "INSERT INTO hosts (host_id, connection_kind, connection_version, "
            "connection_public, connection_protected, enabled, pool_id) "
            "VALUES ('host-1', 'ssh', 1, :public, '{}', 1, 'default')"
        ), {"public": json.dumps({"ssh_host": "203.0.113.10", "ssh_user": "stub"})})
        for identifier, provider in (("vm", "ansible"), ("bare-metal", "bare_metal.ansible")):
            connection.execute(text(
                "INSERT INTO settlement_records (capacity_reservation_id, fulfillment_id, "
                "market, scheduling_requirements, provider, provider_metadata, "
                "pool_id, state, attempt_count, prepared_create_operation) "
                "VALUES (:id, :fulfillment, :market, '{}', :provider, :metadata, "
                ":pool, 'active', 2, :operation)"
            ), {
                "id": identifier, "fulfillment": f"fulfillment-{identifier}",
                "market": "vms" if identifier == "vm" else "bare_metal",
                "provider": provider, "metadata": '{"current_job_id":"job-1"}',
                "pool": "default" if identifier == "vm" else "bare-metal",
                "operation": operation,
            })
        connection.execute(text(
            "DELETE FROM schema_migrations WHERE id='20261019_001_vm_provider_identity'"
        ))
    tables = {
        "resource_pools": "id", "settlement_records": "capacity_reservation_id",
        "ansible_pool_configs": "pool_id", "hosts": "host_id",
    }
    before = {table: _rows(engine, table, key) for table, key in tables.items()}

    run_migrations(engine)
    check_schema_version(engine)

    after = {table: _rows(engine, table, key) for table, key in tables.items()}
    expected = {
        table: [
            {**row, "provider": "vm.ansible"} if row.get("provider") == "ansible" else row
            for row in rows
        ] for table, rows in before.items()
    }
    assert after == expected
    _migrate_vm_provider_identity(engine)
    run_migrations(engine)
    assert {table: _rows(engine, table, key) for table, key in tables.items()} == after
