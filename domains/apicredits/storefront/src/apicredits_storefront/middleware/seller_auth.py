"""Seller route authentication through the shared marketplace v2 contract."""

from __future__ import annotations

import json

from fastapi import HTTPException, Request
from market_identity import EMPTY_BODY

from apicredits_storefront.middleware.response_auth import bind_response_contract
from core_storefront.auth import AuthError, authenticate_request


def _expected_identity():
    from apicredits_storefront.utils.config import resolve_identity_config

    return resolve_identity_config().principal


async def verify_seller_signature(
    request: Request,
    operation: str,
    resource_id: str,
) -> None:
    import apicredits_storefront.container as container

    if container.resolved_sqlite_client is None:
        raise HTTPException(status_code=503, detail="storefront is not initialized")
    bind_response_contract(request, operation=operation, resource=resource_id)
    try:
        body: object = None
        if request.method not in {"GET", "DELETE"}:
            # Seller mutations may carry no body (close, refund); the signature
            # then binds the empty-body hash, so an absent body must not parse.
            raw = await request.body()
            body = json.loads(raw) if raw else EMPTY_BODY
        authenticated = await authenticate_request(
            headers=request.headers,
            method=request.method,
            operation=operation,
            resource=resource_id,
            body=body,
            expected_role="seller",
            replay_store=container.resolved_sqlite_client,
            expected_principal=_expected_identity(),
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if not authenticated.dispatch_allowed:
        raise HTTPException(status_code=409, detail="request was already dispatched")


def make_seller_auth_dep(operation: str, *, resource_param: str = "listing_id"):
    """Build a dependency bound to the configured seller principal.

    ``resource_param`` names the path parameter the signature binds, so a
    deal-scoped route signs its negotiation rather than a listing.
    """

    async def _dep(request: Request) -> None:
        resource_id = request.path_params.get(resource_param, "")
        if not resource_id:
            identity = _expected_identity()
            resource_id = f"{identity.scheme.value}:{identity.identifier}"
        await verify_seller_signature(request, operation, resource_id)

    return _dep
