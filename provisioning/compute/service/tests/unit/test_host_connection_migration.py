"""Hosts' SSH columns become a connection envelope, in one forward migration."""

from __future__ import annotations

import json

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import _migrate_host_connection_envelope

_LEGACY = (
    "ssh_host", "public_host", "ssh_user", "ssh_port", "ssh_key_type", "ssh_key_value",
)


def _engine():
    return create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )


def _legacy_hosts(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE hosts (host_id VARCHAR PRIMARY KEY, ssh_host VARCHAR NOT NULL, "
            "public_host VARCHAR, ssh_user VARCHAR NOT NULL, "
            "ssh_port INTEGER NOT NULL DEFAULT 22, ssh_key_type VARCHAR NOT NULL, "
            "ssh_key_value VARCHAR NOT NULL, gpu_count INTEGER NOT NULL, gpu_model VARCHAR, "
            "enabled BOOLEAN NOT NULL, pool_id VARCHAR NOT NULL DEFAULT 'default')"
        ))
        connection.execute(text(
            "INSERT INTO hosts VALUES ('kvm1', '10.0.0.1', '203.0.113.1', 'root', 2201, "
            "'path', '/keys/id', 2, 'H100', 1, 'gpu'), "
            "('bm1', '10.0.1.1', NULL, 'ops', 22, 'embedded', 'gAAAAA-ciphertext', 0, "
            "NULL, 0, 'default')"
        ))


def _rows(engine) -> dict[str, dict]:
    with engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT host_id, connection_kind, connection_version, connection_public, "
            "connection_protected, gpu_count, gpu_model, enabled, pool_id FROM hosts"
        )).mappings().all()
    return {row["host_id"]: dict(row) for row in rows}


def _columns(engine) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("hosts")}


def test_legacy_rows_become_ssh_connections_with_their_ciphertext_untouched() -> None:
    engine = _engine()
    _legacy_hosts(engine)

    _migrate_host_connection_envelope(engine)

    rows = _rows(engine)
    kvm1, bm1 = rows["kvm1"], rows["bm1"]
    assert (kvm1["connection_kind"], kvm1["connection_version"]) == ("ssh", 1)
    assert json.loads(kvm1["connection_public"]) == {
        "ssh_host": "10.0.0.1",
        "public_host": "203.0.113.1",
        "ssh_port": 2201,
        "ssh_user": "root",
        "key_path": "/keys/id",
    }
    assert json.loads(kvm1["connection_protected"]) == {}
    assert json.loads(bm1["connection_public"])["key_path"] is None
    assert json.loads(bm1["connection_protected"]) == {
        "private_key": {"scheme": "fernet-v1", "ciphertext": "gAAAAA-ciphertext"}
    }
    assert (kvm1["gpu_count"], kvm1["gpu_model"], kvm1["pool_id"]) == (2, "H100", "gpu")
    assert not bm1["enabled"]
    assert not _columns(engine) & set(_LEGACY)


def test_running_it_again_changes_nothing() -> None:
    engine = _engine()
    _legacy_hosts(engine)
    _migrate_host_connection_envelope(engine)
    before = _rows(engine)

    _migrate_host_connection_envelope(engine)

    assert _rows(engine) == before


def test_a_fresh_database_ends_with_only_the_envelope_columns() -> None:
    engine = _engine()

    run_migrations(
        engine,
        default_playbook_path="/configured/playbook.yaml",
        default_inventory_group="kvm_hosts",
    )

    columns = _columns(engine)
    assert {"connection_kind", "connection_public", "connection_protected"} <= columns
    assert not columns & set(_LEGACY)
    # Rebuilding the table to drop the SSH columns keeps its pool reference.
    assert [
        (fk["referred_table"], fk["constrained_columns"])
        for fk in inspect(engine).get_foreign_keys("hosts")
    ] == [("resource_pools", ["pool_id"])]
    with engine.connect() as connection:
        applied = {
            row[0] for row in connection.execute(text("SELECT id FROM schema_migrations"))
        }
    assert "20261002_001_host_connection_envelope" in applied
