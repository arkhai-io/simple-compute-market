"""Admin controller — global pause/resume and status. All endpoints require admin key."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi_utils.cbv import cbv

import market_storefront.container as _container
from market_storefront.server import _set_globally_paused, is_globally_paused

router = APIRouter(prefix="/admin", tags=["admin"])


@cbv(router)
class AdminController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
    ) -> None:
        self._db = db

    @router.post("/pause", summary="Pause new negotiations globally (admin)")
    async def pause(self) -> dict[str, Any]:
        _set_globally_paused(True)
        return {"paused": True, "message": "Storefront paused. New negotiations will receive 503."}

    @router.post("/resume", summary="Resume new negotiations globally (admin)")
    async def resume(self) -> dict[str, Any]:
        _set_globally_paused(False)
        return {"paused": False, "message": "Storefront resumed."}

    @router.get("/status", summary="Live operational snapshot (admin)")
    async def status(self) -> dict[str, Any]:
        counts = await self._db.get_admin_status_counts()
        return {
            "paused": is_globally_paused(),
            "active_negotiations": counts.get("active_negotiations", 0),
            "open_listings": counts.get("open_orders", 0),
            "paused_listings": counts.get("paused_orders", 0),
        }
