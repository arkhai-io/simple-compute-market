"""Signed marketplace responses and durable exact-retry outcomes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from market_identity import EMPTY_BODY

from market_storefront_kit import get_storefront_container

from .runtime import BareMetalStorefrontRuntime
from core_storefront.auth import AuthenticatedPrincipal, signed_response_headers


@dataclass(frozen=True)
class _ResponseAuthContext:
    authenticated: AuthenticatedPrincipal
    operation: str
    resource: str


class _RecordedOutcome(Exception):
    def __init__(self, status: int, body: Any) -> None:
        self.status = status
        self.body = body


def bind_response_auth(
    request: Request,
    authenticated: AuthenticatedPrincipal,
    *,
    operation: str,
    resource: str,
) -> None:
    request.state.marketplace_response_auth = _ResponseAuthContext(
        authenticated=authenticated,
        operation=operation,
        resource=resource,
    )
    if authenticated.exact_retry and authenticated.recorded_outcome is not None:
        status, body = authenticated.recorded_outcome
        raise _RecordedOutcome(status, body)


async def authenticate_response(request: Request, call_next):
    """Sign every authenticated outcome and persist first-dispatch responses."""
    try:
        response = await call_next(request)
    except _RecordedOutcome as exc:
        response = JSONResponse(content=exc.body, status_code=exc.status)
    except Exception:
        context = getattr(request.state, "marketplace_response_auth", None)
        if context is None:
            raise
        response = JSONResponse(
            content={"detail": "Internal Server Error"},
            status_code=500,
        )

    context = getattr(request.state, "marketplace_response_auth", None)
    if context is None:
        return response
    try:
        runtime = get_storefront_container(request)
    except RuntimeError:
        return JSONResponse(
            content={"detail": "storefront runtime unavailable"},
            status_code=503,
        )
    if not isinstance(runtime, BareMetalStorefrontRuntime):
        return JSONResponse(
            content={"detail": "storefront runtime unavailable"},
            status_code=503,
        )

    raw_body = (
        b"".join([chunk async for chunk in response.body_iterator])
        if hasattr(response, "body_iterator")
        else bytes(response.body)
    )
    body: Any = EMPTY_BODY
    if raw_body:
        try:
            body = json.loads(raw_body)
        except (TypeError, ValueError):
            body = raw_body.decode("utf-8")
    authenticated = context.authenticated
    if authenticated.dispatch_allowed:
        await runtime.db.record_replay_outcome(
            authenticated.reservation,
            attempt_token=authenticated.attempt_token,
            status=response.status_code,
            body=body,
        )
    headers = dict(response.headers)
    headers.update(
        signed_response_headers(
            signer=runtime.marketplace_signer,
            role="seller",
            method=request.method,
            operation=context.operation,
            resource=context.resource,
            request_id=authenticated.request_id,
            status=response.status_code,
            body=body,
        )
    )
    return Response(
        content=raw_body,
        status_code=response.status_code,
        headers=headers,
        background=response.background,
    )
