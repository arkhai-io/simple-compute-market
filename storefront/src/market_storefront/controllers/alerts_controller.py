"""Alerts controller — resource imbalance alert ingestion."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi_utils.cbv import cbv

import market_storefront.container as _container
from market_storefront.models.domain_models import ResourceAlertRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/alerts", tags=["alerts"])


@cbv(router)
class AlertsController:
    def __init__(
        self,
        pipeline_svc=Depends(lambda: _container.resolved_policy_pipeline_service),
    ) -> None:
        self._pipeline = pipeline_svc

    @router.post("/resource", summary="Receive a resource imbalance alert")
    async def resource_alert(self, body: ResourceAlertRequest) -> dict[str, Any]:
        try:
            return await self._pipeline.handle_resource_alert(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            logger.error("[ALERT] %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))
