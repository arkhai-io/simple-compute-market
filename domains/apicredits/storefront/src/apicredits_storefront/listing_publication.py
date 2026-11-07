"""The seller's quota-backed publish route: its contract, models, and typed clients.

``POST /api/v1/listings/publish-from-quota`` creates and publishes a listing
backed by a quota resource. It is seller-signed, binding the seller's own
principal as its resource, which ``seller_resource`` renders for both the
route's authentication and these clients. The core storefront client carries no
market's vocabulary, so ``ApiCreditListingClient`` and its sync twin
``SyncApiCreditListingClient`` wrap its market-neutral ``authenticated_request``
with identical method signatures, and list the storefront's listings through
its public listing route.
"""

from __future__ import annotations

from typing import Any, Protocol

from market_identity import Identity
from pydantic import BaseModel, Field
from storefront_client.models import ListingListResponse

PUBLISH_FROM_QUOTA_PATH = "/api/v1/listings/publish-from-quota"
PUBLISH_FROM_QUOTA_OPERATION = "create_listing"


def seller_resource(seller: Identity) -> str:
    """The resource a seller-signed request binds when its path names none."""
    return f"{seller.scheme.value}:{seller.identifier}"


class PublishFromQuotaRequest(BaseModel):
    """Seller's quota-backed publish request."""

    resource_id: str = Field(
        description="Quota resource in the credits service's ledger."
    )
    service_name: str
    accepted_escrows: list[dict[str, Any]] = Field(default_factory=list)
    settlement_clauses: list[dict[str, Any]] | None = None
    description: str | None = None
    openapi_url: str | None = None
    base_url: str | None = None
    paused: bool = False


class PublishFromQuotaResponse(BaseModel):
    status: str
    listing_id: str
    registry_status: str | None = None


class _Transport(Protocol):
    def authenticated_request(self, method: str, path: str, **kwargs: Any) -> Any: ...

    def list_listings(
        self, *, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> Any: ...


def _publish(
    request: PublishFromQuotaRequest | dict[str, Any], seller: Identity
) -> tuple[tuple, dict[str, Any]]:
    body = PublishFromQuotaRequest.model_validate(request).model_dump(mode="json")
    return ("POST", PUBLISH_FROM_QUOTA_PATH), {
        "role": "seller",
        "operation": PUBLISH_FROM_QUOTA_OPERATION,
        "resource": seller_resource(seller),
        "body": body,
    }


class ApiCreditListingClient:
    """Seller listing methods over an async storefront client signing as ``seller``."""

    def __init__(self, client: _Transport, *, seller: Identity) -> None:
        self._client = client
        self._seller = seller

    async def publish_from_quota(
        self,
        request: PublishFromQuotaRequest | dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> PublishFromQuotaResponse:
        """Create and publish a listing backed by ``request``'s quota resource.

        Refused with 400 when the resource is unknown, holds no sellable units,
        or no settlement alternative it may publish is ready for a reason its
        configuration causes, naming the blockers; and with 503 when the only
        reason is that a mechanism it uses has not been reached yet, which the
        same request may retry.
        """
        args, kwargs = _publish(request, self._seller)
        return PublishFromQuotaResponse.model_validate(
            await self._client.authenticated_request(*args, **kwargs, request_id=request_id)
        )

    async def list_listings(
        self, *, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> ListingListResponse:
        """The storefront's local listings, through its public listing route."""
        return await self._client.list_listings(status=status, limit=limit, offset=offset)


class SyncApiCreditListingClient:
    """Seller listing methods over a sync storefront client signing as ``seller``."""

    def __init__(self, client: _Transport, *, seller: Identity) -> None:
        self._client = client
        self._seller = seller

    def publish_from_quota(
        self,
        request: PublishFromQuotaRequest | dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> PublishFromQuotaResponse:
        """See ``ApiCreditListingClient.publish_from_quota``."""
        args, kwargs = _publish(request, self._seller)
        return PublishFromQuotaResponse.model_validate(
            self._client.authenticated_request(*args, **kwargs, request_id=request_id)
        )

    def list_listings(
        self, *, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> ListingListResponse:
        """See ``ApiCreditListingClient.list_listings``."""
        return self._client.list_listings(status=status, limit=limit, offset=offset)
