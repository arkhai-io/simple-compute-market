"""VM fulfillments and their create jobs are rewritten into the job-backed shapes."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning import JobExecutorTable
from compute_provisioning.job_fulfillment import delivery_evidence, job_contract
from compute_provisioning.jobs import JobRetryPolicy
from compute_provisioning.jobs.engine import JobEngine
from compute_provisioning.jobs.submission import JobSubmissionService
from compute_provisioning_contracts import CreateJobResult, ResultEnvelope
from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import (
    VmJobBackedMigrationError,
    _migrate_vm_job_backed_fulfillment,
)

# The parameters a VM create's dispatch submitted, as VM's prepared operation
# carried them (relay endpoint fields and executor fields not yet filled).
_PREPARED_PARAMS = {
    "host_id": "kvm1", "vm_action": "create", "offering_mode": "vm", "vm_target": "vm-1",
    "executor_action": None, "executor_target": None, "vm_ram": 2048, "relay_id": None,
    "vm_remote_port": None, "escrow_uid": "r-1", "playbook_path": "p.yaml",
    "provider_extra_vars": {},
}
# What the job authority stored for that dispatch.
_JOB_PARAMS = {
    **_PREPARED_PARAMS, "executor_action": "create", "executor_target": "vm-1",
    "relay_addr": None, "relay_port": None, "relay_token": None,
}
_RESULT = {
    "action": "create", "status": "running", "vm_name": "vm-1", "host": "kvm1",
    "timestamp": "2030-01-01T00:00:01Z", "tenant_user": "tenant1", "host_ip": "203.0.113.1",
    "ssh_port": "2222", "vm_ip_internal": "192.168.122.9", "ansible_result": {"raw": "x"},
}


def _engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    run_migrations(engine)
    return engine


def _record(engine, reservation, *, metadata, prepared=None, teardown_metadata=None, state="active"):
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO settlement_records (capacity_reservation_id, market, "
            "scheduling_requirements, provider, prepared_create_operation, "
            "provider_metadata, teardown_provider_metadata, state, attempt_count) VALUES "
            "(:id, 'vms', '{}', 'ansible', :prepared, :metadata, :teardown, :state, 0)"
        ), {
            "id": reservation,
            "prepared": json.dumps(prepared) if prepared else None,
            "metadata": json.dumps(metadata),
            "teardown": json.dumps(teardown_metadata) if teardown_metadata else None,
            "state": state,
        })


def _job(engine, job_id, *, reservation, params, result=None):
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO ansible_jobs (id, status, params, retry_count, max_retries, "
            "result, capacity_reservation_id, offering_mode, action_kind, executor_action, "
            "idempotency_key) VALUES (:id, 'succeeded', :params, 0, 3, :result, :reservation, "
            "'vm', 'create', 'create', :key)"
        ), {
            "id": job_id, "params": json.dumps(params), "reservation": reservation,
            "key": f"{reservation}:create",
            "result": json.dumps({
                "offering_mode": "vm", "result_kind": "vm_create", "value": result,
            }) if result is not None else None,
        })


def _prepared_create(reservation, params=_PREPARED_PARAMS):
    return {
        "kind": "vm.ansible.create.v1", "schema_version": 2,
        "payload": {"capacity_reservation_id": reservation, "action": "create",
                    "parameters": params},
    }


def _old_metadata(target="vm-1", **overrides):
    return {"create_job_id": "job-1", "current_job_id": "job-1", "host_id": "kvm1",
            "vm_target": target, "operation": "create", **overrides}


def _json(engine, sql, **params):
    with engine.connect() as connection:
        value = connection.execute(text(sql), params).scalar()
    return json.loads(value) if isinstance(value, str) else value


def test_an_active_vm_fulfillment_and_its_create_job_take_the_job_backed_shapes():
    engine = _engine()
    _record(
        engine, "r-1",
        metadata=_old_metadata(),
        prepared=_prepared_create("r-1"),
        teardown_metadata=_old_metadata(
            create_job_id="", current_job_id="job-2", teardown_job_id="job-2",
            operation="teardown",
        ),
    )
    _job(engine, "job-1", reservation="r-1", params=_JOB_PARAMS, result=_RESULT)

    _migrate_vm_job_backed_fulfillment(engine)

    metadata = _json(engine, "SELECT provider_metadata FROM settlement_records")
    assert metadata == {
        "create_job_id": "job-1", "teardown_job_id": None, "current_job_id": "job-1",
        "operation": "create", "host_id": "kvm1", "executor_target": "vm-1",
    }
    teardown = _json(engine, "SELECT teardown_provider_metadata FROM settlement_records")
    assert (teardown["create_job_id"], teardown["teardown_job_id"]) == ("job-1", "job-2")
    prepared = _json(engine, "SELECT prepared_create_operation FROM settlement_records")
    assert prepared["kind"] == "compute.job-fulfillment.operation"
    assert prepared["payload"]["parameters"] == _JOB_PARAMS
    assert (prepared["payload"]["action"], prepared["payload"]["executor_target"]) == (
        "create", "vm-1",
    )
    result = _json(engine, "SELECT result FROM ansible_jobs WHERE id = 'job-1'")
    assert result["result_kind"] == "compute.create-result.v1"
    created = CreateJobResult.model_validate(result["value"])
    (endpoint,) = created.evidence.endpoints
    assert (endpoint.host, endpoint.port, endpoint.user) == ("203.0.113.1", 2222, "tenant1")
    # Operator data is kept in the detail; the raw fact is not.
    assert created.detail["vm_ip_internal"] == "192.168.122.9"
    assert "ansible_result" not in created.detail


def _relayed_job(engine, reported: str) -> None:
    params = {**_JOB_PARAMS, "relay_id": "site-a", "vm_remote_port": 40001}
    _job(engine, "job-1", reservation="r-1", params=params, result={
        **_RESULT,
        "frp": {"enabled": "True", "relay_addr": "relay.example", "remote_port": reported},
    })


def _created(engine) -> CreateJobResult:
    return CreateJobResult.model_validate(
        _json(engine, "SELECT result FROM ansible_jobs WHERE id = 'job-1'")["value"]
    )


def test_a_relay_backed_create_is_reached_at_the_relay_and_its_leased_port():
    engine = _engine()
    _record(engine, "r-1", metadata=_old_metadata())
    _relayed_job(engine, "40001")

    _migrate_vm_job_backed_fulfillment(engine)

    (endpoint,) = _created(engine).evidence.endpoints
    assert (endpoint.host, endpoint.port) == ("relay.example", 40001)


def test_an_in_flight_create_reporting_another_relay_port_migrates_to_no_evidence():
    """It then fails as any unreadable create does."""
    engine = _engine()
    _record(engine, "r-1", state="dispatching", metadata=_old_metadata())
    _relayed_job(engine, "40002")

    _migrate_vm_job_backed_fulfillment(engine)

    assert _created(engine).evidence is None


@pytest.mark.parametrize(
    "case",
    ["relay-port-disagrees", "no-tenant-account", "no-result", "create-job-missing"],
)
def test_an_active_fulfillment_whose_delivery_would_be_unreadable_refuses_the_upgrade(case):
    """Its VM may be running: the upgrade stops rather than leave it active with
    a delivery no reader can produce, or fail it."""
    engine = _engine()
    _record(engine, "r-0", metadata=_old_metadata(create_job_id="job-0", current_job_id="job-0"),
            prepared=_prepared_create("r-0"))
    _job(engine, "job-0", reservation="r-0", params=_JOB_PARAMS, result=_RESULT)
    _record(engine, "r-1", metadata=_old_metadata())
    if case == "relay-port-disagrees":
        _relayed_job(engine, "40002")
    elif case == "no-tenant-account":
        _job(engine, "job-1", reservation="r-1", params=_JOB_PARAMS,
             result={**_RESULT, "tenant_user": None})
    elif case == "no-result":
        _job(engine, "job-1", reservation="r-1", params=_JOB_PARAMS)

    with pytest.raises(VmJobBackedMigrationError, match="is active"):
        _migrate_vm_job_backed_fulfillment(engine)

    # Nothing was written, the record that could be rewritten included.
    prepared = _json(
        engine, "SELECT prepared_create_operation FROM settlement_records "
        "WHERE capacity_reservation_id = 'r-0'"
    )
    assert prepared["kind"] == "vm.ansible.create.v1"
    assert _json(engine, "SELECT result FROM ansible_jobs WHERE id = 'job-0'")[
        "result_kind"
    ] == "vm_create"


def test_a_blank_target_is_taken_from_the_create_job():
    """A backfilled dispatching lease may have recorded no target."""
    engine = _engine()
    _record(engine, "r-1", state="dispatching", metadata={
        "create_job_id": "job-1", "teardown_job_id": None, "current_job_id": "job-1",
        "operation": "create", "host_id": "kvm1", "executor_target": "",
    })
    _job(engine, "job-1", reservation="r-1", params=_JOB_PARAMS)

    _migrate_vm_job_backed_fulfillment(engine)

    metadata = _json(engine, "SELECT provider_metadata FROM settlement_records")
    assert metadata["executor_target"] == "vm-1"


def test_a_record_naming_no_target_anywhere_aborts_the_whole_migration():
    engine = _engine()
    _record(engine, "r-0", metadata=_old_metadata(), prepared=_prepared_create("r-0"))
    _job(engine, "job-1", reservation="r-0", params=_JOB_PARAMS, result=_RESULT)
    _record(engine, "r-1", state="dispatching", metadata=_old_metadata(
        target="", create_job_id="job-missing", current_job_id="job-missing",
    ))

    with pytest.raises(VmJobBackedMigrationError, match="names no target"):
        _migrate_vm_job_backed_fulfillment(engine)

    # Nothing was written, the record that could be rewritten included.
    prepared = _json(
        engine, "SELECT prepared_create_operation FROM settlement_records "
        "WHERE capacity_reservation_id = 'r-0'"
    )
    assert prepared["kind"] == "vm.ansible.create.v1"


def _submission(engine) -> JobSubmissionService:
    return JobSubmissionService(
        engine=JobEngine(
            sessionmaker(bind=engine),
            executors=JobExecutorTable(),
            host_lookup=lambda host_id: None,
            retry_policy=JobRetryPolicy(),
        ),
        hosts=SimpleNamespace(get_host=lambda host_id: SimpleNamespace(enabled=True)),
        job_queue_provider=lambda: None,
    )


def _redispatch(engine, prepared):
    return asyncio.run(_submission(engine).submit(
        offering_mode="vm",
        action=prepared["payload"]["action"],
        host_id=prepared["payload"]["host_id"],
        params=prepared["payload"]["parameters"],
        contract=job_contract("r-1", "create", "vm"),
    ))


def test_a_dispatch_pending_create_with_no_job_keeps_its_prepared_parameters():
    engine = _engine()
    _record(engine, "r-1", state="dispatch_pending", metadata={},
            prepared=_prepared_create("r-1"))

    _migrate_vm_job_backed_fulfillment(engine)

    prepared = _json(engine, "SELECT prepared_create_operation FROM settlement_records")
    assert prepared["payload"]["parameters"] == _JOB_PARAMS
    assert _json(engine, "SELECT provider_metadata FROM settlement_records") == {}


@pytest.mark.parametrize("result", [None, _RESULT], ids=["queued", "succeeded"])
def test_an_unrecorded_create_job_is_found_by_its_contract_and_redispatch_finds_it(result):
    """Dispatch submitted the job, which may even have finished, but crashed
    before recording it: the migration finds it as a retried dispatch does,
    and converts its result, and the retry then names that job."""
    engine = _engine()
    _record(engine, "r-1", state="dispatch_pending", metadata={},
            prepared=_prepared_create("r-1"))
    _job(engine, "job-old", reservation="r-1", params=_JOB_PARAMS, result=result)

    _migrate_vm_job_backed_fulfillment(engine)

    assert _json(engine, "SELECT provider_metadata FROM settlement_records") == {}
    prepared = _json(engine, "SELECT prepared_create_operation FROM settlement_records")
    assert _redispatch(engine, prepared).job_id == "job-old"
    stored = _json(engine, "SELECT result FROM ansible_jobs WHERE id = 'job-old'")
    if result is None:
        assert stored is None
    else:
        job = SimpleNamespace(job_id="job-old", result=ResultEnvelope.model_validate(stored))
        (endpoint,) = delivery_evidence(job).endpoints
        assert (endpoint.host, endpoint.port) == ("203.0.113.1", 2222)


def test_a_dispatching_create_with_metadata_is_rewritten():
    engine = _engine()
    _record(engine, "r-1", state="dispatching", metadata=_old_metadata(),
            prepared=_prepared_create("r-1"))
    _job(engine, "job-1", reservation="r-1", params=_JOB_PARAMS)

    _migrate_vm_job_backed_fulfillment(engine)

    metadata = _json(engine, "SELECT provider_metadata FROM settlement_records")
    assert (metadata["create_job_id"], metadata["executor_target"]) == ("job-1", "vm-1")


def test_a_teardown_side_row_keeps_its_prepared_teardown_in_the_family_shape():
    engine = _engine()
    _record(engine, "r-1", state="teardown_dispatch_pending", metadata=_old_metadata())
    _job(engine, "job-1", reservation="r-1", params=_JOB_PARAMS, result=_RESULT)
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE settlement_records SET prepared_teardown_operation = :prepared"
        ), {"prepared": json.dumps({
            "kind": "vm.ansible.teardown.v1", "schema_version": 2,
            "payload": {"capacity_reservation_id": "r-1", "action": "teardown",
                        "parameters": {**_PREPARED_PARAMS, "vm_action": "vm_remove"}},
        })})

    _migrate_vm_job_backed_fulfillment(engine)

    teardown = _json(engine, "SELECT prepared_teardown_operation FROM settlement_records")
    assert teardown["kind"] == "compute.job-fulfillment.operation"
    assert teardown["payload"]["operation"] == "teardown"
    assert teardown["payload"]["create_job_id"] == "job-1"
    assert teardown["payload"]["action"] == "vm_remove"


def test_a_second_run_changes_nothing():
    engine = _engine()
    _record(engine, "r-1", metadata=_old_metadata(), prepared=_prepared_create("r-1"))
    _job(engine, "job-1", reservation="r-1", params=_JOB_PARAMS, result=_RESULT)
    _migrate_vm_job_backed_fulfillment(engine)
    with engine.connect() as connection:
        before = connection.execute(text(
            "SELECT * FROM settlement_records")).all(), connection.execute(text(
            "SELECT result FROM ansible_jobs")).all()

    _migrate_vm_job_backed_fulfillment(engine)

    with engine.connect() as connection:
        after = connection.execute(text(
            "SELECT * FROM settlement_records")).all(), connection.execute(text(
            "SELECT result FROM ansible_jobs")).all()
    assert after == before
