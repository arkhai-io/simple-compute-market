"""Settlement-resource selection over site capacity and resource pools.

Scheduling owns placement and returns an already-selected SettlementResource.
Providers execute against that resource and do not perform independent
placement. See ``openspec/specs/fulfillment/spec.md#scheduling-and-assignment``.

``schedule_resource`` is one atomic database transaction: it locks and
validates the reservation, enumerates eligible candidates, applies
scheduling policy (advancing durable round-robin fairness state when
automatic selection is used), performs any fair capacity rebind, and
creates or returns the settlement assignment -- committing or rolling back
all of it together. This exists so a caller (ordinarily the storefront)
never has to build compensating error handling for a partially-completed
schedule the way it would if these were separate calls.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from market_resource_pools import ResourcePoolService
from market_site import resource_satisfies_requirement
from market_site.ledger import CapacityLedgerService

from .settlement_repository import SettlementRepository
from .scheduling_persistence import SchedulingUnitOfWork, SqlAlchemySchedulingUnitOfWork
from .round_robin_policy import DeterministicRoundRobinPolicy
from .scheduling import SchedulingCursorState, SettlementSchedulingPolicy
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


class MissingResourceKindError(SettlementRequestMismatchError):
    """No ``resource_kind`` was found on the deal, the request, or the
    scheduler's configured ``default_resource_kind``."""


def _resource_from_record(record: Any) -> SettlementResource:
    return SettlementResource(
        settlement_resource_id=record.settlement_resource_id,
        pool_id=record.pool_id,
        resource_kind=record.scheduling_requirements.get("resource_kind"),
        provider=record.provider,
        attributes=dict(record.resource_attributes or {}),
    )


class PhysicalSettlementScheduler:
    """Creates one Capacity Settlement Assignment per unchanged reservation."""

    _ACTIVE_STATES = {"reserved", "committed", "leased", "unmanaged"}

    def __init__(
        self,
        pool_service: ResourcePoolService,
        capacity_ledger: CapacityLedgerService,
        session_factory: Any,
        policy: SettlementSchedulingPolicy | None = None,
        default_resource_kind: str | None = None,
        repository: SettlementRepository | None = None,
        unit_of_work: SchedulingUnitOfWork | None = None,
    ) -> None:
        self._pool_service = pool_service
        self._capacity_ledger = capacity_ledger
        self._policy = policy or DeterministicRoundRobinPolicy()
        self._default_resource_kind = default_resource_kind
        self._repository = repository or SettlementRepository()
        self._unit_of_work = unit_of_work or SqlAlchemySchedulingUnitOfWork(
            session_factory, pool_service, capacity_ledger, self._repository
        )

    def schedule_resource(self, request: PhysicalSettlementRequest) -> SettlementResource:
        """Schedule ``request`` through the narrow atomic persistence boundary."""
        with self._unit_of_work.transaction() as tx:
            reservation_row = tx.lock_reservation(request.capacity_reservation_id)
            if reservation_row is None:
                raise SettlementEntityNotFoundError(
                    f"capacity reservation '{request.capacity_reservation_id}' does not exist"
                )
            reservation = self._require_valid_reservation_payload(
                tx.reservation_payload(reservation_row), request
            )
            requirement = self._requirement(reservation, request)
            existing = tx.get_assignment(request.capacity_reservation_id)
            if existing is not None:
                record = tx.schedule_assignment(
                    capacity_reservation_id=request.capacity_reservation_id,
                    market=request.market, scheduling_requirements=requirement,
                    resource=_resource_from_record(existing),
                    resource_id_constraint=request.resource_id,
                )
                return _resource_from_record(record)

            candidates = self._eligible_candidates_in_transaction(
                tx, requirement, request.capacity_reservation_id
            )
            if request.resource_id is not None:
                selected = next((c for c in candidates if c.resource_id == request.resource_id), None)
                if selected is None:
                    raise NoEligibleSettlementResourceError(
                        f"resource '{request.resource_id}' is not eligible for settlement"
                    )
            else:
                cursor_row = tx.load_cursor(requirement.resource_kind)
                selected, updated_cursor = self._policy.select(
                    requirement=requirement, candidates=candidates,
                    cursor=SchedulingCursorState(
                        last_pool_id=cursor_row.last_pool_id,
                        last_resource_by_pool=dict(cursor_row.last_resource_by_pool or {}),
                    ),
                )
                tx.save_cursor(
                    requirement.resource_kind, last_pool_id=updated_cursor.last_pool_id,
                    last_resource_by_pool=dict(updated_cursor.last_resource_by_pool),
                )
            if selected.resource_id != tx.backing_resource_id(request.capacity_reservation_id):
                tx.rebind_capacity(
                    capacity_reservation_id=request.capacity_reservation_id,
                    settlement_resource_id=selected.resource_id,
                )
            resource = SettlementResource(
                settlement_resource_id=selected.resource_id, pool_id=selected.pool_id,
                resource_kind=selected.resource_kind, provider=selected.provider,
                attributes=selected.attributes,
            )
            record = tx.schedule_assignment(
                capacity_reservation_id=request.capacity_reservation_id, market=request.market,
                scheduling_requirements=requirement, resource=resource,
                resource_id_constraint=request.resource_id,
            )
            return _resource_from_record(record)

    def _require_valid_reservation_payload(
        self, reservation: dict[str, Any], request: PhysicalSettlementRequest
    ) -> dict[str, Any]:
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
        # reservation_payload_in_session() always populates -- even for a
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

    def _eligible_candidates_in_transaction(
        self, tx: Any, requirement: SettlementRequirement,
        capacity_reservation_id: str,
    ) -> list[SettlementCandidate]:
        pools = {pool.id: pool for pool in tx.list_enabled_pools()}
        candidates: list[SettlementCandidate] = []
        for payload in tx.list_candidates(
            resource_kind=requirement.resource_kind,
            exclude_reservation_id=capacity_reservation_id,
        ):
            pool_id = payload.pool_id
            pool = pools.get(pool_id)
            if pool is None:
                continue
            if not resource_satisfies_requirement(
                resource=payload,
                required_resource_kind=requirement.resource_kind,
                required_dimensions=requirement.dimensions,
                required_attributes=requirement.attributes,
            ):
                continue
            candidates.append(SettlementCandidate(
                resource_id=payload.resource_id, pool_id=pool_id,
                resource_kind=payload.resource_kind, provider=pool.provider,
                available=dict(payload.available),
                attributes=dict(payload.attributes or {}),
            ))
        if not candidates:
            raise NoEligibleSettlementResourceError("no eligible settlement resource exists")
        return candidates

