"""VM-owned buyer transport for hosted settlement lifecycle routes."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from core_buyer import DEFAULT_HTTP_TIMEOUT
from core_buyer.orchestration import (
    DEFAULT_SETTLEMENT_POLL_INTERVAL,
    DEFAULT_SETTLEMENT_TIMEOUT,
    _signed_json,
)
from market_identity import Identity, Signer, TrustedIdentitySet


def start_hosted_settlement(
    *,
    seller_url: str,
    negotiation_id: str,
    obligation_ref: str,
    funding_authorization_ref: str,
    principal: Identity,
    signer: Signer,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
    resolve_seller_principals: Callable[[], TrustedIdentitySet],
) -> dict[str, Any]:
    """Start an accepted hosted obligation through the VM storefront."""
    return _signed_json(
        seller_url.rstrip("/") + "/api/v1/settlements",
        {
            "negotiation_id": negotiation_id,
            "obligation_ref": obligation_ref,
            "funding_authorization_ref": funding_authorization_ref,
        },
        signer=signer,
        principal=principal,
        method="POST",
        operation="settlement_start",
        resource=obligation_ref,
        timeout=timeout,
        resolve_response_principals=resolve_seller_principals,
    )


def poll_hosted_settlement(
    *,
    seller_url: str,
    settlement_ref: str,
    principal: Identity,
    signer: Signer,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
    resolve_seller_principals: Callable[[], TrustedIdentitySet],
) -> dict[str, Any]:
    """Read one VM hosted-settlement projection."""
    return _signed_json(
        seller_url.rstrip("/") + f"/api/v1/settlements/{settlement_ref}",
        None,
        signer=signer,
        principal=principal,
        method="GET",
        operation="settlement_status",
        resource=settlement_ref,
        timeout=timeout,
        resolve_response_principals=resolve_seller_principals,
    )


def reclaim_hosted_settlement(
    *,
    seller_url: str,
    settlement_ref: str,
    principal: Identity,
    signer: Signer,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
    resolve_seller_principals: Callable[[], TrustedIdentitySet],
) -> dict[str, Any]:
    """Request reclaim for one VM hosted settlement."""
    return _signed_json(
        seller_url.rstrip("/") + f"/api/v1/settlements/{settlement_ref}/reclaim",
        None,
        signer=signer,
        principal=principal,
        method="POST",
        operation="settlement_reclaim",
        resource=settlement_ref,
        timeout=timeout,
        resolve_response_principals=resolve_seller_principals,
    )


def wait_for_hosted_settlement(
    *,
    seller_url: str,
    settlement_ref: str,
    principal: Identity,
    signer: Signer,
    poll_interval: float = DEFAULT_SETTLEMENT_POLL_INTERVAL,
    total_timeout: float = DEFAULT_SETTLEMENT_TIMEOUT,
    on_poll: Optional[Callable[[int, dict], None]] = None,
    on_action: Optional[Callable[[dict[str, Any]], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
    resolve_seller_principals: Callable[[], TrustedIdentitySet],
) -> dict[str, Any]:
    """Poll without retaining transient Checkout or Account Link URLs."""
    deadline = time.monotonic() + total_timeout
    attempts = 0
    while True:
        attempts += 1
        body = poll_hosted_settlement(
            seller_url=seller_url,
            settlement_ref=settlement_ref,
            principal=principal,
            signer=signer,
            resolve_seller_principals=resolve_seller_principals,
        )
        action = body.get("action")
        if isinstance(action, dict) and on_action is not None:
            on_action(action)
        if on_poll is not None:
            on_poll(attempts, body)
        if body.get("status") in {
            "ready",
            "collected",
            "reclaimed",
            "expired",
            "failed",
            "manual_required",
        }:
            return body
        if time.monotonic() >= deadline:
            raise TimeoutError(
                "Hosted settlement did not reach a terminal public status "
                f"within {total_timeout}s"
            )
        sleep(poll_interval)
