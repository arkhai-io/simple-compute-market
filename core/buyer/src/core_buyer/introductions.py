"""Schema-opaque buyer transport for the storefront introduction reveal."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from market_identity import Identity, Signer, TrustedIdentitySet

from core_buyer.orchestration import _signed_json
from core_buyer.orchestrator import DEFAULT_HTTP_TIMEOUT

IntroductionProjection = dict[str, Any]


@dataclass(frozen=True, slots=True)
class IntroductionTransport:
    """Sign and verify the introduction reveal lifecycle.

    The transport knows only accepted marketplace identifiers, the buyer's own
    contact payload, marketplace identities, and the storefront's public
    reveal projection. Domain terms stay outside this boundary.
    """

    seller_url: str
    principal: Identity
    signer: Signer
    resolve_seller_principals: Callable[[], TrustedIdentitySet]
    request_timeout: float = DEFAULT_HTTP_TIMEOUT

    def start(
        self,
        *,
        negotiation_id: str,
        obligation_ref: str,
        contact_payload: dict[str, str],
    ) -> IntroductionProjection:
        """Reveal: supply the buyer contact and receive the counterparty's."""
        return _signed_json(
            self.seller_url.rstrip("/") + "/api/v1/introductions",
            {
                "negotiation_id": negotiation_id,
                "obligation_ref": obligation_ref,
                "contact_payload": dict(contact_payload),
            },
            signer=self.signer,
            principal=self.principal,
            method="POST",
            operation="introduction_start",
            resource=obligation_ref,
            timeout=self.request_timeout,
            resolve_response_principals=self.resolve_seller_principals,
        )

    def read(self, *, obligation_ref: str) -> IntroductionProjection:
        """Idempotently re-read the revealed introduction."""
        return _signed_json(
            self.seller_url.rstrip("/") + f"/api/v1/introductions/{obligation_ref}",
            None,
            signer=self.signer,
            principal=self.principal,
            method="GET",
            operation="introduction_read",
            resource=obligation_ref,
            timeout=self.request_timeout,
            resolve_response_principals=self.resolve_seller_principals,
        )

    def review(self, *, body: dict[str, Any]) -> IntroductionProjection:
        return self._request("/api/v1/introductions/reviews", "POST", "introduction_review", body["obligation_ref"], body)

    def finalize(self, *, body: dict[str, Any]) -> IntroductionProjection:
        return self._request("/api/v1/introductions", "POST", "introduction_start", body["obligation_ref"], body)

    def finalization_read(self, *, obligation_ref: str, finalization_id: str) -> IntroductionProjection:
        return self._request(f"/api/v1/introductions/{obligation_ref}/finalizations/{finalization_id}", "GET", "introduction_finalization_read", f"introduction-finalization:{obligation_ref}:{finalization_id}", None)

    def cancel_finalization(self, *, body: dict[str, Any]) -> IntroductionProjection:
        ref, fid = body["obligation_ref"], body["finalization_id"]
        return self._request(f"/api/v1/introductions/{ref}/finalizations/{fid}/cancel", "POST", "introduction_finalization_cancel", f"introduction-finalization:{ref}:{fid}", body)

    def delivery_read(self, *, obligation_ref: str) -> IntroductionProjection:
        return self._request(f"/api/v1/introductions/{obligation_ref}/delivery", "GET", "introduction_delivery_read", obligation_ref, None)

    def _request(self, path: str, method: str, operation: str, resource: str, body: dict[str, Any] | None) -> IntroductionProjection:
        return _signed_json(self.seller_url.rstrip("/") + path, body,
            signer=self.signer, principal=self.principal, method=method,
            operation=operation, resource=resource, timeout=self.request_timeout,
            resolve_response_principals=self.resolve_seller_principals)


__all__ = ["IntroductionProjection", "IntroductionTransport"]
