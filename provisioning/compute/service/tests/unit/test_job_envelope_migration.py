"""Jobs' results and credentials become envelopes, with neutral routing columns."""

from __future__ import annotations

import json

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.migrations import _migrate_job_envelopes


def _engine():
    return create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )


def _legacy(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE ansible_jobs (id VARCHAR PRIMARY KEY, status VARCHAR NOT NULL, "
            "params JSON NOT NULL, result JSON, logs TEXT, error TEXT, process_id VARCHAR, "
            "retry_count INTEGER NOT NULL DEFAULT 0, max_retries INTEGER NOT NULL DEFAULT 3, "
            "offering_mode VARCHAR, action_kind VARCHAR)"
        ))
        connection.execute(text(
            "CREATE TABLE credentials (id VARCHAR PRIMARY KEY, job_id VARCHAR NOT NULL "
            "REFERENCES ansible_jobs (id), role VARCHAR NOT NULL, password VARCHAR, "
            "ssh_commands JSON, ssh_key_path_host VARCHAR, key_type VARCHAR, "
            "created_at DATETIME)"
        ))
        jobs = [
            ("vm-1", {"offering_mode": "vm", "vm_action": "create", "host_id": "kvm1"},
             {"host_ip": "203.0.113.9"}, "4242", "vm", "create"),
            ("bm-1", {"offering_mode": "bare_metal", "executor_target": "bm-node-1",
                      "executor_action": "node_grant_access"},
             {"action": "node_grant_access"}, '{"pid": 7}', "bare_metal", "node_grant_access"),
            ("old-1", {"vm_target": "t1"}, None, None, None, None),
            ("bare-1", {"offering_mode": "vm"}, None, None, "vm", "destroy"),
            ("down-1", {"offering_mode": "vm", "vm_action": "destroy", "host_id": "kvm1"},
             {"vm_name": "t1"}, None, "vm", "teardown"),
        ]
        for job_id, params, result, pid, mode, action in jobs:
            connection.execute(
                text(
                    "INSERT INTO ansible_jobs (id, status, params, result, process_id, "
                    "offering_mode, action_kind) VALUES (:id, 'succeeded', :params, "
                    ":result, :pid, :mode, :action)"
                ),
                {
                    "id": job_id,
                    "params": json.dumps(params),
                    "result": json.dumps(result) if result is not None else None,
                    "pid": pid,
                    "mode": mode,
                    "action": action,
                },
            )
        connection.execute(text(
            "INSERT INTO credentials (id, job_id, role, password, ssh_commands, "
            "ssh_key_path_host, key_type) VALUES "
            "('c1', 'vm-1', 'tenant', 'pw', '{\"external\": \"ssh -p 2222\"}', NULL, 'ed25519'), "
            "('c2', 'vm-1', 'root', 'rootpw', NULL, '/root/key', NULL)"
        ))


def _jobs(engine) -> dict[str, dict]:
    with engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT id, host_id, execution_handle, result FROM ansible_jobs"
        )).mappings().all()
    decode = lambda value: json.loads(value) if value is not None else None  # noqa: E731
    return {
        row["id"]: {
            "host_id": row["host_id"],
            "handle": decode(row["execution_handle"]),
            "result": decode(row["result"]),
        }
        for row in rows
    }


def _credentials(engine) -> dict[str, dict]:
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, envelope FROM credentials")).all()
    return {row[0]: json.loads(row[1]) for row in rows}


def test_results_and_handles_convert_and_hosts_are_recorded() -> None:
    engine = _engine()
    _legacy(engine)

    _migrate_job_envelopes(engine, default_host_id="kvm-default")

    jobs = _jobs(engine)
    assert jobs["vm-1"] == {
        "host_id": "kvm1",
        "handle": {"pid": 4242},
        "result": {
            "offering_mode": "vm",
            "result_kind": "vm_create",
            "value": {"host_ip": "203.0.113.9"},
        },
    }
    assert jobs["bm-1"]["host_id"] == "bm-node-1"
    assert jobs["bm-1"]["handle"] == {"pid": 7}
    assert jobs["bm-1"]["result"]["result_kind"] == "bare_metal_access"
    assert jobs["old-1"] == {"host_id": "t1", "handle": None, "result": None}
    with engine.connect() as connection:
        route = connection.execute(text(
            "SELECT offering_mode, action_kind, executor_action FROM ansible_jobs "
            "WHERE id = 'old-1'"
        )).one()
    assert tuple(route) == ("vm", "create", "create")
    assert jobs["bare-1"]["host_id"] == "kvm-default"
    # A contract action keeps its identity; the job is routed, and its result
    # labelled, by the action its executor ran.
    assert jobs["down-1"]["result"]["result_kind"] == "vm_destroy"
    with engine.connect() as connection:
        route = connection.execute(text(
            "SELECT action_kind, executor_action FROM ansible_jobs WHERE id = 'down-1'"
        )).one()
    assert tuple(route) == ("teardown", "destroy")


def test_credentials_become_the_envelopes_the_contract_route_served() -> None:
    engine = _engine()
    _legacy(engine)

    _migrate_job_envelopes(engine)

    assert _credentials(engine) == {
        "c1": {
            "offering_mode": "vm",
            "credential_kind": "tenant",
            "value": {
                "password": "pw",
                "ssh_commands": {"external": "ssh -p 2222"},
                "key_type": "ed25519",
            },
        },
        "c2": {
            "offering_mode": "vm",
            "credential_kind": "root",
            "value": {"password": "rootpw", "ssh_key_path_host": "/root/key"},
        },
    }
    credential_columns = {c["name"] for c in inspect(engine).get_columns("credentials")}
    assert not credential_columns & {"role", "password", "ssh_commands", "key_type"}
    assert "process_id" not in {c["name"] for c in inspect(engine).get_columns("ansible_jobs")}
    assert [fk["referred_table"] for fk in inspect(engine).get_foreign_keys("credentials")] == [
        "ansible_jobs"
    ]


def test_running_it_again_changes_nothing() -> None:
    engine = _engine()
    _legacy(engine)
    _migrate_job_envelopes(engine, default_host_id="kvm-default")
    before = (_jobs(engine), _credentials(engine))

    _migrate_job_envelopes(engine, default_host_id="kvm-default")

    assert (_jobs(engine), _credentials(engine)) == before
