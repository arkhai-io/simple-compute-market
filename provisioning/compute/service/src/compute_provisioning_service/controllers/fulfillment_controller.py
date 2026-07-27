"""Durable fulfillment scheduling, acceptance, and side-effect-free validation endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi_utils.cbv import cbv

from compute_provisioning.contracts import (
    FulfillmentAcceptanceResponse,
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    FulfillmentScheduleResponse,
    FulfillmentStatusResponse,
    FulfillmentValidationResponse,
)
from compute_provisioning_service import container as _container_module
from market_fulfillment import (
    CapacityReservationExpiredError,
    CredentialFetchFailedError,
    FulfillmentConflictError,
    FulfillmentOrchestrator,
    NoEligibleSettlementResourceError,
    PhysicalSettlementRequest,
    PhysicalSettlementScheduler,
    ProviderConfigInvalidError,
    ProviderNotFoundError,
    SettlementEntityNotFoundError,
    SettlementRequestMismatchError,
    VersionedEnvelope,
)

router = APIRouter(prefix="/fulfillment", tags=["fulfillment"])


@cbv(router)
class FulfillmentController:
    def __init__(
        self,
        service: FulfillmentOrchestrator = Depends(
            lambda: _container_module.resolved_fulfillment_service
        ),
        scheduler: PhysicalSettlementScheduler = Depends(
            lambda: _container_module.resolved_physical_settlement_scheduler
        ),
    ) -> None:
        self._service = service
        self._scheduler = scheduler

    @router.post("/schedule", response_model=FulfillmentScheduleResponse)
    def schedule(self, body: FulfillmentScheduleRequest) -> FulfillmentScheduleResponse:
        try:
            resource = self._scheduler.schedule_resource(
                PhysicalSettlementRequest(
                    capacity_reservation_id=body.capacity_reservation_id,
                    market=body.market,
                    requirements=body.requirements,
                    resource_id=body.resource_id,
                )
            )
        except SettlementEntityNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "fulfillment_not_found", "message": "The capacity reservation was not found."},
            ) from exc
        except CapacityReservationExpiredError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "fulfillment_conflict", "message": "The capacity reservation has expired."},
            ) from exc
        except NoEligibleSettlementResourceError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "no_eligible_resource", "message": "No eligible settlement resource satisfies the request."},
            ) from exc
        except SettlementRequestMismatchError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "fulfillment_conflict", "message": "The request conflicts with the existing scheduled resource."},
            ) from exc
        return FulfillmentScheduleResponse(
            settlement_resource_id=resource.settlement_resource_id,
            pool_id=resource.pool_id,
            resource_kind=resource.resource_kind,
            provider=resource.provider,
            attributes=resource.attributes,
        )

    @router.post("/validate", response_model=FulfillmentValidationResponse)
    def validate(self, body: FulfillmentRequestBody) -> FulfillmentValidationResponse:
        result = self._service.validate_fulfillment(
            body.capacity_reservation_id,
            body.market,
            body.fulfillment_request,
        )
        return FulfillmentValidationResponse(
            valid=result.valid,
            issues=[issue.__dict__ for issue in result.issues],
        )

    @router.post("/begin", response_model=FulfillmentAcceptanceResponse)
    async def begin(
        self,
        body: FulfillmentRequestBody,
    ) -> FulfillmentAcceptanceResponse:
        try:
            result = await self._service.begin_fulfillment(
                body.capacity_reservation_id,
                body.market,
                body.fulfillment_request,
            )
        except (SettlementEntityNotFoundError, LookupError) as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "fulfillment_not_found", "message": "The scheduled fulfillment resource was not found."},
            ) from exc
        except ProviderConfigInvalidError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "provider_config_invalid", "message": "The fulfillment provider configuration is invalid."},
            ) from exc
        except (FulfillmentConflictError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "fulfillment_conflict", "message": "The request conflicts with the durable fulfillment state."},
            ) from exc
        except ProviderNotFoundError as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "fulfillment_provider_unavailable",
                    "message": "The configured fulfillment provider is unavailable.",
                },
            ) from exc
        return FulfillmentAcceptanceResponse(**result.__dict__)

    @router.post(
        "/{fulfillment_id}/begin-teardown",
        response_model=FulfillmentAcceptanceResponse,
    )
    async def begin_teardown(self, fulfillment_id: str) -> FulfillmentAcceptanceResponse:
        try:
            result = await self._service.begin_fulfillment_teardown(fulfillment_id)
        except SettlementEntityNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "fulfillment_not_found", "message": "No fulfillment exists for this identifier."},
            ) from exc
        except ProviderConfigInvalidError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "provider_config_invalid", "message": "The fulfillment provider configuration is invalid."},
            ) from exc
        except (FulfillmentConflictError, LookupError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "fulfillment_conflict", "message": "The request conflicts with the durable fulfillment state."},
            ) from exc
        except ProviderNotFoundError as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "fulfillment_provider_unavailable",
                    "message": "The configured fulfillment provider is unavailable.",
                },
            ) from exc
        return FulfillmentAcceptanceResponse(**result.__dict__)

    @router.get("/{fulfillment_id}/status", response_model=FulfillmentStatusResponse)
    def status(self, fulfillment_id: str) -> FulfillmentStatusResponse:
        try:
            result = self._service.get_fulfillment_status(fulfillment_id)
        except SettlementEntityNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "fulfillment_not_found", "message": "No fulfillment exists for this identifier."},
            ) from exc
        return FulfillmentStatusResponse(**result.__dict__)

    @router.get("/{fulfillment_id}/result", response_model=VersionedEnvelope[dict[str, Any]])
    async def result(self, fulfillment_id: str) -> VersionedEnvelope[dict[str, Any]]:
        try:
            envelope = await self._service.get_fulfillment_result(fulfillment_id)
        except SettlementEntityNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "fulfillment_not_found", "message": "No fulfillment exists for this identifier."},
            ) from exc
        except CredentialFetchFailedError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "credential_fetch_failed",
                    "message": "Credentials could not be fetched right now; retry the read.",
                },
            ) from exc
        return envelope

    @classmethod
    def make_router(cls) -> APIRouter:
        return router
