"""Buyer authentication through the shared body-bound marketplace contract."""

from __future__ import annotations

from fastapi import HTTPException, Request

from core_storefront.auth import AuthError, AuthenticatedPrincipal, authenticate_request
from market_identity import EMPTY_BODY, Identity
from apicredits_storefront.middleware.response_auth import (
    bind_response_auth,
    bind_response_contract,
)


async def _verify(
    request: Request,
    operation: str,
    resource_id: str,
    *,
    expected_principal: Identity,
    body: object = EMPTY_BODY,
    allow_exact_retry: bool = False,
) -> AuthenticatedPrincipal:
    """Verify and replay-reserve a complete principal before route dispatch."""
    import apicredits_storefront.container as container

    replay_store = container.resolved_sqlite_client
    if replay_store is None:
        raise HTTPException(status_code=503, detail="storefront is not initialized")
    payload = (
        body.model_dump(mode="json", exclude_none=True, exclude_unset=True)
        if hasattr(body, "model_dump")
        else body
    )
    bind_response_contract(request, operation=operation, resource=resource_id)
    try:
        authenticated = await authenticate_request(
            headers=request.headers,
            method=request.method,
            operation=operation,
            resource=resource_id,
            body=payload,
            expected_role="buyer",
            replay_store=replay_store,
            expected_principal=expected_principal,
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    bind_response_auth(
        request,
        authenticated,
        operation=operation,
        resource=resource_id,
    )
    if not authenticated.dispatch_allowed and not (
        allow_exact_retry and authenticated.exact_retry
    ):
        raise HTTPException(status_code=409, detail="request was already dispatched")
    return authenticated
