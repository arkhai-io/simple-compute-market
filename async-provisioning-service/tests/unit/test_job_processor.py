from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.orm import sessionmaker

from async_provisioning_service.db.models import JobStatus, ProvisioningJob
from async_provisioning_service.services import job_processor
from async_provisioning_service.services.provisioning import PlaybookError, ProvisioningResult


def test_normalize_utc_datetime_assumes_utc_for_naive_input():
    naive = datetime(2026, 3, 20, 12, 0, 0)

    normalized = job_processor._normalize_utc_datetime(naive)

    assert normalized.tzinfo == timezone.utc
    assert normalized.isoformat() == "2026-03-20T12:00:00+00:00"


def test_normalize_utc_datetime_preserves_aware_input():
    aware = datetime(2026, 3, 20, 5, 0, 0, tzinfo=timezone.utc)

    normalized = job_processor._normalize_utc_datetime(aware)

    assert normalized is aware


def test_process_job_accepts_timezone_aware_next_retry_at(db_session, monkeypatch):
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=db_session.bind,
    )
    monkeypatch.setattr(job_processor, "SessionLocal", session_factory)

    enqueue_job = AsyncMock()
    monkeypatch.setattr(job_processor, "enqueue_job", enqueue_job)

    job = ProvisioningJob(
        id="job-aware",
        status=JobStatus.queued.value,
        params={"vm_host": "ww1", "vm_action": "check"},
        next_retry_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    db_session.add(job)
    db_session.commit()

    asyncio.run(job_processor._process_job(job.id))

    enqueue_job.assert_awaited_once_with(job.id)


def test_process_job_cleans_up_stale_vm_before_retrying_create(db_session, monkeypatch):
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=db_session.bind,
    )
    monkeypatch.setattr(job_processor, "SessionLocal", session_factory)

    enqueue_job = AsyncMock()
    monkeypatch.setattr(job_processor, "enqueue_job", enqueue_job)

    stale_logs = (
        "TASK [Fail if VM already exists] ********************************\n"
        "fatal: [btc1]: FAILED! => \n"
        "    msg: VM 'tenant-f8a2' already exists on host 'btc1'. Use a different name\n"
    )

    start_playbook = AsyncMock(
        side_effect=[
            SimpleNamespace(process_id=1111),
            SimpleNamespace(process_id=2222),
            SimpleNamespace(process_id=3333),
        ]
    )
    wait_for_playbook = AsyncMock(
        side_effect=[
            PlaybookError("Playbook failed", stale_logs, ""),
            object(),
            object(),
        ]
    )
    monkeypatch.setattr(job_processor, "start_playbook", start_playbook)
    monkeypatch.setattr(job_processor, "wait_for_playbook", wait_for_playbook)

    job = ProvisioningJob(
        id="job-stale-create",
        status=JobStatus.queued.value,
        params={
            "vm_host": "btc1",
            "vm_action": "create",
            "vm_target": "tenant-f8a2",
            "ssh_pubkey": "ssh-ed25519 AAAA stale",
        },
        retry_count=0,
        max_retries=3,
    )
    db_session.add(job)
    db_session.commit()

    asyncio.run(job_processor._process_job(job.id))

    create_params = start_playbook.await_args_list[0].args[0]
    destroy_params = start_playbook.await_args_list[1].args[0]
    cleanup_params = start_playbook.await_args_list[2].args[0]

    assert create_params.vm_action == "create"
    assert create_params.vm_target == "tenant-f8a2"
    assert destroy_params.vm_action == "destroy"
    assert destroy_params.vm_target == "tenant-f8a2"
    assert cleanup_params.vm_action == "undefine"
    assert cleanup_params.vm_target == "tenant-f8a2"
    enqueue_job.assert_awaited_once_with(job.id)

    db_session.expire_all()
    refreshed = db_session.query(ProvisioningJob).filter_by(id=job.id).one()
    assert refreshed.status == JobStatus.queued.value
    assert refreshed.retry_count == 1
    assert "Attempt 1 failed: Playbook failed" in refreshed.error


