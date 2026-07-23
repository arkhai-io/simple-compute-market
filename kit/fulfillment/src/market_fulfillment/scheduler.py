"""Settlement-resource selection over site capacity and resource pools.

Scheduling owns placement and returns an already-selected SettlementResource.
Providers execute against that resource and do not perform independent
placement. See ``openspec/specs/fulfillment/spec.md#scheduling-and-assignment``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import Any

from market_resource_pools import ResourcePoolService
from market_site import resource_satisfies_requirement
from market_site.ledger import CapacityLedgerService

from .settlement_types import (
    CapacityReservationExpiredError,
    NoEligibleSettlementResourceError,
    PhysicalSettlementRequest,
    SettlementCandidate,
    SettlementEntityNotFoundError,
    SettlementRequestMismatchError,
    SettlementRequirement,
    SettlementResource,
)
from .scheduling import SettlementSchedulingPolicy
from .round_robin_policy import DeterministicRoundRobinPolicy


class MissingResourceKindError(SettlementRequestMismatchError):
    """No ``resource_kind`` was found on the deal, the request, or the
    scheduler's configured ``default_resource_kind``."""


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
        default_resource_kind: str | None = None,
    ) -> None:
        del session_factory
        self._pool_service = pool_service
        self._capacity_ledger = capacity_ledger
        self._policy = policy or DeterministicRoundRobinPolicy()
        self._default_resource_kind = default_resource_kind
        self._lock = threading.Lock()
        self._capacity_settlement_assignments: dict[str, SettlementResource] = {}

    def get_settlement_assignment(self, capacity_reservation_id: str) -> SettlementResource | None:
        with self._lock:
            return self._capacity_settlement_assignments.get(capacity_reservation_id)

    def record_settlement_assignment(
        self, capacity_reservation_id: str, resource: SettlementResource
    ) -> SettlementResource:
        self._capacity_settlement_assignments[capacity_reservation_id] = resource
        return resource

    def select_resource(self, request: PhysicalSettlementRequest) -> SettlementResource:
        with self._lock:
            reservation = self._require_valid_reservation(request)
            existing = self._capacity_settlement_assignments.get(request.capacity_reservation_id)
            if existing is not None:
                if request.resource_id and request.resource_id != existing.settlement_resource_id:
                    raise SettlementRequestMismatchError(
                        "explicit resource does not match the existing Capacity Settlement Assignment"
                    )
                return existing

            requirement = self._requirement(reservation, request)
            candidates = self._eligible_candidates(requirement, reservation)
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
            return self.record_settlement_assignment(request.capacity_reservation_id, resource)

    def _require_valid_reservation(self, request: PhysicalSettlementRequest) -> dict[str, Any]:
        reservation = self._capacity_ledger.get_reservation(request.capacity_reservation_id)
        if reservation is None:
            raise SettlementEntityNotFoundError(
                f"capacity reservation '{request.capacity_reservation_id}' does not exist"
            )
        if reservation.get("state") not in self._ACTIVE_STATES:
            raise SettlementRequestMismatchError(
                f"capacity reservation '{request.capacity_reservation_id}' is not active"
            )
        expires = reservation.get("hold_expires_at")
        if expires:
            expiry = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= datetime.now(timezone.utc):
                raise CapacityReservationExpiredError(
                    f"capacity reservation '{request.capacity_reservation_id}' has expired"
                )
        deal_ref = reservation.get("deal_ref") or {}
        known_market = deal_ref.get("market")
        if known_market is not None and known_market != request.market:
            raise SettlementRequestMismatchError("market does not match the capacity reservation")
        known_requirements = deal_ref.get("requirements", deal_ref.get("terms"))
        if known_requirements is not None and dict(known_requirements) != request.requirements:
            raise SettlementRequestMismatchError("requirements do not match the capacity reservation")
        return reservation

    def _requirement(
        self, reservation: dict[str, Any], request: PhysicalSettlementRequest
    ) -> SettlementRequirement:
        deal_ref = reservation.get("deal_ref") or {}
        resource_kind = (
            deal_ref.get("resource_kind")
            or request.requirements.get("resource_kind")
            or self._default_resource_kind
        )
        if resource_kind is None:
            raise MissingResourceKindError(
                "no resource_kind on the capacity reservation, the request, or this "
                "scheduler's configured default_resource_kind"
            )
        attributes = dict(request.requirements.get("attributes") or {})
        # dimensions is authoritative when the reservation carries one.
        # Otherwise fall back to the reservation's own dimensions, which
        # ledger.get_reservation() always populates -- even for a
        # pre-migration reservation that only ever had "units"
        # (CapacityLedgerService._reservation_dimensions applies that
        # fallback once, centrally, before this dict ever reaches the
        # scheduler). Do not re-derive a "units" fallback here: it would be
        # dead code today and, worse, a second copy of a rule that must
        # only live in one place.
        reservation_dimensions = dict(reservation["dimensions"])
        requested_dimensions = request.requirements.get("dimensions")
        if requested_dimensions:
            dimensions = dict(requested_dimensions)
            # A request may narrow what it actually needs relative to what
            # was reserved (e.g. scheduling 2 GPUs against a 4-GPU
            # reservation), but it must never widen a dimension the
            # reservation itself governs -- that would let scheduling admit
            # a shape reservation-time admission never verified fits
            # anywhere. Dimensions the reservation does not mention are not
            # governed by it and are not checked here.
            exceeded = {
                dimension: (dimensions[dimension], reservation_dimensions[dimension])
                for dimension in dimensions
                if dimension in reservation_dimensions
                and dimensions[dimension] > reservation_dimensions[dimension]
            }
            if exceeded:
                raise SettlementRequestMismatchError(
                    "requested dimensions exceed the capacity reservation: "
                    f"{exceeded} (requested, reserved)"
                )
        else:
            dimensions = reservation_dimensions
        return SettlementRequirement(
            resource_kind=resource_kind,
            dimensions=dimensions,
            attributes=attributes,
        )

    def _eligible_candidates(
        self,
        requirement: SettlementRequirement,
        reservation: dict[str, Any],
    ) -> list[SettlementCandidate]:
        pools = {pool.id: pool for pool in self._pool_service.list_pools(enabled_only=True)}
        # Guaranteed non-empty by CapacityLedgerService.get_reservation() --
        # see the comment in _requirement().
        reservation_dimensions = dict(reservation["dimensions"])
        backing_resource_id = self._capacity_ledger.get_reservation_backing_resource_id(
            reservation["capacity_reservation_id"]
        )
        candidates: list[SettlementCandidate] = []
        for payload in self._capacity_ledger.list_resources():
            attributes = dict(payload.get("attributes") or {})
            # Prefer the real pool_id column; the attributes JSON fallback
            # covers resources registered before a caller passed the real
            # column explicitly, and any resource type that still relies
            # on attributes-only registration.
            pool_id = payload.get("pool_id") or attributes.get("pool_id")
            if not isinstance(pool_id, str) or pool_id not in pools:
                continue
            if not payload.get("enabled"):
                continue
            # Cheap early exit before the credit-back computation below;
            # resource_satisfies_requirement is still the sole source of
            # truth for the eligibility decision itself.
            if payload.get("resource_type") != requirement.resource_kind:
                continue
            available = dict(payload.get("available") or {})
            # The ledger reserves against a concrete line item before
            # scheduling runs. Credit this reservation's own held
            # dimensions back during eligibility evaluation so the
            # resource it already holds capacity against can still be
            # selected; durable assignment persistence will move this
            # bookkeeping into the assignment transaction instead.
            if payload.get("resource_id") == backing_resource_id:
                for key, amount in reservation_dimensions.items():
                    available[key] = available.get(key, 0) + amount
            if not resource_satisfies_requirement(
                resource_kind=payload["resource_type"],
                available=available,
                attributes=attributes,
                required_resource_kind=requirement.resource_kind,
                required_dimensions=requirement.dimensions,
                required_attributes=requirement.attributes,
            ):
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
