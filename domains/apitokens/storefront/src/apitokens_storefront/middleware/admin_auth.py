"""Admin API key authentication (X-Admin-Key, core verification)."""

from __future__ import annotations

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from core_storefront.auth import AuthError, verify_admin_key

from apitokens_storefront.utils.config import settings

_admin_key_header = APIKeyHeader(
    name="X-Admin-Key",
    auto_error=False,
    description="Admin API key. Required for all /admin/* endpoints and admin actions.",
)


def require_admin_key(key: str | None = Security(_admin_key_header)) -> None:
    """FastAPI dependency enforcing X-Admin-Key.

    With no ``admin_api_key`` configured (local dev) all admin endpoints
    are unprotected.
    """
    try:
        verify_admin_key(configured=settings.admin_api_key, supplied=key)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
