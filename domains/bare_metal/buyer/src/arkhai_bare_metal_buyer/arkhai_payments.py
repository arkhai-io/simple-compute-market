"""Bare-metal buyer settlement transport for Arkhai payments.

Approval itself is the payments kit's ``PaymentApproval``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core_buyer import DEFAULT_HTTP_TIMEOUT, signed_storefront_json
from market_identity import Identity, Signer, TrustedIdentitySet


@dataclass(frozen=True, slots=True)
class BareMetalSettlementTransport:
    """Submit a negotiation-scoped settlement request to its trusted storefront."""

    seller_url: str
    principal: Identity
    signer: Signer
    resolve_seller_principals: Callable[[], TrustedIdentitySet]
    timeout: float = DEFAULT_HTTP_TIMEOUT

    def settle(self, negotiation_id: str) -> dict[str, Any]:
        body = {
            "negotiation_id": negotiation_id,
            "buyer_principal": self.principal.model_dump(mode="json"),
        }
        return signed_storefront_json(
            self.seller_url.rstrip("/") + f"/api/v1/settle/{negotiation_id}",
            body,
            signer=self.signer,
            principal=self.principal,
            method="POST",
            operation="settle_escrow",
            resource=negotiation_id,
            timeout=self.timeout,
            resolve_response_principals=self.resolve_seller_principals,
        )


__all__ = ["BareMetalSettlementTransport"]
