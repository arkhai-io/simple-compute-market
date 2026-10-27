"""Health and version bindings."""

from __future__ import annotations

from typing import Callable

from arkhai_api_authority import SystemRouteService
from fastapi import APIRouter, Depends


def make_health_router() -> APIRouter:
    """Bare liveness probe at ``/health`` (bypasses auth)."""
    router = APIRouter()

    @router.get("/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok"}

    return router


def make_system_router(get_service: Callable[[], SystemRouteService]) -> APIRouter:
    router = APIRouter(prefix="/system", tags=["system"])

    @router.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @router.get("/version")
    def version(service: SystemRouteService = Depends(get_service)) -> dict:
        return service.version()

    return router
