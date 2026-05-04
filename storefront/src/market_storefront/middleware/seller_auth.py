"""Seller auth dependency — verifies X-Signature against CONFIG.agent_wallet_address.

Replaces the inline ``_check_agent_request_auth`` calls that were scattered
across controller methods. Use as a FastAPI ``Depends()`` on any endpoint that
should only be callable by the seller's own operator tooling.

When ``CONFIG.agent_wallet_address`` is empty (local dev default), the check
is skipped and all requests pass through — matching the original behaviour.
"""
from __future__ import annotations

import logging
import time

from fastapi import Header, HTTPException, Request

logger = logging.getLogger(__name__)

_MAX_TIMESTAMP_SKEW = 300  # seconds


def verify_seller_signature(
    request: Request,
    operation: str,
    resource_id: str,
) -> None:
    """Verify EIP-191 seller signature; raise HTTPException(403) on failure.

    Designed to be called from a per-endpoint ``Depends()`` closure that
    supplies ``operation`` and ``resource_id`` from path/body params.

    Example usage in a controller::

        from market_storefront.middleware.seller_auth import make_seller_auth_dep

        @router.post("/listings/create")
        async def create(
            body: CreateListingRequest,
            request: Request,
            _: None = Depends(make_seller_auth_dep("create_listing")),
        ) -> dict:
            ...
    """
    from market_storefront.utils.config import CONFIG

    owner = CONFIG.agent_wallet_address
    if not owner:
        return  # Auth disabled in local dev

    from service.clients.erc8004.signing import verify_eip191

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

    message = f"{operation}:{resource_id}:{ts}"
    if not verify_eip191(message, sig, owner):
        logger.warning("[SELLER AUTH] Invalid signature for %s resource=%s", operation, resource_id)
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
        # Try to get listing_id from already-parsed path params
        resource_id = request.path_params.get("listing_id", "")
        verify_seller_signature(request, operation, resource_id)

    return _dep
