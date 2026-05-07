"""Alerts controller — resource imbalance alert ingestion."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi_utils.cbv import cbv
from pydantic import BaseModel

import market_storefront.container as _container
from market_storefront.models.domain_models import ResourceAlertRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


class ResourceAlertResponse(BaseModel):
    root_agent_response: str
    model_config = {"extra": "allow"}


@cbv(router)
class AlertsController:
    def __init__(
        self,
        policy_svc=Depends(lambda: _container.resolved_policy_service),
    ) -> None:
        self._policy_svc = policy_svc

    @router.post(
        "/resource",
        response_model=ResourceAlertResponse,
        summary="Receive a resource imbalance alert",
    )
    async def resource_alert(self, body: ResourceAlertRequest) -> ResourceAlertResponse:
        try:
            result = await self._policy_svc.handle_resource_alert(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            logger.error("[ALERT] %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
        return ResourceAlertResponse(**result)
