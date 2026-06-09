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

from fastapi import HTTPException, Request

from market_core.storefront.auth import (
    AuthError,
    DEFAULT_IDENTITY_SCHEME,
    resolve_expected_identity,
    verify_expected_identity_signature,
)
from market_identity import Identity


def _expected_identity() -> Identity | None:
    """Return the seller's configured identity, or None if auth is disabled."""
    from market_storefront.utils.config import settings

    owner = settings.wallet.address
    if not owner:
        return None
    return Identity(scheme=DEFAULT_IDENTITY_SCHEME, identifier=owner)


def _resolve_identity(request: Request, expected: Identity) -> Identity:
    """Resolve the claimed identity from request headers, defaulting to ``expected``.

    Raises HTTPException(403) when the client supplies an identity that
    disagrees with the storefront's configured identity.
    """
    try:
        return resolve_expected_identity(request.headers, expected)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


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
    try:
        verify_expected_identity_signature(
            headers=request.headers,
            operation=operation,
            resource_id=resource_id,
            expected=expected,
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


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
