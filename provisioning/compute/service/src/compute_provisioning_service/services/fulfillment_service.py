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

from market_fulfillment import FulfillmentValidationIssue, FulfillmentValidationResult

from market_fulfillment import PhysicalSettlementRequest, SettlementResource
from market_fulfillment import (
    FulfillmentConflictError,
    FulfillmentRequestInvalidError,
    FulfillmentResult,
    ProviderNotFoundError,
    ProviderStatus,
)
from market_fulfillment import ProviderRegistry


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
    """Scoped to market/requirements (from the request) and the entire
    selected SettlementResource — explicitly NOT request.resource_id, which
    is an optional selection constraint on the request, not part of
    fulfillment identity. Both PhysicalSettlementRequest and
    SettlementResource are pydantic models with structural equality, so
    this is plain field comparison, not a custom fingerprint hash.

    No longer scoped to agreement_id: PhysicalSettlementRequest dropped it
    entirely (tasks.md 1.5) -- the provisioning boundary is
    capacity-reservation-centric and MUST NOT carry storefront commercial
    identities (design.md, "Cross-domain identities and terminology").
    ``capacity_reservation_id`` is not compared here either, deliberately:
    it is the dict key entries are already looked up by (see
    ``FulfillmentService.create``/``validate_create``), so comparing it
    again would be redundant with the lookup that got here.
    """
    return (
        entry.request.market == request.market
        and entry.request.requirements == request.requirements
        and entry.resource == resource
    )


class FulfillmentService:
    def __init__(self, *, provider_registry: ProviderRegistry, capacity_ledger=None) -> None:
        self._provider_registry = provider_registry
        self._capacity_ledger = capacity_ledger
        self._entries: dict[str, FulfillmentEntry] = {}

    def validate_create(
        self, request: PhysicalSettlementRequest, resource: SettlementResource
    ) -> FulfillmentValidationResult:
        issues: list[FulfillmentValidationIssue] = []
        try:
            provider = self._provider_registry.require(resource.provider)
        except Exception as exc:
            issues.append(FulfillmentValidationIssue(code="provider_not_found", message=str(exc), field="resource.provider"))
            return FulfillmentValidationResult(tuple(issues))
        validator = getattr(provider, "validate_create", None)
        if validator is not None:
            try:
                validator(request, resource)
            except Exception as exc:
                issues.append(FulfillmentValidationIssue(code="request_invalid", message=str(exc)))
        existing = self._entries.get(request.capacity_reservation_id)
        if existing is not None and not _is_equivalent(existing, request, resource):
            issues.append(FulfillmentValidationIssue(code="fulfillment_conflict", message="capacity reservation already has a different fulfillment"))
        return FulfillmentValidationResult(tuple(issues))


    @staticmethod
    def _raise_validation_error(validation: FulfillmentValidationResult) -> None:
        """Preserve typed create failures while dry-run returns structured issues."""
        message = "; ".join(issue.message for issue in validation.issues)
        codes = {issue.code for issue in validation.issues}
        if "provider_not_found" in codes:
            raise ProviderNotFoundError(message)
        if "request_invalid" in codes:
            raise FulfillmentRequestInvalidError(message)
        raise FulfillmentConflictError(message)

    async def create(
        self,
        request: PhysicalSettlementRequest,
        resource: SettlementResource,
    ) -> FulfillmentResult:
        validation = self.validate_create(request, resource)
        if not validation.valid:
            self._raise_validation_error(validation)
        existing = self._entries.get(request.capacity_reservation_id)
        if existing is not None:
            if _is_equivalent(existing, request, resource):
                return existing.create_result
            raise FulfillmentConflictError(
                f"capacity_reservation_id={request.capacity_reservation_id!r} already has a "
                "fulfillment with a different market, requirements, or "
                "selected resource"
            )

        if self._capacity_ledger is not None:
            # CapacityLedgerService.assign_settlement_resource's own
            # parameter is still named capacity_reservation_id (kit/site's
            # SiteAllocation/allocation_id rename is tasks.md Section 2,
            # not this section) -- passing capacity_reservation_id
            # through positionally-by-keyword to it is correct as long as
            # the keyword name matches kit/site's current signature.
            assignment = self._capacity_ledger.assign_settlement_resource(
                allocation_id=request.capacity_reservation_id,
                settlement_resource_id=resource.settlement_resource_id,
            )
            if assignment is None:
                raise FulfillmentConflictError(
                    f"capacity_reservation_id={request.capacity_reservation_id!r} does not exist"
                )
        provider = self._provider_registry.require(resource.provider)
        result = await provider.create(request, resource)
        self._entries[request.capacity_reservation_id] = FulfillmentEntry(
            request=request, resource=resource, create_result=result
        )
        return result

    async def teardown(self, capacity_reservation_id: str) -> FulfillmentResult:
        entry = self._require_entry(capacity_reservation_id)
        if entry.teardown_result is not None:
            return entry.teardown_result

        provider = self._provider_registry.require(entry.resource.provider)
        result = await provider.teardown(
            allocation_id, entry.resource, entry.create_result.provider_metadata
        )
        self._entries[capacity_reservation_id] = FulfillmentEntry(
            request=entry.request,
            resource=entry.resource,
            create_result=entry.create_result,
            teardown_result=result,
        )
        return result

    async def get_status(
        self,
        capacity_reservation_id: str,
        operation: Literal["create", "teardown"] = "create",
    ) -> ProviderStatus:
        entry = self._require_entry(capacity_reservation_id)
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

    def _require_entry(self, capacity_reservation_id: str) -> FulfillmentEntry:
        entry = self._entries.get(capacity_reservation_id)
        if entry is None:
            raise LookupError(
                f"No fulfillment exists for allocation_id={allocation_id!r}"
            )
        return entry
