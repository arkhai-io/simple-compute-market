"""Typed seller methods for contact exchange over a storefront client's transport.

The seller is a party to every introduction it accepted, so it re-reads a reveal
the same way the buyer does, signed with the marketplace identity the Agreement
names. Starting a reveal carries the buyer's contact and is the buyer's alone, so
re-reading is the only seller method. As with the operator client, these methods
wrap the core client's market-neutral ``authenticated_request``; the path and
operation come from this module, which the storefront routes bind as well.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

#: The route a storefront composing contact exchange serves for re-reading a reveal.
INTRODUCTION_ROUTE = "/api/v1/introductions/{obligation_ref}"
#: The semantic operation the route authenticates; the resource is the obligation ref.
INTRODUCTION_READ_OPERATION = "introduction_read"


class IntroductionReveal(BaseModel):
    """One party's view of a revealed introduction: the counterparty's contact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    obligation_ref: str
    mechanism: str
    revealed: bool
    introduction: dict[str, Any]
    counterparty_contact: dict[str, Any]
    retention: dict[str, Any] | None = None


class _Transport(Protocol):
    def authenticated_request(self, method: str, path: str, **kwargs: Any) -> Any: ...


def _read(obligation_ref: str) -> tuple[tuple[str, str], dict[str, Any]]:
    return (
        "GET",
        INTRODUCTION_ROUTE.format(obligation_ref=obligation_ref),
    ), {
        "role": "seller",
        "operation": INTRODUCTION_READ_OPERATION,
        "resource": obligation_ref,
    }


class IntroductionSellerClient:
    """Seller contact-exchange methods over an async storefront client."""

    def __init__(self, client: _Transport) -> None:
        self._client = client

    async def read_introduction(
        self, obligation_ref: str, *, request_id: str | None = None
    ) -> IntroductionReveal:
        """Re-read one revealed introduction as its seller.

        Served whether or not the storefront still offers contact exchange for
        new work. Refused with 409 before the buyer starts the reveal, and with
        410 once the introduction's contact payloads are deleted.
        """
        args, kwargs = _read(obligation_ref)
        return IntroductionReveal.model_validate(
            await self._client.authenticated_request(*args, **kwargs, request_id=request_id)
        )


class SyncIntroductionSellerClient:
    """Seller contact-exchange methods over a sync storefront client."""

    def __init__(self, client: _Transport) -> None:
        self._client = client

    def read_introduction(
        self, obligation_ref: str, *, request_id: str | None = None
    ) -> IntroductionReveal:
        """Re-read one revealed introduction as its seller; see
        ``IntroductionSellerClient.read_introduction``."""
        args, kwargs = _read(obligation_ref)
        return IntroductionReveal.model_validate(
            self._client.authenticated_request(*args, **kwargs, request_id=request_id)
        )


__all__ = [
    "INTRODUCTION_READ_OPERATION",
    "INTRODUCTION_ROUTE",
    "IntroductionReveal",
    "IntroductionSellerClient",
    "SyncIntroductionSellerClient",
]
