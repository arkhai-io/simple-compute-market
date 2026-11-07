"""The migration dropping the host table's GPU columns, over file-backed SQLite.

A host describes no hardware, so ``hosts.gpu_count`` and ``hosts.gpu_model`` are
dropped by rebuilding the table from the model. These tests prove every other
column of every host survives, declarations are untouched, the foreign key
still holds, and a table already without the columns is left alone.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import (
    _migrate_hosts_drop_gpu_columns,
    apply_schema_migrations,
)

_MIGRATION_ID = "20261028_002_hosts_drop_gpu_columns"
_GPU_COLUMNS = {"gpu_count", "gpu_model"}

# The schema a database had after the migrations through 20260911_001, when
# every host carried a GPU count and model.
_PREVIOUS_SCHEMA = (
    Path(__file__).parents[1] / "unit" / "fixtures" / "schema_through_20260911_001.sql"
)

# kvm1's key is embedded: a stand-in ciphertext, not a real Fernet token, which
# the migration chain carries without decrypting.
_HOSTS = {
    "kvm1": {
        "kvm_host": "10.0.0.1", "gpu_count": 4, "gpu_model": "H200", "pool": "default",
        "key_type": "embedded", "key_value": "gAAAA-development-ciphertext", "enabled": 1,
    },
    "kvm2": {
        "kvm_host": "10.0.0.2", "gpu_count": 0, "gpu_model": None, "pool": "gpu-pool",
        "key_type": "path", "key_value": "/keys/id", "enabled": 0,
    },
}


def _engine(path: Path):
    return create_engine(f"sqlite:///{path}")


def _database_before_the_drop(tmp_path: Path):
    """A database whose hosts carry GPU values, at the step before the drop.

    The chain runs from an older schema, so its hosts and the declaration the
    upgrade derived from kvm1's GPU count are those a deployed database holds.
    The chain's own rebuild drops the GPU columns, so they are added back with
    ``ALTER TABLE`` and each host's values, and the drop's record removed: a
    reconstruction of the table a database upgraded through the previous
    release holds, with the same columns and rows but not its exact DDL.
    """
    engine = _engine(tmp_path / "provisioning.db")
    raw = engine.raw_connection()
    try:
        raw.driver_connection.executescript(_PREVIOUS_SCHEMA.read_text())
    finally:
        raw.close()
    with engine.begin() as connection:
        for pool_id in ("default", "gpu-pool"):
            connection.execute(
                text(
                    "INSERT INTO resource_pools (id, label, provider, enabled, policy_tags) "
                    "VALUES (:id, :id, 'vm.ansible', 1, '{}')"
                ),
                {"id": pool_id},
            )
        for name, host in _HOSTS.items():
            connection.execute(
                text(
                    "INSERT INTO hosts (name, kvm_host, ssh_user, ssh_key_type, "
                    "ssh_key_value, gpu_count, gpu_model, enabled, pool_id) VALUES "
                    "(:name, :kvm_host, 'root', :key_type, :key_value, :gpu_count, "
                    ":gpu_model, :enabled, :pool)"
                ),
                {"name": name, **host},
            )
    apply_schema_migrations(engine)

    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE hosts ADD COLUMN gpu_count INTEGER NOT NULL DEFAULT 0"
        ))
        connection.execute(text("ALTER TABLE hosts ADD COLUMN gpu_model VARCHAR"))
        for name, host in _HOSTS.items():
            connection.execute(
                text(
                    "UPDATE hosts SET gpu_count = :gpu_count, gpu_model = :gpu_model "
                    "WHERE host_id = :name"
                ),
                {"name": name, **host},
            )
        connection.execute(
            text("DELETE FROM schema_migrations WHERE id = :id"), {"id": _MIGRATION_ID}
        )
    return engine


def _host_columns(engine) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("hosts")}


def _rows(engine, table: str, key: str) -> dict[str, dict]:
    """Every column of every row, as stored."""
    with engine.begin() as connection:
        rows = connection.execute(
            text(f"SELECT * FROM {table} ORDER BY {key}")
        ).mappings().all()
    return {row[key]: dict(row) for row in rows}


def _table_identity(engine) -> tuple:
    """The table's page and DDL; a rebuild changes the page even when the
    columns and rows come out the same."""
    with engine.begin() as connection:
        return tuple(connection.execute(text(
            "SELECT rootpage, sql FROM sqlite_master WHERE type='table' AND name='hosts'"
        )).one())


def test_existing_hosts_keep_every_other_value_and_lose_their_gpu_columns(
    tmp_path, caplog
):
    engine = _database_before_the_drop(tmp_path)
    assert _GPU_COLUMNS <= _host_columns(engine)
    before = _rows(engine, "hosts", "host_id")
    assert {name: row["gpu_count"] for name, row in before.items()} == {"kvm1": 4, "kvm2": 0}

    caplog.clear()
    with caplog.at_level("DEBUG"):
        apply_schema_migrations(engine)

    # The discarded values were never sellable, so no host is logged.
    assert not [record for record in caplog.records if "kvm" in record.getMessage()]
    assert not _GPU_COLUMNS & _host_columns(engine)
    after = _rows(engine, "hosts", "host_id")
    assert after == {
        name: {column: value for column, value in row.items() if column not in _GPU_COLUMNS}
        for name, row in before.items()
    }
    # Identity, connection, the protected key's ciphertext, pool, enabled
    # state, and timestamps all come through the rebuild as stored.
    assert {name: (row["pool_id"], row["enabled"]) for name, row in after.items()} == {
        "kvm1": ("default", 1), "kvm2": ("gpu-pool", 0),
    }
    assert json.loads(after["kvm1"]["connection_protected"]) == {
        "private_key": {"scheme": "fernet-v1", "ciphertext": "gAAAA-development-ciphertext"}
    }
    assert all(row["created_at"] and row["updated_at"] for row in after.values())
    references = [
        (fk["referred_table"], fk["constrained_columns"])
        for fk in inspect(engine).get_foreign_keys("hosts")
    ]
    assert references == [("resource_pools", ["pool_id"])]
    with engine.begin() as connection:
        assert connection.execute(text("PRAGMA foreign_key_check")).fetchall() == []


def test_declarations_are_untouched_when_the_host_values_disagree(tmp_path):
    """The upgrade derived kvm1's declaration from its GPU count; an operator
    then declared it differently. Dropping the host's columns leaves the
    operator's declaration as it is."""
    engine = _database_before_the_drop(tmp_path)
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE capacity_buckets SET total_units = 2, "
            "capacity = '{\"gpu_count\": 2, \"vcpu_count\": 32}' WHERE host_id = 'kvm1'"
        ))
    declarations = _rows(engine, "capacity_buckets", "capacity_bucket_id")
    assert [row["host_id"] for row in declarations.values()] == ["kvm1"]

    apply_schema_migrations(engine)

    assert _rows(engine, "capacity_buckets", "capacity_bucket_id") == declarations


def test_a_fresh_database_has_no_gpu_column_and_the_drop_leaves_it_alone(tmp_path):
    engine = _engine(tmp_path / "provisioning.db")

    # The migration entrypoint, which creates the model's tables before the
    # versioned chain runs.
    run_migrations(engine)

    assert not _GPU_COLUMNS & _host_columns(engine)
    created = _table_identity(engine)
    _migrate_hosts_drop_gpu_columns(engine)
    assert _table_identity(engine) == created


def test_a_repeated_run_changes_nothing(tmp_path):
    engine = _database_before_the_drop(tmp_path)
    apply_schema_migrations(engine)
    rebuilt = _table_identity(engine)
    before = _rows(engine, "hosts", "host_id")

    _migrate_hosts_drop_gpu_columns(engine)
    apply_schema_migrations(engine)

    assert _table_identity(engine) == rebuilt
    assert _rows(engine, "hosts", "host_id") == before
