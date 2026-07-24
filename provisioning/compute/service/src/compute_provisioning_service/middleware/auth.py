import logging
import secrets

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


logger = logging.getLogger(__name__)

EXCLUDED_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})


class StorefrontAuthMiddleware(BaseHTTPMiddleware):
    """Gate the provisioning API to the storefront that operates it.

    The provisioning service is an internal dependency of a single
    storefront — there are no other callers, and credentials are always
    mediated back through the storefront, never served to tenants directly.
    The only thing this gate enforces is "the request came from my
    storefront," so the storefront↔provisioning hop can cross an untrusted
    network: both sides share the operator's ``admin_api_key`` (the same
    secret the provisioning→storefront callback already presents), and the
    storefront sends it as ``X-Admin-Key`` on every request.

    When no key is configured (local dev), the gate is open. ``/health`` and
    the docs routes are always open.
    """

    def __init__(self, app, admin_key: str | None = None):
        super().__init__(app)
        self._admin_key = admin_key or None

    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXCLUDED_PATHS or self._admin_key is None:
            return await call_next(request)

        presented = request.headers.get("X-Admin-Key", "")
        if not presented or not secrets.compare_digest(presented, self._admin_key):
            logger.warning("Rejected %s %s: missing/invalid X-Admin-Key", request.method, request.url.path)
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing or invalid admin key"},
            )
        return await call_next(request)
