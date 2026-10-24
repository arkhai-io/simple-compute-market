"""Request authentication and response signing for a storefront's routes.

Administrator, buyer, and seller requests are verified under the marketplace
version 2 contract against the collaborators the storefront injects: its replay
store, its signer, its trusted administrators, and its own principal. Every
authenticated outcome is signed, and so is a refusal raised while
authenticating, so a caller can read why it was refused.

This is the library's one framework-facing module: it reads the request and
wraps the response, so it binds to the web framework the storefront kit builds
the application with. The route services stay framework-free.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from core_storefront.auth import (
    AuthenticatedPrincipal,
    AuthError,
    authenticate_request,
    signed_response_headers,
)
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response
from market_identity import EMPTY_BODY, Identity, Signer, TrustedIdentitySet

from arkhai_api_selling.publish_route import seller_resource

NOT_INITIALIZED = "storefront is not initialized"


@dataclass(frozen=True)
class _ResponseAuthContext:
    operation: str
    resource: str
    authenticated: AuthenticatedPrincipal | None = None


class _RecordedOutcome(Exception):
    def __init__(self, status: int, body: Any) -> None:
        self.status = status
        self.body = body


def bind_response_contract(request: Request, *, operation: str, resource: str) -> None:
    """Name the route a refusal will be bound to, before trust is established.

    The operation and resource come from the route, not from the caller's
    claims, so they are known whether or not authentication goes on to
    succeed. Binding them here is what lets a caller read why it was refused
    instead of discarding an unsigned answer.
    """
    existing = getattr(request.state, "marketplace_response_auth", None)
    if isinstance(existing, _ResponseAuthContext) and existing.authenticated:
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
    """Bind response proof fields after a request has been verified."""
    request.state.marketplace_response_auth = _ResponseAuthContext(
        authenticated=authenticated,
        operation=operation,
        resource=resource,
    )
    if authenticated.exact_retry and authenticated.recorded_outcome is not None:
        status, body = authenticated.recorded_outcome
        raise _RecordedOutcome(status, body)


class StorefrontAuth:
    """One storefront's request authentication and response signing.

    Each collaborator is read when a request is handled, since the replay
    store and the signer exist only while the storefront's lifespan runs.
    """

    def __init__(
        self,
        *,
        replay_store: Callable[[], Any | None],
        signer: Callable[[], Signer | None],
        admin_principals: Callable[[], TrustedIdentitySet],
        seller_principal: Callable[[], Identity],
    ) -> None:
        self._replay_store = replay_store
        self._signer = signer
        self._admin_principals = admin_principals
        self._seller_principal = seller_principal

    def _store(self) -> Any:
        store = self._replay_store()
        if store is None:
            raise HTTPException(status_code=503, detail=NOT_INITIALIZED)
        return store

    async def require_admin_principal(self, request: Request) -> Identity:
        """Authenticate one of the trusted administrators under the route's own name and path."""
        route = request.scope.get("route")
        operation = getattr(route, "name", None)
        if not isinstance(operation, str) or not operation:
            raise HTTPException(status_code=500, detail="admin route has no operation name")
        query = urlencode(sorted(request.query_params.multi_items()))
        resource = request.url.path + (f"?{query}" if query else "")
        return await self.authenticate_admin(request, operation=operation, resource=resource)

    async def authenticate_admin(
        self,
        request: Request,
        *,
        operation: str,
        resource: str,
    ) -> Identity:
        """Authenticate an administrator under an explicit signed operation and resource.

        Routes whose contract a shared typed client defines verify the
        operation and resource that client signs, rather than this
        storefront's route name and path.
        """
        store = self._store()
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
                replay_store=store,
                allowed_principals=self._admin_principals().identities,
            )
        except AuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        bind_response_auth(request, authenticated, operation=operation, resource=resource)
        if not authenticated.dispatch_allowed:
            raise HTTPException(status_code=409, detail="request was already dispatched")
        return authenticated.principal

    async def verify_buyer(
        self,
        request: Request,
        operation: str,
        resource_id: str,
        *,
        expected_principal: Identity,
        body: object = EMPTY_BODY,
        allow_exact_retry: bool = False,
    ) -> AuthenticatedPrincipal:
        """Verify and replay-reserve the claimed buyer before route dispatch."""
        store = self._store()
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
                replay_store=store,
                expected_principal=expected_principal,
            )
        except AuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        bind_response_auth(request, authenticated, operation=operation, resource=resource_id)
        if not authenticated.dispatch_allowed and not (
            allow_exact_retry and authenticated.exact_retry
        ):
            raise HTTPException(status_code=409, detail="request was already dispatched")
        return authenticated

    async def verify_seller(self, request: Request, operation: str, resource_id: str) -> None:
        """Verify the storefront's own seller signature on an operator's request."""
        store = self._store()
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
                replay_store=store,
                expected_principal=self._seller_principal(),
            )
        except AuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        if not authenticated.dispatch_allowed:
            raise HTTPException(status_code=409, detail="request was already dispatched")

    def seller_dependency(
        self, operation: str, *, resource_param: str = "listing_id"
    ) -> Callable[[Request], Awaitable[None]]:
        """A route dependency verifying the seller over the path parameter the signature binds.

        ``resource_param`` names that parameter, so a deal-scoped route signs
        its negotiation rather than a listing; a route naming none signs the
        seller's own resource.
        """

        async def _dep(request: Request) -> None:
            resource_id = request.path_params.get(resource_param, "")
            if not resource_id:
                resource_id = seller_resource(self._seller_principal())
            await self.verify_seller(request, operation, resource_id)

        return _dep

    async def sign_responses(self, request: Request, call_next: Any) -> Response:
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
        signer = self._signer()
        replay_store = self._replay_store()
        if signer is None or replay_store is None:
            return JSONResponse(content={"detail": NOT_INITIALIZED}, status_code=503)

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
                return Response(
                    content=raw_body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    background=response.background,
                )
        else:
            request_id = authenticated.request_id
            if authenticated.dispatch_allowed:
                await replay_store.record_replay_outcome(
                    authenticated.reservation,
                    attempt_token=authenticated.attempt_token,
                    status=response.status_code,
                    body=body,
                )
        headers = dict(response.headers)
        headers.update(
            signed_response_headers(
                signer=signer,
                role="seller",
                method=request.method,
                operation=context.operation,
                resource=context.resource,
                request_id=request_id,
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


__all__ = [
    "NOT_INITIALIZED",
    "StorefrontAuth",
    "bind_response_auth",
    "bind_response_contract",
]
