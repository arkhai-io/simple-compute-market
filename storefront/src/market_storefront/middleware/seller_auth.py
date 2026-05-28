"""Seller auth dependency — verifies a signed request against the seller's identity.

Replaces the inline ``_check_agent_request_auth`` calls that were scattered
across controller methods. Use as a FastAPI ``Depends()`` on any endpoint that
should only be callable by the seller's own operator tooling.

When ``settings.wallet.address`` is empty (local dev default), the check
is skipped and all requests pass through — matching the original behaviour.

Identity dispatch
-----------------
The request may include ``X-Identity-Scheme`` + ``X-Identity`` headers
(introduced in the pluggable-identity refactor). When absent, the scheme
defaults to ``eip191`` and the identifier defaults to
``settings.wallet.address`` — preserving back-compat with clients that
predate the headers. When the headers are present, the supplied identity
must match what the storefront expects (case-insensitive for ``eip191``)
or the request is rejected; this prevents a client from claiming a
different identity than the one its signature attests.
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


def _expected_identity() -> Identity | None:
    """Return the seller's configured identity, or None if auth is disabled."""
    from market_storefront.utils.config import settings

    owner = settings.wallet.address
    if not owner:
        return None
    return Identity(scheme=_DEFAULT_SCHEME, identifier=owner)


def _resolve_identity(request: Request, expected: Identity) -> Identity:
    """Resolve the claimed identity from request headers, defaulting to ``expected``.

    Raises HTTPException(403) when the client supplies an identity that
    disagrees with the storefront's configured identity.
    """
    scheme = request.headers.get("X-Identity-Scheme") or expected.scheme
    identifier = request.headers.get("X-Identity") or expected.identifier
    claimed = Identity(scheme=scheme, identifier=identifier)

    if claimed.scheme != expected.scheme:
        raise HTTPException(status_code=403, detail="Identity scheme mismatch")
    if claimed.identifier != expected.identifier:
        # Identity.identifier is already lowercased for eip191 via the model
        # validator, so the comparison is safe.
        raise HTTPException(status_code=403, detail="Identity mismatch")
    return claimed


def verify_seller_signature(
    request: Request,
    operation: str,
    resource_id: str,
) -> None:
    """Verify a signed seller request; raise HTTPException(403) on failure.

    Designed to be called from a per-endpoint ``Depends()`` closure that
    supplies ``operation`` and ``resource_id`` from path/body params.
    """
    expected = _expected_identity()
    if expected is None:
        return  # Auth disabled in local dev

    sig = request.headers.get("X-Signature")
    ts_raw = request.headers.get("X-Timestamp")
    if not sig or not ts_raw:
        logger.warning("[SELLER AUTH] Missing headers for %s", operation)
        raise HTTPException(status_code=403, detail="Missing auth headers")

    try:
        ts = int(ts_raw)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid X-Timestamp")

    if abs(time.time() - ts) > _MAX_TIMESTAMP_SKEW:
        raise HTTPException(status_code=403, detail="Timestamp out of range")

    identity = _resolve_identity(request, expected)

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
            "[SELLER AUTH] Invalid signature for %s resource=%s",
            operation,
            resource_id,
        )
        raise HTTPException(status_code=403, detail="Invalid signature")


def make_seller_auth_dep(operation: str):
    """Return a Depends()-compatible function for a given operation.

    The resource_id is read from the request body's ``listing_id`` field if
    present, else from the first path segment after ``/listings/``, else ``""``.

    For endpoints where the resource_id comes from a typed Pydantic body that
    is parsed before the Depends runs, pass the body as a second arg to the
    returned function.

    Usage::

        @router.post("/listings/create")
        async def create(
            body: CreateListingRequest,
            request: Request,
            _: None = Depends(make_seller_auth_dep("create_listing")),
        ) -> dict: ...
    """
    async def _dep(request: Request) -> None:
        # Path params take priority (e.g. /listings/{listing_id}/close)
        resource_id = request.path_params.get("listing_id", "")
        if not resource_id:
            # No listing_id path param — this is create_listing, which the client
            # signs as "create_listing:{agent_wallet_address}:{ts}".
            # Use settings.wallet.address as the resource_id to match.
            from market_storefront.utils.config import settings
            resource_id = settings.wallet.address or ""
        verify_seller_signature(request, operation, resource_id)

    return _dep
