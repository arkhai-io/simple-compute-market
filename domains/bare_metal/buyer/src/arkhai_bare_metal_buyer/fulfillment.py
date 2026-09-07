"""Signed buyer transport for bare-metal physical lifecycle reads."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core_buyer import DEFAULT_HTTP_TIMEOUT, signed_storefront_json
from market_identity import Identity, Signer, TrustedIdentitySet


@dataclass(frozen=True, slots=True)
class BareMetalFulfillmentTransport:
    """Verify buyer-authorized physical projections from one trusted storefront."""

    seller_url: str
    principal: Identity
    signer: Signer
    resolve_seller_principals: Callable[[], TrustedIdentitySet]
    timeout: float = DEFAULT_HTTP_TIMEOUT

    def _request(
        self,
        negotiation_id: str,
        suffix: str,
        operation: str,
        *,
        method: str = "GET",
    ) -> dict[str, Any]:
        return signed_storefront_json(
            self.seller_url.rstrip("/")
            + f"/api/v1/fulfillments/{negotiation_id}/{suffix}",
            None,
            signer=self.signer,
            principal=self.principal,
            method=method,
            operation=operation,
            resource=negotiation_id,
            timeout=self.timeout,
            resolve_response_principals=self.resolve_seller_principals,
        )

    def settle(
        self,
        *,
        escrow_uid: str,
        negotiation_id: str,
        buyer_evm_address: str,
    ) -> dict[str, Any]:
        """Ask the seller to verify the buyer's funded escrow on chain.

        The signature covers `escrow_uid` as its resource, matching the route's
        own `settle_escrow` authorization; signing the negotiation instead would
        let one authorization be replayed against another escrow.

        The seller writes `settlement_verified` only after reading the chain, and
        `begin` below refuses to reserve capacity without that record, so this
        call is what turns a funded escrow into a reservable agreement.
        """
        return signed_storefront_json(
            self.seller_url.rstrip("/") + f"/api/v1/settle/{escrow_uid}",
            {
                "negotiation_id": negotiation_id,
                "buyer_principal": self.principal.model_dump(mode="json"),
                "buyer_evm_address": buyer_evm_address,
            },
            signer=self.signer,
            principal=self.principal,
            method="POST",
            operation="settle_escrow",
            resource=escrow_uid,
            timeout=self.timeout,
            resolve_response_principals=self.resolve_seller_principals,
        )

    def begin(self, *, negotiation_id: str, escrow_uid: str) -> dict[str, Any]:
        """Start physical fulfillment for a settlement the seller has verified."""
        return signed_storefront_json(
            self.seller_url.rstrip("/") + "/api/v1/fulfillments/begin",
            {
                "negotiation_id": negotiation_id,
                "escrow_uid": escrow_uid,
                "buyer_principal": self.principal.model_dump(mode="json"),
            },
            signer=self.signer,
            principal=self.principal,
            method="POST",
            operation="bare_metal_fulfillment_begin",
            resource=negotiation_id,
            timeout=self.timeout,
            resolve_response_principals=self.resolve_seller_principals,
        )

    def status(self, negotiation_id: str) -> dict[str, Any]:
        return self._request(
            negotiation_id,
            "status",
            "bare_metal_fulfillment_status",
        )

    def result(self, negotiation_id: str) -> dict[str, Any]:
        return self._request(
            negotiation_id,
            "result",
            "bare_metal_fulfillment_result",
        )

    def access(self, negotiation_id: str) -> dict[str, Any]:
        return self._request(
            negotiation_id,
            "access",
            "bare_metal_fulfillment_access",
        )

    def teardown(self, negotiation_id: str) -> dict[str, Any]:
        return self._request(
            negotiation_id,
            "teardown",
            "bare_metal_fulfillment_teardown",
            method="POST",
        )


__all__ = ["BareMetalFulfillmentTransport"]
