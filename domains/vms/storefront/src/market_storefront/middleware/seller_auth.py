"""Scheme-neutral v2 authentication for listing lifecycle mutations."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from core_storefront.auth import (
    AuthenticatedPrincipal,
    AuthError,
    authenticate_request,
    signed_response_headers,
)
from fastapi import Request
from market_identity import EMPTY_BODY, Identity
from starlette.responses import JSONResponse, Response

import market_storefront.container as _container


@dataclass(frozen=True, slots=True)
class ListingMutation:
    operation: str
    resource: str
    role: str
    principal: Identity
    body: Any


logger = logging.getLogger(__name__)


def _seller_signer():
    signer = _container.resolved_marketplace_signer
    if signer is None:
        raise AuthError("Storefront marketplace signer is unavailable", status_code=503)
    return signer


async def _durable_buyer(*, listing_id: str, escrow_uid: str | None = None) -> Identity:
    db = _container.resolved_sqlite_client
    if db is None:
        raise AuthError("Storefront identity state is unavailable", status_code=503)
    escrow = (
        await db.load_escrow(escrow_uid=escrow_uid)
        if escrow_uid
        else await db.load_primary_escrow_for_listing(listing_id=listing_id)
    )
    if not escrow:
        raise AuthError(
            "Listing has no durable buyer ownership record", status_code=409
        )
    thread = await db.load_negotiation_thread_row(
        negotiation_id=str(escrow["negotiation_id"])
    )
    if not thread or str(thread.get("our_listing_id") or "") != listing_id:
        raise AuthError("Escrow does not belong to this listing", status_code=403)
    try:
        return Identity.model_validate(thread["buyer_principal"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError(
            "Durable buyer principal is malformed", status_code=409
        ) from exc


async def resolve_listing_mutation(
    request: Request, body: Any
) -> ListingMutation | None:
    """Map one protected listing mutation to its exact v2 authorization binding."""

    path = request.url.path.rstrip("/")
    prefix = "/api/v1/listings/"
    if request.method != "POST" or not path.startswith(prefix):
        return None
    suffix = path[len(prefix) :]
    signer = _seller_signer()
    if suffix == "create":
        return ListingMutation("create_listing", "", "seller", signer.identity, body)

    parts = suffix.split("/")
    if len(parts) != 2 or not parts[0]:
        return None
    listing_id, action = parts
    seller_operations = {
        "close": "close_listing",
        "refund": "refund_listing",
        "claim": "claim_listing",
        "arbitrate": "arbitrate_listing",
    }
    if action == "close":
        return ListingMutation(
            "close_listing", listing_id, "seller", signer.identity, EMPTY_BODY
        )
    if action in seller_operations:
        if not isinstance(body, dict):
            raise AuthError("Malformed listing mutation body", status_code=400)
        if action == "claim":
            try:
                Identity.model_validate(body.get("claimant_principal"))
            except (TypeError, ValueError) as exc:
                raise AuthError(
                    "Malformed claimant principal", status_code=400
                ) from exc
        if action == "refund":
            try:
                Identity.model_validate(body.get("buyer_principal"))
            except (TypeError, ValueError) as exc:
                raise AuthError(
                    "Malformed refund buyer principal", status_code=400
                ) from exc
        return ListingMutation(
            seller_operations[action], listing_id, "seller", signer.identity, body
        )
    if action == "reclaim":
        if not isinstance(body, dict):
            raise AuthError("Malformed reclaim body", status_code=400)
        try:
            payer = Identity.model_validate(body.get("payer_principal"))
        except (TypeError, ValueError) as exc:
            raise AuthError(
                "Malformed reclaim payer principal", status_code=400
            ) from exc
        return ListingMutation("reclaim_listing", listing_id, "buyer", payer, body)
    return None


async def authenticate_listing_mutation(
    request: Request,
    mutation: ListingMutation,
) -> AuthenticatedPrincipal:
    db = _container.resolved_sqlite_client
    if db is None:
        raise AuthError("Storefront replay state is unavailable", status_code=503)
    return await authenticate_request(
        headers=request.headers,
        method="POST",
        operation=mutation.operation,
        resource=mutation.resource,
        body=mutation.body,
        expected_role=mutation.role,
        expected_principal=mutation.principal,
        replay_store=db,
    )


async def authenticate_buyer_contract(
    request: Request,
    *,
    operation: str,
    resource: str,
    body: Any,
) -> AuthenticatedPrincipal | None:
    """Authenticate raw buyer bodies before framework validation can short-circuit."""

    if not isinstance(body, dict) or "buyer_principal" not in body:
        return None
    try:
        principal = Identity.model_validate(body["buyer_principal"])
    except (TypeError, ValueError) as exc:
        raise AuthError("Malformed buyer principal", status_code=400) from exc
    db = _container.resolved_sqlite_client
    if db is None:
        raise AuthError("Storefront replay state is unavailable", status_code=503)
    authenticated = await authenticate_request(
        headers=request.headers,
        method=request.method,
        operation=operation,
        resource=resource,
        body=body,
        expected_role="buyer",
        expected_principal=principal,
        replay_store=db,
    )
    request.state.marketplace_authenticated = authenticated
    return authenticated


async def authorize_listing_mutation(mutation: ListingMutation) -> None:
    """Apply body-to-durable-principal bindings after proof verification."""

    if mutation.operation == "claim_listing":
        claimant = Identity.model_validate(mutation.body["claimant_principal"])
        if claimant != _seller_signer().identity:
            raise AuthError("Claimant principal is not the storefront principal")
    elif mutation.operation == "refund_listing":
        buyer = Identity.model_validate(mutation.body["buyer_principal"])
        if buyer != await _durable_buyer(listing_id=mutation.resource):
            raise AuthError("Refund buyer principal does not match durable ownership")
    elif mutation.operation == "reclaim_listing":
        payer = Identity.model_validate(mutation.body["payer_principal"])
        durable = await _durable_buyer(
            listing_id=mutation.resource,
            escrow_uid=str(mutation.body.get("escrow_uid") or "") or None,
        )
        if payer != durable:
            raise AuthError("Reclaim payer principal does not match durable ownership")


def _wire_body(raw: bytes) -> Any:
    if not raw:
        return EMPTY_BODY
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw.decode("utf-8", errors="replace")


async def signed_listing_response(
    *,
    response: Response,
    mutation: ListingMutation,
    auth: AuthenticatedPrincipal,
) -> Response:
    """Record a replay outcome and attach the storefront's v2 response proof."""

    raw = (
        b"".join([chunk async for chunk in response.body_iterator])
        if hasattr(response, "body_iterator")
        else bytes(response.body)
    )
    body = _wire_body(raw)
    db = _container.resolved_sqlite_client
    if db is None:
        raise RuntimeError("Storefront replay state is unavailable")
    await db.record_replay_outcome(
        auth.reservation,
        attempt_token=auth.attempt_token,
        status=response.status_code,
        body=body,
    )
    headers = dict(response.headers)
    headers.update(
        signed_response_headers(
            signer=_seller_signer(),
            role="seller",
            method="POST",
            operation=mutation.operation,
            resource=mutation.resource,
            request_id=auth.request_id,
            status=response.status_code,
            body=body,
        )
    )
    headers.pop("content-length", None)
    return Response(
        content=raw,
        status_code=response.status_code,
        headers=headers,
        media_type=response.media_type,
        background=response.background,
    )


