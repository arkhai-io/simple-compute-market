"""Seller auth dependency — verifies a signed request against the seller.

When ``settings.wallet.address`` is empty (local dev default) the check
is skipped, matching the VM storefront.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from core_storefront.auth import (
    AuthError,
    DEFAULT_IDENTITY_SCHEME,
    verify_expected_identity_signature,
)
from market_identity import Identity


def _expected_identity() -> Identity | None:
    from apitokens_storefront.utils.config import settings

    owner = settings.wallet.address
    if not owner:
        return None
    return Identity(scheme=DEFAULT_IDENTITY_SCHEME, identifier=owner)


def verify_seller_signature(
    request: Request,
    operation: str,
    resource_id: str,
) -> None:
    try:
        verify_expected_identity_signature(
            headers=request.headers,
            operation=operation,
            resource_id=resource_id,
            expected=_expected_identity(),
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def make_seller_auth_dep(operation: str):
    """Depends()-compatible verifier; resource_id from path or wallet."""

    async def _dep(request: Request) -> None:
        resource_id = request.path_params.get("listing_id", "")
        if not resource_id:
            from apitokens_storefront.utils.config import settings

            resource_id = settings.wallet.address or ""
        verify_seller_signature(request, operation, resource_id)

    return _dep
