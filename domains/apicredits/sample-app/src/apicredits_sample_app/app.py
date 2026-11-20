"""A minimal gated service for the e2e topology.

Stands in for "any HTTP API a seller sells metered access to": one
trivial business endpoint (``GET /api/forecast``) behind the
:class:`TokenGateMiddleware`, plus an ungated ``/health``. Every call
to ``/api/*`` spends one credit; a drained key gets a 402 whose body
points back at the listing. The gate config comes entirely from
``APICREDITS_MIDDLEWARE_*`` env vars so the container is configured the
same way the storefront and service are.

The app reads the time of the world from one source, installed from
``APICREDITS_SAMPLE_APP_TIME_SOURCE``: ``"wall"`` by default, ``"injected"`` in
a lane whose every party shares one time the scenario sets. The gate signs every
call to the credits service at that source's instant, and offers no time control
of its own, so under injected time the app serves the lane doubles' time control
and status (``POST /test/time``, ``GET /test/status``) behind the control bearer
token ``APICREDITS_SAMPLE_APP_CONTROL_TOKEN``, outside the gate: setting the
app's time is not a metered call. A wall-time app serves neither.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

import injected_time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from injected_time import TimeSource

from arkhai_api_gate import GateConfig, TokenGate, TokenGateMiddleware
from lane_double_controls import ControlError, Status, TimeControl
from lane_double_controls import routes as controls

ENV_PREFIX = "APICREDITS_MIDDLEWARE_"
AUTHORITY_LABEL = "credits-service"
TIME_SOURCE_SETTING = "APICREDITS_SAMPLE_APP_TIME_SOURCE"
CONTROL_TOKEN_SETTING = "APICREDITS_SAMPLE_APP_CONTROL_TOKEN"

log = logging.getLogger(__name__)


def create_app(
    config: GateConfig | None = None, *, gate: TokenGate | None = None,
    source: TimeSource | None = None, control_token: str | None = None,
) -> FastAPI:
    """Build the gated app.

    ``config`` (default: from ``APICREDITS_MIDDLEWARE_*`` env) configures
    the gate. Tests pass a pre-built ``gate`` wired to a scripted credits
    service so they exercise the real app without a live service.
    ``source`` is the time the app reads, the process's installed source
    unless given; when it is injected the time control is served, and
    ``control_token`` is required.
    """
    config = config or GateConfig.from_env(ENV_PREFIX, authority_label=AUTHORITY_LABEL)
    time_control = TimeControl(source or injected_time.installed())
    app = FastAPI(title="apicredits-sample-app")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/forecast")
    def forecast() -> dict[str, str]:
        """The metered endpoint — one credit per call."""
        return {"forecast": "sunny", "high_c": "24", "low_c": "13"}

    excluded = ["/health", "/docs", "/openapi.json", "/redoc"]
    if time_control.settable:
        if not control_token:
            raise ValueError(
                f"{CONTROL_TOKEN_SETTING} is required when {TIME_SOURCE_SETTING} is "
                '"injected": the time control is served behind it')
        excluded += _add_time_controls(app, time_control, control_token)

    # Gate everything except the excluded paths. Added last so it wraps
    # the routes above.
    kwargs = {"gate": gate} if gate is not None else {"config": config}
    app.add_middleware(TokenGateMiddleware, exclude_paths=tuple(excluded), **kwargs)
    return app


def _add_time_controls(app: FastAPI, time_control: TimeControl, token: str) -> list[str]:
    """Serve the time control and status behind ``token``; the paths served."""

    @app.exception_handler(ControlError)
    async def control_error(_: Request, exc: ControlError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status)

    async def set_time(request: Request) -> Any:
        answer = time_control.set_time(await request.body())
        return answer.model_dump(mode="json", exclude_none=True)

    async def status(request: Request) -> Any:
        return Status(time=time_control.view(), contracts={}).model_dump(
            mode="json", exclude_none=True)

    handlers: dict[controls.ControlRoute, Callable[[Request], Awaitable[Any]]] = {
        controls.TIME: set_time, controls.STATUS: status,
    }
    # Every control route the contract gives the sample app has its handler.
    if set(handlers) != set(controls.routes_for("sample-app", time_settable=True)):
        raise RuntimeError("the sample app serves a different set of control routes "
                           "than the control contract gives it")

    def authorized(handler: Callable[[Request], Awaitable[Any]]
                   ) -> Callable[[Request], Awaitable[Any]]:
        async def endpoint(request: Request) -> Any:
            controls.authorize(request.headers.get("authorization"), token)
            return await handler(request)
        return endpoint

    for route, handler in handlers.items():
        app.add_api_route(route.path, authorized(handler), methods=[route.method])
    return [route.path for route in handlers]


def configured_app() -> FastAPI:
    """The app as its environment configures it, its time source installed first.

    Any time source but ``"wall"`` or ``"injected"`` refuses the start, naming the
    setting; an injected source is announced.
    """
    source = injected_time.install(injected_time.source_for(
        os.environ.get(TIME_SOURCE_SETTING, injected_time.WALL), setting=TIME_SOURCE_SETTING))
    if source.name != injected_time.WALL:
        log.info("%s is %s: the app holds %s until its time control sets it",
                 TIME_SOURCE_SETTING, source.name, source.now())
    return create_app(source=source, control_token=os.environ.get(CONTROL_TOKEN_SETTING))


def main() -> None:
    """Console-script entry point: serve under uvicorn."""
    import uvicorn

    # uvicorn builds the app through the factory after this, so the time
    # source's announcement is shown.
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "apicredits_sample_app.app:configured_app",
        factory=True,
        host=os.environ.get("APICREDITS_SAMPLE_APP_HOST", "0.0.0.0"),
        port=int(os.environ.get("APICREDITS_SAMPLE_APP_PORT", "8085")),
        log_level=os.environ.get("APICREDITS_SAMPLE_APP_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
