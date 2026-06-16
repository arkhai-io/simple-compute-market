import logging
import secrets

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


logger = logging.getLogger(__name__)

EXCLUDED_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})


class AdminKeyAuthMiddleware(BaseHTTPMiddleware):
    """Gate the tokens API behind the operator's shared secret.

    Same trust model as the provisioning service's gate: the tokens
    service is an internal dependency of one seller — its callers are
    the storefront (issuance, guard lookups, quota) and the gated
    service's middlewares (consume/verify), both seller-side components
    holding the operator's ``admin_api_key``. Each presents it as
    ``X-Admin-Key``; nothing here is buyer-facing.

    When no key is configured (local dev), the gate is open. ``/health``
    and the docs routes are always open.
    """

    def __init__(self, app, admin_key: str | None = None):
        super().__init__(app)
        self._admin_key = admin_key or None

    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXCLUDED_PATHS or self._admin_key is None:
            return await call_next(request)

        presented = request.headers.get("X-Admin-Key", "")
        if not presented or not secrets.compare_digest(presented, self._admin_key):
            logger.warning(
                "Rejected %s %s: missing/invalid X-Admin-Key",
                request.method, request.url.path,
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing or invalid admin key"},
            )
        return await call_next(request)
