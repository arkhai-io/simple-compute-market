"""Invalid evidence fails before physical effects; interrupted delivery keeps identities absent."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from market_storefront.services.vm_fulfillment_service import fulfill_vm_obligation
from tests.fulfillment_fixtures import make_vm_lifecycle_fixture, vm_delivery_evidence


@pytest.mark.asyncio
async def test_malformed_evidence_fails_before_capacity_or_failure_policy():
    capacity = AsyncMock()
    apply_failure_policy = AsyncMock()
    stage_events: list[tuple[str, str, dict]] = []

    def stage_event(stage: str, kind: str, **kwargs) -> None:
        stage_events.append((stage, kind, kwargs))

    with pytest.raises(ValueError, match="valid, non-empty settlement order"):
        await fulfill_vm_obligation(
            evidence=vm_delivery_evidence(order={}),
            get_sqlite_client=lambda: AsyncMock(),
            capacity=capacity,
            stage_event=stage_event,
            provision_vm=AsyncMock(),
            apply_failure_policy=apply_failure_policy,
        )
    # An invalid authorization is rejected before physical failure handling.
    apply_failure_policy.assert_not_awaited()
    capacity.reserve.assert_not_awaited()
    capacity.probe.assert_not_awaited()


@pytest.mark.asyncio
async def test_interrupted_fulfillment_never_persists_the_string_none_as_settlement_resource_id(
    tmp_path,
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
    lifecycle = await make_vm_lifecycle_fixture(
        tmp_path / "interrupted.db", with_context=False
    )
    sqlite_client = lifecycle.db
    capacity = SimpleNamespace(
        reserve=AsyncMock(
            return_value={
                "capacity_reservation_id": "reservation-1",
                # No "resource_id", no "vm_host" -- exactly what the real
                # opaque reservation boundary returns.
            }
        ),
        commit=AsyncMock(),
    )
    apply_failure_policy = AsyncMock()

    async def failing_provision_vm(*args, **kwargs) -> dict:
        raise RuntimeError("simulated interruption before schedule_resource() runs")

    result = await fulfill_vm_obligation(
        evidence=lifecycle.evidence,
        get_sqlite_client=lambda: sqlite_client,
        capacity=capacity,
        stage_event=lambda *a, **k: None,
        provision_vm=failing_provision_vm,
        apply_failure_policy=apply_failure_policy,
    )

    assert result["status"] == "error"

    assert "simulated interruption" in result["message"]
    row = await sqlite_client.load_vm_delivery(
        negotiation_id=lifecycle.evidence.negotiation_id
    )
    assert row["capacity_reservation_id"] == "reservation-1"
    assert row["settlement_resource_id"] is None
