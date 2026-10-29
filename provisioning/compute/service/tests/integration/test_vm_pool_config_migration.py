"""The VM pool configuration migration, over file-backed SQLite.

A VM pool's ``playbook_path`` becomes nullable, so a pool may leave its playbook
to the service, and the unread ``inventory_group`` is dropped. SQLite cannot
relax ``NOT NULL`` in place, so the table is rebuilt; these tests prove the
rebuild keeps every row's other values, the foreign keys, and the relay index,
and that a table already in shape is left alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import (
    _migrate_vm_pool_playbook_optional,
    apply_schema_migrations,
)

# The schema a database had after the migrations through 20260911_001, when the
# pool configuration table still required a playbook and an inventory group.
_PREVIOUS_SCHEMA = (
    Path(__file__).parents[1] / "unit" / "fixtures" / "schema_through_20260911_001.sql"
)

_ROWS = {
    "pool-a": {
        "playbook_path": "/opt/playbooks/vm-a.yaml",
        "requirement_delegate": "vm_management_v1",
        "extra_vars": '{"region": "eu"}',
        "default_vm_ram": 4096,
        "default_vm_vcpus": 2,
        "default_vm_disk_size": "40G",
        "relay_id": "relay-1",
    },
    "pool-b": {
        "playbook_path": "/opt/playbooks/vm-b.yaml",
        "requirement_delegate": "vm_management_v1",
        "extra_vars": "{}",
        "default_vm_ram": None,
        "default_vm_vcpus": None,
        "default_vm_disk_size": None,
        "relay_id": None,
    },
}


def _engine(path: Path):
    return create_engine(f"sqlite:///{path}")


def _previous_database(tmp_path: Path):
    engine = _engine(tmp_path / "provisioning.db")
    raw = engine.raw_connection()
    try:
        raw.driver_connection.executescript(_PREVIOUS_SCHEMA.read_text())
    finally:
        raw.close()
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO relays (id, relay_addr, relay_port, vm_port_range_start, "
            "vm_port_range_count) VALUES ('relay-1', '203.0.113.9', 7000, 6100, 100)"
        ))
        for pool_id, row in _ROWS.items():
            connection.execute(
                text(
                    "INSERT INTO resource_pools (id, label, provider, enabled, policy_tags) "
                    "VALUES (:id, :id, 'vm.ansible', 1, '{}')"
                ),
                {"id": pool_id},
            )
            connection.execute(
                text(
                    "INSERT INTO ansible_pool_configs (pool_id, playbook_path, "
                    "requirement_delegate, inventory_group, extra_vars, default_vm_ram, "
                    "default_vm_vcpus, default_vm_disk_size, relay_id) VALUES (:pool_id, "
                    ":playbook_path, :requirement_delegate, 'kvm_hosts', :extra_vars, "
                    ":default_vm_ram, :default_vm_vcpus, :default_vm_disk_size, :relay_id)"
                ),
                {"pool_id": pool_id, **row},
            )
    return engine


def _columns(engine) -> dict[str, dict]:
    # Reflected types compare by identity, so each is kept as its rendering.
    return {
        c["name"]: {**c, "type": str(c["type"])}
        for c in inspect(engine).get_columns("ansible_pool_configs")
    }


def _rows(engine) -> dict[str, dict]:
    with engine.begin() as connection:
        rows = connection.execute(text(
            "SELECT pool_id, playbook_path, requirement_delegate, extra_vars, "
            "default_vm_ram, default_vm_vcpus, default_vm_disk_size, relay_id "
            "FROM ansible_pool_configs ORDER BY pool_id"
        )).mappings().all()
    return {row["pool_id"]: {k: v for k, v in row.items() if k != "pool_id"} for row in rows}


def _table_identity(engine) -> tuple:
    """The table's page and DDL; a rebuild changes the page even when the
    columns and rows come out the same."""
    with engine.begin() as connection:
        return tuple(connection.execute(text(
            "SELECT rootpage, sql FROM sqlite_master "
            "WHERE type='table' AND name='ansible_pool_configs'"
        )).one())


def _assert_current_shape(engine) -> None:
    columns = _columns(engine)
    assert columns["playbook_path"]["nullable"] is True
    assert "inventory_group" not in columns
    assert "ix_ansible_pool_configs_relay_id" in {
        index["name"] for index in inspect(engine).get_indexes("ansible_pool_configs")
    }
    references = {
        fk["referred_table"] for fk in inspect(engine).get_foreign_keys("ansible_pool_configs")
    }
    assert references == {"resource_pools", "relays"}


def _insert_unstated_playbook(engine, pool_id: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO resource_pools (id, label, provider, enabled, policy_tags) "
                "VALUES (:id, :id, 'vm.ansible', 1, '{}')"
            ),
            {"id": pool_id},
        )
        connection.execute(
            text(
                "INSERT INTO ansible_pool_configs (pool_id, playbook_path, extra_vars) "
                "VALUES (:id, NULL, '{}')"
            ),
            {"id": pool_id},
        )


def test_existing_rows_keep_every_value_as_the_table_is_relaxed(tmp_path):
    engine = _previous_database(tmp_path)
    assert _columns(engine)["playbook_path"]["nullable"] is False
    assert "inventory_group" in _columns(engine)
    previous = _table_identity(engine)

    apply_schema_migrations(engine)

    assert _table_identity(engine) != previous
    _assert_current_shape(engine)
    assert _rows(engine) == _ROWS
    _insert_unstated_playbook(engine, "pool-c")
    assert _rows(engine)["pool-c"]["playbook_path"] is None


def test_the_rebuilt_table_still_refuses_an_unknown_pool(tmp_path):
    engine = _previous_database(tmp_path)
    apply_schema_migrations(engine)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            connection.execute(text(
                "INSERT INTO ansible_pool_configs (pool_id, playbook_path, extra_vars) "
                "VALUES ('no-such-pool', NULL, '{}')"
            ))


def test_a_fresh_database_is_created_in_the_current_shape(tmp_path):
    engine = _engine(tmp_path / "provisioning.db")

    # The migration entrypoint, which creates the model's tables before the
    # versioned chain runs.
    run_migrations(engine)

    _assert_current_shape(engine)
    created = _table_identity(engine)
    _migrate_vm_pool_playbook_optional(engine)
    assert _table_identity(engine) == created
    _insert_unstated_playbook(engine, "pool-fresh")


def test_a_repeated_run_changes_nothing(tmp_path):
    engine = _previous_database(tmp_path)
    apply_schema_migrations(engine)
    rebuilt = _table_identity(engine)
    before = (_columns(engine), _rows(engine))

    _migrate_vm_pool_playbook_optional(engine)
    apply_schema_migrations(engine)

    assert _table_identity(engine) == rebuilt
    assert (_columns(engine), _rows(engine)) == before
    _assert_current_shape(engine)
