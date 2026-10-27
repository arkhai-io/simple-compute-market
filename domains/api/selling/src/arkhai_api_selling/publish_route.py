"""The seller's publish-from-quota route: its contract, its request and response, and its typed clients.

A domain's request model extends ``PublishFromQuotaRequest`` with what its listing describes.
"""

from __future__ import annotations

from typing import Any, Protocol

from market_identity import Identity
from pydantic import BaseModel, Field

PUBLISH_FROM_QUOTA_PATH = "/api/v1/listings/publish-from-quota"
PUBLISH_FROM_QUOTA_OPERATION = "create_listing"

#: The request fields the listing service reads itself; every other field is the
#: domain's description of what the listing sells.
SERVICE_FIELDS = frozenset({"resource_id", "accepted_escrows", "settlement_clauses", "paused"})


def seller_resource(seller: Identity) -> str:
    """The resource a seller-signed request binds when its path names none."""
    return f"{seller.scheme.value}:{seller.identifier}"


class PublishFromQuotaRequest(BaseModel):
    """Seller's quota-backed publish request."""

    resource_id: str = Field(description="Quota resource in the credits service's ledger.")
    accepted_escrows: list[dict[str, Any]] = Field(default_factory=list)
    settlement_clauses: list[dict[str, Any]] | None = None
    paused: bool = False

    def listing_request(self) -> dict[str, Any]:
        """The fields the domain's publication mapping reads."""
        return {
            name: value
            for name, value in self.model_dump().items()
            if name not in SERVICE_FIELDS
        }


class PublishFromQuotaResponse(BaseModel):
    status: str
    listing_id: str
    registry_status: str | None = None


class _Transport(Protocol):
    def authenticated_request(self, method: str, path: str, **kwargs: Any) -> Any: ...


def _publish(
    request_model: type[PublishFromQuotaRequest],
    request: PublishFromQuotaRequest | dict[str, Any],
    seller: Identity,
) -> tuple[tuple, dict[str, Any]]:
    body = request_model.model_validate(
        request.model_dump() if isinstance(request, BaseModel) else request
    ).model_dump(mode="json")
    return ("POST", PUBLISH_FROM_QUOTA_PATH), {
        "role": "seller",
        "operation": PUBLISH_FROM_QUOTA_OPERATION,
        "resource": seller_resource(seller),
        "body": body,
    }


class ListingClient:
    """Seller listing methods over an async storefront client signing as ``seller``."""

    def __init__(
        self,
        client: _Transport,
        *,
        seller: Identity,
        request_model: type[PublishFromQuotaRequest],
    ) -> None:
        self._client = client
        self._seller = seller
        self._request_model = request_model

    async def publish_from_quota(
        self,
        request: PublishFromQuotaRequest | dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> PublishFromQuotaResponse:
        """Create and publish a listing; refused with 400 when the quota or a settlement alternative is unavailable."""
        args, kwargs = _publish(self._request_model, request, self._seller)
        return PublishFromQuotaResponse.model_validate(
            await self._client.authenticated_request(*args, **kwargs, request_id=request_id)
        )


class SyncListingClient:
    """Seller listing methods over a sync storefront client signing as ``seller``."""

    def __init__(
        self,
        client: _Transport,
        *,
        seller: Identity,
        request_model: type[PublishFromQuotaRequest],
    ) -> None:
        self._client = client
        self._seller = seller
        self._request_model = request_model

    def publish_from_quota(
        self,
        request: PublishFromQuotaRequest | dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> PublishFromQuotaResponse:
        """See ``ListingClient.publish_from_quota``."""
        args, kwargs = _publish(self._request_model, request, self._seller)
        return PublishFromQuotaResponse.model_validate(
            self._client.authenticated_request(*args, **kwargs, request_id=request_id)
        )
