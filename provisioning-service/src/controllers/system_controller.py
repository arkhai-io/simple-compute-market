"""System diagnostics and health controller.

Exposes three endpoint groups:

  ``GET /health``                          Kubernetes liveness/readiness probe.
  ``GET /api/v1/system/health``            Same handler, discoverable under the
                                           versioned prefix.
  ``GET /api/v1/system/version``           Service version + active config profiles.
  ``GET /api/v1/system/ansible/readiness`` Ansible binary, inventory, playbook, and
                                           SSH key file diagnostics.

``/health`` is intentionally kept at the root (no prefix) to preserve the
well-established Kubernetes probe convention.  The Helm deployment's
``livenessProbe`` and ``readinessProbe`` continue to use ``/health`` unchanged.

Registration in ``main.py``
---------------------------
Two routers are exported::

    SystemController.make_health_router()   → registers GET /health
    SystemController.make_system_router()   → registers GET /api/v1/system/*
"""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from fastapi_utils.cbv import cbv
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

import container as _container_module
from config import Settings
from models.system_model import (
    AnsibleReadinessResponse,
    HealthResponse,
    VersionResponse,
)
from services.ansible_service import AnsibleService
from services.system_service import SystemService

_health_router = APIRouter(tags=["system"])
_system_router = APIRouter(prefix="/system", tags=["system"])


@cbv(_health_router)
@cbv(_system_router)
class SystemController:
    def __init__(
        self,
        session_factory: sessionmaker[Session] = Depends(
            lambda: _container_module.resolved_session_factory
        ),
        system_service: SystemService = Depends(
            lambda: _container_module.resolved_system_service
        ),
    ) -> None:
        self._session_factory = session_factory
        self._system_service = system_service

    # ------------------------------------------------------------------
    # Health — registered on both routers
    # ------------------------------------------------------------------

    async def _health_impl(self) -> JSONResponse:
        checks: dict[str, str] = {"api": "ok"}

        try:
            with self._session_factory() as db:
                db.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc}"

        job_queue = _container_module.resolved_job_queue
        checks["job_processor"] = (
            "ok" if (job_queue is not None and job_queue.is_alive()) else "degraded"
        )

        all_ok = all(v == "ok" for v in checks.values())
        return JSONResponse(
            content={"status": "ok" if all_ok else "degraded", "checks": checks},
            status_code=200 if all_ok else 503,
        )

    @_health_router.get(
        "/health",
        response_model=HealthResponse,
        summary="Service health check (liveness probe)",
        description=(
            "Verifies API, database, and job processor health. "
            "Used as the Kubernetes liveness and readiness probe at ``/health``."
        ),
    )
    async def health_bare(self) -> JSONResponse:
        return await self._health_impl()

    @_system_router.get(
        "/health",
        response_model=HealthResponse,
        summary="Service health check (versioned alias)",
        description=(
            "Alias for ``GET /health`` discoverable under the "
            "``/api/v1/system`` prefix."
        ),
    )
    async def health_system(self) -> JSONResponse:
        return await self._health_impl()

    # ------------------------------------------------------------------
    # Version
    # ------------------------------------------------------------------

    @_system_router.get(
        "/version",
        response_model=VersionResponse,
        summary="Service version and active configuration profiles",
    )
    def version(self) -> VersionResponse:
        """Return the service version and the active dynaconf profiles.

        Active profiles determine which ``config-<profile>.yml`` files were
        loaded at startup.  Useful for confirming that a ConfigMap or
        environment-specific profile was applied.

        The version is read from the installed package metadata
        (``importlib.metadata``) with a fallback to ``pyproject.toml``.
        """
        raw_profiles: str = os.environ.get("ACTIVE_PROFILES", "")
        active = [p.strip() for p in raw_profiles.split(",") if p.strip()]
        return VersionResponse(
            version=self._system_service.get_version(),
            active_profiles=active,
        )

    # ------------------------------------------------------------------
    # Ansible readiness
    # ------------------------------------------------------------------

    @_system_router.get(
        "/ansible/readiness",
        response_model=AnsibleReadinessResponse,
        summary="Ansible configuration readiness check",
    )
    async def ansible_readiness(self) -> AnsibleReadinessResponse:
        """Verify that the Ansible binary, inventory, playbook, and SSH keys
        are all present and readable.

        This is a **diagnostic** endpoint, not a Kubernetes probe.  It is
        intended for operators and smoke-test scripts that need to confirm
        the service is correctly configured before submitting any jobs.

        Returns 200 regardless of readiness state — the per-field ``exists``
        flags carry the diagnostic result.

        SSH key paths are read from the ``ansible_ssh_private_key_file`` host
        variable in the inventory.  The ``~`` prefix is expanded using the
        process owner's home directory.  The SHA-256 digest allows operators
        to verify that the mounted key matches an expected value without
        exposing any key material (SHA-256 is a one-way function).
        """
        return await asyncio.to_thread(self._system_service.ansible_readiness)

    @_system_router.post(
        "/check-leases",
        summary="Trigger immediate lease lifecycle processing (admin)",
    )
    async def check_leases(self) -> dict:
        """Run one lease lifecycle cycle immediately, outside the watchdog timer.

        Equivalent to one iteration of the LeaseWatchdog background loop.
        Finds all leases with ``lease_end_utc < now`` and status in
        ``pending`` / ``active``, patches the corresponding storefront
        resources to ``available``, and updates lease status.

        Returns a summary dict::

            {
                "checked": <int>,   # leases examined
                "released": <int>,  # successfully patched to available
                "forced": <int>,    # force-patched after grace period
                "skipped": <int>,   # errors or transient states
            }

        Intended for:
          - Operator use: release leases immediately without waiting for the
            watchdog timer.
          - Test scenarios: trigger release in integration / e2e tests without
            sleeping for the poll interval.
        """
        lease_lifecycle_svc = getattr(_container_module, "resolved_lease_lifecycle_service", None)
        if lease_lifecycle_svc is None:
            return {"error": "lease_lifecycle_service not initialised", "checked": 0}
        return await lease_lifecycle_svc.check_leases()

    # ------------------------------------------------------------------
    # Router factories
    # ------------------------------------------------------------------

    @classmethod
    def make_health_router(cls) -> APIRouter:
        """Returns the bare ``/health`` router (registered without prefix)."""
        return _health_router

    @classmethod
    def make_system_router(cls) -> APIRouter:
        """Returns the ``/system`` router (registered under ``/api/v1``)."""
        return _system_router
