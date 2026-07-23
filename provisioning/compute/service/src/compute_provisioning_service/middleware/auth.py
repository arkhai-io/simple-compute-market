"""Credential-bound authentication for storefront-to-provisioning calls."""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Mapping
from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

EXCLUDED_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})
LEGACY_STOREFRONT_PRINCIPAL = "legacy-admin"
LOCAL_DEVELOPMENT_PRINCIPAL = "local-development"


def configured_storefront_principals(
    *,
    admin_key: str | None,
    principal_keys: Mapping[str, str] | str | None = None,
) -> dict[str, str]:
    """Validate configured principal-to-secret bindings.

    JSON configuration is accepted for Dynaconf/environment compatibility.
    The legacy key remains one explicit principal rather than a bypass around
    principal ownership.
    """
    parsed: Any = principal_keys
    if isinstance(parsed, str):
        raw = parsed.strip()
        parsed = json.loads(raw) if raw else {}
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, Mapping):
        raise ValueError("storefront_api_keys must be a JSON object")

    bindings: dict[str, str] = {}
    for raw_principal, raw_secret in parsed.items():
        principal = str(raw_principal).strip()
        secret = str(raw_secret).strip()
        if not principal or not secret:
            raise ValueError("storefront principals and secrets must be non-empty")
        bindings[principal] = secret
    legacy_secret = str(admin_key or "").strip()
    if legacy_secret:
        existing = bindings.get(LEGACY_STOREFRONT_PRINCIPAL)
        if existing is not None and existing != legacy_secret:
            raise ValueError("legacy storefront principal has conflicting secrets")
        bindings[LEGACY_STOREFRONT_PRINCIPAL] = legacy_secret
    if len(set(bindings.values())) != len(bindings):
        raise ValueError("each storefront principal must use a distinct secret")
    return bindings


class StorefrontAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate an operator-configured storefront principal by secret.

    ``X-Agent-ID`` remains correlation metadata and never grants authority.
    Open local development still receives one stable principal so downstream
    ownership checks use the same shape as authenticated deployments.
    """

    def __init__(
        self,
        app,
        admin_key: str | None = None,
        principal_keys: Mapping[str, str] | str | None = None,
    ) -> None:
        super().__init__(app)
        self._principal_keys = configured_storefront_principals(
            admin_key=admin_key,
            principal_keys=principal_keys,
        )

    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)

        if not self._principal_keys:
            request.state.storefront_principal = LOCAL_DEVELOPMENT_PRINCIPAL
            return await call_next(request)

        presented = request.headers.get("X-Admin-Key", "")
        matched_principal: str | None = None
        for principal, expected in self._principal_keys.items():
            if secrets.compare_digest(presented, expected):
                matched_principal = principal
        if matched_principal is None:
            logger.warning(
                "Rejected %s %s: missing/invalid X-Admin-Key",
                request.method,
                request.url.path,
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing or invalid admin key"},
            )
        request.state.storefront_principal = matched_principal
        return await call_next(request)
