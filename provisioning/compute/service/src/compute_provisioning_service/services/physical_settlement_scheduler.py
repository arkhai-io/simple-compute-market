"""Deterministic, executor-neutral capacity settlement scheduling."""

from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import Any

from compute_provisioning import (
    CapacityReservationExpiredError,
    NoEligibleSettlementResourceError,
    PhysicalSettlementRequest,
    SettlementCandidate,
    SettlementEntityNotFoundError,
    SettlementRequestMismatchError,
    SettlementRequirement,
    SettlementResource,
    SettlementSchedulingPolicy,
)
from market_resource_pools import ResourcePoolService
from market_site.ledger import CapacityLedgerService
from compute_provisioning_service.services.deterministic_round_robin_policy import DeterministicRoundRobinPolicy


class PhysicalSettlementScheduler:
    """Creates one Capacity Settlement Assignment per unchanged reservation.

    The in-memory assignment and cursor repositories are an intermediate
    implementation boundary. They are deliberately named for the domain
    concepts they approximate so durable repositories can replace them
    without changing scheduler policy or public contracts.
    """

    _ACTIVE_STATES = {"reserved", "committed", "leased", "unmanaged"}

    def __init__(
        self,
        pool_service: ResourcePoolService,
        capacity_ledger: CapacityLedgerService,
        session_factory: Any | None = None,
        policy: SettlementSchedulingPolicy | None = None,
    ) -> None:
        del session_factory
        self._pool_service = pool_service
        self._capacity_ledger = capacity_ledger
        self._policy = policy or DeterministicRoundRobinPolicy()
        self._lock = threading.Lock()
        self._capacity_settlement_assignments: dict[str, SettlementResource] = {}

    def get_settlement_assignment(self, allocation_id: str) -> SettlementResource | None:
        with self._lock:
            return self._capacity_settlement_assignments.get(allocation_id)

    def record_settlement_assignment(
        self, allocation_id: str, resource: SettlementResource
    ) -> SettlementResource:
        self._capacity_settlement_assignments[allocation_id] = resource
        return resource

    def select_resource(self, request: PhysicalSettlementRequest) -> SettlementResource:
        with self._lock:
            allocation = self._require_valid_allocation(request)
            existing = self._capacity_settlement_assignments.get(request.allocation_id)
            if existing is not None:
                if request.resource_id and request.resource_id != existing.settlement_resource_id:
                    raise SettlementRequestMismatchError(
                        "explicit resource does not match the existing Capacity Settlement Assignment"
                    )
                return existing

            requirement = self._requirement(allocation, request)
            candidates = self._eligible_candidates(requirement, allocation)
            if request.resource_id is not None:
                selected = next(
                    (item for item in candidates if item.resource_id == request.resource_id),
                    None,
                )
                if selected is None:
                    raise NoEligibleSettlementResourceError(
                        f"resource '{request.resource_id}' is not eligible for settlement"
                    )
            else:
                selected = self._policy.select(
                    requirement=requirement,
                    candidates=candidates,
                )

            resource = SettlementResource(
                settlement_resource_id=selected.resource_id,
                pool_id=selected.pool_id,
                resource_kind=selected.resource_kind,
                provider=selected.provider,
                attributes=selected.attributes,
            )
            return self.record_settlement_assignment(request.allocation_id, resource)

    def _require_valid_allocation(self, request: PhysicalSettlementRequest) -> dict[str, Any]:
        allocation = self._capacity_ledger.get_allocation(request.allocation_id)
        if allocation is None:
            raise SettlementEntityNotFoundError(
                f"capacity allocation '{request.allocation_id}' does not exist"
            )
        if allocation.get("state") not in self._ACTIVE_STATES:
            raise SettlementRequestMismatchError(
                f"capacity allocation '{request.allocation_id}' is not active"
            )
        expires = allocation.get("hold_expires_at")
        if expires:
            expiry = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= datetime.now(timezone.utc):
                raise CapacityReservationExpiredError(
                    f"capacity allocation '{request.allocation_id}' has expired"
                )
        deal_ref = allocation.get("deal_ref") or {}
        known_agreement = deal_ref.get("agreement_id") or deal_ref.get("deal_id")
        if known_agreement is not None and known_agreement != request.agreement_id:
            raise SettlementRequestMismatchError(
                "agreement_id does not match the capacity reservation"
            )
        known_market = deal_ref.get("market")
        if known_market is not None and known_market != request.market:
            raise SettlementRequestMismatchError("market does not match the capacity reservation")
        known_requirements = deal_ref.get("requirements", deal_ref.get("terms"))
        if known_requirements is not None and dict(known_requirements) != request.requirements:
            raise SettlementRequestMismatchError("requirements do not match the capacity reservation")
        return allocation

    @staticmethod
    def _requirement(
        allocation: dict[str, Any], request: PhysicalSettlementRequest
    ) -> SettlementRequirement:
        deal_ref = allocation.get("deal_ref") or {}
        resource_kind = (
            deal_ref.get("resource_kind")
            or request.requirements.get("resource_kind")
            or "compute.gpu"
        )
        attributes = dict(request.requirements.get("attributes") or {})
        # dimensions is authoritative when the reservation carries one.
        #  Otherwise fall back to the allocation's own dimensions which
        # ledger.get_allocation() always populates.
        # Even for a pre-migration allocation that only ever had "units"
        # (CapacityLedgerService._allocation_dimensions applies that
        # fallback once, centrally, before this dict ever reaches the
        # scheduler). Do NOT re-derive a "units" fallback here: it would
        # be dead code today and, worse, a second copy of a rule that
        # must only live in one place (found in code review, 2026-07-20;
        # see test_scheduler_schedules_full-capacity_legacy_allocation).
        dimensions = dict(
            request.requirements.get("dimensions") or allocation["dimensions"]
        )
        return SettlementRequirement(
            resource_kind=resource_kind,
            dimensions=dimensions,
            attributes=attributes,
        )

    def _eligible_candidates(
        self,
        requirement: SettlementRequirement,
        allocation: dict[str, Any],
    ) -> list[SettlementCandidate]:
        pools = {pool.id: pool for pool in self._pool_service.list_pools(enabled_only=True)}
        # Guaranteed non-empty by CapacityLedgerService.get_allocation() --
        # see the comment in _requirement().
        allocation_dimensions = dict(allocation["dimensions"])
        candidates: list[SettlementCandidate] = []
        for payload in self._capacity_ledger.list_resources():
            attributes = dict(payload.get("attributes") or {})
            pool_id = attributes.get("pool_id")
            if not isinstance(pool_id, str) or pool_id not in pools:
                continue
            if not payload.get("enabled"):
                continue
            if payload.get("resource_type") != requirement.resource_kind:
                continue
            available = dict(payload.get("available") or {})
            # The current ledger reserves against a concrete line item before
            # POOLS-2 scheduling. Credit this allocation's own held
            # dimensions back during eligibility evaluation; POOLS-3
            # persistence will move the concrete claim into the assignment
            # transaction.
            if payload.get("resource_id") == allocation.get("resource_id"):
                for key, amount in allocation_dimensions.items():
                    available[key] = available.get(key, 0) + amount
            fits = all(
                available.get(dim, 0) >= amount
                for dim, amount in requirement.dimensions.items()
            )
            if not fits:
                continue
            if any(attributes.get(key) != value for key, value in requirement.attributes.items()):
                continue
            pool = pools[pool_id]
            candidates.append(
                SettlementCandidate(
                    resource_id=payload["resource_id"],
                    pool_id=pool_id,
                    resource_kind=payload["resource_type"],
                    available=available,
                    provider=pool.provider,
                    attributes=attributes,
                )
            )
        if not candidates:
            raise NoEligibleSettlementResourceError(
                "no enabled pooled resource can satisfy the capacity reservation"
            )
        return candidates


# Compatibility aliases for callers transitioning from the POOLS-2 draft.
NoEligiblePoolError = NoEligibleSettlementResourceError
ResourceNotFoundError = SettlementEntityNotFoundError
