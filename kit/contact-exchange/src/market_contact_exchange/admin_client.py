"""Typed operator methods for contact exchange over a storefront client's transport.

The core storefront client carries no mechanism's vocabulary, so these methods wrap
its market-neutral ``authenticated_request``. ``IntroductionAdminClient`` wraps the
async client and ``SyncIntroductionAdminClient`` the sync one, with identical method
signatures. The path and operation come from this module, which the storefront route
binds as well, so the client and the route cannot name the operation differently.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

#: The route a storefront composing contact exchange serves for operator deletion.
INTRODUCTION_PAYLOADS_ROUTE = "/api/v1/admin/introductions/{obligation_ref}/payloads"
#: The semantic operation the route authenticates; the resource is the obligation ref.
DELETE_INTRODUCTION_PAYLOADS_OPERATION = "admin_delete_introduction_payloads"


class IntroductionPayloadsDeletion(BaseModel):
    """The outcome of deleting one introduction's contact payloads.

    ``redacted`` says whether this call deleted them. ``payloads_deleted_at`` is when
    they were deleted, by this call or an earlier one, and None when the deal never
    revealed an introduction.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    obligation_ref: str
    redacted: bool
    payloads_deleted_at: str | None


class _Transport(Protocol):
    def authenticated_request(self, method: str, path: str, **kwargs: Any) -> Any: ...


def _delete(obligation_ref: str) -> tuple[tuple[str, str], dict[str, Any]]:
    return (
        "DELETE",
        INTRODUCTION_PAYLOADS_ROUTE.format(obligation_ref=obligation_ref),
    ), {
        "role": "admin",
        "operation": DELETE_INTRODUCTION_PAYLOADS_OPERATION,
        "resource": obligation_ref,
    }


class IntroductionAdminClient:
    """Operator contact-exchange methods over an async storefront client."""

    def __init__(self, client: _Transport) -> None:
        self._client = client

    async def delete_introduction_payloads(
        self, obligation_ref: str, *, request_id: str | None = None
    ) -> IntroductionPayloadsDeletion:
        """Delete one introduction's contact payloads now, whatever the window says.

        The deal and its obligation record remain, and repeating the call converges.
        Refused with 404 by a storefront that does not compose contact exchange.
        """
        args, kwargs = _delete(obligation_ref)
        return IntroductionPayloadsDeletion.model_validate(
            await self._client.authenticated_request(*args, **kwargs, request_id=request_id)
        )


class SyncIntroductionAdminClient:
    """Operator contact-exchange methods over a sync storefront client."""

    def __init__(self, client: _Transport) -> None:
        self._client = client

    def delete_introduction_payloads(
        self, obligation_ref: str, *, request_id: str | None = None
    ) -> IntroductionPayloadsDeletion:
        """Delete one introduction's contact payloads now; see
        ``IntroductionAdminClient.delete_introduction_payloads``."""
        args, kwargs = _delete(obligation_ref)
        return IntroductionPayloadsDeletion.model_validate(
            self._client.authenticated_request(*args, **kwargs, request_id=request_id)
        )


__all__ = [
    "DELETE_INTRODUCTION_PAYLOADS_OPERATION",
    "INTRODUCTION_PAYLOADS_ROUTE",
    "IntroductionAdminClient",
    "IntroductionPayloadsDeletion",
    "SyncIntroductionAdminClient",
]
