"""Health, version, status, and time bindings."""

from __future__ import annotations

from typing import Callable

from arkhai_api_authority import RouteRefusal, SystemRouteService
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse


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

    @router.get("/status")
    def status(service: SystemRouteService = Depends(get_service)) -> dict:
        """The administrator's status: the service's time source, in either mode."""
        return service.status()

    return router


def make_time_router(get_service: Callable[[], SystemRouteService]) -> APIRouter:
    """The ``/system/time`` router, which the service mounts only while its
    source is injected, so a wall-time service serves no such route.

    The route sets the installed source to the instant the body carries: a
    body other than ``{"now": <Unix seconds>}`` is 422 ``invalid_time``, an
    earlier instant 409 ``time_moves_forward``, and the answer is signed at the
    instant set.
    """
    router = APIRouter(prefix="/system", tags=["system"])

    @router.post("/time")
    async def set_time(
        request: Request, service: SystemRouteService = Depends(get_service)
    ) -> JSONResponse:
        try:
            answer = service.set_time(await request.body())
        except RouteRefusal as refusal:
            return JSONResponse(status_code=refusal.status_code, content=refusal.body)
        return JSONResponse(content=answer)

    return router
