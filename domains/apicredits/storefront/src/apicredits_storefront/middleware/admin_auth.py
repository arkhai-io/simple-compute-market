"""Admin route authentication through the marketplace v2 contract."""

from __future__ import annotations

import json
from urllib.parse import urlencode

from fastapi import HTTPException, Request
from market_identity import EMPTY_BODY, Identity

import apicredits_storefront.container as container
from apicredits_storefront.utils.config import resolve_admin_identities
from core_storefront.auth import AuthError, authenticate_request
from apicredits_storefront.middleware.response_auth import bind_response_auth


async def require_admin_principal(request: Request) -> Identity:
    """Authenticate one of the configured admin principals."""
    if container.resolved_sqlite_client is None:
        raise HTTPException(status_code=503, detail="storefront is not initialized")
    route = request.scope.get("route")
    operation = getattr(route, "name", None)
    if not isinstance(operation, str) or not operation:
        raise HTTPException(status_code=500, detail="admin route has no operation name")
    query = urlencode(sorted(request.query_params.multi_items()))
    resource = request.url.path + (f"?{query}" if query else "")
    raw_body = await request.body()
    try:
        body = json.loads(raw_body) if raw_body else EMPTY_BODY
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="request body must be JSON") from exc
    try:
        authenticated = await authenticate_request(
            headers=request.headers,
            method=request.method,
            operation=operation,
            resource=resource,
            body=body,
            expected_role="admin",
            replay_store=container.resolved_sqlite_client,
            allowed_principals=resolve_admin_identities().identities,
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    bind_response_auth(
        request,
        authenticated,
        operation=operation,
        resource=resource,
    )
    if not authenticated.dispatch_allowed:
        raise HTTPException(status_code=409, detail="request was already dispatched")
    return authenticated.principal
