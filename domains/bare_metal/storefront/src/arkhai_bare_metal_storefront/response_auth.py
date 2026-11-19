"""Signed marketplace responses and durable exact-retry outcomes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from market_identity import EMPTY_BODY
from market_deal_servicing.evidence import EvidenceSession, transaction

from market_storefront_kit import get_storefront_container

from .runtime import BareMetalStorefrontRuntime
from core_storefront.auth import AuthenticatedPrincipal, signed_response_headers

#: The buyer routes whose answer can carry access material, by operation, each
#: with the response members that hold it. Such a route's outcome is recorded
#: without those members, and an exact retry runs the route again, which reads
#: afresh under current admission and is refused after an end, rather than
#: replaying a recorded body. The status route carries no member of its own,
#: but it reports whether access is live, so its retry reads again too.
#: Request reservation, first-use skew, changed-request refusal and response
#: signing are as for every route. See
#: openspec/specs/marketplace-identity/spec.md, "Body-bound authenticated
#: request and response version".
CREDENTIAL_CAPABLE_ROUTES: Mapping[str, frozenset[str]] = MappingProxyType({
    "bare_metal_fulfillment_access": frozenset({"host", "port", "username"}),
    "bare_metal_fulfillment_status": frozenset(),
})


def without_access_material(operation: str, body: Any) -> Any:
    """``body`` as a credential-capable route's outcome is recorded: without its access material."""
    members = CREDENTIAL_CAPABLE_ROUTES.get(operation)
    if not members or not isinstance(body, dict):
        return body
    return {key: value for key, value in body.items() if key not in members}


@dataclass(frozen=True)
class _ResponseAuthContext:
    operation: str
    resource: str
    authenticated: AuthenticatedPrincipal | None = None


class _RecordedOutcome(Exception):
    def __init__(self, status: int, body: Any) -> None:
        self.status = status
        self.body = body


def bind_response_contract(
    request: Request, *, operation: str, resource: str
) -> None:
    """Name the route a refusal will be bound to, before trust is established.

    The operation and resource come from the route, not from the caller's
    claims, so they are known whether or not authentication goes on to
    succeed. Binding them here is what lets a caller read why it was refused
    instead of discarding an unsigned answer.
    """

    existing = getattr(request.state, "marketplace_response_auth", None)
    if isinstance(existing, _ResponseAuthContext) and existing.authenticated:
        # A route that authenticates twice has already bound the stronger of
        # the two contexts; naming the route again must not discard it.
        return
    request.state.marketplace_response_auth = _ResponseAuthContext(
        operation=operation,
        resource=resource,
    )


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
    # A credential-capable route resolves its own exact retry by running again;
    # every other route replays its recorded outcome.
    if (
        authenticated.exact_retry
        and authenticated.recorded_outcome is not None
        and operation not in CREDENTIAL_CAPABLE_ROUTES
    ):
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
    if authenticated is None:
        # Refused while authenticating: nothing was reserved and nothing was
        # dispatched, so there is no outcome to record. The caller's own
        # request identity is still bindable, and a caller that sent none has
        # nothing to compare a signature against.
        request_id = request.headers.get("X-Market-Request-ID") or None
        if request_id is None:
            return response
    else:
        request_id = authenticated.request_id
        if authenticated.dispatch_allowed:
            await runtime.db.record_replay_outcome(
                authenticated.reservation,
                attempt_token=authenticated.attempt_token,
                status=response.status_code,
                body=without_access_material(context.operation, body),
            )
    headers = dict(response.headers)
    headers.update(
        signed_response_headers(
            signer=runtime.marketplace_signer,
            role="seller",
            method=request.method,
            operation=context.operation,
            resource=context.resource,
            request_id=request_id,
            status=response.status_code,
            body=body,
        )
    )
    if isinstance(body, dict) and body.get("negotiation_id") and body.get("agreement_bytes"):
        with transaction(runtime.db.db_path) as conn:
            EvidenceSession(conn).capture(
                body["negotiation_id"], evidence_id="seller-response:" + request_id,
                body=raw_body, headers=headers,
                context={"operation": context.operation, "resource": context.resource},
                recorded_at=int(headers["X-Market-Timestamp"]),
            )
    return Response(
        content=raw_body,
        status_code=response.status_code,
        headers=headers,
        background=response.background,
    )
