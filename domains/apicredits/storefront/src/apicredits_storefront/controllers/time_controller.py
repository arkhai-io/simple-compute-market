"""The time-setting route: the storefront's injected time, set by its administrator.

Bound through the storefront kit's route service, so the path, the signed
operation and the answers are the canonical storefront client's, the same on
every storefront. The application mounts this router only while the process's
source is injected time, and the request is authenticated without its
timestamp's freshness, as the time-setting operation is.
"""

from __future__ import annotations

from core_storefront.auth import ADMIN_TIME_OPERATION, ADMIN_TIME_RESOURCE
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from market_storefront_kit import (
    StorefrontTimeRouteService,
    TimeRouteError,
    time_refusal_body,
)

from apicredits_storefront.middleware.admin_auth import authenticate_admin

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.post("/time")
async def set_time(request: Request) -> JSONResponse:
    """Set the storefront's injected time to the instant the body carries."""
    await authenticate_admin(
        request, operation=ADMIN_TIME_OPERATION, resource=ADMIN_TIME_RESOURCE
    )
    try:
        answer = StorefrontTimeRouteService().set_time(await request.body())
    except TimeRouteError as error:
        return JSONResponse(
            status_code=error.status_code, content=time_refusal_body(error)
        )
    return JSONResponse(content=answer)
