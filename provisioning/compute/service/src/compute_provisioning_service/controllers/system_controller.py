"""The provisioning service's system routes.

``GET /health`` stays at the root, where Kubernetes probes expect it; every
other route is under ``/api/v1/system``:

- ``GET /health`` and ``GET /system/health``: local liveness.
- ``GET /system/status``: the operator's status, including execution and the
  readiness components.
- ``GET /system/version``: the service version and active profiles.
- ``POST /system/check-leases``: one lease lifecycle cycle, run whether or not
  the watchdog's timer is paused.
- ``POST /system/fulfillment-convergence/{run-cycle,advance-cycle,pause,resume}``
  and ``POST /system/lease-watchdog/{pause,resume}``: the workers' controls.

Health and status answer 503 with their body when degraded. A worker control
answers 503 while its worker is not composed, and 409 when the request
conflicts with the worker's state: an advance needs the convergence timer
paused. Each manual cycle runs the worker's own production cycle.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from compute_provisioning.route_errors import require_composed
from compute_provisioning_contracts import (
    HealthResponse,
    SystemStatusResponse,
    VersionResponse,
)
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from compute_provisioning_service.controllers.route_errors import routed
from compute_provisioning_service.services.system_status import SystemStatusService


def make_system_routers(
    *,
    status_service: Callable[[], SystemStatusService | None],
    lease_lifecycle: Callable[[], Any],
    convergence_watchdog: Callable[[], Any],
) -> tuple[APIRouter, APIRouter]:
    """The root health router and the ``/system`` router, over accessors.

    The service mounts both when it builds the app and composes their
    collaborators at startup, so each request resolves them through the
    accessors; one not yet composed answers 503.
    """
    health_router = APIRouter(tags=["system"])
    system_router = APIRouter(prefix="/system", tags=["system"])

    def require(accessor: Callable[[], Any], what: str) -> Any:
        return routed(lambda: require_composed(accessor, what))

    def health_response() -> JSONResponse:
        body = require(status_service, "system status").health()
        return JSONResponse(
            content=body.model_dump(mode="json"),
            status_code=200 if body.status == "ok" else 503,
        )

    @health_router.get(
        "/health",
        response_model=HealthResponse,
        summary="Service health check (liveness probe)",
        description=(
            "Database and job processor, with no outbound call. "
            "Used as the Kubernetes liveness and readiness probe."
        ),
    )
    async def health_bare() -> JSONResponse:
        return health_response()

    @system_router.get(
        "/health",
        response_model=HealthResponse,
        summary="Service health check (versioned alias)",
    )
    async def health_system() -> JSONResponse:
        return health_response()

    @system_router.get(
        "/status",
        response_model=SystemStatusResponse,
        summary="Operational status: storefront, watchdog, contract, and execution",
    )
    async def system_status() -> JSONResponse:
        """Heavier than ``/health``: it calls the storefront, runs ``ansible
        --version``, and hashes playbooks. Not a probe."""
        body = await require(status_service, "system status").status()
        return JSONResponse(
            content=body.model_dump(mode="json"),
            status_code=200 if body.status == "ok" else 503,
        )

    @system_router.get(
        "/version",
        response_model=VersionResponse,
        summary="Service version and active configuration profiles",
    )
    def service_version() -> VersionResponse:
        return require(status_service, "system status").version()

    @system_router.post(
        "/check-leases",
        summary="Run one lease lifecycle cycle, paused or not (admin)",
    )
    async def check_leases() -> dict:
        """One cycle of the lease watchdog, run whether or not its timer is
        paused, so a test or an operator advances leases one step at a time."""
        return await require(lease_lifecycle, "the lease lifecycle").force_check_leases()

    @system_router.post(
        "/fulfillment-convergence/run-cycle",
        summary="Run one fulfillment convergence cycle (admin)",
    )
    async def run_fulfillment_convergence_cycle() -> dict:
        """The production cycle as it is. Its response holds bounded
        diagnostics, never prepared operations, provider payloads, or
        credentials."""
        watchdog = require(convergence_watchdog, "fulfillment convergence")
        return await watchdog.run_cycle()

    @system_router.post(
        "/fulfillment-convergence/advance-cycle",
        summary="Advance fulfillment convergence by one cycle (admin)",
    )
    async def advance_fulfillment_convergence_cycle() -> dict:
        """One cycle that reaches this worker's own claimed rows.

        A pending provider poll keeps its row claimed so the claim lease
        spaces the next poll, which a plain cycle cannot reach until the lease
        lapses. This releases the worker's own claims first, so one call is one
        observable advance. Releasing them while timer cycles run could act
        twice on one in-flight operation, so the timer must be paused first:
        409 otherwise.
        """
        watchdog = require(convergence_watchdog, "fulfillment convergence")
        if not watchdog.is_paused:
            raise HTTPException(
                status_code=409,
                detail="pause fulfillment convergence before advancing it",
            )
        return await watchdog.advance_cycle()

    @system_router.post(
        "/fulfillment-convergence/pause",
        summary="Pause timer-driven fulfillment convergence cycles (admin)",
    )
    def pause_fulfillment_convergence() -> dict:
        """Hold the timer; explicit cycles still run."""
        require(convergence_watchdog, "fulfillment convergence").pause()
        return {"paused": True}

    @system_router.post(
        "/fulfillment-convergence/resume",
        summary="Resume timer-driven fulfillment convergence cycles (admin)",
    )
    def resume_fulfillment_convergence() -> dict:
        require(convergence_watchdog, "fulfillment convergence").resume()
        return {"paused": False}

    @system_router.post(
        "/lease-watchdog/pause",
        summary="Pause timer-driven lease watchdog cycles (admin)",
    )
    def pause_lease_watchdog() -> dict:
        """Hold the timer at its gate; ``check-leases`` still runs a cycle."""
        require(lease_lifecycle, "the lease lifecycle").pause()
        return {"paused": True}

    @system_router.post(
        "/lease-watchdog/resume",
        summary="Resume timer-driven lease watchdog cycles (admin)",
    )
    def resume_lease_watchdog() -> dict:
        require(lease_lifecycle, "the lease lifecycle").resume()
        return {"paused": False}

    return health_router, system_router


__all__ = ["make_system_routers"]
