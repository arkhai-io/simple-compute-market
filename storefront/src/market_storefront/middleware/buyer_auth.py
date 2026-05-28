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

import logging
import time

from fastapi import HTTPException, Request

from service.identity import get_identity_verifier
from service.schemas import Identity

logger = logging.getLogger(__name__)

_MAX_TIMESTAMP_SKEW = 300  # seconds
_DEFAULT_SCHEME = "eip191"


def _resolve_buyer_identity(request: Request, claimed_address: str) -> Identity:
    """Resolve buyer identity from headers, defaulting to the body-supplied address.

    Raises HTTPException when the headers carry an identity that
    disagrees with the body's ``buyer_address`` (the legacy claim path).
    """
    scheme = request.headers.get("X-Identity-Scheme") or _DEFAULT_SCHEME
    header_identifier = request.headers.get("X-Identity")
    identifier = header_identifier or claimed_address
    identity = Identity(scheme=scheme, identifier=identifier)

    if header_identifier is not None and scheme == _DEFAULT_SCHEME:
        # Both header-supplied and body-supplied: must match. Compare on the
        # normalized form so EIP-191 case differences don't reject.
        if identity.identifier != claimed_address.lower():
            raise HTTPException(
                status_code=403,
                detail="X-Identity does not match buyer_address",
            )
    return identity


def _verify(
    request: Request, operation: str, resource_id: str, claimed_address: str
) -> None:
    """Core signed-request verification; raises HTTPException on failure."""
    if not claimed_address or not claimed_address.startswith("0x") or len(claimed_address) != 42:
        raise HTTPException(status_code=400, detail="Missing or malformed buyer_address")

    sig = request.headers.get("X-Signature")
    ts_raw = request.headers.get("X-Timestamp")
    if not sig or not ts_raw:
        raise HTTPException(status_code=403, detail="Missing auth headers")

    try:
        ts = int(ts_raw)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid X-Timestamp")

    if abs(time.time() - ts) > _MAX_TIMESTAMP_SKEW:
        raise HTTPException(status_code=403, detail="Timestamp out of range")

    identity = _resolve_buyer_identity(request, claimed_address)

    try:
        verifier = get_identity_verifier(identity.scheme)
    except KeyError:
        raise HTTPException(
            status_code=400, detail=f"Unknown identity scheme: {identity.scheme}"
        )

    message = f"{operation}:{resource_id}:{ts}".encode("utf-8")
    try:
        proof = bytes.fromhex(sig.removeprefix("0x"))
    except ValueError:
        raise HTTPException(status_code=403, detail="Malformed X-Signature")

    if not verifier.verify_signature(identity, message, proof):
        logger.warning(
            "[BUYER AUTH] Invalid signature for %s resource=%s claimed=%s scheme=%s",
            operation, resource_id, claimed_address, identity.scheme,
        )
        raise HTTPException(
            status_code=403, detail="Invalid signature for claimed buyer identity"
        )


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
    from market_storefront.models.negotiation_models import NegotiateNewRequest
    if not isinstance(body, NegotiateNewRequest):
        raise HTTPException(status_code=400, detail="Invalid request body type")
    _verify(request, "negotiate_new", body.listing_id, body.buyer_address)


def negotiate_continue_auth(neg_id: str, body, request: Request) -> None:
    """Depends for POST /negotiate/{neg_id}."""
    from market_storefront.models.negotiation_models import NegotiateContinueRequest
    if not isinstance(body, NegotiateContinueRequest):
        raise HTTPException(status_code=400, detail="Invalid request body type")
    _verify(request, "negotiate_continue", neg_id, body.buyer_address)


def settle_escrow_auth(escrow_uid: str, body, request: Request) -> None:
    """Depends for POST /settle/{escrow_uid}."""
    from market_storefront.models.settle_models import SettleRequest
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