def exact_retry_response(
    *, mutation: ListingMutation, auth: AuthenticatedPrincipal
) -> Response:
    if auth.recorded_outcome is None:
        raise AuthError("Exact retry outcome is not available", status_code=409)
    status, body = auth.recorded_outcome
    headers = signed_response_headers(
        signer=_seller_signer(),
        role="seller",
        method="POST",
        operation=mutation.operation,
        resource=mutation.resource,
        request_id=auth.request_id,
        status=status,
        body=body,
    )
    return JSONResponse(status_code=status, content=body, headers=headers)


def _buyer_response_contract(request: Request, body: Any) -> tuple[str, str] | None:
    path = request.url.path.rstrip("/")
    method = request.method
    if method == "POST" and path == "/api/v1/negotiate/new":
        resource = str(body.get("listing_id") or "") if isinstance(body, dict) else ""
        return "negotiate_new", resource
    if method == "POST" and path.startswith("/api/v1/negotiate/"):
        return "negotiate_continue", path.rsplit("/", 1)[-1]
    if path.startswith("/api/v1/settle/"):
        suffix = path[len("/api/v1/settle/") :]
        if method == "GET" and suffix.endswith("/status"):
            return "settle_status", suffix[: -len("/status")]
        if method == "POST" and "/" not in suffix:
            return "settle_escrow", suffix
    if (
        method == "POST"
        and path.startswith("/api/v1/deals/")
        and path.endswith("/heartbeat")
    ):
        return "deal_heartbeat", path.split("/")[-2]
    if path == "/api/v1/settlements" and method == "POST":
        resource = (
            str(body.get("obligation_ref") or "") if isinstance(body, dict) else ""
        )
        return "settlement_start", resource
    if path.startswith("/api/v1/settlements/"):
        suffix = path[len("/api/v1/settlements/") :]
        if method == "GET" and "/" not in suffix:
            return "settlement_status", suffix
        if method == "POST" and suffix.endswith("/reclaim"):
            return "settlement_reclaim", suffix[: -len("/reclaim")]
    return None


