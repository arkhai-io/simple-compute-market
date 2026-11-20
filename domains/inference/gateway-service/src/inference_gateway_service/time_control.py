"""The gateway's time control under injected time: a time route and a status behind a bearer token.

The gate signs every call to the inference authority at the process's time
source and offers no time control of its own. In a lane whose every party shares
one time a scenario sets, the gateway therefore serves the control the lane
doubles serve, on the wire their typed client speaks: ``POST /test/time`` with
``{"now": <Unix seconds>}``, answered ``{"source": "injected", "now": …}``, and
``GET /test/status``, answered ``{"time": {…}, "contracts": {}}``; a refusal is
``{"code", "message"}``. The time component's route service validates and
performs both, so the gateway depends on no test tool; its suite drives the
control through the doubles' client, which holds the two to one wire.
"""

from __future__ import annotations

import hmac
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from injected_time import TimeRouteError, TimeRouteService, TimeSource

TIME_PATH = "/test/time"
STATUS_PATH = "/test/status"
#: The paths the control serves, which never reach the gate.
CONTROL_PATHS = frozenset({TIME_PATH, STATUS_PATH})

# The scheme name is case-insensitive (RFC 7235); a token holds no whitespace.
_BEARER = re.compile(r"^bearer (\S+)$", re.IGNORECASE)


class _Refused(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.body = {"code": code, "message": message}


def _authorize(authorization: str | None, token: str) -> None:
    match = _BEARER.fullmatch(authorization or "")
    if match is None or not hmac.compare_digest(match.group(1).encode(), token.encode()):
        raise _Refused(401, "authentication_required", "a control call needs the gateway's control bearer token")


def control_app(source: TimeSource, token: str) -> FastAPI:
    """The time route and the status over ``source``, each behind ``token``."""
    routes = TimeRouteService(source)
    if not routes.settable:
        raise ValueError("a wall-time gateway serves no time control")
    app = FastAPI(title="inference-gateway-time-control", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(_Refused)
    async def refused(_: Request, error: _Refused) -> JSONResponse:
        return JSONResponse(error.body, status_code=error.status)

    @app.post(TIME_PATH)
    async def set_time(request: Request) -> Any:
        _authorize(request.headers.get("authorization"), token)
        try:
            return routes.set_time(await request.body())
        except TimeRouteError as error:
            raise _Refused(error.status_code, error.code, error.detail) from None

    @app.get(STATUS_PATH)
    async def status(request: Request) -> Any:
        _authorize(request.headers.get("authorization"), token)
        # The gateway serves no contract resource of the doubles'.
        return {"time": routes.status(), "contracts": {}}

    return app
