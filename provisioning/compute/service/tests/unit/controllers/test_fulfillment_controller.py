from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from market_fulfillment import SettlementResource

from compute_provisioning import FulfillmentScheduleRequest
from compute_provisioning_service.controllers.fulfillment_controller import (
    FulfillmentController,
)


class _Ledger:
    def __init__(self, owner: str | None) -> None:
        self.owner = owner

    def reservation_owner_principal(self, _reservation_id: str) -> str | None:
        return self.owner


class _Scheduler:
    def __init__(self) -> None:
        self.requests = []

    def schedule_resource(self, request):
        self.requests.append(request)
        return SettlementResource(
            settlement_resource_id="resource-1",
            pool_id="pool-1",
            resource_kind="bare_metal",
            provider="ansible",
            attributes={"machine_id": "machine-1"},
        )


def _request(principal: str):
    return SimpleNamespace(
        state=SimpleNamespace(storefront_principal=principal),
    )


def test_schedule_returns_neutral_resource_for_owner() -> None:
    scheduler = _Scheduler()
    controller = FulfillmentController(
        scheduler=scheduler,
        capacity_ledger=_Ledger("seller-a"),
        fulfillment_service=SimpleNamespace(),
    )

    result = controller.schedule_resource(
        FulfillmentScheduleRequest(
            capacity_reservation_id="reservation-1",
            market="bare_metal",
            requirements={"resource_kind": "bare_metal", "units": 1},
        ),
        _request("seller-a"),
    )

    assert result.capacity_reservation_id == "reservation-1"
    assert result.settlement_resource_id == "resource-1"
    assert result.attributes == {"machine_id": "machine-1"}
    assert scheduler.requests[0].market == "bare_metal"


def test_schedule_hides_reservation_from_other_principal() -> None:
    scheduler = _Scheduler()
    controller = FulfillmentController(
        scheduler=scheduler,
        capacity_ledger=_Ledger("seller-a"),
        fulfillment_service=SimpleNamespace(),
    )

    with pytest.raises(HTTPException) as raised:
        controller.schedule_resource(
            FulfillmentScheduleRequest(
                capacity_reservation_id="reservation-1",
                market="bare_metal",
            ),
            _request("seller-b"),
        )

    assert raised.value.status_code == 404
    assert scheduler.requests == []
