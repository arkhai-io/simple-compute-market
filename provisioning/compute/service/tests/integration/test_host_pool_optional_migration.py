"""The host placement migration, over file-backed SQLite.

A host's pool becomes optional, so ``hosts.pool_id`` loses its ``NOT NULL`` and
its ``'default'`` default. SQLite cannot relax a column in place, so the table is
rebuilt; these tests prove the rebuild keeps every host's pool and other values
and its foreign key, and that a table already in shape is left alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import (
    _migrate_hosts_pool_optional,
    apply_schema_migrations,
)

# The schema a database had after the migrations through 20260911_001, when a
# host's pool was required and defaulted to 'default'.
_PREVIOUS_SCHEMA = (
    Path(__file__).parents[1] / "unit" / "fixtures" / "schema_through_20260911_001.sql"
)

# kvm1's key is embedded: a stand-in ciphertext, not a real Fernet token, which
# the migration chain carries without decrypting.
_HOSTS = {
    "kvm1": {
        "kvm_host": "10.0.0.1", "gpu_count": 4, "gpu_model": "H200", "pool": "default",
        "key_type": "embedded", "key_value": "gAAAA-development-ciphertext",
    },
    "kvm2": {
        "kvm_host": "10.0.0.2", "gpu_count": 0, "gpu_model": None, "pool": "gpu-pool",
        "key_type": "path", "key_value": "/keys/id",
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
                    ":gpu_model, 1, :pool)"
                ),
                {"name": name, **host},
            )
    return engine


def _pool_column(engine) -> dict:
    (column,) = [c for c in inspect(engine).get_columns("hosts") if c["name"] == "pool_id"]
    return column


def _rows(engine) -> dict[str, dict]:
    """Every column of every host, as stored."""
    with engine.begin() as connection:
        rows = connection.execute(text("SELECT * FROM hosts ORDER BY host_id")).mappings().all()
    return {row["host_id"]: dict(row) for row in rows}


def _table_identity(engine) -> tuple:
    """The table's page and DDL; a rebuild changes the page even when the
    columns and rows come out the same."""
    with engine.begin() as connection:
        return tuple(connection.execute(text(
            "SELECT rootpage, sql FROM sqlite_master WHERE type='table' AND name='hosts'"
        )).one())


def _assert_current_shape(engine) -> None:
    column = _pool_column(engine)
    assert column["nullable"] is True
    assert column["default"] is None
    references = [
        (fk["referred_table"], fk["constrained_columns"])
        for fk in inspect(engine).get_foreign_keys("hosts")
    ]
    assert references == [("resource_pools", ["pool_id"])]


def _insert_unplaced(engine, host_id: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO hosts (host_id, connection_kind, connection_version, "
                "connection_public, connection_protected, gpu_count, enabled) "
                "VALUES (:id, 'ssh', 1, '{}', '{}', 0, 1)"
            ),
            {"id": host_id},
        )


def test_existing_hosts_keep_their_pools_and_every_value_as_the_column_is_relaxed(tmp_path):
    engine = _previous_database(tmp_path)
    assert _pool_column(engine)["nullable"] is False

    # The chain from there, so the table this migration meets is the one a
    # deployed database holds.
    apply_schema_migrations(engine)

    _assert_current_shape(engine)
    rows = _rows(engine)
    assert {host: row["pool_id"] for host, row in rows.items()} == {
        "kvm1": "default", "kvm2": "gpu-pool",
    }
    for name, host in _HOSTS.items():
        row = rows[name]
        assert (row["gpu_count"], row["gpu_model"]) == (host["gpu_count"], host["gpu_model"])
        assert json.loads(row["connection_public"])["ssh_host"] == host["kvm_host"]
    # An embedded key, protected at rest, comes through the chain and the
    # rebuild as the stored ciphertext.
    assert json.loads(rows["kvm1"]["connection_protected"]) == {
        "private_key": {"scheme": "fernet-v1", "ciphertext": "gAAAA-development-ciphertext"}
    }
    _insert_unplaced(engine, "kvm3")
    assert _rows(engine)["kvm3"]["pool_id"] is None


def test_a_rebuild_keeps_every_column_of_every_row_and_passes_the_foreign_key_check(tmp_path):
    engine = _previous_database(tmp_path)
    apply_schema_migrations(engine)
    # Put the table back in the required, defaulted shape an older database
    # holds, with every row this chain wrote.
    with engine.begin() as connection:
        ddl = connection.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='hosts'"
        )).scalar_one()
    restored = ddl.replace("pool_id VARCHAR", "pool_id VARCHAR DEFAULT 'default' NOT NULL", 1)
    assert restored != ddl
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE hosts RENAME TO hosts_previous"))
        connection.execute(text(restored))
        connection.execute(text("INSERT INTO hosts SELECT * FROM hosts_previous"))
        connection.execute(text("DROP TABLE hosts_previous"))
    assert _pool_column(engine)["nullable"] is False
    before = _rows(engine)
    previous = _table_identity(engine)

    _migrate_hosts_pool_optional(engine)

    assert _table_identity(engine) != previous
    _assert_current_shape(engine)
    assert _rows(engine) == before
    with engine.begin() as connection:
        assert connection.execute(text("PRAGMA foreign_key_check")).fetchall() == []


def test_the_rebuilt_table_still_refuses_an_unknown_pool(tmp_path):
    engine = _previous_database(tmp_path)
    apply_schema_migrations(engine)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            connection.execute(text(
                "INSERT INTO hosts (host_id, connection_kind, connection_version, "
                "connection_public, connection_protected, gpu_count, enabled, pool_id) "
                "VALUES ('kvm9', 'ssh', 1, '{}', '{}', 0, 1, 'no-such-pool')"
            ))


def test_a_fresh_database_is_created_in_the_current_shape(tmp_path):
    engine = _engine(tmp_path / "provisioning.db")

    # The migration entrypoint, which creates the model's tables before the
    # versioned chain runs.
    run_migrations(engine)

    _assert_current_shape(engine)
    created = _table_identity(engine)
    _migrate_hosts_pool_optional(engine)
    assert _table_identity(engine) == created
    _insert_unplaced(engine, "kvm-fresh")


def test_a_repeated_run_changes_nothing(tmp_path):
    engine = _previous_database(tmp_path)
    apply_schema_migrations(engine)
    rebuilt = _table_identity(engine)
    before = _rows(engine)

    _migrate_hosts_pool_optional(engine)
    apply_schema_migrations(engine)

    assert _table_identity(engine) == rebuilt
    assert _rows(engine) == before
    _assert_current_shape(engine)
