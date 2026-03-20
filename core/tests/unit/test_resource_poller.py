from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.agent.app.resource_poller import _poll_once


def _future_lease_end(hours: int = 1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")


@pytest.mark.asyncio
async def test_poll_once_frees_leased_resource_after_early_cleanup_when_no_vms_running() -> None:
    sqlite_client = SimpleNamespace(
        list_resources=AsyncMock(
            return_value=[
                {
                    "resource_id": "gpu-1",
                    "resource_type": "compute.gpu",
                    "state": "leased",
                    "attributes": {
                        "vm_host": "ww1",
                        "lease_end_utc": _future_lease_end(),
                    },
                }
            ]
        ),
        apply_resource_transition=AsyncMock(return_value={"applied": True}),
    )
    provisioning_fn = AsyncMock(return_value={"available": False, "running_vms": 0})

    await _poll_once(sqlite_client, provisioning_fn)

    provisioning_fn.assert_awaited_once()
    sqlite_client.apply_resource_transition.assert_awaited_once_with(
        resource_id="gpu-1",
        event_type="resource_availability_poll",
        idempotency_key="resource-poll-gpu-1-leased-0-available",
        set_state="available",
        set_attribute={"$.lease_end_utc": None},
    )


@pytest.mark.asyncio
async def test_poll_once_keeps_future_leased_resource_when_vm_still_running() -> None:
    sqlite_client = SimpleNamespace(
        list_resources=AsyncMock(
            return_value=[
                {
                    "resource_id": "gpu-1",
                    "resource_type": "compute.gpu",
                    "state": "leased",
                    "attributes": {
                        "vm_host": "ww1",
                        "lease_end_utc": _future_lease_end(),
                    },
                }
            ]
        ),
        apply_resource_transition=AsyncMock(return_value={"applied": True}),
    )
    provisioning_fn = AsyncMock(return_value={"available": False, "running_vms": 1})

    await _poll_once(sqlite_client, provisioning_fn)

    provisioning_fn.assert_awaited_once()
    sqlite_client.apply_resource_transition.assert_not_awaited()