async def _signed_buyer_response(
    *,
    request: Request,
    response: Response,
    operation: str,
    resource: str,
) -> Response:
    raw = (
        b"".join([chunk async for chunk in response.body_iterator])
        if hasattr(response, "body_iterator")
        else bytes(response.body)
    )
    body = _wire_body(raw)
    authenticated = getattr(request.state, "marketplace_authenticated", None)
    if not isinstance(authenticated, AuthenticatedPrincipal):
        return Response(
            content=raw,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
            background=response.background,
        )
    request_id = authenticated.request_id
    if authenticated.dispatch_allowed:
        db = _container.resolved_sqlite_client
        if db is None:
            raise RuntimeError("Storefront replay state is unavailable")
        await db.record_replay_outcome(
            authenticated.reservation,
            attempt_token=authenticated.attempt_token,
            status=response.status_code,
            body=body,
        )
    headers = dict(response.headers)
    headers.update(
        signed_response_headers(
            signer=_seller_signer(),
            role="seller",
            method=request.method,
            operation=operation,
            resource=resource,
            request_id=request_id,
            status=response.status_code,
            body=body,
        )
    )
    headers.pop("content-length", None)
    return Response(
        content=raw,
        status_code=response.status_code,
        headers=headers,
        media_type=response.media_type,
        background=response.background,
    )


async def listing_lifecycle_middleware(request: Request, call_next):
    """Authenticate mutations and response-sign all buyer/seller v2 routes."""

    raw = await request.body()
    if raw:
        try:
            body = json.loads(raw)
        except (TypeError, ValueError):
            body = raw.decode("utf-8", errors="replace")
    else:
        body = EMPTY_BODY
    try:
        mutation = await resolve_listing_mutation(request, body)
        buyer_contract = (
            _buyer_response_contract(request, body) if mutation is None else None
        )
        if mutation is None and buyer_contract is None:
            return await call_next(request)
        _seller_signer()
        if mutation is None:
            operation, resource = buyer_contract
            auth = await authenticate_buyer_contract(
                request,
                operation=operation,
                resource=resource,
                body=body,
            )
            try:
                if auth is not None and auth.exact_retry:
                    if auth.recorded_outcome is None:
                        raise AuthError(
                            "Exact retry outcome is not available",
                            status_code=409,
                        )
                    status, recorded_body = auth.recorded_outcome
                    response = JSONResponse(status_code=status, content=recorded_body)
                else:
                    response = await call_next(request)
            except AuthError:
                raise
            except Exception:
                logger.exception("Buyer route failed after authentication")
                response = JSONResponse(
                    status_code=500,
                    content={"detail": "Storefront request failed"},
                )
            operation, resource = buyer_contract
            return await _signed_buyer_response(
                request=request,
                response=response,
                operation=operation,
                resource=resource,
            )
        auth = await authenticate_listing_mutation(request, mutation)
        await authorize_listing_mutation(mutation)
        if auth.exact_retry:
            return exact_retry_response(mutation=mutation, auth=auth)
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Listing mutation failed after authentication")
            response = JSONResponse(
                status_code=500,
                content={"detail": "Storefront request failed"},
            )
        return await signed_listing_response(
            response=response,
            mutation=mutation,
            auth=auth,
        )
    except AuthError as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
