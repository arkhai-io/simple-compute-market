"""Buyer auth — verify a signed request against the buyer's identity.

Thin wrapper over ``core_storefront.auth.verify_buyer_signature``; the
operation vocabulary matches the VM storefront so the same buyer client
signs both.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from core_storefront.auth import AuthError, verify_buyer_signature


def _verify(
    request: Request, operation: str, resource_id: str, claimed_address: str,
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
