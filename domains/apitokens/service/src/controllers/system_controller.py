"""Health and version endpoints."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from fastapi import APIRouter


def _service_version() -> str:
    try:
        return _pkg_version("arkhai-apitokens-service")
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
        return {"service": "arkhai-apitokens-service", "version": _service_version()}

    return router
