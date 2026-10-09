"""Schema-opaque buyer transport for the storefront introduction reveal."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from market_identity import Identity, Signer, TrustedIdentitySet

from core_buyer.negotiation_client import AuthenticatedHTTPError
from core_buyer.orchestrator import DEFAULT_HTTP_TIMEOUT
from core_buyer.orchestration import _signed_json

IntroductionProjection = dict[str, Any]

#: The stable code a storefront answers, with HTTP 410, for an introduction
#: whose contact payloads it has deleted.
INTRODUCTION_PAYLOADS_DELETED = "introduction_payloads_deleted"


class IntroductionPayloadsDeleted(RuntimeError):
    """The storefront deleted this introduction's contact payloads.

    An outcome rather than a fault: the deal happened and its obligation stands,
    but the storefront no longer holds either party's contact for it, so there
    is nothing to reveal or re-read.
    """

    def __init__(self, *, obligation_ref: str, payloads_deleted_at: str | None) -> None:
        super().__init__("the introduction's contact payloads have been deleted")
        self.obligation_ref = obligation_ref
        self.payloads_deleted_at = payloads_deleted_at

    def outcome(self) -> dict[str, Any]:
        """The deleted outcome as the buyer reports it."""

        return {
            "obligation_ref": self.obligation_ref,
            "revealed": False,
            "code": INTRODUCTION_PAYLOADS_DELETED,
            "payloads_deleted_at": self.payloads_deleted_at,
        }


def _deleted_detail(error: AuthenticatedHTTPError) -> Mapping[str, Any] | None:
    if error.status_code != 410 or not isinstance(error.body, Mapping):
        return None
    detail = error.body.get("detail")
    if isinstance(detail, Mapping) and detail.get("code") == INTRODUCTION_PAYLOADS_DELETED:
        return detail
    return None


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
        return self._reveal(obligation_ref, lambda: _signed_json(
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
        ))

    def read(self, *, obligation_ref: str) -> IntroductionProjection:
        """Idempotently re-read the revealed introduction."""
        return self._reveal(obligation_ref, lambda: _signed_json(
            self.seller_url.rstrip("/") + f"/api/v1/introductions/{obligation_ref}",
            None,
            signer=self.signer,
            principal=self.principal,
            method="GET",
            operation="introduction_read",
            resource=obligation_ref,
            timeout=self.request_timeout,
            resolve_response_principals=self.resolve_seller_principals,
        ))

    @staticmethod
    def _reveal(
        obligation_ref: str,
        call: Callable[[], IntroductionProjection],
    ) -> IntroductionProjection:
        """Run one reveal call, raising the deleted outcome as its own error."""
        try:
            return call()
        except AuthenticatedHTTPError as exc:
            detail = _deleted_detail(exc)
            if detail is None:
                raise
            deleted_at = detail.get("payloads_deleted_at")
            raise IntroductionPayloadsDeleted(
                obligation_ref=obligation_ref,
                payloads_deleted_at=deleted_at if isinstance(deleted_at, str) else None,
            ) from exc


__all__ = [
    "INTRODUCTION_PAYLOADS_DELETED",
    "IntroductionPayloadsDeleted",
    "IntroductionProjection",
    "IntroductionTransport",
]
