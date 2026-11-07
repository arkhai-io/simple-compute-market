"""The system routes' binding: what a request finds before composition.

The integration suite composes every worker, so it cannot reach a control
whose worker is missing; this binds the routers over accessors returning
nothing and checks each answers 503, while an advance against a running
convergence timer answers 409. Status codes only: the bodies are the
integration suite's, through the typed client.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from compute_provisioning_service.controllers.system_controller import make_system_routers

_UNCOMPOSED = [
    ("GET", "/health"),
    ("GET", "/api/v1/system/health"),
    ("GET", "/api/v1/system/status"),
    ("GET", "/api/v1/system/version"),
    ("POST", "/api/v1/system/check-leases"),
    ("POST", "/api/v1/system/fulfillment-convergence/run-cycle"),
    ("POST", "/api/v1/system/fulfillment-convergence/advance-cycle"),
    ("POST", "/api/v1/system/fulfillment-convergence/pause"),
    ("POST", "/api/v1/system/fulfillment-convergence/resume"),
    ("POST", "/api/v1/system/lease-watchdog/pause"),
    ("POST", "/api/v1/system/lease-watchdog/resume"),
]


def _app(*, status_service=None, lease_lifecycle=None, convergence_watchdog=None):
    health, system = make_system_routers(
        status_service=lambda: status_service,
        lease_lifecycle=lambda: lease_lifecycle,
        convergence_watchdog=lambda: convergence_watchdog,
    )
    app = FastAPI()
    app.include_router(health)
    app.include_router(system, prefix="/api/v1")
    return app


async def _status(app, method, path) -> int:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return (await client.request(method, path)).status_code


@pytest.mark.parametrize(("method", "path"), _UNCOMPOSED)
async def test_a_route_whose_collaborator_is_not_composed_answers_503(method, path):
    assert await _status(_app(), method, path) == 503


class _RunningWatchdog:
    is_paused = False

    def __init__(self) -> None:
        self.advanced = False

    async def advance_cycle(self):
        self.advanced = True
        return {}


async def test_an_advance_while_convergence_runs_answers_409_and_advances_nothing():
    watchdog = _RunningWatchdog()

    status = await _status(
        _app(convergence_watchdog=watchdog),
        "POST",
        "/api/v1/system/fulfillment-convergence/advance-cycle",
    )

    assert status == 409
    assert watchdog.advanced is False