def test_process_job_cleans_up_stale_vm_before_running_retry_attempt(db_session, monkeypatch):
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=db_session.bind,
    )
    monkeypatch.setattr(job_processor, "SessionLocal", session_factory)

    cleanup = AsyncMock()
    monkeypatch.setattr(job_processor, "_cleanup_stale_vm_before_retry", cleanup)

    enqueue_job = AsyncMock()
    monkeypatch.setattr(job_processor, "enqueue_job", enqueue_job)

    start_playbook = AsyncMock(return_value=SimpleNamespace(process_id=1111))
    wait_for_playbook = AsyncMock(
        return_value=ProvisioningResult(
            stdout="ok",
            stderr="",
            ssh_port=None,
            tenant_user=None,
            vm_host_ip=None,
            ssh_command=None,
            ansible_result=None,
            process_id=1111,
        )
    )
    monkeypatch.setattr(job_processor, "start_playbook", start_playbook)
    monkeypatch.setattr(job_processor, "wait_for_playbook", wait_for_playbook)

    stale_logs = "msg: VM 'tenant-f8a2' already exists on host 'btc1'. Use a different name"
    job = ProvisioningJob(
        id="job-retry-cleanup",
        status=JobStatus.queued.value,
        params={
            "vm_host": "btc1",
            "vm_action": "create",
            "vm_target": "tenant-f8a2",
        },
        retry_count=1,
        max_retries=3,
        logs=stale_logs,
    )
    db_session.add(job)
    db_session.commit()

    asyncio.run(job_processor._process_job(job.id))

    cleanup.assert_awaited_once()
    cleanup_params = cleanup.await_args.args[0]
    cleanup_logs = cleanup.await_args.args[1]
    assert cleanup_params.vm_target == "tenant-f8a2"
    assert cleanup_logs == stale_logs


def test_cleanup_stale_vm_attempts_destroy_before_undefine(monkeypatch):
    params = job_processor.ProvisioningParams(
        vm_host="btc1",
        vm_target="tenant-63b9",
        vm_action="create",
    )
    stale_logs = "msg: VM 'tenant-63b9' already exists on host 'btc1'. Use a different name"

    start_playbook = AsyncMock(
        side_effect=[
            SimpleNamespace(process_id=1111),
            SimpleNamespace(process_id=2222),
        ]
    )
    wait_for_playbook = AsyncMock(side_effect=[object(), object()])
    monkeypatch.setattr(job_processor, "start_playbook", start_playbook)
    monkeypatch.setattr(job_processor, "wait_for_playbook", wait_for_playbook)

    asyncio.run(job_processor._cleanup_stale_vm_before_retry(params, stale_logs))

    attempted_actions = [call.args[0].vm_action for call in start_playbook.await_args_list]
    assert attempted_actions == ["destroy", "undefine"]


def test_cleanup_stale_vm_continues_when_destroy_reports_not_running(monkeypatch):
    params = job_processor.ProvisioningParams(
        vm_host="btc1",
        vm_target="tenant-63b9",
        vm_action="create",
    )
    stale_logs = "msg: VM 'tenant-63b9' already exists on host 'btc1'. Use a different name"

    start_playbook = AsyncMock(
        side_effect=[
            SimpleNamespace(process_id=1111),
            SimpleNamespace(process_id=2222),
        ]
    )
    wait_for_playbook = AsyncMock(
        side_effect=[
            PlaybookError("Playbook failed", "", "Domain is not running"),
            object(),
        ]
    )
    monkeypatch.setattr(job_processor, "start_playbook", start_playbook)
    monkeypatch.setattr(job_processor, "wait_for_playbook", wait_for_playbook)

    asyncio.run(job_processor._cleanup_stale_vm_before_retry(params, stale_logs))

    attempted_actions = [call.args[0].vm_action for call in start_playbook.await_args_list]
    assert attempted_actions == ["destroy", "undefine"]
