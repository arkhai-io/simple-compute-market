"""Site-authority capacity ledger.

The authoritative resource ledger for this site
(docs/development/ARCHITECTURE.md, "Capacity and the Site Authority"):
unit-counted resources, reservation holds with their lease tail, and the
anonymous versioned capacity-event feed. Storefronts reach it through
the ``/api/v1/capacity`` HTTP surface, which mirrors the
``core_storefront.capacity.CapacityClient`` contract verb for verb.

Matching semantics: a claim is an exact-match attribute mapping plus a
quantity request, checked first against the resource's attributes JSON
and then against its top-level fields. Domain-specific eligibility should
normally be expressed in those claims — for example VM claims name
``vm_host`` while bare-metal claims name ``physical_host_id`` and
``allocation_mode``. ``required_attributes`` remains available for
single-domain hosts that need a coarse local invariant, but multi-domain
provisioners should pass none.

A claim's ``dimensions`` mapping is authoritative when present and is
checked against every dimension a candidate resource declares in its
``capacity`` map.

Legacy single-quantity claims (``units``/``gpu_count``) keep working.
They translate internally to ``dimensions={"gpu_count": n}``.
``CapacityBucket.total_units`` and ``CapacityReservation.units`` remain
service-maintained mirrors for payload and caller compatibility.

``capacity``/``dimensions`` are the source of truth.

Mutations serialize on a process-level lock: the site authority is the
serialization point for reserves across storefronts, and that point is
exactly one process per site (SQLite is single-writer anyway). Every
mutation appends a ``CapacityEvent`` row in the same transaction, so the
feed is always consistent with a snapshot.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy.orm import Session, sessionmaker

from .db import (
    HELD_RESERVATION_STATES,
    ReservationState,
    CapacityEvent,
    CapacityBucket,
    CapacityReservation,
    CapacityReservationDebit,
)

logger = logging.getLogger(__name__)

ALLOCATION_MODE_ATTR = "allocation_mode"
ALLOCATION_MODE_EXCLUSIVE = "exclusive"
ALLOCATION_MODE_SHAREABLE = "shareable"
PHYSICAL_HOST_ID_ATTR = "physical_host_id"
VM_EXECUTOR_KIND = "vm"


class CapacityConflictError(Exception):
    """Raised when a mutation references a row in an incompatible state."""


def parse_utc(value: str | None) -> Optional[datetime]:
    """Tolerantly parse the ISO-ish timestamp strings the ledger stores.

    Accepts ``YYYY-MM-DD HH:MM[:SS]`` (the storefront's lease format) and
    full ISO-8601 with or without timezone; naive values are taken as UTC.
    """
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for candidate in (text, text.replace(" ", "T", 1)):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _lease_window(
    *,
    lease_start_utc: str | None = None,
    lease_duration_seconds: int | None = None,
    lease_end_utc: str | None = None,
) -> tuple[datetime | None, datetime | None]:
    """Return a normalized lease window.

    Start omitted means "now" only when a duration is supplied. Without
    duration or explicit end, callers are using the timeless/open-ended path.
    """
    start = parse_utc(lease_start_utc)
    end = parse_utc(lease_end_utc)
    if lease_duration_seconds is not None:
        seconds = int(lease_duration_seconds)
        if seconds <= 0:
            raise ValueError("lease_duration_seconds must be > 0")
        if start is None:
            start = datetime.now(timezone.utc)
        end = start + timedelta(seconds=seconds)
    return start, end


def _windows_overlap(
    a_start: datetime | None,
    a_end: datetime | None,
    b_start: datetime | None,
    b_end: datetime | None,
) -> bool:
    """Half-open interval overlap, with None as unbounded."""
    if a_end is not None and b_start is not None and a_end <= b_start:
        return False
    if b_end is not None and a_start is not None and b_end <= a_start:
        return False
    return True


# Claim keys that request a unit count rather than matching an attribute.
# "units" is the generic key. Domain-specific aliases (e.g. the VM
# domain's "gpu_count") are supplied by the composition root via
# CapacityLedgerService(unit_claim_keys=...) rather than hardcoded here,
# so this module carries no VM-specific knowledge.
_DEFAULT_UNIT_CLAIM_KEYS: tuple[str, ...] = ("units",)
_DIMENSIONS_CLAIM_KEY = "dimensions"

# The dimension that CapacityBucket.total_units / CapacityReservation.units /
# legacy single-quantity claims all mean. Every pre-pass-1 caller speaks
# only this one dimension, so it's what they mirror into/out of.
PRIMARY_DIMENSION = "gpu_count"


def _requested_units(
    claim: Mapping[str, Any] | None,
    *,
    unit_claim_keys: Sequence[str] = _DEFAULT_UNIT_CLAIM_KEYS,
) -> int:
    """Legacy single-quantity parse, kept for the primary-dimension mirror."""
    claim = claim or {}
    key = next((k for k in unit_claim_keys if claim.get(k) is not None), None)
    if key is None:
        return 1
    raw = claim[key]
    if isinstance(raw, bool):
        raise ValueError(f"{key} must be an integer, got {raw!r}")
    try:
        requested = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer, got {raw!r}") from exc
    if requested < 1:
        raise ValueError(f"{key} must be >= 1, got {requested}")
    return requested


def _to_decimal(value: Any, *, label: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric, got {value!r}")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric, got {value!r}") from exc
    # NaN/Infinity parse without error but raise InvalidOperation on comparison
    if not amount.is_finite():
        raise ValueError(f"{label} must be a finite number, got {value!r}")
    if amount <= 0:
        raise ValueError(f"{label} must be > 0, got {amount}")
    return amount


def _requested_dimensions(
    claim: Mapping[str, Any] | None,
    *,
    unit_claim_keys: Sequence[str] = _DEFAULT_UNIT_CLAIM_KEYS,
) -> dict[str, Decimal]:
    """Parse a claim's quantity request as a dimensions map.

    ``dimensions`` is authoritative when *present* — not merely truthy.
    ``{"dimensions": {}}`` is a malformed claim (declares nothing to
    request) and must fail loudly rather than silently falling through to
    the legacy single-quantity parse, which would otherwise default to a
    request the caller never actually made.
    Only the *absence* of the key falls back to the legacy
    single-quantity claim (``units``/domain-specific aliases), translated
    to ``{"gpu_count": n}`` so every existing caller's claim shape keeps
    working unchanged.
    """
    claim = claim or {}
    if _DIMENSIONS_CLAIM_KEY not in claim:
        return {PRIMARY_DIMENSION: Decimal(_requested_units(claim, unit_claim_keys=unit_claim_keys))}
    raw = claim[_DIMENSIONS_CLAIM_KEY]
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError(
            f"dimensions must be a non-empty mapping, got {raw!r}"
        )
    return {
        str(key): _to_decimal(value, label=f"dimensions[{key}]")
        for key, value in raw.items()
    }


def _serialize_dimensions(dimensions: Mapping[str, Decimal]) -> dict[str, float | int]:
    """Return a JSON-safe numeric dimension map.

    Current governed dimensions are integral. Non-integral values remain
    numeric for compatibility with in-process scheduling arithmetic.
    """
    result: dict[str, float | int] = {}
    for key, amount in dimensions.items():
        as_int = int(amount)
        result[key] = as_int if Decimal(as_int) == amount else float(amount)
    return result


def _to_decimal_nonneg(value: Any, *, label: str) -> Decimal:
    """Like :func:`_to_decimal` but allows zero (a declared-but-empty dimension)."""
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric, got {value!r}")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric, got {value!r}") from exc
    if not amount.is_finite():
        raise ValueError(f"{label} must be a finite number, got {value!r}")
    if amount < 0:
        raise ValueError(f"{label} must be >= 0, got {amount}")
    return amount


def _resource_capacity(resource: CapacityBucket) -> dict[str, Decimal]:
    """A resource's declared total capacity per dimension.

    Falls back to ``{"gpu_count": total_units}`` when the dimension map is absent
    that have never had ``capacity`` populated.
    """
    if resource.capacity:
        return {
            str(key): _to_decimal_nonneg(value, label=f"capacity[{key}]")
            for key, value in resource.capacity.items()
        }
    return {PRIMARY_DIMENSION: Decimal(int(resource.total_units or 0))}


def _reservation_dimensions(reservation: CapacityReservation) -> dict[str, Decimal]:
    """An reservation's held quantity per dimension.

    Falls back to ``{"gpu_count": units}`` for rows that
    have never had ``dimensions`` populated.
    """
    if reservation.dimensions:
        return {
            str(key): Decimal(str(value))
            for key, value in reservation.dimensions.items()
        }
    return {PRIMARY_DIMENSION: Decimal(int(reservation.units or 0))}


def _capacity_change_kind(
    delta: Mapping[str, Decimal], *, old_enabled: bool | None, new_enabled: bool,
) -> str:
    """Classify a capacity-registration delta for the event feed's ``kind``.

    A single grew/shrank boolean cannot represent a mixed-direction
    change (e.g. GPU count grows while RAM shrinks). Returns "capacity_changed"
    for that case rather than mislabeling it "released" or "reserved".
    Enablement toggling folds in as its own signed contribution: going disabled is a
    decrease, going enabled is an increase, regardless of the capacity
    numbers, since a disabled resource is unavailable no matter what its
    declared capacity says.
    """
    signs = {1 if amount > 0 else -1 for amount in delta.values() if amount != 0}
    if old_enabled is not None and old_enabled != new_enabled:
        signs.add(1 if new_enabled else -1)
    if not signs or signs == {1}:
        return "released"
    if signs == {-1}:
        return "reserved"
    return "capacity_changed"


@dataclass(frozen=True)
class ResourceFeasibilityView:
    """Canonical resource facts used by admission and scheduling."""

    resource_id: str
    pool_id: str
    resource_kind: str
    available: Mapping[str, Any]
    attributes: Mapping[str, Any]


def resource_feasibility_view(
    *,
    resource_id: str,
    pool_id: str | None,
    resource_kind: str,
    available: Mapping[str, Any],
    attributes: Mapping[str, Any] | None = None,
    resource_subtype: str | None = None,
    value: Any = None,
    units: Any = None,
) -> ResourceFeasibilityView:
    """Build the immutable, authoritative view used for feasibility checks."""
    normalized = {
        "resource_id": resource_id,
        "resource_type": resource_kind,
        "resource_subtype": resource_subtype,
        "value": value,
        "units": units,
        "gpu_count": units,
        **dict(attributes or {}),
    }
    authoritative_pool_id = pool_id or resource_id
    normalized["pool_id"] = authoritative_pool_id
    return ResourceFeasibilityView(
        resource_id=resource_id,
        pool_id=authoritative_pool_id,
        resource_kind=resource_kind,
        available=MappingProxyType(dict(available)),
        attributes=MappingProxyType(normalized),
    )


def resource_satisfies_requirement(
    *,
    resource: ResourceFeasibilityView | None = None,
    resource_kind: str | None = None,
    available: Mapping[str, Any] | None = None,
    attributes: Mapping[str, Any] | None = None,
    required_resource_kind: str | None,
    required_dimensions: Mapping[str, Any],
    required_attributes: Mapping[str, Any] = {},
) -> bool:
    """Return whether a canonical resource view satisfies a requirement.

    The scalar arguments remain as a compatibility surface for direct callers;
    service code supplies the canonical view.
    """
    if resource is None:
        resource = resource_feasibility_view(
            resource_id="",
            pool_id="",
            resource_kind=resource_kind or "",
            available=available or {},
            attributes=attributes,
        )
    if required_resource_kind is not None and resource.resource_kind != required_resource_kind:
        return False
    if any(
        resource.available.get(dimension, 0) < amount
        for dimension, amount in required_dimensions.items()
    ):
        return False
    return all(
        resource.attributes.get(key) == value
        for key, value in required_attributes.items()
    )


def _resource_feasibility_view(
    resource: CapacityBucket, available: Mapping[str, Any]
) -> ResourceFeasibilityView:
    return resource_feasibility_view(
        resource_id=resource.backing_resource_id,
        pool_id=resource.pool_id,
        resource_kind=resource.resource_type,
        available=available,
        attributes=resource.attributes,
        resource_subtype=resource.resource_subtype,
        value=resource.total_units,
        units=resource.total_units,
    )


def _split_claim_requirement(
    claim: Mapping[str, Any] | None,
    *,
    unit_claim_keys: Sequence[str] = _DEFAULT_UNIT_CLAIM_KEYS,
) -> tuple[str | None, dict[str, Any]]:
    """Split a claim into an optional resource-kind constraint and the
    remaining exact-match attribute requirements, excluding quantity keys.
    """
    claim = claim or {}
    attributes = {
        key: expected
        for key, expected in claim.items()
        if key not in unit_claim_keys
        and key != _DIMENSIONS_CLAIM_KEY
        and key != "resource_type"
    }
    return claim.get("resource_type"), attributes


class CapacityLedgerService:
    """Authoritative capacity operations over the site ledger tables."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        required_attributes: Sequence[str] = (),
        unit_claim_keys: Sequence[str] = _DEFAULT_UNIT_CLAIM_KEYS,
    ) -> None:
        """``required_attributes`` is an optional coarse local eligibility
        invariant: a resource matches only when its attributes give each
        named key a non-empty string. Multi-domain provisioners should pass
        none and put domain-specific eligibility in reservation claims.

        ``unit_claim_keys`` lists the claim keys that request a unit count
        rather than match an attribute (``"units"`` is the generic key).
        Defaults to the domain-neutral ``("units",)``; the VM composition
        root passes ``("units", "gpu_count")`` explicitly to keep its
        existing claim shape working. Kept out of the ledger's own default
        so this module carries no VM-specific knowledge.
        """
        self._session_factory = session_factory
        self._required_attributes = tuple(required_attributes)
        self._unit_claim_keys = tuple(unit_claim_keys)
        # Re-entrant and held across READS too: the service's SQLite
        # engine is a StaticPool — every session shares one connection,
        # so an unserialized read interleaving with a write transaction
        # raises "cannot commit - no transaction is active". One site's
        # ledger has exactly one serialization point; this is it.
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Resource registry
    # ------------------------------------------------------------------

    def register_resource(
        self,
        *,
        resource_id: str,
        total_units: int,
        resource_type: str = "compute.gpu",
        resource_subtype: str | None = None,
        pool_id: str | None = None,
        attributes: Mapping[str, Any] | None = None,
        capacity: Mapping[str, Any] | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Insert or update a ledger resource; emits a delta on change.

        ``capacity`` is the multidimensional total.
        ``total_units`` remains a service-maintained mirror of ``capacity["gpu_count"]``.
        When ``capacity`` includes ``gpu_count`` *and* it disagrees with
        ``total_units``, that is a caller bug, raises ``ValueError``.

        An upsert emits a signed per-dimension delta on the event
        (authoritative). ``kind`` is a coarser hint for legacy
        single-dimension consumers: "released" when every changed
        dimension and enablement moved to a non-decreasing net effect,
        "reserved" when every changed dimension and enablement moved to a
        non-increasing net effect, and "capacity_changed" when the
        direction is genuinely mixed (e.g. GPU count grew while RAM
        shrank) -- a case a single grew/shrank boolean cannot represent.
        First-time registration is always "released": brand new capacity
        appearing is unambiguous.
        """
        with self._lock, self._session_factory() as db:
            bucket = self._bucket_by_backing_resource(db, resource_id)
            old_capacity = _resource_capacity(bucket) if bucket is not None else {}
            old_enabled = bool(bucket.enabled) if bucket is not None else None
            new_dimensions = dict(capacity or {})
            if PRIMARY_DIMENSION in new_dimensions:
                supplied = _to_decimal_nonneg(
                    new_dimensions[PRIMARY_DIMENSION], label="capacity[gpu_count]",
                )
                if supplied != Decimal(int(total_units)):
                    raise ValueError(
                        f"capacity['gpu_count']={supplied} disagrees with "
                        f"total_units={total_units}; pass one consistent value"
                    )
            else:
                new_dimensions[PRIMARY_DIMENSION] = int(total_units)
            new_capacity = {
                str(key): _to_decimal_nonneg(value, label=f"capacity[{key}]")
                for key, value in new_dimensions.items()
            }
            mirrored_units = int(new_capacity[PRIMARY_DIMENSION])
            is_new = bucket is None
            effective_pool_id = pool_id
            if bucket is None:
                bucket = CapacityBucket(
                    capacity_bucket_id=str(uuid.uuid4()),
                    backing_resource_id=resource_id,
                    pool_id=effective_pool_id,
                    resource_type=resource_type,
                    resource_subtype=resource_subtype,
                    total_units=mirrored_units,
                    capacity=_serialize_dimensions(new_capacity),
                    attributes=dict(attributes or {}),
                    enabled=enabled,
                )
                db.add(bucket)
            else:
                bucket.pool_id = effective_pool_id
                bucket.resource_type = resource_type
                bucket.resource_subtype = resource_subtype
                bucket.total_units = mirrored_units
                bucket.capacity = _serialize_dimensions(new_capacity)
                bucket.attributes = dict(attributes or {})
                bucket.enabled = enabled
            delta = {
                key: new_capacity.get(key, Decimal(0)) - old_capacity.get(key, Decimal(0))
                for key in set(new_capacity) | set(old_capacity)
            }
            kind = "released" if is_new else _capacity_change_kind(
                delta, old_enabled=old_enabled, new_enabled=enabled,
            )
            db.add(CapacityEvent(
                kind=kind,
                resource_id=resource_id,
                dimensions=_serialize_dimensions(delta),
            ))
            db.commit()
            return self._resource_payload(db, bucket)

    def list_resources(self) -> list[dict[str, Any]]:
        with self._lock, self._session_factory() as db:
            self._expire_stale_holds(db)
            rows = (
                db.query(CapacityBucket)
                .order_by(CapacityBucket.updated_at.asc())
                .all()
            )
            return [self._resource_payload(db, row) for row in rows]

    # ------------------------------------------------------------------
    # CapacityClient verbs
    # ------------------------------------------------------------------

    def snapshot(self) -> list[dict[str, Any]]:
        """Advisory availability view (enabled resources only)."""
        return [r for r in self.list_resources() if r.get("enabled")]

    def probe(
        self,
        *,
        claim: Mapping[str, Any] | None = None,
        lease_start_utc: str | None = None,
        lease_duration_seconds: int | None = None,
    ) -> dict[str, Any] | None:
        """Dry-run match for ``claim`` — consumes nothing."""
        requested = _requested_dimensions(claim, unit_claim_keys=self._unit_claim_keys)
        window_start, window_end = _lease_window(
            lease_start_utc=lease_start_utc,
            lease_duration_seconds=lease_duration_seconds,
        )
        with self._lock, self._session_factory() as db:
            self._expire_stale_holds(db)
            match = self._find_candidate(db, claim, requested, window_start, window_end)
            if match is None:
                return None
            resource, available = match
            return self._match_payload(resource, available, requested)

    def reserve(
        self,
        *,
        claim: Mapping[str, Any] | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        ttl_seconds: float | None = None,
        lease_start_utc: str | None = None,
        lease_duration_seconds: int | None = None,
    ) -> dict[str, Any] | None:
        """Atomically check-and-reserve capacity matching ``claim``."""
        requested = _requested_dimensions(claim, unit_claim_keys=self._unit_claim_keys)
        deal = dict(deal_ref or {})
        window_start, window_end = _lease_window(
            lease_start_utc=lease_start_utc,
            lease_duration_seconds=lease_duration_seconds,
        )
        with self._lock, self._session_factory() as db:
            self._expire_stale_holds(db)
            match = self._find_candidate(db, claim, requested, window_start, window_end)
            if match is None:
                return None
            resource, available = match
            hold_expires_at = None
            if ttl_seconds is not None:
                hold_expires_at = (
                    datetime.now(timezone.utc) + timedelta(seconds=float(ttl_seconds))
                ).isoformat()
            mirrored_units = int(requested.get(PRIMARY_DIMENSION, Decimal(0)))
            reservation = CapacityReservation(
                capacity_reservation_id=str(uuid.uuid4()),
                units=mirrored_units,
                dimensions=_serialize_dimensions(requested),
                state=ReservationState.reserved.value,
                deal_ref=deal,
                escrow_uid=deal.get("escrow_uid"),
                hold_expires_at=hold_expires_at,
                vm_host=(resource.attributes or {}).get("vm_host"),
                executor_kind=(
                    VM_EXECUTOR_KIND
                    if (resource.attributes or {}).get("vm_host")
                    else None
                ),
                lease_start_utc=window_start.isoformat() if window_start else None,
                lease_end_utc=window_end.isoformat() if window_end else None,
            )
            db.add(reservation)
            db.flush()
            db.add(CapacityReservationDebit(
                capacity_reservation_id=reservation.capacity_reservation_id,
                capacity_bucket_id=resource.capacity_bucket_id,
                dimensions=_serialize_dimensions(requested),
            ))
            db.add(CapacityEvent(
                kind="reserved",
                resource_id=resource.backing_resource_id,
                dimensions=_serialize_dimensions({k: -v for k, v in requested.items()}),
            ))
            db.commit()
            available_after = {
                key: available.get(key, Decimal(0)) - requested.get(key, Decimal(0))
                for key in set(available) | set(requested)
            }
            payload = self._match_payload(resource, available_after, requested)
            payload["capacity_reservation_id"] = reservation.capacity_reservation_id
            payload["settlement_resource_id"] = reservation.settlement_resource_id
            payload["hold_expires_at"] = hold_expires_at
            return payload

    def assign_settlement_resource(
        self, *, capacity_reservation_id: str, settlement_resource_id: str
    ) -> dict[str, Any] | None:
        """Atomically bind a held reservation to the selected physical resource.

        Opens and commits its own transaction. Callers that must combine this
        rebind with another repository's write in one transaction (for
        example, persisting a settlement/fulfillment assignment alongside it)
        should use ``assign_settlement_resource_in_session`` against a session
        they already hold open, not this method.
        """
        with self._lock, self._session_factory() as db:
            self._expire_stale_holds(db)
            result = self.assign_settlement_resource_in_session(
                db,
                capacity_reservation_id=capacity_reservation_id,
                settlement_resource_id=settlement_resource_id,
            )
            db.commit()
            return result

    def assign_settlement_resource_in_session(
        self, db: Session, *, capacity_reservation_id: str, settlement_resource_id: str
    ) -> dict[str, Any] | None:
        """Session-scoped core of ``assign_settlement_resource``.

        Does not commit or expire stale holds: the caller owns the
        transaction boundary and decides when those happen relative to its
        own writes in the same session. Availability accounting is
        unchanged by this method: it still keys off ``resource_id``, which
        this method still moves on an actual reassignment, exactly as
        before ``settlement_resource_id`` existed. ``settlement_resource_id``
        is a scheduling-state marker, not a second accounting key. After
        assignment it identifies the concrete resource selected for
        fulfillment. Repeating the same assignment is idempotent.
        """
        reservation = self._find_reservation(db, capacity_reservation_id=capacity_reservation_id)
        if reservation is None:
            return None
        if reservation.state not in HELD_RESERVATION_STATES:
            raise CapacityConflictError(
                f"reservation {capacity_reservation_id} is {reservation.state}; cannot assign settlement resource"
            )
        if self._backing_resource_id(db, reservation.capacity_reservation_id) == settlement_resource_id:
            if reservation.settlement_resource_id != settlement_resource_id:
                reservation.settlement_resource_id = settlement_resource_id
            return self._reservation_payload(reservation)
        destination = self._bucket_by_backing_resource(db, settlement_resource_id)
        if destination is None or not destination.enabled:
            raise CapacityConflictError(
                f"settlement resource {settlement_resource_id!r} is unavailable"
            )
        reservation_dims = _reservation_dimensions(reservation)
        held = self._held_dimensions(db, settlement_resource_id)
        capacity = _resource_capacity(destination)
        insufficient = any(
            capacity.get(dim, Decimal(0)) - held.get(dim, Decimal(0)) < amount
            for dim, amount in reservation_dims.items()
        )
        if insufficient:
            raise CapacityConflictError(
                f"settlement resource {settlement_resource_id!r} lacks capacity"
            )
        source_id = self._backing_resource_id(db, reservation.capacity_reservation_id)
        debit = self._debit_for_reservation(db, reservation.capacity_reservation_id)
        if debit is None:
            raise CapacityConflictError(f"reservation {capacity_reservation_id} has no capacity debit")
        debit.capacity_bucket_id = destination.capacity_bucket_id
        reservation.settlement_resource_id = settlement_resource_id
        reservation.vm_host = (destination.attributes or {}).get("vm_host")
        serialized_dims = _serialize_dimensions(reservation_dims)
        db.add(CapacityEvent(
            kind="capacity_released_for_reassignment",
            resource_id=source_id,
            dimensions=serialized_dims,
        ))
        db.add(CapacityEvent(
            kind="capacity_assigned_for_settlement",
            resource_id=settlement_resource_id,
            dimensions=_serialize_dimensions({k: -v for k, v in reservation_dims.items()}),
        ))
        return self._reservation_payload(reservation)

    def lock_reservation(
        self, db: Session, capacity_reservation_id: str
    ) -> CapacityReservation | None:
        """Return the reservation row locked ``FOR UPDATE`` within ``db``.

        For callers building one transaction across the reservation and
        another repository's write (for example, a settlement/fulfillment
        assignment) — ``get_reservation`` and ``_find_reservation`` read
        without a row lock and are not a substitute for this when a
        concurrent scheduling attempt against the same reservation must be
        serialized rather than race.
        """
        return db.get(CapacityReservation, capacity_reservation_id, with_for_update=True)

    def backing_resource_id_in_session(
        self, db: Session, capacity_reservation_id: str
    ) -> str | None:
        """Public, session-scoped exposure of the private backing-resource lookup.

        Lets a caller already holding ``db`` open (for example, while
        evaluating scheduling eligibility inside one atomic transaction)
        read this without opening a second session.
        """
        return self._backing_resource_id(db, capacity_reservation_id)

    def commit(
        self,
        *,
        resource_id: str | None = None,
        capacity_reservation_id: str | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        idempotency_ref: str | None = None,
    ) -> dict[str, Any] | None:
        """Confirm a reservation into an active lease.

        Idempotent: committing an already-leased reservation records the
        derived lease window and clears any TTL hold. ``lease_end_utc=None``
        commits an open-ended hold (no lease tail — the watchdog never sees it).
        """
        window_start, window_end = _lease_window(
            lease_start_utc=lease_start_utc,
            lease_end_utc=lease_end_utc,
        )
        with self._lock, self._session_factory() as db:
            reservation = self._find_reservation(
                db, capacity_reservation_id=capacity_reservation_id,
                resource_id=None if capacity_reservation_id else resource_id,
            )
            if reservation is None:
                return None
            if reservation.state not in HELD_RESERVATION_STATES:
                raise CapacityConflictError(
                    f"reservation {reservation.capacity_reservation_id} is "
                    f"{reservation.state}; cannot commit"
                )
            reservation.state = ReservationState.leased.value
            if window_end is not None:
                reservation.lease_end_utc = str(lease_end_utc)
            reservation.hold_expires_at = None
            if window_start is not None:
                reservation.lease_start_utc = window_start.isoformat()
            elif not reservation.lease_start_utc:
                reservation.lease_start_utc = datetime.now(timezone.utc).isoformat()
            db.add(CapacityEvent(kind="committed", resource_id=self._backing_resource_id(db, reservation.capacity_reservation_id)))
            db.commit()
            return self._reservation_payload(reservation)

    def release(
        self,
        *,
        capacity_reservation_id: str | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        state: str = ReservationState.released.value,
        failure_reason: str | None = None,
        failure_message: str | None = None,
    ) -> dict[str, Any] | None:
        """Return a held/leased reservation's capacity to the pool."""
        escrow_uid = dict(deal_ref or {}).get("escrow_uid")
        with self._lock, self._session_factory() as db:
            reservation = self._find_reservation(
                db, capacity_reservation_id=capacity_reservation_id,
                escrow_uid=None if capacity_reservation_id else escrow_uid,
            )
            if reservation is None:
                return None
            if reservation.state in {
                ReservationState.released.value,
                ReservationState.force_released.value,
            }:
                return self._reservation_payload(reservation)
            if reservation.state not in HELD_RESERVATION_STATES:
                return None
            reservation.state = state
            reservation.released_at = datetime.now(timezone.utc).isoformat()
            reservation.failure_reason = failure_reason
            reservation.failure_message = failure_message
            db.add(CapacityEvent(
                kind="released",
                resource_id=self._backing_resource_id(db, reservation.capacity_reservation_id),
                dimensions=_serialize_dimensions(_reservation_dimensions(reservation)),
            ))
            db.commit()
            return self._reservation_payload(reservation)

    def truncate_lease(
        self,
        *,
        capacity_reservation_id: str,
        lease_end_utc: str,
    ) -> dict[str, Any] | None:
        """End a lease early; injected compute lifecycle observes the new expiry."""
        with self._lock, self._session_factory() as db:
            reservation = self._find_reservation(db, capacity_reservation_id=capacity_reservation_id)
            if reservation is None or reservation.state not in HELD_RESERVATION_STATES:
                return None
            reservation.state = ReservationState.leased.value
            reservation.lease_end_utc = str(lease_end_utc)
            db.add(CapacityEvent(
                kind="lease_truncated", resource_id=self._backing_resource_id(db, reservation.capacity_reservation_id),
            ))
            db.commit()
            return self._reservation_payload(reservation)

    # ------------------------------------------------------------------
    # Lease tail (the merged vm_leases half of the reservation row)
    # ------------------------------------------------------------------

    def attach_lease(
        self,
        *,
        capacity_reservation_id: str | None = None,
        escrow_uid: str | None = None,
        vm_host: str | None = None,
        vm_target: str | None = None,
        executor_kind: str | None = None,
        executor_target: str | None = None,
        executor_ref: Mapping[str, Any] | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        create_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Record the lease tail on an existing held reservation.

        The ledger-mode replacement for registering a ``vm_leases`` row:
        the reservation and its lease are one record, so the watchdog
        tears down and releases in one local transaction. Emits no
        capacity event — availability already moved at commit time.
        Returns None when no held reservation matches (the caller falls
        back to the legacy lease table).
        """
        with self._lock, self._session_factory() as db:
            reservation = self._find_reservation(
                db, capacity_reservation_id=capacity_reservation_id,
                escrow_uid=None if capacity_reservation_id else escrow_uid,
            )
            if reservation is None or reservation.state not in HELD_RESERVATION_STATES:
                return None
            if vm_host:
                reservation.vm_host = vm_host
            if vm_target:
                reservation.vm_target = vm_target
            self._sync_executor_fields(
                reservation,
                executor_kind=executor_kind,
                executor_target=executor_target,
                executor_ref=executor_ref,
            )
            if lease_start_utc:
                reservation.lease_start_utc = str(lease_start_utc)
            if lease_end_utc:
                reservation.lease_end_utc = str(lease_end_utc)
            if create_job_id:
                reservation.create_job_id = create_job_id
            if escrow_uid and not reservation.escrow_uid:
                reservation.escrow_uid = escrow_uid
            reservation.state = ReservationState.leased.value
            db.commit()
            return self._reservation_payload(reservation)

    def list_lease_due(self, now: datetime) -> list[dict[str, Any]]:
        """Leased reservations whose lease_end_utc has passed."""
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        due: list[dict[str, Any]] = []
        with self._lock, self._session_factory() as db:
            rows = (
                db.query(CapacityReservation)
                .filter(
                    CapacityReservation.state == ReservationState.leased.value,
                    CapacityReservation.lease_end_utc.isnot(None),
                )
                .all()
            )
            for reservation in rows:
                lease_end = parse_utc(reservation.lease_end_utc)
                if lease_end is not None and lease_end <= now:
                    due.append(self._reservation_payload(reservation))
        return due

    def begin_releasing(
        self,
        capacity_reservation_id: str,
        *,
        vm_remove_job_id: str | None = None,
        release_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Transition a leased reservation to releasing (teardown in flight).

        No capacity event: releasing still holds the units — the workload
        may not be torn down yet.
        """
        with self._lock, self._session_factory() as db:
            reservation = db.get(CapacityReservation, capacity_reservation_id)
            if reservation is None or reservation.state not in HELD_RESERVATION_STATES:
                return None
            reservation.state = ReservationState.releasing.value
            self._sync_release_job_fields(
                reservation,
                release_job_id=release_job_id or vm_remove_job_id,
            )
            db.commit()
            return self._reservation_payload(reservation)

    def update_lease_fields(
        self,
        capacity_reservation_id: str,
        *,
        vm_host: str | None = None,
        vm_target: str | None = None,
        executor_kind: str | None = None,
        executor_target: str | None = None,
        executor_ref: Mapping[str, Any] | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        vm_remove_job_id: str | None = None,
        release_job_id: str | None = None,
        create_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Update lease-tail fields on a non-terminal reservation.

        Unlike ``attach_lease``, this operates on any non-terminal state
        (including ``releasing``) and never changes the reservation state.
        Returns ``None`` when the reservation does not exist or is already
        terminal.  Used by the operator PATCH endpoint to update expiry time,
        host coordinates, or job references without driving a state transition.
        """
        with self._lock, self._session_factory() as db:
            reservation = db.get(CapacityReservation, capacity_reservation_id)
            terminal = {
                ReservationState.released.value,
                ReservationState.force_released.value,
                ReservationState.provisioning_failed.value,
            }
            if reservation is None or reservation.state in terminal:
                return None
            if vm_host is not None:
                reservation.vm_host = vm_host
            if vm_target is not None:
                reservation.vm_target = vm_target
            self._sync_executor_fields(
                reservation,
                executor_kind=executor_kind,
                executor_target=executor_target,
                executor_ref=executor_ref,
            )
            if lease_start_utc is not None:
                reservation.lease_start_utc = str(lease_start_utc)
            if lease_end_utc is not None:
                reservation.lease_end_utc = str(lease_end_utc)
            self._sync_release_job_fields(
                reservation,
                release_job_id=release_job_id or vm_remove_job_id,
            )
            if create_job_id is not None:
                reservation.create_job_id = create_job_id
            db.commit()
            return self._reservation_payload(reservation)

    def find_active_lease_by_vm_target(
        self, vm_host: str, vm_target: str
    ) -> dict[str, Any] | None:
        """Return the first active (held) lease reservation for a VM, or None.

        Used by the ``POST /vms/{vm_name}/remove`` endpoint to cancel any
        watchdog-managed lease before submitting the explicit removal job,
        avoiding a double-fire when the lease would otherwise expire later.
        """
        with self._lock, self._session_factory() as db:
            reservation = (
                db.query(CapacityReservation)
                .filter(
                    CapacityReservation.vm_host == vm_host,
                    CapacityReservation.vm_target == vm_target,
                    CapacityReservation.state.in_(HELD_RESERVATION_STATES),
                    CapacityReservation.lease_end_utc.isnot(None),
                )
                .order_by(CapacityReservation.created_at.desc())
                .first()
            )
            return self._reservation_payload(reservation) if reservation else None


    def update_reservation_state(
        self,
        capacity_reservation_id: str,
        *,
        state: str,
        failure_reason: str | None = None,
        failure_message: str | None = None,
        vm_remove_job_id: str | None = None,
        release_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Update a site reservation state without emitting capacity events.

        This is a generic state mutation primitive for lifecycle services.
        Releasing, release_failed, and unmanaged still consume capacity; use
        ``release`` when capacity should become available and an event should be
        published.
        """
        with self._lock, self._session_factory() as db:
            reservation = db.get(CapacityReservation, capacity_reservation_id)
            if reservation is None:
                return None
            reservation.state = str(state)
            if failure_reason is not None:
                reservation.failure_reason = failure_reason
            if failure_message is not None:
                reservation.failure_message = failure_message
            self._sync_release_job_fields(
                reservation,
                release_job_id=release_job_id or vm_remove_job_id,
            )
            db.commit()
            return self._reservation_payload(reservation)

    # ------------------------------------------------------------------
    # Event feed
    # ------------------------------------------------------------------

    def events_after(
        self, after_version: int, *, limit: int = 500
    ) -> tuple[list[dict[str, Any]], int]:
        """Return (events newer than ``after_version``, latest version).

        The latest version is reported even when ``limit`` truncates the
        page, so pollers know to keep paging; a subscriber that finds a
        gap versus what it last applied resyncs from a snapshot.
        """
        with self._lock, self._session_factory() as db:
            rows = (
                db.query(CapacityEvent)
                .filter(CapacityEvent.version > int(after_version))
                .order_by(CapacityEvent.version.asc())
                .limit(int(limit))
                .all()
            )
            latest = (
                db.query(CapacityEvent.version)
                .order_by(CapacityEvent.version.desc())
                .limit(1)
                .scalar()
            ) or 0
            events = [
                {
                    "version": row.version,
                    "kind": row.kind,
                    "resource_id": row.resource_id,
                    "dimensions": dict(row.dimensions) if row.dimensions else None,
                    "occurred_at": (
                        row.occurred_at.isoformat() if row.occurred_at else None
                    ),
                }
                for row in rows
            ]
            return events, int(latest)

    # ------------------------------------------------------------------
    # Reservation queries (watchdog / deal-event plumbing)
    # ------------------------------------------------------------------

    def get_reservation(self, capacity_reservation_id: str) -> dict[str, Any] | None:
        with self._lock, self._session_factory() as db:
            reservation = db.get(CapacityReservation, capacity_reservation_id)
            return self._reservation_payload(reservation) if reservation else None

    def get_reservation_by_escrow(self, escrow_uid: str) -> dict[str, Any] | None:
        with self._lock, self._session_factory() as db:
            reservation = self._find_reservation(db, escrow_uid=escrow_uid)
            return self._reservation_payload(reservation) if reservation else None

    def get_reservation_backing_resource_id(
        self, capacity_reservation_id: str
    ) -> str | None:
        """Return the private inventory resource currently backing a reservation.

        This lookup is for provisioning and scheduling bookkeeping. The backing
        resource is intentionally absent from the storefront-facing reservation
        payload because admission does not create a durable placement commitment.
        """
        with self._lock, self._session_factory() as db:
            return self._backing_resource_id(db, capacity_reservation_id)

    def list_reservations(
        self, *, state: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock, self._session_factory() as db:
            q = db.query(CapacityReservation)
            if state is not None:
                q = q.filter(CapacityReservation.state == state)
            rows = q.order_by(CapacityReservation.created_at.asc()).all()
            return [self._reservation_payload(row) for row in rows]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _debit_for_reservation(
        db: Session, capacity_reservation_id: str
    ) -> CapacityReservationDebit | None:
        return db.get(CapacityReservationDebit, capacity_reservation_id)

    @staticmethod
    def _bucket_by_backing_resource(
        db: Session, backing_resource_id: str
    ) -> CapacityBucket | None:
        return (
            db.query(CapacityBucket)
            .filter(CapacityBucket.backing_resource_id == backing_resource_id)
            .one_or_none()
        )

    def _bucket_for_reservation(
        self, db: Session, capacity_reservation_id: str
    ) -> CapacityBucket | None:
        debit = self._debit_for_reservation(db, capacity_reservation_id)
        return db.get(CapacityBucket, debit.capacity_bucket_id) if debit is not None else None

    def _backing_resource_id(self, db: Session, capacity_reservation_id: str) -> str | None:
        bucket = self._bucket_for_reservation(db, capacity_reservation_id)
        return bucket.backing_resource_id if bucket is not None else None

    def expire_due_holds(self) -> None:
        """Public entry point for a periodic watchdog to sweep expired holds.

        Every ``reserve``/``commit``/``release``/``probe`` call already runs
        :meth:`_expire_stale_holds` lazily against its own open session, so
        an uncommitted hold is self-healing the moment anything touches the
        ledger again. This method exists for the case where nothing does —
        an idle site with no incoming requests — so a hold doesn't sit
        expired-but-unreleased indefinitely.
        """
        with self._lock, self._session_factory() as db:
            self._expire_stale_holds(db)

    def _expire_stale_holds(self, db: Session) -> None:
        """Lapse TTL'd reservations whose hold expired without a commit.

        Runs lazily ahead of reads and reserves so expired holds never
        block capacity; each lapse emits a "released" event in the same
        transaction.
        """
        now = datetime.now(timezone.utc)
        stale = (
            db.query(CapacityReservation)
            .filter(
                CapacityReservation.state == ReservationState.reserved.value,
                CapacityReservation.hold_expires_at.isnot(None),
            )
            .all()
        )
        lapsed = False
        for reservation in stale:
            expires = parse_utc(reservation.hold_expires_at)
            if expires is None or expires > now:
                continue
            reservation.state = ReservationState.released.value
            reservation.released_at = now.isoformat()
            reservation.failure_reason = "hold_expired"
            db.add(CapacityEvent(
                kind="released", resource_id=self._backing_resource_id(db, reservation.capacity_reservation_id),
            ))
            lapsed = True
            logger.info(
                "[CAPACITY] TTL hold expired for reservation %s (resource=%s)",
                reservation.capacity_reservation_id, self._backing_resource_id(db, reservation.capacity_reservation_id),
            )
        if lapsed:
            db.commit()

    def _held_dimensions(
        self,
        db: Session,
        resource_id: str,
        lease_start: datetime | None = None,
        lease_end: datetime | None = None,
    ) -> dict[str, Decimal]:
        """Sum held quantity per dimension across overlapping reservations.

        Generalizes the old single-dimension ``_held_units``.
        """
        bucket = self._bucket_by_backing_resource(db, resource_id)
        if bucket is None:
            return {}
        rows = (
            db.query(CapacityReservation)
            .join(
                CapacityReservationDebit,
                CapacityReservationDebit.capacity_reservation_id
                == CapacityReservation.capacity_reservation_id,
            )
            .filter(
                CapacityReservationDebit.capacity_bucket_id == bucket.capacity_bucket_id,
                CapacityReservation.state.in_(HELD_RESERVATION_STATES),
            )
            .all()
        )
        totals: dict[str, Decimal] = {}

        def _accumulate(row: CapacityReservation) -> None:
            for key, amount in _reservation_dimensions(row).items():
                totals[key] = totals.get(key, Decimal(0)) + amount

        if lease_start is None and lease_end is None:
            for row in rows:
                _accumulate(row)
            return totals
        for row in rows:
            if row.state in {
                ReservationState.releasing.value,
                ReservationState.release_failed.value,
                ReservationState.unmanaged.value,
            }:
                _accumulate(row)
                continue
            row_start = parse_utc(row.lease_start_utc)
            row_end = parse_utc(row.lease_end_utc)
            if row_start is None and row_end is None:
                # Legacy/current holds without a window block every window.
                _accumulate(row)
                continue
            if _windows_overlap(lease_start, lease_end, row_start, row_end):
                _accumulate(row)
        return totals

    def _held_units(
        self,
        db: Session,
        resource_id: str,
        lease_start: datetime | None = None,
        lease_end: datetime | None = None,
    ) -> int:
        """Legacy single-dimension accessor, kept for the primary mirror."""
        held = self._held_dimensions(db, resource_id, lease_start, lease_end)
        return int(held.get(PRIMARY_DIMENSION, Decimal(0)))

    def _find_candidate(
        self,
        db: Session,
        claim: Mapping[str, Any] | None,
        requested: Mapping[str, Decimal],
        lease_start: datetime | None = None,
        lease_end: datetime | None = None,
    ) -> tuple[CapacityBucket, dict[str, Decimal]] | None:
        rows = (
            db.query(CapacityBucket)
            .filter(CapacityBucket.enabled.is_(True))
            .order_by(CapacityBucket.updated_at.asc())
            .all()
        )
        required_resource_kind, required_attributes = _split_claim_requirement(
            claim, unit_claim_keys=self._unit_claim_keys
        )
        for resource in rows:
            attrs = resource.attributes or {}
            if any(
                not isinstance(attrs.get(key), str) or not attrs[key].strip()
                for key in self._required_attributes
            ):
                continue
            if self._has_physical_host_conflict(
                db, resource, lease_start, lease_end,
            ):
                continue
            capacity = _resource_capacity(resource)
            held = self._held_dimensions(db, resource.backing_resource_id, lease_start, lease_end)
            available = {
                key: capacity.get(key, Decimal(0)) - held.get(key, Decimal(0))
                for key in capacity
            }
            if not resource_satisfies_requirement(
                resource=_resource_feasibility_view(resource, available),
                required_resource_kind=required_resource_kind,
                required_dimensions=requested,
                required_attributes=required_attributes,
            ):
                continue
            return resource, available
        return None

    def _find_reservation(
        self,
        db: Session,
        *,
        capacity_reservation_id: str | None = None,
        escrow_uid: str | None = None,
        resource_id: str | None = None,
    ) -> CapacityReservation | None:
        if capacity_reservation_id:
            return db.get(CapacityReservation, capacity_reservation_id)
        q = db.query(CapacityReservation).filter(
            CapacityReservation.state.in_(HELD_RESERVATION_STATES)
        )
        if escrow_uid:
            q = q.filter(CapacityReservation.escrow_uid == escrow_uid)
        elif resource_id:
            bucket = self._bucket_by_backing_resource(db, resource_id)
            if bucket is None:
                return None
            q = q.join(
                CapacityReservationDebit,
                CapacityReservationDebit.capacity_reservation_id
                == CapacityReservation.capacity_reservation_id,
            ).filter(CapacityReservationDebit.capacity_bucket_id == bucket.capacity_bucket_id)
        else:
            return None
        return q.order_by(CapacityReservation.created_at.desc()).first()

    def _resource_payload(self, db: Session, row: CapacityBucket) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        capacity = _resource_capacity(row)
        held = self._held_dimensions(
            db,
            row.backing_resource_id,
            now,
            now + timedelta(microseconds=1),
        )
        total = int(row.total_units or 0)
        held_primary = int(held.get(PRIMARY_DIMENSION, Decimal(0)))
        blocked = self._has_physical_host_conflict(
            db, row, now, now + timedelta(microseconds=1),
        )
        if blocked:
            available_map = {key: Decimal(0) for key in capacity}
            state = "leased"
        else:
            available_map = {
                key: max(capacity.get(key, Decimal(0)) - held.get(key, Decimal(0)), Decimal(0))
                for key in capacity
            }
            available_primary = int(available_map.get(PRIMARY_DIMENSION, Decimal(total)))
            if available_primary >= total or held_primary <= 0:
                state = "available"
            elif available_primary > 0:
                state = "available"
            else:
                state = "leased"
        return {
            "resource_id": row.backing_resource_id,
            "pool_id": row.pool_id,
            "resource_type": row.resource_type,
            "resource_subtype": row.resource_subtype,
            "unit": "count",
            "value": total,
            "state": state,
            "available_units": int(available_map.get(PRIMARY_DIMENSION, Decimal(total))),
            "capacity": _serialize_dimensions(capacity),
            "available": _serialize_dimensions(available_map),
            "attributes": dict(row.attributes or {}),
            "enabled": bool(row.enabled),
        }

    def _has_physical_host_conflict(
        self,
        db: Session,
        resource: CapacityBucket,
        lease_start: datetime | None = None,
        lease_end: datetime | None = None,
    ) -> bool:
        physical_host_id = self._physical_host_id(resource)
        mode = self._allocation_mode(resource)
        if not physical_host_id or mode is None:
            return False

        rows = (
            db.query(CapacityReservation)
            .filter(CapacityReservation.state.in_(HELD_RESERVATION_STATES))
            .all()
        )
        for reservation in rows:
            held_resource = self._bucket_for_reservation(db, reservation.capacity_reservation_id)
            if held_resource is None:
                continue
            if self._physical_host_id(held_resource) != physical_host_id:
                continue
            held_mode = self._allocation_mode(held_resource)
            if held_mode is None:
                continue
            if not self._reservation_overlaps(reservation, lease_start, lease_end):
                continue
            if mode == ALLOCATION_MODE_EXCLUSIVE:
                return True
            if held_mode == ALLOCATION_MODE_EXCLUSIVE:
                return True
        return False

    @staticmethod
    def _reservation_overlaps(
        reservation: CapacityReservation,
        lease_start: datetime | None = None,
        lease_end: datetime | None = None,
    ) -> bool:
        if reservation.state in {
            ReservationState.releasing.value,
            ReservationState.release_failed.value,
            ReservationState.unmanaged.value,
        }:
            return True
        row_start = parse_utc(reservation.lease_start_utc)
        row_end = parse_utc(reservation.lease_end_utc)
        if row_start is None and row_end is None:
            return True
        return _windows_overlap(lease_start, lease_end, row_start, row_end)

    @staticmethod
    def _physical_host_id(resource: CapacityBucket) -> str | None:
        value = (resource.attributes or {}).get(PHYSICAL_HOST_ID_ATTR)
        return str(value) if value else None

    @staticmethod
    def _allocation_mode(resource: CapacityBucket) -> str | None:
        value = str((resource.attributes or {}).get(ALLOCATION_MODE_ATTR) or "")
        if value in {ALLOCATION_MODE_EXCLUSIVE, ALLOCATION_MODE_SHAREABLE}:
            return value
        return None

    @staticmethod
    def _match_payload(
        resource: CapacityBucket,
        available: Mapping[str, Decimal],
        requested: Mapping[str, Decimal],
    ) -> dict[str, Any]:
        """Shape a probe/reserve result like the embedded adapter's.

        pool/member are storefront (aggregator) concepts the site does not
        know; they are present-and-None for payload compatibility.
        ``requested``/``available`` are full per-dimension maps (
        pass 1); ``allocated_units``/``available_units`` and their
        ``*_gpu_count`` aliases stay byte-compatible by mirroring the
        primary (``gpu_count``) dimension.
        """
        attrs = dict(resource.attributes or {})
        allocated_primary = int(requested.get(PRIMARY_DIMENSION, Decimal(0)))
        available_primary = int(available.get(PRIMARY_DIMENSION, Decimal(0)))
        return {
            "resource_id": resource.backing_resource_id,
            "pool_id": None,
            "member_id": None,
            "vm_host": attrs.get("vm_host"),
            "resource_subtype": resource.resource_subtype,
            "unit": "count",
            "state": "available",
            "value": int(resource.total_units or 0),
            "allocated_units": allocated_primary,
            "available_units": available_primary,
            # VM-domain aliases, kept so the remote client stays
            # byte-compatible with the embedded adapter it replaced.
            "allocated_gpu_count": allocated_primary,
            "available_gpu_count": available_primary,
            "dimensions": _serialize_dimensions(requested),
            "available": _serialize_dimensions(available),
            "capacity": _serialize_dimensions(_resource_capacity(resource)),
            "attributes": attrs,
        }

    @staticmethod
    def _reservation_payload(reservation: CapacityReservation) -> dict[str, Any]:
        return {
            "capacity_reservation_id": reservation.capacity_reservation_id,
            "settlement_resource_id": reservation.settlement_resource_id,
            "pool_id": None,
            "units": int(reservation.units or 0),
            "allocated_gpu_count": int(reservation.units or 0),
            "dimensions": _serialize_dimensions(_reservation_dimensions(reservation)),
            "state": reservation.state,
            "deal_ref": dict(reservation.deal_ref or {}),
            "escrow_uid": reservation.escrow_uid,
            "hold_expires_at": reservation.hold_expires_at,
            "executor_kind": reservation.executor_kind,
            "executor_target": reservation.executor_target,
            "release_job_id": reservation.release_job_id,
            "executor_ref": dict(reservation.executor_ref or {}),
            "vm_host": reservation.vm_host,
            "vm_target": reservation.vm_target,
            "lease_start_utc": reservation.lease_start_utc,
            "lease_end_utc": reservation.lease_end_utc,
            "create_job_id": reservation.create_job_id,
            "vm_remove_job_id": reservation.vm_remove_job_id,
            "failure_reason": reservation.failure_reason,
            "released_at": reservation.released_at,
        }

    @staticmethod
    def _sync_executor_fields(
        reservation: CapacityReservation,
        *,
        executor_kind: str | None = None,
        executor_target: str | None = None,
        executor_ref: Mapping[str, Any] | None = None,
    ) -> None:
        if executor_kind is not None:
            reservation.executor_kind = executor_kind
        elif reservation.vm_host and not reservation.executor_kind:
            reservation.executor_kind = VM_EXECUTOR_KIND

        if executor_target is not None:
            reservation.executor_target = executor_target
        elif reservation.vm_target and not reservation.executor_target:
            reservation.executor_target = reservation.vm_target

        if executor_ref is not None:
            reservation.executor_ref = dict(executor_ref)
        elif reservation.vm_host and not reservation.executor_ref:
            reservation.executor_ref = {"vm_host": reservation.vm_host}

    @staticmethod
    def _sync_release_job_fields(
        reservation: CapacityReservation,
        *,
        release_job_id: str | None,
    ) -> None:
        if release_job_id is None:
            return
        reservation.release_job_id = release_job_id
        if reservation.executor_kind in (None, VM_EXECUTOR_KIND):
            reservation.vm_remove_job_id = release_job_id
