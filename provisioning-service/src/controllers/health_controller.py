from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from fastapi_utils.cbv import cbv
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

import container as _container_module
from services.job_service import AnsibleJobService

router = APIRouter(tags=["health"])


@cbv(router)
class HealthController:
    def __init__(
        self,
        job_service: AnsibleJobService = Depends(lambda: _container_module.resolved_job_service),
        session_factory: sessionmaker[Session] = Depends(lambda: _container_module.resolved_session_factory),
    ) -> None:
        self._job_service = job_service
        self._session_factory = session_factory

    @router.get(
        "/health",
        summary="Service health check",
        response_description="Health status with dependency checks",
    )
    async def health(self) -> JSONResponse:
        """Verifies API, database, and job processor health.

        Returns **200** when all checks pass, **503** when any check fails.
        """
        checks: dict[str, str] = {"api": "ok"}

        try:
            with self._session_factory() as db:
                db.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc}"

        checks["job_processor"] = (
            "ok" if self._job_service.is_processing_loop_alive() else "degraded"
        )

        all_ok = all(v == "ok" for v in checks.values())
        return JSONResponse(
            content={"status": "ok" if all_ok else "degraded", "checks": checks},
            status_code=200 if all_ok else 503,
        )

    @classmethod
    def make_router(cls) -> APIRouter:
        return router