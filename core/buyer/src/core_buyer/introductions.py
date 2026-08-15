"""Schema-opaque buyer transport for the storefront introduction reveal."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from market_identity import Identity, Signer, TrustedIdentitySet

from core_buyer.orchestrator import DEFAULT_HTTP_TIMEOUT
from core_buyer.orchestration import _signed_json

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


__all__ = ["IntroductionProjection", "IntroductionTransport"]
