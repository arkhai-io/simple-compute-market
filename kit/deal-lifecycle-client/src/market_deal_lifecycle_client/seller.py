"""Typed seller lifecycle commands over a storefront's authenticated transport."""

from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import urlencode

from market_deal_lifecycle_contracts.models import (
    DealPage, LifecycleCommand, LifecycleRead, ListDealsRequest, SubmitResponse,
)
from market_deal_lifecycle_contracts.routes import lifecycle_route


class _Transport(Protocol):
    def authenticated_request(self, method: str, path: str, **kwargs: Any) -> Any: ...


def _request(operation: str, negotiation_id: str = "") -> tuple[tuple[str, str], dict[str, Any]]:
    if operation != "lifecycle_list" and (not negotiation_id or any(c in negotiation_id for c in "/?#%") or negotiation_id in {".", ".."}):
        raise ValueError("negotiation_id must be one unescaped path segment")
    route = lifecycle_route(operation)
    return (route["method"], route["path"].replace(r"(?P<negotiation_id>[^/]+)", negotiation_id)), {
        "role": "admin", "operation": operation, "resource": negotiation_id,
    }


class SellerLifecycleClient:
    """Seller methods over an async storefront client, using administrator authentication."""

    def __init__(self, client: _Transport) -> None:
        self._client = client

    async def notice(
        self, negotiation_id: str, *, operation_key: str, at: int | None = None,
    ) -> SubmitResponse:
        command = LifecycleCommand(negotiation_id=negotiation_id, kind="notice", operation_key=operation_key, at=at)
        args, kwargs = _request("lifecycle_submit", command.negotiation_id)
        return SubmitResponse.model_validate(await self._client.authenticated_request(
            *args, **kwargs, body=command.model_dump(mode="json", exclude_none=True),
        ))

    async def read(self, negotiation_id: str) -> LifecycleRead:
        args, kwargs = _request("lifecycle_seller_read", negotiation_id)
        result = LifecycleRead.model_validate(await self._client.authenticated_request(*args, **kwargs))
        if result.negotiation_id != negotiation_id:
            raise ValueError("lifecycle read names another negotiation")
        return result

    async def list(self, request: ListDealsRequest = ListDealsRequest()) -> DealPage:
        args, kwargs = _request("lifecycle_list")
        query = {key: str(value) for key, value in request.model_dump(exclude_none=True).items()}
        kwargs["resource"] = "?" + urlencode(sorted(query.items()))
        return DealPage.model_validate(await self._client.authenticated_request(*args, **kwargs, params=query))


class SyncSellerLifecycleClient:
    """The same seller methods over a sync storefront client."""

    def __init__(self, client: _Transport) -> None:
        self._client = client

    def notice(
        self, negotiation_id: str, *, operation_key: str, at: int | None = None,
    ) -> SubmitResponse:
        command = LifecycleCommand(negotiation_id=negotiation_id, kind="notice", operation_key=operation_key, at=at)
        args, kwargs = _request("lifecycle_submit", command.negotiation_id)
        return SubmitResponse.model_validate(self._client.authenticated_request(
            *args, **kwargs, body=command.model_dump(mode="json", exclude_none=True),
        ))

    def read(self, negotiation_id: str) -> LifecycleRead:
        args, kwargs = _request("lifecycle_seller_read", negotiation_id)
        result = LifecycleRead.model_validate(self._client.authenticated_request(*args, **kwargs))
        if result.negotiation_id != negotiation_id:
            raise ValueError("lifecycle read names another negotiation")
        return result

    def list(self, request: ListDealsRequest = ListDealsRequest()) -> DealPage:
        args, kwargs = _request("lifecycle_list")
        query = {key: str(value) for key, value in request.model_dump(exclude_none=True).items()}
        kwargs["resource"] = "?" + urlencode(sorted(query.items()))
        return DealPage.model_validate(self._client.authenticated_request(*args, **kwargs, params=query))
