"""Authenticated domain-neutral scheduling and fulfillment routes."""

from __future__ import annotations

from typing import cast

from compute_provisioning.contracts import (
    FulfillmentScheduleRequest,
    SettlementResourceView,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi_utils.cbv import cbv
from market_fulfillment import (
    CapacityReservationExpiredError,
    NoEligibleSettlementResourceError,
    PhysicalSettlementRequest,
    PhysicalSettlementScheduler,
    SettlementEntityNotFoundError,
    SettlementRequestMismatchError,
)
from market_site.ledger import CapacityLedgerService

from compute_provisioning_service import container as _container_module

router = APIRouter(prefix="/fulfillment", tags=["fulfillment"])


def _not_found(reservation_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=f"capacity reservation {reservation_id!r} not found",
    )


@cbv(router)
class FulfillmentController:
    def __init__(
        self,
        scheduler: PhysicalSettlementScheduler = Depends(
            lambda: _container_module.resolved_physical_settlement_scheduler,
        ),
        capacity_ledger: CapacityLedgerService = Depends(
            lambda: _container_module.resolved_capacity_ledger_service,
        ),
    ) -> None:
        self._scheduler = cast(PhysicalSettlementScheduler, scheduler)
        self._capacity_ledger = cast(CapacityLedgerService, capacity_ledger)

    @router.post("/schedules", response_model=SettlementResourceView)
    def schedule_resource(
        self,
        body: FulfillmentScheduleRequest,
        request: Request,
    ) -> SettlementResourceView:
        principal = str(request.state.storefront_principal)
        if self._capacity_ledger.reservation_owner_principal(
            body.capacity_reservation_id,
        ) != principal:
            raise _not_found(body.capacity_reservation_id)
        try:
            selected = self._scheduler.schedule_resource(
                PhysicalSettlementRequest(
                    capacity_reservation_id=body.capacity_reservation_id,
                    market=body.market,
                    requirements=body.requirements,
                    resource_id=body.resource_id,
                ),
            )
        except SettlementEntityNotFoundError as exc:
            raise _not_found(body.capacity_reservation_id) from exc
        except (
            CapacityReservationExpiredError,
            SettlementRequestMismatchError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except NoEligibleSettlementResourceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return SettlementResourceView(
            capacity_reservation_id=body.capacity_reservation_id,
            settlement_resource_id=selected.settlement_resource_id,
            pool_id=selected.pool_id,
            resource_kind=selected.resource_kind,
            provider=selected.provider,
            attributes=selected.attributes,
        )

    @classmethod
    def make_router(cls) -> APIRouter:
        return router
