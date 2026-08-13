"""fulfill_vm_obligation must route plan-building failures (missing or
malformed order) through the same graceful-failure path — apply_failure_policy,
the 'provision failed' stage event, and a {"status": "error", ...} response —
as every other reservation failure, rather than raising past it."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from market_storefront.services import vm_fulfillment_service as vfs
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


@pytest.mark.asyncio
async def test_interrupted_fulfillment_never_persists_the_string_none_as_settlement_resource_id(
    monkeypatch,
):
    """Regression test for a bug distinct from the vm_host/resource_id-
    required guards: even once those were removed,
    ``fulfill_vm_obligation`` used to compute
    ``str(reserved.get("resource_id"))`` and persist it as
    ``settlement_resource_id`` immediately after reserving -- before
    ``schedule_resource()`` (inside ``provision_vm``) has run and actually
    established the real value. On the happy path that write gets
    overwritten by the correct one moments later, but if fulfillment is
    interrupted in between (exactly what this test simulates by making
    ``provision_vm`` raise), a stuck order was left with the literal
    three-character string ``"None"`` as its persisted settlement resource
    -- worse than simply having no value recorded at all.

    The reservation response deliberately carries no ``resource_id`` here,
    matching what the real opaque capacity-reservation wire boundary
    returns (see ``test_capacity_reservation_boundary.py`` for the
    real-boundary version of this guarantee).
    """
    plan = SimpleNamespace(order_id="listing-1", required_attributes={})
    monkeypatch.setattr(vfs, "build_vm_fulfillment_plan", lambda **_: plan)

    sqlite_client = SimpleNamespace(
        update_escrow=AsyncMock(),
        update_listing=AsyncMock(),
        store_credential=AsyncMock(),
    )
    capacity = SimpleNamespace(
        reserve=AsyncMock(return_value={
            "capacity_reservation_id": "reservation-1",
            # No "resource_id", no "vm_host" -- exactly what the real
            # opaque reservation boundary returns.
        }),
        commit=AsyncMock(),
    )
    apply_failure_policy = AsyncMock()

    async def failing_provision_vm(*args, **kwargs) -> dict:
        raise RuntimeError("simulated interruption before schedule_resource() runs")

    result = await fulfill_vm_obligation(
        client=None,
        escrow_uid="escrow-1",
        ssh_public_key="ssh-ed25519 test",
        order={"listing_id": "listing-1"},
        get_sqlite_client=lambda: sqlite_client,
        capacity=capacity,
        stage_event=lambda *a, **k: None,
        provision_vm=failing_provision_vm,
        schedule_shutdown=AsyncMock(),
        register_lease=AsyncMock(),
        apply_failure_policy=apply_failure_policy,
    )

    assert result["status"] == "error"

    persisted_resource_ids = [
        call.kwargs.get("settlement_resource_id")
        for call in sqlite_client.update_escrow.await_args_list
        if "settlement_resource_id" in call.kwargs
    ]
    assert "None" not in persisted_resource_ids, (
        "settlement_resource_id must never be persisted as the literal "
        "string \"None\" -- either omit it entirely until the real value "
        "is known (schedule_resource()'s job, never reached here), or "
        "persist an actual None"
    )

