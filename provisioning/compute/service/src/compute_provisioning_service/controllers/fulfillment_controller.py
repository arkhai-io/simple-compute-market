"""Durable fulfillment acceptance and side-effect-free validation endpoints."""
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from fastapi_utils.cbv import cbv
from pydantic import BaseModel
from compute_provisioning_service import container as _container_module
from market_fulfillment import FulfillmentOrchestrator, VersionedEnvelope

router=APIRouter(prefix='/fulfillment',tags=['fulfillment'])

class FulfillmentRequestBody(BaseModel):
    capacity_reservation_id:str
    market:str
    fulfillment_request:VersionedEnvelope[Any]

class FulfillmentAcceptanceResponse(BaseModel):
    fulfillment_id:str
    capacity_reservation_id:str
    state:str

class FulfillmentValidationResponse(BaseModel):
    valid:bool
    issues:list[dict[str,Any]]

@cbv(router)
class FulfillmentController:
    def __init__(self, service:FulfillmentOrchestrator=Depends(lambda:_container_module.resolved_fulfillment_service)) -> None:
        self._service=service
    @router.post('/validate',response_model=FulfillmentValidationResponse)
    def validate(self, body:FulfillmentRequestBody)->FulfillmentValidationResponse:
        result=self._service.validate_fulfillment(body.capacity_reservation_id,body.market,body.fulfillment_request)
        return FulfillmentValidationResponse(valid=result.valid,issues=[issue.__dict__ for issue in result.issues])
    @router.post('/begin',response_model=FulfillmentAcceptanceResponse)
    async def begin(self, body:FulfillmentRequestBody)->FulfillmentAcceptanceResponse:
        try:
            result=await self._service.begin_fulfillment(body.capacity_reservation_id,body.market,body.fulfillment_request)
        except Exception as exc:
            raise HTTPException(status_code=409,detail=str(exc)) from exc
        return FulfillmentAcceptanceResponse(**result.__dict__)

    @classmethod
    def make_router(cls) -> APIRouter:
        return router
