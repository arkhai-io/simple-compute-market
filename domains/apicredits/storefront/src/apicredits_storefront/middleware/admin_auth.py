"""Admin route authentication through the marketplace v2 contract."""

from __future__ import annotations

import json
from urllib.parse import quote, urlencode

from fastapi import HTTPException, Request
from market_identity import EMPTY_BODY, Identity

import apicredits_storefront.container as container
from apicredits_storefront.utils.config import resolve_admin_identities
from core_storefront.auth import (
    AuthError,
    admin_time_setting_operation,
    authenticate_request,
)
from apicredits_storefront.middleware.response_auth import (
    bind_response_auth,
    bind_response_contract,
)

# The query parameters a negotiation list may carry. Each is bound into the
# signed resource, so any other parameter, or a repeated one, could change what
# is returned without changing what was signed, and is refused.
_NEGOTIATION_LIST_QUERY = frozenset(
    {"limit", "offset", "buyer_identifier", "buyer_scheme", "terminal_state"}
)


async def require_admin_principal(request: Request) -> Identity:
    """Authenticate one of the configured admin principals."""
    route = request.scope.get("route")
    operation = getattr(route, "name", None)
    if not isinstance(operation, str) or not operation:
        raise HTTPException(status_code=500, detail="admin route has no operation name")
    query = urlencode(sorted(request.query_params.multi_items()))
    resource = request.url.path + (f"?{query}" if query else "")
    return await authenticate_admin(request, operation=operation, resource=resource)


def negotiation_list_resource(request: Request, listing_id: str) -> str:
    """The signed resource of a negotiation list, rebuilt from its query.

    The canonical storefront client builds the same string: the listing, then
    the sorted, percent-encoded query with ``limit`` and ``offset`` defaulted.
    """
    query = request.query_params
    if not set(query.keys()) <= _NEGOTIATION_LIST_QUERY or any(
        len(query.getlist(name)) != 1 for name in query.keys()
    ):
        raise HTTPException(
            status_code=400,
            detail="negotiation query contains an unauthenticated alias",
        )
    values = {"limit": query.get("limit", "50"), "offset": query.get("offset", "0")}
    for name in ("buyer_identifier", "buyer_scheme", "terminal_state"):
        value = query.get(name)
        if value is not None:
            values[name] = value
    return f"{listing_id}/negotiations?" + urlencode(
        sorted(values.items()), quote_via=quote, safe=""
    )


async def authenticate_admin(
    request: Request,
    *,
    operation: str,
    resource: str,
) -> Identity:
    """Authenticate an administrator under an explicit signed operation and resource.

    Routes whose contract a shared typed client defines -- the lifecycle
    controls and negotiation routes every storefront serves -- verify the
    operation and resource that client signs, rather than this storefront's
    route name and path. The time-setting operation, while it is mounted, is
    verified without its timestamp's freshness.
    """
    if container.resolved_sqlite_client is None:
        raise HTTPException(status_code=503, detail="storefront is not initialized")
    raw_body = await request.body()
    try:
        body = json.loads(raw_body) if raw_body else EMPTY_BODY
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="request body must be JSON") from exc
    bind_response_contract(request, operation=operation, resource=resource)
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
            time_setting_operation=admin_time_setting_operation(),
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
