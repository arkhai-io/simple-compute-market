"""Bare-metal jobs' stored parameters and results take bare metal's own shape."""

from __future__ import annotations

import json

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from bare_metal_provisioning_adapter.codec import BareMetalJobParams
from compute_provisioning_service.db.migrations import _migrate_bare_metal_job_shapes

# A grant as the VM job parameters stored it: bare-metal fields filled, VM ones empty.
_VM_SHAPED_GRANT = {
    "host_id": "bm-node-1",
    "vm_target": "bm-node-1",
    "vm_action": "node_grant_access",
    "offering_mode": "bare_metal",
    "executor_action": "node_grant_access",
    "executor_target": "bm-node-1",
    "executor_ref": {"physical_host_id": "p-1"},
    "image_setup_type": "scratch",
    "vm_ram": None,
    "escrow_uid": "0xbm",
    "physical_host_id": "p-1",
    "ssh_user": "tenant-a",
    "ssh_public_key": "ssh-ed25519 AAAA tenant-a",
    "access_ref": {"ssh_user": "tenant-a"},
    "bare_metal_reclaim_policy": None,
    "provider_extra_vars": {},
}
_FACT = {"action": "node_grant_access", "host": "10.0.0.5", "port": "22", "ssh_user": "tenant-a"}


def _envelope(value: dict) -> dict:
    return {
        "offering_mode": "bare_metal",
        "result_kind": "bare_metal_access",
        "schema_version": 1,
        "value": value,
    }


def _engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE ansible_jobs (id VARCHAR PRIMARY KEY, offering_mode VARCHAR, "
            "params JSON NOT NULL, result JSON)"
        ))
        rows = [
            ("grant", "bare_metal", _VM_SHAPED_GRANT,
             _envelope({"tenant_user": None, "ansible_result": _FACT})),
            ("reclaim", "bare_metal",
             {**_VM_SHAPED_GRANT, "vm_action": "node_reclaim_access",
              "executor_action": "node_reclaim_access",
              "bare_metal_reclaim_policy": "lock_user"},
             _envelope({"ssh_port": None, "ansible_result": None})),
            ("vm", "vm", {"offering_mode": "vm", "vm_action": "create", "host_id": "kvm1"},
             {**_envelope({"ansible_result": {"action": "create"}}), "offering_mode": "vm"}),
        ]
        for job_id, mode, params, result in rows:
            connection.execute(
                text(
                    "INSERT INTO ansible_jobs (id, offering_mode, params, result) "
                    "VALUES (:id, :mode, :params, :result)"
                ),
                {"id": job_id, "mode": mode, "params": json.dumps(params),
                 "result": json.dumps(result)},
            )
    return engine


def _rows(engine) -> dict[str, tuple[dict, dict | None]]:
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, params, result FROM ansible_jobs")).all()
    return {
        row[0]: (json.loads(row[1]), json.loads(row[2]) if row[2] is not None else None)
        for row in rows
    }


def test_bare_metal_parameters_become_the_bare_metal_model() -> None:
    engine = _engine()

    _migrate_bare_metal_job_shapes(engine)

    grant, _ = _rows(engine)["grant"]
    reclaim, _ = _rows(engine)["reclaim"]
    # What the bare-metal codec reads back, with nothing left over.
    assert BareMetalJobParams.model_validate(grant).action == "node_grant_access"
    assert grant["ssh_public_key"] == "ssh-ed25519 AAAA tenant-a"
    assert grant["reclaim_policy"] is None
    assert BareMetalJobParams.model_validate(reclaim).reclaim_policy == "lock_user"


def test_a_bare_metal_result_becomes_its_access_fact() -> None:
    engine = _engine()

    _migrate_bare_metal_job_shapes(engine)

    _, grant_result = _rows(engine)["grant"]
    _, reclaim_result = _rows(engine)["reclaim"]
    assert grant_result == _envelope(_FACT)
    # A result that carried no fact reported nothing; it is removed.
    assert reclaim_result is None


def test_vm_jobs_are_untouched_and_a_rerun_changes_nothing() -> None:
    engine = _engine()
    before = _rows(engine)["vm"]

    _migrate_bare_metal_job_shapes(engine)
    once = _rows(engine)
    _migrate_bare_metal_job_shapes(engine)

    assert once["vm"] == before
    assert _rows(engine) == once
