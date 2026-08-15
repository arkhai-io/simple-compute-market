"""Scheme-neutral, body-bound buyer authentication dependencies."""

from __future__ import annotations

from typing import Any

from core_storefront.auth import AuthenticatedPrincipal, AuthError, authenticate_request
from fastapi import HTTPException, Request
from market_identity import EMPTY_BODY, Identity

import market_storefront.container as _container


async def _verify(
    request: Request,
    operation: str,
    resource_id: str,
    claimed_principal: Identity,
    body: Any = EMPTY_BODY,
) -> AuthenticatedPrincipal:
    """Authenticate one buyer request against its explicit principal claim."""

    cached = getattr(request.state, "marketplace_authenticated", None)
    if isinstance(cached, AuthenticatedPrincipal):
        if cached.role != "buyer" or cached.principal != claimed_principal:
            raise HTTPException(
                status_code=403,
                detail="Authenticated buyer principal does not match the request",
            )
        return cached

    replay_store = _container.resolved_sqlite_client
    if replay_store is None:
        raise HTTPException(
            status_code=503, detail="authentication store is unavailable"
        )
    try:
        authenticated = await authenticate_request(
            headers=request.headers,
            method=request.method,
            operation=operation,
            resource=resource_id,
            body=body,
            expected_role="buyer",
            replay_store=replay_store,
            expected_principal=claimed_principal,
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    request.state.marketplace_authenticated = authenticated
    return authenticated


async def negotiate_new_auth(body, request: Request) -> AuthenticatedPrincipal:
    from core_storefront.models.negotiation_models import NegotiateNewRequest

    if not isinstance(body, NegotiateNewRequest):
        raise HTTPException(status_code=400, detail="Invalid request body type")
    return await _verify(
        request,
        "negotiate_new",
        body.listing_id,
        body.buyer_principal,
        body.model_dump(mode="json"),
    )


async def negotiate_continue_auth(
    neg_id: str, body, request: Request
) -> AuthenticatedPrincipal:
    from core_storefront.models.negotiation_models import NegotiateContinueRequest

    if not isinstance(body, NegotiateContinueRequest):
        raise HTTPException(status_code=400, detail="Invalid request body type")
    return await _verify(
        request,
        "negotiate_continue",
        neg_id,
        body.buyer_principal,
        body.model_dump(mode="json"),
    )


async def settle_escrow_auth(
    escrow_uid: str,
    body,
    request: Request,
    *,
    negotiation_thread: Any = None,
) -> AuthenticatedPrincipal:
    from market_storefront.models.settle_models import VmSettleRequest

    if not isinstance(body, VmSettleRequest):
        raise HTTPException(status_code=400, detail="Invalid request body type")
    thread = negotiation_thread
    if thread is None:
        replay_store = _container.resolved_sqlite_client
        if replay_store is None:
            raise HTTPException(
                status_code=503, detail="authentication store is unavailable"
            )
        thread = await replay_store.load_negotiation_thread_row(
            negotiation_id=body.negotiation_id
        )
    if not isinstance(thread, dict):
        raise HTTPException(status_code=404, detail="accepted negotiation not found")
    persisted_negotiation_id = str(thread.get("negotiation_id") or "")
    if persisted_negotiation_id and persisted_negotiation_id != body.negotiation_id:
        raise HTTPException(
            status_code=403,
            detail="settlement negotiation does not match persisted binding",
        )
    try:
        persisted_buyer = Identity.model_validate(thread.get("buyer_principal"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail="accepted negotiation has no valid buyer owner",
        ) from exc
    if body.buyer_principal != persisted_buyer:
        raise HTTPException(
            status_code=403,
            detail="settlement buyer does not match persisted owner",
        )
    return await _verify(
        request,
        "settle_escrow",
        escrow_uid,
        persisted_buyer,
        body.model_dump(mode="json"),
    )


async def deal_heartbeat_auth(
    escrow_uid: str, body, request: Request
) -> AuthenticatedPrincipal:
    from core_storefront.models.deal_models import DealHeartbeatRequest

    if not isinstance(body, DealHeartbeatRequest):
        raise HTTPException(status_code=400, detail="Invalid request body type")
    return await _verify(
        request,
        "deal_heartbeat",
        escrow_uid,
        body.buyer_principal,
        body.model_dump(mode="json"),
    )
