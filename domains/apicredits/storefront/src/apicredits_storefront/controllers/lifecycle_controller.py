"""Lifecycle controls: one pause holding the timer loops, and one step per loop.

The signed operations and resources are the canonical storefront client's, so
one administrator client drives every storefront.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from market_storefront_kit import LifecycleRouteError, StorefrontLifecycleRouteService

import apicredits_storefront.container as _container
from apicredits_storefront.middleware.admin_auth import authenticate_admin

router = APIRouter(prefix="/api/v1/admin/lifecycle", tags=["admin-lifecycle"])


def _routes() -> StorefrontLifecycleRouteService:
    loops = _container.resolved_loop_controller
    if loops is None:
        raise HTTPException(status_code=503, detail="storefront is not initialized")
    return StorefrontLifecycleRouteService(loops)


@router.post("/pause")
async def pause_lifecycle_loops(request: Request) -> dict[str, Any]:
    """Hold every timer loop at its next cycle boundary; trading is unaffected."""
    await authenticate_admin(request, operation="admin_pause_lifecycle_loops", resource="lifecycle")
    return await _routes().pause()


@router.post("/resume")
async def resume_lifecycle_loops(request: Request) -> dict[str, Any]:
    """Return every timer loop to work."""
    await authenticate_admin(request, operation="admin_resume_lifecycle_loops", resource="lifecycle")
    return await _routes().resume()


@router.post("/{loop}/run-cycle")
async def run_lifecycle_cycle(loop: str, request: Request) -> dict[str, Any]:
    """Run exactly the cycle the loop's timer runs, whether or not loops are held."""
    await authenticate_admin(request, operation="admin_run_lifecycle_cycle", resource=loop)
    try:
        return dict(await _routes().run_cycle(loop))
    except LifecycleRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/{loop}/dry-run")
async def dry_run_lifecycle_cycle(loop: str, request: Request) -> dict[str, Any]:
    """Report the loop's next cycle without applying it, where it offers a preview."""
    await authenticate_admin(request, operation="admin_dry_run_lifecycle_cycle", resource=loop)
    try:
        return dict(await _routes().dry_run(loop))
    except LifecycleRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
