from __future__ import annotations

import pytest

from market_settlement_runtime import (
    SettlementAdminRouteError,
    SettlementAdminRouteService,
)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _service(*, statuses=None, verify=None, preview=None, clock=None):
    statuses = list(statuses or [])

    async def settle_status(_uid):
        return statuses.pop(0) if statuses else None

    async def default_verify(_uid, request):
        return {"valid": request.get("seller_wallet") == "0xseller"}

    async def default_preview(_uid, request):
        return {"would_submit": True, "host_id": request["listing_id"]}

    return SettlementAdminRouteService(
        verify=verify or default_verify,
        preview_fulfillment=preview or default_preview,
        settle_status=settle_status,
        is_terminal=lambda status: status.get("status") in {"ready", "failed"},
        poll_seconds=0.0,
        clock=clock or Clock(),
    )


async def test_verify_and_evaluate_report_the_domain_result_for_the_escrow() -> None:
    service = _service()

    verified = await service.verify("uid-1", {"seller_wallet": "0xseller"})
    evaluated = await service.evaluate("uid-1", {"listing_id": "listing-1"})

    assert verified == {"valid": True, "escrow_uid": "uid-1"}
    assert evaluated == {
        "would_submit": True,
        "host_id": "listing-1",
        "escrow_uid": "uid-1",
    }


async def test_an_unknown_reference_is_not_found() -> None:
    async def unknown(_uid, _request):
        raise LookupError("listing 'x' not found")

    service = _service(verify=unknown, preview=unknown)

    for call in (service.verify, service.evaluate):
        with pytest.raises(SettlementAdminRouteError) as refused:
            await call("uid-1", {})
        assert refused.value.status_code == 404


async def test_wait_returns_once_the_settlement_is_terminal() -> None:
    service = _service(
        statuses=[
            {"status": "provisioning"},
            {"status": "ready", "fulfillment_id": "f-1"},
        ]
    )

    waited = await service.wait("uid-1", timeout=5)

    assert waited["ready"] is True
    assert waited["status"] == "ready"
    assert waited["fulfillment_id"] == "f-1"


async def test_wait_times_out_with_the_last_status() -> None:
    clock = Clock()

    async def settle_status(_uid):
        clock.now += 1.0
        return {"status": "provisioning"}

    service = SettlementAdminRouteService(
        settle_status=settle_status,
        is_terminal=lambda status: status.get("status") == "ready",
        poll_seconds=0.0,
        clock=clock,
    )

    waited = await service.wait("uid-1", timeout=2)

    assert waited["ready"] is False
    assert waited["status"] == "provisioning"


async def test_wait_reports_unknown_when_nothing_is_recorded() -> None:
    clock = Clock()

    async def settle_status(_uid):
        clock.now += 1.0
        return None

    service = SettlementAdminRouteService(
        settle_status=settle_status,
        is_terminal=lambda status: True,
        poll_seconds=0.0,
        clock=clock,
    )

    waited = await service.wait("uid-1", timeout=1)

    assert waited["ready"] is False
    assert waited["status"] == "unknown"


async def test_a_storefront_without_dry_runs_refuses_them() -> None:
    async def settle_status(_uid):
        return None

    service = SettlementAdminRouteService(
        settle_status=settle_status, is_terminal=lambda status: True
    )

    for call in (service.verify, service.evaluate):
        with pytest.raises(SettlementAdminRouteError) as refused:
            await call("uid-1", {})
        assert refused.value.status_code == 404
