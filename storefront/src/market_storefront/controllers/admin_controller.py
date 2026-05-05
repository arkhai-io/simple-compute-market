"""Admin controller — global pause/resume and status.

require_admin_key is applied via __init__ Depends (not router-level) to avoid
a fastapi_utils @cbv + router-level dependencies interaction issue that causes
routes to return 404.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi_utils.cbv import cbv

import market_storefront.container as _container
from market_storefront.middleware.admin_auth import require_admin_key
from market_storefront.models.system_models import AdminPauseResponse, AdminStatusResponse
from market_storefront.server import _set_globally_paused, is_globally_paused

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