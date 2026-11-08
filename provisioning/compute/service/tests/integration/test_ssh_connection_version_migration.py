"""The migration rewriting stored ``ssh`` version-1 connections to version 2, over
file-backed SQLite.

A host stored at version 1 runs no work, since the ``ssh`` codec serves version 2
alone. These tests prove each such host is rewritten with its public fields and
protected values exactly as stored, that the jobs naming it read the rewritten
connection, that a connection version 2 refuses fails the migration naming its
host with nothing rewritten, and that a rerun changes nothing.

Addresses are RFC 5737 documentation values, and the ciphertext is a stand-in,
not a real Fernet token: fixture values that must never be used on a public
network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from compute_provisioning.hosts.db import Host
from compute_provisioning_ansible import SshConnectionCodec
from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import (
    SchemaDriftError,
    apply_schema_migrations,
)

_MIGRATION_ID = "20261108_001_ssh_connections_version_2"

# kvm1's key is protected, as the envelope migration carried an embedded key;
# bm1's is a key file. Both are stored as the envelope migration wrote them,
# with an explicit null public_host and key_path.
_HOSTS = {
    "kvm1": {
        "public": {
            "ssh_host": "192.0.2.10",
            "public_host": "203.0.113.10",
            "ssh_port": 2201,
            "ssh_user": "root",
            "key_path": None,
        },
        "protected": {
            "private_key": {"scheme": "fernet-v1", "ciphertext": "gAAAA-development-ciphertext"}
        },
    },
    "bm1": {
        "public": {
            "ssh_host": "192.0.2.20",
            "public_host": None,
            "ssh_port": 22,
            "ssh_user": "ops",
            "key_path": "/keys/id_ed25519",
        },
        "protected": {},
    },
}

# A queued create on kvm1 and a teardown on bm1 waiting for its retry: jobs
# not yet finished, each naming its host.
_JOBS = {
    "job-create": {"host_id": "kvm1", "status": "queued", "action": "create"},
    "job-teardown": {"host_id": "bm1", "status": "queued", "action": "destroy"},
}


def _engine(path: Path):
    return create_engine(f"sqlite:///{path}")


def _database_before_the_rewrite(tmp_path: Path, hosts=_HOSTS):
    """A migrated database whose hosts are stored at version 1, with the
    rewrite's record removed, as a database the previous release migrated
    holds them."""
    engine = _engine(tmp_path / "provisioning.db")
    run_migrations(engine)
    with engine.begin() as connection:
        for host_id, host in hosts.items():
            connection.execute(
                text(
                    "INSERT INTO hosts (host_id, connection_kind, connection_version, "
                    "connection_public, connection_protected, enabled) VALUES "
                    "(:host_id, 'ssh', 1, :public, :protected, 1)"
                ),
                {
                    "host_id": host_id,
                    "public": json.dumps(host["public"]),
                    "protected": json.dumps(host["protected"]),
                },
            )
        for job_id, job in _JOBS.items():
            if job["host_id"] not in hosts:
                continue
            connection.execute(
                text(
                    "INSERT INTO ansible_jobs (id, status, params, host_id, retry_count, "
                    "max_retries, offering_mode, action_kind, executor_action) VALUES "
                    "(:id, :status, :params, :host_id, 0, 3, 'vm', :action, :action)"
                ),
                {
                    "id": job_id,
                    "status": job["status"],
                    "params": json.dumps({"vm_target": f"guest-{job_id}"}),
                    "host_id": job["host_id"],
                    "action": job["action"],
                },
            )
        connection.execute(
            text("DELETE FROM schema_migrations WHERE id = :id"), {"id": _MIGRATION_ID}
        )
    return engine


def _rows(engine, table: str, key: str) -> dict[str, dict]:
    with engine.begin() as connection:
        rows = connection.execute(
            text(f"SELECT * FROM {table} ORDER BY {key}")
        ).mappings().all()
    return {row[key]: dict(row) for row in rows}


def _recorded(engine) -> bool:
    with engine.begin() as connection:
        return connection.execute(
            text("SELECT 1 FROM schema_migrations WHERE id = :id"), {"id": _MIGRATION_ID}
        ).first() is not None


def test_version_1_hosts_are_rewritten_with_their_fields_and_ciphertext_as_stored(tmp_path):
    engine = _database_before_the_rewrite(tmp_path)
    hosts_before = _rows(engine, "hosts", "host_id")
    jobs_before = _rows(engine, "ansible_jobs", "id")

    apply_schema_migrations(engine)

    hosts_after = _rows(engine, "hosts", "host_id")
    assert {host_id: row["connection_version"] for host_id, row in hosts_after.items()} == {
        "bm1": 2, "kvm1": 2,
    }
    # Only the version changes: the public fields and the protected key's
    # ciphertext are the stored bytes, and every other column is untouched.
    assert hosts_after == {
        host_id: {**row, "connection_version": 2} for host_id, row in hosts_before.items()
    }
    assert json.loads(hosts_after["kvm1"]["connection_protected"]) == _HOSTS["kvm1"]["protected"]
    assert _recorded(engine)

    # The unfinished jobs hold no connection of their own: their rows are
    # unchanged, and the host each names now reads at the served version.
    assert _rows(engine, "ansible_jobs", "id") == jobs_before
    with sessionmaker(bind=engine)() as db:
        for job_id, job in _JOBS.items():
            connection = db.get(Host, job["host_id"]).connection()
            parsed = SshConnectionCodec.parse(connection)
            assert parsed.ssh_host == _HOSTS[job["host_id"]]["public"]["ssh_host"], job_id
            assert connection.protected_schemes() == {
                name: value["scheme"]
                for name, value in _HOSTS[job["host_id"]]["protected"].items()
            }


def test_a_connection_version_2_refuses_fails_naming_its_host_and_nothing_is_rewritten(
    tmp_path,
):
    """A quoted port is the wrong type at version 2, whose codec validates
    strictly; kvm1 stays at version 1 beside it, though kvm1 alone is valid."""
    hosts = {
        **_HOSTS,
        "bad1": {
            "public": {"ssh_host": "192.0.2.30", "ssh_port": "2222", "key_path": "/keys/id"},
            "protected": {},
        },
    }
    engine = _database_before_the_rewrite(tmp_path, hosts)
    before = _rows(engine, "hosts", "host_id")

    with pytest.raises(SchemaDriftError) as refused:
        apply_schema_migrations(engine)

    assert "'bad1'" in str(refused.value)
    assert "ssh_port" in str(refused.value)
    assert "'kvm1'" not in str(refused.value)
    assert _rows(engine, "hosts", "host_id") == before
    assert not _recorded(engine)


def test_a_host_naming_no_usable_key_fails_naming_it(tmp_path):
    """Version 2 needs exactly one of key_path and a protected private_key."""
    hosts = {
        "keyless": {
            "public": {"ssh_host": "192.0.2.40", "key_path": None},
            "protected": {},
        },
    }
    engine = _database_before_the_rewrite(tmp_path, hosts)

    with pytest.raises(SchemaDriftError, match="'keyless'"):
        apply_schema_migrations(engine)

    assert _rows(engine, "hosts", "host_id")["keyless"]["connection_version"] == 1


def test_a_rerun_changes_nothing(tmp_path):
    engine = _database_before_the_rewrite(tmp_path)
    apply_schema_migrations(engine)
    hosts = _rows(engine, "hosts", "host_id")
    jobs = _rows(engine, "ansible_jobs", "id")

    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM schema_migrations WHERE id = :id"), {"id": _MIGRATION_ID}
        )
    apply_schema_migrations(engine)

    assert _rows(engine, "hosts", "host_id") == hosts
    assert _rows(engine, "ansible_jobs", "id") == jobs
    assert _recorded(engine)
