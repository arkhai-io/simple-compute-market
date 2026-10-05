"""Bare-metal access jobs are submitted to the job authority in bare metal's shape."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from arkhai_bare_metal import (
    BareMetalAccessGrant,
    NODE_GRANT_ACCESS_ACTION,
    NODE_RECLAIM_ACCESS_ACTION,
    bare_metal_executor_ref,
)
from compute_provisioning_contracts import JobSubmitResponse

from bare_metal_provisioning_adapter.services.bare_metal_operations_service import (
    BareMetalHostValidationError,
    BareMetalOperationsService,
)


@pytest.mark.asyncio
async def test_grant_access_submits_node_grant_job():
    queue = object()
    jobs = MagicMock()
    jobs.submit = AsyncMock(
        return_value=JobSubmitResponse(job_id="grant-1", status="queued"),
    )
    service = BareMetalOperationsService(
        jobs=jobs,
        job_queue_provider=lambda: queue,
        host_service=MagicMock(
            get_host=MagicMock(return_value=SimpleNamespace(enabled=True)),
        ),
    )

    response = await service.grant_access(
        BareMetalAccessGrant(
            escrow_uid="0xbm",
            host_id="bm-node-1",
            physical_host_id="host-physical-1",
            lease_end_utc=datetime(2099, 1, 1, tzinfo=timezone.utc),
            access_ref={
                "ssh_user": "tenant-a",
                "ssh_public_key": "ssh-ed25519 AAAA tenant-a",
            },
        ),
    )

    assert response.job_id == "grant-1"
    submitted = jobs.submit.await_args.kwargs
    assert submitted["job_queue"] is queue
    assert (submitted["offering_mode"], submitted["action"], submitted["host_id"]) == (
        "bare_metal", NODE_GRANT_ACCESS_ACTION, "bm-node-1",
    )
    assert submitted["escrow_uid"] == "0xbm"
    assert submitted["params"] == {
        "action": NODE_GRANT_ACCESS_ACTION,
        "host_id": "bm-node-1",
        "physical_host_id": "host-physical-1",
        "escrow_uid": "0xbm",
        "executor_ref": {
            "physical_host_id": "host-physical-1",
            "ssh_user": "tenant-a",
            "ssh_public_key": "ssh-ed25519 AAAA tenant-a",
        },
        "access_ref": {
            "ssh_user": "tenant-a",
            "ssh_public_key": "ssh-ed25519 AAAA tenant-a",
        },
        "ssh_user": "tenant-a",
        "ssh_public_key": "ssh-ed25519 AAAA tenant-a",
        "reclaim_policy": None,
    }


@pytest.mark.asyncio
async def test_reclaim_access_reclaims_exactly_what_the_grant_gave():
    queue = object()
    jobs = MagicMock()
    jobs.submit = AsyncMock(
        return_value=JobSubmitResponse(job_id="reclaim-1", status="queued"),
    )
    service = BareMetalOperationsService(
        jobs=jobs,
        job_queue_provider=lambda: queue,
        reclaim_policy="lock_user",
        host_service=MagicMock(
            get_host=MagicMock(return_value=SimpleNamespace(enabled=True)),
        ),
    )

    response = await service.reclaim_access(
        BareMetalAccessGrant(
            capacity_reservation_id="reservation-1",
            escrow_uid="0xbm",
            host_id="bm-node-1",
            physical_host_id="host-physical-1",
            lease_end_utc=datetime(2099, 1, 1, tzinfo=timezone.utc),
            access_ref={
                "ssh_user": "tenant-a",
                "ssh_public_key": "ssh-ed25519 AAAA tenant-a",
            },
        )
    )

    assert response.job_id == "reclaim-1"
    submitted = jobs.submit.await_args.kwargs
    assert submitted["job_queue"] is queue
    assert (submitted["offering_mode"], submitted["action"], submitted["host_id"]) == (
        "bare_metal", NODE_RECLAIM_ACCESS_ACTION, "bm-node-1",
    )
    params = submitted["params"]
    assert params["action"] == NODE_RECLAIM_ACCESS_ACTION
    assert params["physical_host_id"] == "host-physical-1"
    assert params["executor_ref"] == bare_metal_executor_ref(
        "host-physical-1",
        access_ref={"ssh_user": "tenant-a", "ssh_public_key": "ssh-ed25519 AAAA tenant-a"},
    )
    assert params["ssh_user"] == "tenant-a"
    assert params["ssh_public_key"] == "ssh-ed25519 AAAA tenant-a"
    assert params["reclaim_policy"] == "lock_user"
    assert not any(name.startswith("vm_") for name in params)


def test_an_unset_reclaim_policy_is_the_default_and_an_unknown_one_is_refused():
    service = BareMetalOperationsService(
        jobs=MagicMock(), job_queue_provider=lambda: object(), host_service=MagicMock()
    )
    assert service._reclaim_policy == "remove_lease_key"
    with pytest.raises(ValueError, match="Invalid bare_metal_reclaim_policy"):
        BareMetalOperationsService(
            jobs=MagicMock(),
            job_queue_provider=lambda: object(),
            host_service=MagicMock(),
            reclaim_policy="wipe_disk",
        )


@pytest.mark.asyncio
async def test_grant_access_unknown_machine_raises_without_submitting_job():
    jobs = MagicMock()
    jobs.submit = AsyncMock()
    service = BareMetalOperationsService(
        jobs=jobs,
        job_queue_provider=lambda: object(),
        host_service=MagicMock(get_host=MagicMock(return_value=None)),
    )

    with pytest.raises(BareMetalHostValidationError) as exc_info:
        await service.grant_access(
            BareMetalAccessGrant(
                escrow_uid="0xbm",
                host_id="missing-node",
                physical_host_id="host-physical-1",
                lease_end_utc=datetime(2099, 1, 1, tzinfo=timezone.utc),
            ),
        )

    assert exc_info.value.status_code == 404
    jobs.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_grant_access_disabled_machine_raises_without_submitting_job():
    jobs = MagicMock()
    jobs.submit = AsyncMock()
    service = BareMetalOperationsService(
        jobs=jobs,
        job_queue_provider=lambda: object(),
        host_service=MagicMock(
            get_host=MagicMock(return_value=SimpleNamespace(enabled=False)),
        ),
    )

    with pytest.raises(BareMetalHostValidationError) as exc_info:
        await service.grant_access(
            BareMetalAccessGrant(
                escrow_uid="0xbm",
                host_id="disabled-node",
                physical_host_id="host-physical-1",
                lease_end_utc=datetime(2099, 1, 1, tzinfo=timezone.utc),
            ),
        )

    assert exc_info.value.status_code == 409
    jobs.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_reclaim_access_on_an_unknown_machine_raises_without_submitting_job():
    jobs = MagicMock()
    jobs.submit = AsyncMock()
    service = BareMetalOperationsService(
        jobs=jobs,
        job_queue_provider=lambda: object(),
        host_service=MagicMock(get_host=MagicMock(return_value=None)),
    )

    with pytest.raises(BareMetalHostValidationError):
        await service.reclaim_access(
            BareMetalAccessGrant(
                escrow_uid="0xbm",
                host_id="missing-node",
                physical_host_id="host-physical-1",
                lease_end_utc=datetime(2099, 1, 1, tzinfo=timezone.utc),
            )
        )

    jobs.submit.assert_not_awaited()


def test_the_host_registry_is_required():
    """Host validation has no path that skips it for want of a registry."""
    with pytest.raises(TypeError):
        BareMetalOperationsService(
            jobs=MagicMock(),
            job_queue_provider=lambda: object(),
        )
