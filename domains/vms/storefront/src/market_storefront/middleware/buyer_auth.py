"""Buyer auth dependencies — verify a signed request against the buyer's identity.

Each exported function is a FastAPI Depends()-compatible callable that raises
HTTPException(403) on auth failure.

FastAPI injects these by matching parameter names to already-declared endpoint
parameters — e.g., ``body`` (the Pydantic model), ``request`` (the raw request),
and path parameters like ``neg_id`` or ``escrow_uid``.

Identity dispatch
-----------------
The request may include ``X-Identity-Scheme`` + ``X-Identity`` headers
(introduced in the pluggable-identity refactor). When absent, the scheme
defaults to ``eip191`` and the identifier defaults to the body's
``buyer_address`` (or the corresponding query param) — preserving
back-compat with clients that predate the headers. When both are
present, they must agree; otherwise the request is rejected as a
mismatched identity claim.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from core_storefront.auth import (
    AuthError,
    resolve_buyer_identity as _core_resolve_buyer_identity,
    verify_buyer_signature,
)
from market_identity import Identity


def _resolve_buyer_identity(request: Request, claimed_address: str) -> Identity:
    """Resolve buyer identity from headers, defaulting to the body-supplied address.

    Raises HTTPException when the headers carry an identity that
    disagrees with the body's ``buyer_address`` (the legacy claim path).
    """
    try:
        return _core_resolve_buyer_identity(request.headers, claimed_address)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _verify(
    request: Request, operation: str, resource_id: str, claimed_address: str
) -> None:
    """Core signed-request verification; raises HTTPException on failure."""
    try:
        verify_buyer_signature(
            headers=request.headers,
            operation=operation,
            resource_id=resource_id,
            claimed_address=claimed_address,
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


# ---------------------------------------------------------------------------
# Per-operation dependency callables.
# Each declares exactly the parameters FastAPI needs to inject from the
# enclosing endpoint's declared parameters.
# ---------------------------------------------------------------------------

def negotiate_new_auth(body, request: Request) -> None:
    """Depends for POST /negotiate/new.

    ``body`` is the already-parsed NegotiateNewRequest from the endpoint.
    FastAPI injects it because it's declared on the endpoint and we request
    the same name here.
    """
    from core_storefront.models.negotiation_models import NegotiateNewRequest
    if not isinstance(body, NegotiateNewRequest):
        raise HTTPException(status_code=400, detail="Invalid request body type")
    _verify(request, "negotiate_new", body.listing_id, body.buyer_address)


def negotiate_continue_auth(neg_id: str, body, request: Request) -> None:
    """Depends for POST /negotiate/{neg_id}."""
    from core_storefront.models.negotiation_models import NegotiateContinueRequest
    if not isinstance(body, NegotiateContinueRequest):
        raise HTTPException(status_code=400, detail="Invalid request body type")
    _verify(request, "negotiate_continue", neg_id, body.buyer_address)


def settle_escrow_auth(escrow_uid: str, body, request: Request) -> None:
    """Depends for POST /settle/{escrow_uid}."""
    from core_storefront.models.settle_models import SettleRequest
    if not isinstance(body, SettleRequest):
        raise HTTPException(status_code=400, detail="Invalid request body type")
    _verify(request, "settle_escrow", escrow_uid, body.buyer_address)


def settle_status_auth(escrow_uid: str, buyer_address: str, request: Request) -> None:
    """Depends for GET /settle/{escrow_uid}/status.

    ``buyer_address`` is a Query param declared on the endpoint.
    """
    if not buyer_address:
        raise HTTPException(status_code=400, detail="Missing 'buyer_address' query param")
    _verify(request, "settle_status", escrow_uid, buyer_address)
