"""Admin API key authentication.

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

"""
from __future__ import annotations

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from market_core.storefront.auth import AuthError, verify_admin_key
from market_storefront.utils.config import settings

_admin_key_header = APIKeyHeader(
    name="X-Admin-Key",
    auto_error=False,
    description="Admin API key. Required for all /admin/* endpoints and admin actions.",
)

def require_admin_key(key: str | None = Security(_admin_key_header)) -> None:
    """FastAPI dependency that enforces the X-Admin-Key header.

    When ``settings.admin_api_key`` is not set (local dev), all admin endpoints
    are unprotected — matching the previous middleware behaviour.
    """
    configured = settings.admin_api_key
    try:
        verify_admin_key(configured=configured, supplied=key)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
