"""Health, version, status, and time endpoints."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

import injected_time
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from injected_time import TimeRouteError, TimeRouteService


def _service_version() -> str:
    try:
        return _pkg_version("arkhai-apicredits-service")
    except PackageNotFoundError:
        return "dev"


def make_health_router() -> APIRouter:
    """Bare liveness probe at ``/health`` (bypasses auth)."""
    router = APIRouter()

    @router.get("/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok"}

    return router


def make_system_router() -> APIRouter:
    router = APIRouter(prefix="/system", tags=["system"])

    @router.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @router.get("/version")
    def version() -> dict:
        return {"service": "arkhai-apicredits-service", "version": _service_version()}

    @router.get("/status")
    def status() -> dict:
        """The administrator's status: the service's time source, in either mode."""
        return {"time": TimeRouteService(injected_time.installed()).status()}

    return router


def make_time_router() -> APIRouter:
    """The ``/api/v1/system/time`` router, at its full path, which the service
    mounts only while its source is injected, so a wall-time service serves no
    such route.

    The route sets the installed source to the instant the body carries: a
    body other than ``{"now": <Unix seconds>}`` is 422 ``invalid_time``, an
    earlier instant 409 ``time_moves_forward``, and the answer is signed at the
    instant set.
    """
    router = APIRouter(prefix="/api/v1/system", tags=["system"])

    @router.post("/time")
    async def set_time(request: Request) -> JSONResponse:
        try:
            answer = TimeRouteService(injected_time.installed()).set_time(
                await request.body()
            )
        except TimeRouteError as error:
            return JSONResponse(
                status_code=error.status_code,
                content={"code": error.code, "detail": error.detail},
            )
        return JSONResponse(content=answer)

    return router
