"""Admin API key authentication middleware.

Protects all routes under ``/admin/*`` and any per-resource admin actions
(listing pause/resume, negotiation advance/force-accept) with a shared secret.

The key is read from ``CONFIG.admin_api_key`` at startup.  Callers supply it
via the ``X-Admin-Key`` request header.

Routes that do NOT require the admin key (normal buyer/operator routes) pass
through unchanged.  The middleware only fires when a request path matches one
of the protected prefixes/patterns defined in ``_ADMIN_PATHS``.

If ``CONFIG.admin_api_key`` is None or empty the middleware is a no-op —
admin endpoints are effectively unprotected.  This is intentional for local
dev where the key is not configured; Helm deployments always inject the key.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


# Path prefixes / suffixes that require an admin key.
# Checked in order; first match wins.
_ADMIN_PREFIXES = ("/admin/",)
_ADMIN_SUFFIXES = (
    "/pause",
    "/resume",
    "/advance",
    "/force-accept",
    "/system/events",
)


def _requires_admin(path: str) -> bool:
    for prefix in _ADMIN_PREFIXES:
        if path.startswith(prefix):
            return True
    for suffix in _ADMIN_SUFFIXES:
        if path.endswith(suffix):
            return True
    return False


class AdminAuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces ``X-Admin-Key`` on admin routes.

    Instantiate and add to the Starlette app::

        from market_storefront.middleware.admin_auth import AdminAuthMiddleware
        app.add_middleware(AdminAuthMiddleware, admin_api_key="secret")
    """

    def __init__(self, app, *, admin_api_key: str | None = None) -> None:
        super().__init__(app)
        # Normalise: treat blank string the same as None (unprotected).
        self._key: str | None = admin_api_key.strip() if admin_api_key else None

    async def dispatch(self, request: Request, call_next):
        if not _requires_admin(request.url.path):
            return await call_next(request)

        if not self._key:
            # No key configured → allow all admin requests (dev mode).
            return await call_next(request)

        supplied = request.headers.get("X-Admin-Key", "")
        if not supplied or supplied != self._key:
            return JSONResponse(
                {"error": "Forbidden", "detail": "Valid X-Admin-Key header required"},
                status_code=403,
            )

        return await call_next(request)
