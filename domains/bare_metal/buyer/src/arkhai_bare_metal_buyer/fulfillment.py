"""Signed buyer transport for bare-metal physical lifecycle reads."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core_buyer import DEFAULT_HTTP_TIMEOUT, signed_storefront_json
from market_identity import Identity, Signer, TrustedIdentitySet
from market_deal_lifecycle_client import LifecycleClient

from .lifecycle import run_sync


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
        async def end():
            async with LifecycleClient(
                self.seller_url, self.signer, self.resolve_seller_principals(), timeout=self.timeout,
            ) as client:
                return (await client.end_delivery(negotiation_id)).model_dump(mode="json")

        return run_sync(end)

    def delivery(self, negotiation_id: str) -> dict[str, Any]:
        async def read():
            async with LifecycleClient(
                self.seller_url, self.signer, self.resolve_seller_principals(), timeout=self.timeout,
            ) as client:
                return (await client.read(negotiation_id)).model_dump(mode="json")

        return run_sync(read)


__all__ = ["BareMetalFulfillmentTransport"]
