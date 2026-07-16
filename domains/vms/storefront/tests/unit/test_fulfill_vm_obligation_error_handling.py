"""fulfill_vm_obligation must route plan-building failures (missing or
malformed order) through the same graceful-failure path — apply_failure_policy,
the 'provision failed' stage event, and a {"status": "error", ...} response —
as every other reservation failure, rather than raising past it."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from market_storefront.services.vm_fulfillment_service import fulfill_vm_obligation


@pytest.mark.asyncio
async def test_malformed_order_returns_graceful_error_and_runs_failure_policy():
    capacity = AsyncMock()
    apply_failure_policy = AsyncMock()
    stage_events: list[tuple[str, str, dict]] = []

    def stage_event(stage: str, kind: str, **kwargs) -> None:
        stage_events.append((stage, kind, kwargs))

    result = await fulfill_vm_obligation(
        client=None,
        escrow_uid="escrow-1",
        ssh_public_key="ssh-ed25519 test",
        order=None,  # missing order — build_vm_fulfillment_plan raises
        get_sqlite_client=lambda: AsyncMock(),
        capacity=capacity,
        stage_event=stage_event,
        provision_vm=AsyncMock(),
        schedule_shutdown=AsyncMock(),
        register_lease=AsyncMock(),
        apply_failure_policy=apply_failure_policy,
    )

    assert result["status"] == "error"
    assert "escrow-1" == result["escrow_uid"]
    assert result["connection_details"] is None

    apply_failure_policy.assert_awaited_once()
    assert apply_failure_policy.await_args.kwargs["escrow_uid"] == "escrow-1"
    assert apply_failure_policy.await_args.kwargs["reason"] == "provisioning_failed"

    assert ("provision", "failed", ) == stage_events[-1][:2]

    capacity.reserve.assert_not_awaited()
    capacity.probe.assert_not_awaited()
