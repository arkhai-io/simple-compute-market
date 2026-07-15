"""Provisioning-side fulfillment consistency boundary.

FulfillmentService sits above ProviderRegistry and is the entry point
future storefront-facing code calls. It owns:

- validation that the allocation and already-selected resource may be
  fulfilled;
- the allocation-to-fulfillment identity;
- equivalent-retry detection and conflicting-request rejection, for both
  create and teardown;
- provider resolution and dispatch;
- normalization of provider operation state.

It does NOT call PhysicalSettlementScheduler and never will — placement and
execution stay separate services, called in sequence by whatever
orchestrates the workflow. See design.md Decision 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from compute_provisioning import PhysicalSettlementRequest, SettlementResource
from services.fulfillment_provider import (
    FulfillmentConflictError,
    FulfillmentResult,
    ProviderStatus,
)
from services.provider_registry import ProviderRegistry


@dataclass(frozen=True)
class FulfillmentEntry:
    """One allocation's fulfillment record (in-memory this round — see
    POOLS 3 design.md Decision 4.
    No a concurrency guarantees, not durable across restarts"""

    request: PhysicalSettlementRequest
    resource: SettlementResource
    create_result: FulfillmentResult
    teardown_result: FulfillmentResult | None = None


def _is_equivalent(
    entry: FulfillmentEntry,
    request: PhysicalSettlementRequest,
    resource: SettlementResource,
) -> bool:
    """Scoped to agreement_id/market/terms (from the request) and the entire
    selected SettlementResource — explicitly NOT request.resource_id, which
    is an optional selection constraint on the request, not part of
    fulfillment identity. Both PhysicalSettlementRequest and
    SettlementResource are pydantic models with structural equality, so
    this is plain field comparison, not a custom fingerprint hash.
    """
    return (
        entry.request.agreement_id == request.agreement_id
        and entry.request.market == request.market
        and entry.request.terms == request.terms
        and entry.resource == resource
    )


class FulfillmentService:
    def __init__(self, *, provider_registry: ProviderRegistry) -> None:
        self._provider_registry = provider_registry
        self._entries: dict[str, FulfillmentEntry] = {}

    async def create(
        self,
        request: PhysicalSettlementRequest,
        resource: SettlementResource,
    ) -> FulfillmentResult:
        existing = self._entries.get(request.allocation_id)
        if existing is not None:
            if _is_equivalent(existing, request, resource):
                return existing.create_result
            raise FulfillmentConflictError(
                f"allocation_id={request.allocation_id!r} already has a "
                "fulfillment with a different agreement, market, terms, or "
                "selected resource"
            )

        provider = self._provider_registry.require(resource.provider)
        result = await provider.create(request, resource)
        self._entries[request.allocation_id] = FulfillmentEntry(
            request=request, resource=resource, create_result=result
        )
        return result

    async def teardown(self, allocation_id: str) -> FulfillmentResult:
        entry = self._require_entry(allocation_id)
        if entry.teardown_result is not None:
            return entry.teardown_result

        provider = self._provider_registry.require(entry.resource.provider)
        result = await provider.teardown(
            allocation_id, entry.resource, entry.create_result.provider_metadata
        )
        self._entries[allocation_id] = FulfillmentEntry(
            request=entry.request,
            resource=entry.resource,
            create_result=entry.create_result,
            teardown_result=result,
        )
        return result

    async def get_status(
        self,
        allocation_id: str,
        operation: Literal["create", "teardown"] = "create",
    ) -> ProviderStatus:
        entry = self._require_entry(allocation_id)
        result = entry.create_result if operation == "create" else entry.teardown_result
        if result is None:
            raise LookupError(
                f"allocation_id={allocation_id!r} has no {operation!r} operation "
                "to check status for"
            )
        provider = self._provider_registry.require(entry.resource.provider)
        return await provider.get_status(
            allocation_id, entry.resource, result.provider_metadata
        )

    def _require_entry(self, allocation_id: str) -> FulfillmentEntry:
        entry = self._entries.get(allocation_id)
        if entry is None:
            raise LookupError(
                f"No fulfillment exists for allocation_id={allocation_id!r}"
            )
        return entry
