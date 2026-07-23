"""Authenticated domain-neutral scheduling and fulfillment routes."""

from __future__ import annotations

from typing import cast

from compute_provisioning.contracts import (
    FulfillmentAcceptanceView,
    FulfillmentBeginRequest,
    FulfillmentDryRunView,
    FulfillmentScheduleRequest,
    FulfillmentStatusView,
    FulfillmentValidationIssueView,
    SettlementResourceView,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi_utils.cbv import cbv
from market_fulfillment import (
    CapacityReservationExpiredError,
    FulfillmentConflictError,
    FulfillmentRequestInvalidError,
    NoEligibleSettlementResourceError,
    PhysicalSettlementRequest,
    PhysicalSettlementScheduler,
    ProviderConfigInvalidError,
    ProviderNotFoundError,
    SettlementEntityNotFoundError,
    SettlementRequestMismatchError,
    VersionedEnvelope,
)
from market_site.ledger import CapacityLedgerService

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.services.fulfillment_service import FulfillmentService

router = APIRouter(tags=["fulfillment"])


def _fulfillment_not_found(fulfillment_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=f"fulfillment {fulfillment_id!r} not found",
    )


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
        fulfillment_service: FulfillmentService = Depends(
            lambda: _container_module.resolved_fulfillment_service,
        ),
    ) -> None:
        self._scheduler = cast(PhysicalSettlementScheduler, scheduler)
        self._capacity_ledger = cast(CapacityLedgerService, capacity_ledger)
        self._fulfillment_service = cast(FulfillmentService, fulfillment_service)

    @router.post("/fulfillment/schedules", response_model=SettlementResourceView)
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

    @staticmethod
    def _envelope(body: FulfillmentBeginRequest) -> VersionedEnvelope:
        return VersionedEnvelope.model_validate(
            body.fulfillment_request.model_dump(mode="json")
        )

    @router.post("/fulfillments", response_model=FulfillmentAcceptanceView)
    async def begin_fulfillment(
        self,
        body: FulfillmentBeginRequest,
        request: Request,
    ) -> FulfillmentAcceptanceView:
        try:
            accepted = await self._fulfillment_service.begin_fulfillment(
                capacity_reservation_id=body.capacity_reservation_id,
                market=body.market,
                fulfillment_request=self._envelope(body),
                owner_principal=str(request.state.storefront_principal),
            )
        except SettlementEntityNotFoundError as exc:
            raise _not_found(body.capacity_reservation_id) from exc
        except (FulfillmentConflictError, SettlementRequestMismatchError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (
            FulfillmentRequestInvalidError,
            ProviderConfigInvalidError,
            ProviderNotFoundError,
            ValueError,
        ) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return FulfillmentAcceptanceView(
            capacity_reservation_id=accepted.capacity_reservation_id,
            fulfillment_id=accepted.fulfillment_id,
            state=accepted.state,
        )

    @router.get(
        "/fulfillments/{fulfillment_id}/status",
        response_model=FulfillmentStatusView,
    )
    def get_fulfillment_status(
        self,
        fulfillment_id: str,
        request: Request,
    ) -> FulfillmentStatusView:
        try:
            status = self._fulfillment_service.get_status(
                fulfillment_id=fulfillment_id,
                owner_principal=str(request.state.storefront_principal),
            )
        except SettlementEntityNotFoundError as exc:
            raise _fulfillment_not_found(fulfillment_id) from exc
        return FulfillmentStatusView(
            fulfillment_id=status.fulfillment_id,
            capacity_reservation_id=status.capacity_reservation_id,
            state=status.state,
            failure_reason=status.failure_reason,
            failure_message=status.failure_message,
        )

    @router.post("/fulfillments/dry-run", response_model=FulfillmentDryRunView)
    def dry_run_fulfillment(
        self,
        body: FulfillmentBeginRequest,
        request: Request,
    ) -> FulfillmentDryRunView:
        try:
            validation = self._fulfillment_service.validate_create(
                capacity_reservation_id=body.capacity_reservation_id,
                market=body.market,
                fulfillment_request=self._envelope(body),
                owner_principal=str(request.state.storefront_principal),
            )
        except SettlementEntityNotFoundError as exc:
            raise _not_found(body.capacity_reservation_id) from exc
        return FulfillmentDryRunView(
            valid=validation.valid,
            issues=[
                FulfillmentValidationIssueView(
                    code=issue.code,
                    message=issue.message,
                    field=issue.field,
                )
                for issue in validation.issues
            ],
        )

    @classmethod
    def make_router(cls) -> APIRouter:
        return router
