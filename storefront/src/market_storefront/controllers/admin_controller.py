"""Admin controller — global pause/resume, status, and resource maintenance.

require_admin_key is applied via __init__ Depends (not router-level) to avoid
a fastapi_utils @cbv + router-level dependencies interaction issue that causes
routes to return 404.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi_utils.cbv import cbv

import market_storefront.container as _container
from market_storefront.middleware.admin_auth import require_admin_key
from market_storefront.models.system_models import (
    AdminPauseResponse,
    AdminStatusResponse,
    ReleaseReservationsResponse,
)
from market_storefront.server import _set_globally_paused, is_globally_paused

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

@cbv(router)
class AdminController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
        _key: None = Depends(require_admin_key),
    ) -> None:
        self._db = db

    @router.post("/pause", response_model=AdminPauseResponse,
                 summary="Pause new negotiations globally (admin)")
    async def pause(self) -> AdminPauseResponse:
        _set_globally_paused(True)
        return AdminPauseResponse(
            paused=True, message="Storefront paused. New negotiations will receive 503."
        )

    @router.post("/resume", response_model=AdminPauseResponse,
                 summary="Resume new negotiations globally (admin)")
    async def resume(self) -> AdminPauseResponse:
        _set_globally_paused(False)
        return AdminPauseResponse(paused=False, message="Storefront resumed.")

    @router.get("/status", response_model=AdminStatusResponse,
                summary="Live operational snapshot (admin)")
    async def status(self) -> AdminStatusResponse:
        counts = await self._db.get_admin_status_counts()
        return AdminStatusResponse(
            paused=is_globally_paused(),
            active_negotiations=counts.get("active_negotiations", 0),
            open_listings=counts.get("open_orders", 0),
            paused_listings=counts.get("paused_orders", 0),
        )

    @router.post(
        "/portfolio/release-reservations",
        response_model=ReleaseReservationsResponse,
        summary="Release all reserved compute resources back to available (admin)",
    )
    async def release_reservations(self) -> ReleaseReservationsResponse:
        """Force every ``reserved`` resource back to ``available``.

        Use cases:
          - e2e test teardown between back-to-back runs against the same stack
            (mocked provisioning never expires leases, so reserved resources
            otherwise leak across runs).
          - Operator recovery after a provisioner crash: when the storefront
            knows a resource was reserved but the actual workload is gone,
            this clears the reservation without touching value/inventory data.

        Does not touch resources in any other state. Idempotent — safe to call
        repeatedly.
        """
        resources = await self._db.list_resources()
        released = []
        for r in resources:
            if r.get("state") != "reserved":
                continue
            resource_id = str(r["resource_id"])
            await self._db.apply_resource_set_transition(
                resource_id=resource_id,
                event_type="reservation_released_by_admin",
                idempotency_key=f"admin-release:{resource_id}:{r.get('updated_at', '')}",
                set_state="available",
            )
            released.append(resource_id)
        if released:
            logger.info(
                "[ADMIN] Released %d reservation(s): %s",
                len(released), released,
            )
        return ReleaseReservationsResponse(
            released_count=len(released),
            resource_ids=released,
        )