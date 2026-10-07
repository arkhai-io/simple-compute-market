"""Trading pause: whether this storefront opens new negotiations.

Bound through the storefront kit's route service, so the paths, signed
operations, and responses are the canonical storefront client's, the same on
every storefront. Separate from the lifecycle pause, which holds the timer loops.
"""

from __future__ import annotations

from core_storefront.models.system_models import AdminPauseResponse
from fastapi import APIRouter, Request
from market_storefront_kit import TradingPauseRouteService

import apicredits_storefront.container as _container
from apicredits_storefront.middleware.admin_auth import authenticate_admin

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.post("/pause", response_model=AdminPauseResponse)
async def pause(request: Request) -> AdminPauseResponse:
    """Refuse new negotiations until resumed or the process restarts."""
    await authenticate_admin(request, operation="admin_pause", resource="")
    return TradingPauseRouteService(_container.trading_pause).pause()


@router.post("/resume", response_model=AdminPauseResponse)
async def resume(request: Request) -> AdminPauseResponse:
    """Open new negotiations again."""
    await authenticate_admin(request, operation="admin_resume", resource="")
    return TradingPauseRouteService(_container.trading_pause).resume()
