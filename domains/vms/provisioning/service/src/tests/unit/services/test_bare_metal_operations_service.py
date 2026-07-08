from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from arkhai_bare_metal import (
    BareMetalLeaseCreate,
    NODE_GRANT_ACCESS_ACTION,
    NODE_RECLAIM_ACCESS_ACTION,
    bare_metal_executor_ref,
)
from provisioning_client.models import JobSubmitResponse

from services.bare_metal_operations_service import (
    BareMetalHostValidationError,
    BareMetalOperationsService,
)


@pytest.mark.asyncio
async def test_grant_access_submits_node_grant_job():
    queue = object()
    job_service = MagicMock()
    job_service.submit = AsyncMock(
        return_value=JobSubmitResponse(job_id="grant-1", status="queued"),
    )
    service = BareMetalOperationsService(
        job_service=job_service,
        job_queue_provider=lambda: queue,
        host_service=MagicMock(
            get_host=MagicMock(return_value=SimpleNamespace(enabled=True)),
        ),
    )

    response = await service.grant_access(
        BareMetalLeaseCreate(
            escrow_uid="0xbm",
            machine_id="bm-node-1",
            physical_host_id="host-physical-1",
            lease_end_utc=datetime(2099, 1, 1, tzinfo=timezone.utc),
            access_ref={
                "ssh_user": "tenant-a",
                "ssh_public_key": "ssh-ed25519 AAAA tenant-a",
            },
        ),
    )

    assert response.job_id == "grant-1"
    params, submitted_queue = job_service.submit.await_args.args
    assert submitted_queue is queue
    assert params.vm_host == "bm-node-1"
    assert params.vm_target == "bm-node-1"
    assert params.vm_action == NODE_GRANT_ACCESS_ACTION
    assert params.executor_kind == "bare_metal"
    assert params.executor_action == NODE_GRANT_ACCESS_ACTION
    assert params.executor_target == "bm-node-1"
    assert params.executor_ref == {
        "physical_host_id": "host-physical-1",
        "ssh_user": "tenant-a",
        "ssh_public_key": "ssh-ed25519 AAAA tenant-a",
    }
    assert params.escrow_uid == "0xbm"
    assert params.physical_host_id == "host-physical-1"
    assert params.ssh_user == "tenant-a"
    assert params.ssh_public_key == "ssh-ed25519 AAAA tenant-a"


@pytest.mark.asyncio
async def test_reclaim_access_submits_node_reclaim_job_from_allocation():
    queue = object()
    job_service = MagicMock()
    job_service.submit = AsyncMock(
        return_value=JobSubmitResponse(job_id="reclaim-1", status="queued"),
    )
    service = BareMetalOperationsService(
        job_service=job_service,
        job_queue_provider=lambda: queue,
        settings=MagicMock(bare_metal_reclaim_policy="lock_user"),
        host_service=MagicMock(
            get_host=MagicMock(return_value=SimpleNamespace(enabled=True)),
        ),
    )

    job_id = await service.reclaim_access_for_allocation({
        "escrow_uid": "0xbm",
        "executor_target": "bm-node-1",
        "executor_ref": bare_metal_executor_ref(
            "host-physical-1",
            access_ref={
                "ssh_user": "tenant-a",
                "ssh_public_key": "ssh-ed25519 AAAA tenant-a",
            },
        ),
    })

    assert job_id == "reclaim-1"
    params, submitted_queue = job_service.submit.await_args.args
    assert submitted_queue is queue
    assert params.vm_host == "bm-node-1"
    assert params.vm_target == "bm-node-1"
    assert params.vm_action == NODE_RECLAIM_ACCESS_ACTION
    assert params.executor_kind == "bare_metal"
    assert params.executor_action == NODE_RECLAIM_ACCESS_ACTION
    assert params.executor_target == "bm-node-1"
    assert params.executor_ref == {
        "physical_host_id": "host-physical-1",
        "ssh_user": "tenant-a",
        "ssh_public_key": "ssh-ed25519 AAAA tenant-a",
    }
    assert params.escrow_uid == "0xbm"
    assert params.physical_host_id == "host-physical-1"
    assert params.ssh_user == "tenant-a"
    assert params.ssh_public_key == "ssh-ed25519 AAAA tenant-a"
    assert params.bare_metal_reclaim_policy == "lock_user"


@pytest.mark.asyncio
async def test_reclaim_access_without_machine_id_returns_none():
    job_service = MagicMock()
    job_service.submit = AsyncMock()
    service = BareMetalOperationsService(
        job_service=job_service,
        job_queue_provider=lambda: object(),
    )

    assert await service.reclaim_access_for_allocation({}) is None
    job_service.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_grant_access_unknown_machine_raises_without_submitting_job():
    job_service = MagicMock()
    job_service.submit = AsyncMock()
    service = BareMetalOperationsService(
        job_service=job_service,
        job_queue_provider=lambda: object(),
        host_service=MagicMock(get_host=MagicMock(return_value=None)),
    )

    with pytest.raises(BareMetalHostValidationError) as exc_info:
        await service.grant_access(
            BareMetalLeaseCreate(
                escrow_uid="0xbm",
                machine_id="missing-node",
                physical_host_id="host-physical-1",
                lease_end_utc=datetime(2099, 1, 1, tzinfo=timezone.utc),
            ),
        )

    assert exc_info.value.status_code == 404
    job_service.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_grant_access_disabled_machine_raises_without_submitting_job():
    job_service = MagicMock()
    job_service.submit = AsyncMock()
    service = BareMetalOperationsService(
        job_service=job_service,
        job_queue_provider=lambda: object(),
        host_service=MagicMock(
            get_host=MagicMock(return_value=SimpleNamespace(enabled=False)),
        ),
    )

    with pytest.raises(BareMetalHostValidationError) as exc_info:
        await service.grant_access(
            BareMetalLeaseCreate(
                escrow_uid="0xbm",
                machine_id="disabled-node",
                physical_host_id="host-physical-1",
                lease_end_utc=datetime(2099, 1, 1, tzinfo=timezone.utc),
            ),
        )

    assert exc_info.value.status_code == 409
    job_service.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_reclaim_access_for_unknown_machine_returns_none_without_submitting_job():
    job_service = MagicMock()
    job_service.submit = AsyncMock()
    service = BareMetalOperationsService(
        job_service=job_service,
        job_queue_provider=lambda: object(),
        host_service=MagicMock(get_host=MagicMock(return_value=None)),
    )

    result = await service.reclaim_access_for_allocation({
        "executor_target": "missing-node",
        "executor_ref": {"physical_host_id": "host-physical-1"},
    })

    assert result is None
    job_service.submit.assert_not_awaited()
