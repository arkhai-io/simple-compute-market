"""Admin API key authentication.

Replaced ``AdminAuthMiddleware`` (Starlette path-matching middleware) with a
FastAPI ``Security()`` dependency. This makes admin auth explicit per-router,
visible to OpenAPI/Swagger, and eliminates the fragile path-pattern list.

Usage on a router::

    from market_storefront.middleware.admin_auth import require_admin_key
    from fastapi import APIRouter

    router = APIRouter(
        prefix="/api/v1/admin",
        dependencies=[Depends(require_admin_key)],
    )

Or per-endpoint::

    @router.post("/{listing_id}/pause", dependencies=[Depends(require_admin_key)])
    async def pause(...): ...

TOMBSTONE: AdminAuthMiddleware has been removed.
The server.py ``app.add_middleware(AdminAuthMiddleware, ...)`` call is deleted.
"""
from __future__ import annotations

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from market_storefront.utils.config import CONFIG

_admin_key_header = APIKeyHeader(
    name="X-Admin-Key",
    auto_error=False,
    description="Admin API key. Required for all /admin/* endpoints and admin actions.",
)


def require_admin_key(key: str | None = Security(_admin_key_header)) -> None:
    """FastAPI dependency that enforces the X-Admin-Key header.

    When ``CONFIG.admin_api_key`` is not set (local dev), all admin endpoints
    are unprotected — matching the previous middleware behaviour.
    """
    configured = CONFIG.admin_api_key
    if not configured:
        return  # dev mode — unprotected
    if not key or key != configured:
        raise HTTPException(
            status_code=403,
            detail="Valid X-Admin-Key header required",
        )
