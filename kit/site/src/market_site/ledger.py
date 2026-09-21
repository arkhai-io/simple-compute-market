"""Site-authority capacity ledger.

The authoritative resource ledger for this site
(docs/development/ARCHITECTURE.md, "Capacity and the Site Authority"):
unit-counted resources, reservation holds with their lease tail, and the
anonymous versioned capacity-event feed. Storefronts reach it through
the ``/api/v1/capacity`` HTTP surface, which mirrors the
``core_storefront.capacity.SiteCapacityAuthority`` contract verb for verb.

Matching semantics: a claim is an exact-match attribute mapping plus a
quantity request, checked first against the resource's attributes JSON
and then against its top-level fields. Domain-specific eligibility should
normally be expressed in those claims — for example bare-metal claims
name ``physical_host_id`` and ``allocation_mode``. The host a resource is
delivered through is its ``host_id`` column, not a matchable attribute. ``required_attributes`` remains available for
single-domain hosts that need a coarse local invariant, but multi-domain
provisioners should pass none.

A claim's ``dimensions`` mapping is authoritative when present and is
checked against every dimension a candidate resource declares in its
``capacity`` map.

Legacy single-quantity claims (``units`` and composition-supplied aliases)
keep working. They translate to ``dimensions={<mirror>: n}``, where the
mirror dimension is supplied by the composition root. ``CapacityBucket
.total_units`` and ``CapacityReservation.units`` remain service-maintained
mirrors of that one dimension for payload and caller compatibility; a
declaration that names no mirror dimension has no ``total_units``.

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
from collections.abc import Iterator
from contextlib import contextmanager
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Optional, Protocol, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker
from market_resource_pools import (
    DEFAULT_POOL_ID,
    ResourcePool,
    pool_delivers_offering_mode,
)

from .declarations import CapacityDeclaration
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
VM_OFFERING_MODE = "vm"
OFFERING_MODE_CLAIM_KEY = "offering_mode"


def _executor_ref_for_resource(resource: CapacityBucket) -> dict[str, Any] | None:
    """Build the generic ``executor_ref`` a reservation should carry when
    it binds to ``resource``, from that resource's ``host_id``.

    ``kit/site`` carries no VM-specific columns on the shared reservation
    table — physical placement identity lives uniformly in the generic
    ``executor_ref`` JSON field across every domain, the same way
    bare-metal's ``physical_host_id`` already does. This is the one place
    that derivation happens, used by every reservation-binding write site
    (fresh reservation, resize-supersede, settlement-resource rebind) so
    they cannot drift from each other.
    """
    return {"host_id": resource.host_id} if resource.host_id else None


class CapacityConflictError(Exception):
    """Raised when a mutation references a row in an incompatible state."""


class UnknownPoolError(ValueError):
    """A declaration names a Resource Pool the site does not have."""


class UndeclaredOfferingModeError(CapacityConflictError):
    """Raised when a matching pool does not declare the requested mode."""


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

# The dimension CapacityBucket.total_units / CapacityReservation.units and
# legacy single-quantity claims mirror when the composition root names none.
# Domain-neutral on purpose: a composition whose unit is something else (a
# VM's GPU count, say) supplies its own, the way it supplies unit_claim_keys.
_DEFAULT_MIRROR_DIMENSION = "units"

def _requested_offering_mode(
    claim: Mapping[str, Any] | None,
    *,
    required: bool,
) -> str | None:
    raw = (claim or {}).get(OFFERING_MODE_CLAIM_KEY)
    if raw is None:
        if required:
            raise ValueError(
                f"capacity claim must include explicit {OFFERING_MODE_CLAIM_KEY}"
            )
        return None
    if not isinstance(raw, str) or not raw.strip() or raw != raw.strip():
        raise ValueError(
            f"{OFFERING_MODE_CLAIM_KEY} must be a non-empty canonical string"
        )
    return raw



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
    mirror_dimension: str = _DEFAULT_MIRROR_DIMENSION,
) -> dict[str, Decimal]:
    """Parse a claim's quantity request as a dimensions map.

    ``dimensions`` is authoritative when *present* — not merely truthy.
    ``{"dimensions": {}}`` is a malformed claim (declares nothing to
    request) and must fail loudly rather than silently falling through to
    the legacy single-quantity parse, which would otherwise default to a
    request the caller never actually made.
    Only the *absence* of the key falls back to the legacy
    single-quantity claim (``units``/domain-specific aliases), translated
    to ``{mirror_dimension: n}`` so every existing caller's claim shape keeps
    working unchanged.
    """
    claim = claim or {}
    if _DIMENSIONS_CLAIM_KEY not in claim:
        return {
            mirror_dimension: Decimal(
                _requested_units(claim, unit_claim_keys=unit_claim_keys)
            )
        }
    raw = claim[_DIMENSIONS_CLAIM_KEY]
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError(f"dimensions must be a non-empty mapping, got {raw!r}")
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


def _resource_capacity(
    resource: CapacityBucket,
    mirror_dimension: str = _DEFAULT_MIRROR_DIMENSION,
) -> dict[str, Decimal]:
    """A resource's declared total capacity per dimension.

    Falls back to ``{mirror_dimension: total_units}`` for a row whose
    ``capacity`` map was never populated, and to no dimension at all when it
    has no ``total_units`` either.
    """
    if resource.capacity:
        return {
            str(key): _to_decimal_nonneg(value, label=f"capacity[{key}]")
            for key, value in resource.capacity.items()
        }
    if resource.total_units is None:
        return {}
    return {mirror_dimension: Decimal(int(resource.total_units))}


def _reservation_dimensions(
    reservation: CapacityReservation,
    mirror_dimension: str = _DEFAULT_MIRROR_DIMENSION,
) -> dict[str, Decimal]:
    """A reservation's held quantity per dimension.

    Falls back to ``{mirror_dimension: units}`` for rows that have never had
    ``dimensions`` populated.
    """
    if reservation.dimensions:
        return {
            str(key): Decimal(str(value))
            for key, value in reservation.dimensions.items()
        }
    return {mirror_dimension: Decimal(int(reservation.units or 0))}


def _capacity_change_kind(
    delta: Mapping[str, Decimal],
    *,
    old_enabled: bool | None,
    new_enabled: bool,
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
    host_id: str | None = None


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
    host_id: str | None = None,
    mirror_dimension: str = _DEFAULT_MIRROR_DIMENSION,
) -> ResourceFeasibilityView:
    """Build the immutable, authoritative view used for feasibility checks.

    ``mirror_dimension`` must be the one the backing ``CapacityLedgerService``
    was composed with: the scalar unit total is a matchable fact under that
    name and under ``units``, and under no other domain's dimension name.
    """
    # Claims match declared attributes and the resource's own facts in one
    # namespace, so the facts are written last: a declaration's fields and the
    # ledger's derived totals are authoritative, and an attribute of the same
    # name (possible only in a row stored before registration refused them)
    # must not restate them. ``host_id`` is a fact so a claim may pin the host
    # a resource is delivered through.
    authoritative_pool_id = pool_id or resource_id
    normalized = {
        **dict(attributes or {}),
        "resource_id": resource_id,
        "host_id": host_id,
        "resource_type": resource_kind,
        "resource_subtype": resource_subtype,
        "value": value,
        "units": units,
        mirror_dimension: units,
        "pool_id": authoritative_pool_id,
    }
    return ResourceFeasibilityView(
        resource_id=resource_id,
        pool_id=authoritative_pool_id,
        resource_kind=resource_kind,
        available=MappingProxyType(dict(available)),
        attributes=MappingProxyType(normalized),
        host_id=host_id,
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
    if (
        required_resource_kind is not None
        and resource.resource_kind != required_resource_kind
    ):
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


def dict_resource_satisfies_claim(
    row: Mapping[str, Any],
    claim: Mapping[str, Any] | None,
    *,
    unit_claim_keys: Sequence[str] = _DEFAULT_UNIT_CLAIM_KEYS,
    mirror_dimension: str = _DEFAULT_MIRROR_DIMENSION,
) -> bool:
    """Match a plain-dict ``snapshot()`` row against a claim, using the
    same requirement-parsing and feasibility semantics admission uses.

    An injectable ``ClaimMatcher`` for callers outside ``kit/site`` (see
    ``core/storefront/aggregation.py``) that need exact claim semantics
    against the wire-shaped snapshot payload rather than a live
    ``CapacityBucket``. Does no independent interpretation of the claim or
    the row: reuses ``_split_claim_requirement``/``_requested_dimensions``
    to parse the claim and ``resource_feasibility_view``/
    ``resource_satisfies_requirement`` to match it, so there remains
    exactly one implementation of both. Raises the same way the ledger's
    own admission path does on a malformed claim (e.g. an empty or
    non-mapping ``dimensions``) rather than silently treating it as
    unconstrained — the caller is expected to validate claims before they
    reach ranking or admission.

    A row missing an attribute the claim requires does not match: reading
    a missing key returns ``None``, which is equal to the required value
    only if the claim itself requires ``None`` — never treated as
    "unconstrained".

    ``unit_claim_keys`` and ``mirror_dimension`` must match whatever the
    backing ``CapacityLedgerService`` was composed with (e.g. VM's
    ``("units", "gpu_count")`` in ``container.py``) for the legacy
    non-dimensional claim fallback to agree with admission; the default
    here is the module-wide default, not any particular domain's.
    """
    if not claim:
        return True
    resource_kind, required_attributes = _split_claim_requirement(
        claim,
        unit_claim_keys=unit_claim_keys,
    )
    required_dimensions = _requested_dimensions(
        claim,
        unit_claim_keys=unit_claim_keys,
        mirror_dimension=mirror_dimension,
    )
    resource = resource_feasibility_view(
        resource_id=str(row.get("resource_id") or ""),
        pool_id=row.get("pool_id") or row.get("resource_id"),
        resource_kind=row.get("resource_type") or "",
        available=row.get("available") or {},
        attributes=row.get("attributes") or {},
        resource_subtype=row.get("resource_subtype"),
        value=row.get("value"),
        units=row.get("available_units"),
        host_id=row.get("host_id"),
        mirror_dimension=mirror_dimension,
    )
    return resource_satisfies_requirement(
        resource=resource,
        required_resource_kind=resource_kind,
        required_dimensions=required_dimensions,
        required_attributes=required_attributes,
    )


def _resource_feasibility_view(
    resource: CapacityBucket,
    available: Mapping[str, Any],
    mirror_dimension: str,
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
        host_id=resource.host_id,
        mirror_dimension=mirror_dimension,
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
        and key != OFFERING_MODE_CLAIM_KEY
        and key != "resource_type"
    }
    return claim.get("resource_type"), attributes


class SettlementAbandonmentHook(Protocol):
    """React to a reservation losing its capacity hold, within the caller's transaction.

    ``market_site`` must not import ``market_fulfillment`` (see
    ``openspec/specs/fulfillment/spec.md#dependency-boundary``), so this
    protocol lets ``CapacityLedgerService`` listing_resource every capacity-reclaiming
    site a chance to react without knowing what "settlement" or
    "fulfillment" mean. The concrete implementation is supplied by
    ``market_fulfillment`` at composition time and decides on its own
    whether there is anything to do; the ledger calls it unconditionally.
    """

    def __call__(self, db: Session, capacity_reservation_id: str) -> None: ...


class CapacityLedgerService:
    """Authoritative capacity operations over the site ledger tables."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        required_attributes: Sequence[str] = (),
        unit_claim_keys: Sequence[str] = _DEFAULT_UNIT_CLAIM_KEYS,
        mirror_dimension: str = _DEFAULT_MIRROR_DIMENSION,
        settlement_abandonment_hook: SettlementAbandonmentHook | None = None,
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

        ``mirror_dimension`` is the one dimension the legacy scalar
        ``total_units``/``units`` mirror and a legacy single-quantity claim
        requests. Supplied by the composition root for the same reason as
        ``unit_claim_keys``: the VM composition passes ``"gpu_count"``, and
        the domain-neutral default is ``"units"``.

        ``settlement_abandonment_hook``, if supplied, is called
        unconditionally, in the same open transaction, from every internal
        path that can strand a reservation's fulfillment-scheduling state
        while reclaiming its capacity: a lapsed TTL hold
        (``_expire_stale_holds``), a terminal release (``release``), and a
        negotiation-driven resize's supersede step (``resize_reservation``).
        Whether there is anything to react to is entirely the hook's
        decision, not this service's.
        """
        self._session_factory = session_factory
        self._required_attributes = tuple(required_attributes)
        self._unit_claim_keys = tuple(unit_claim_keys)
        self._mirror_dimension = mirror_dimension
        self._settlement_abandonment_hook = settlement_abandonment_hook
        # Re-entrant and held across READS too: the service's SQLite
        # engine is a StaticPool — every session shares one connection,
        # so an unserialized read interleaving with a write transaction
        # raises "cannot commit - no transaction is active". One site's
        # ledger has exactly one serialization point; this is it.
        self._lock = threading.RLock()
        # How deeply the current thread holds the lock through
        # ``serialized()``, so an in-session mutator can refuse to run
        # outside it.
        self._holding = threading.local()

    @contextmanager
    def serialized(self) -> Iterator[None]:
        """Hold the ledger's serialization lock for the enclosed work.

        Every ledger operation runs inside it. A caller composing ledger
        writes into its own transaction holds it around that whole
        transaction, through its commit: a check the ledger makes (a pool
        move against live obligations, say) is only true until something
        else commits, so the lock must outlast the write it guards.
        Re-entrant. Take it before opening the session, as every ledger
        operation does, so the lock is always acquired ahead of the database.
        """
        with self._lock:
            depth = getattr(self._holding, "depth", 0)
            self._holding.depth = depth + 1
            try:
                yield
            finally:
                self._holding.depth = depth

    def _require_serialized(self, operation: str) -> None:
        if not getattr(self._holding, "depth", 0):
            raise RuntimeError(
                f"{operation} writes into the caller's transaction and must run "
                "inside CapacityLedgerService.serialized(), held through that "
                "transaction's commit"
            )

    # ------------------------------------------------------------------
    # Resource registry
    # ------------------------------------------------------------------

    def register_resource(
        self,
        *,
        resource_id: str,
        pool_id: str,
        total_units: int | None = None,
        resource_type: str = "compute.gpu",
        resource_subtype: str | None = None,
        attributes: Mapping[str, Any] | None = None,
        capacity: Mapping[str, Any] | None = None,
        enabled: bool = True,
        host_id: str | None = None,
    ) -> dict[str, Any]:
        """Insert or update a ledger resource in its own transaction.

        See :meth:`register_resource_in_session` for the declaration rules.
        """
        with self.serialized(), self._session_factory() as db:
            payload = self.register_resource_in_session(
                db,
                resource_id=resource_id,
                pool_id=pool_id,
                total_units=total_units,
                resource_type=resource_type,
                resource_subtype=resource_subtype,
                attributes=attributes,
                capacity=capacity,
                enabled=enabled,
                host_id=host_id,
            )
            db.commit()
            return payload

    def register_resource_in_session(
        self,
        db: Session,
        *,
        resource_id: str,
        pool_id: str,
        total_units: int | None = None,
        resource_type: str = "compute.gpu",
        resource_subtype: str | None = None,
        attributes: Mapping[str, Any] | None = None,
        capacity: Mapping[str, Any] | None = None,
        enabled: bool = True,
        host_id: str | None = None,
    ) -> dict[str, Any]:
        """Insert or update a ledger resource inside the caller's transaction.

        The caller holds :meth:`serialized` around that transaction. Neither
        opens a session nor commits, so a caller can land a
        declaration together with other writes — a definition document's
        reconciliation and the digest recording it, most immediately.

        A declaration is authoritative for exactly the dimensions it names.
        ``capacity`` is the multidimensional total; when a caller supplies
        it, no dimension is added to it. Only a caller that declares no
        ``capacity`` falls back to the legacy scalar, which becomes
        ``{mirror_dimension: total_units}``. ``total_units`` is the
        service-maintained mirror of the mirror dimension and is absent when
        the declaration does not name that dimension: absent rather than
        zero, so the consistency check below never asserts a false equality.
        A ``total_units`` that disagrees with the declared mirror dimension is
        a caller bug and raises ``ValueError``, as does a declaration naming
        no dimension at all.

        ``pool_id`` is required. Registration replaces the whole
        declaration, so a defaulted pool would move the resource without
        anyone asking. ``host_id`` names the host this capacity is delivered
        through; at most one resource may name a given host.

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
        self._require_serialized("register_resource_in_session")
        if not pool_id:
            raise ValueError("a capacity declaration must name its pool_id")
        mirror = self._mirror_dimension
        if capacity:
            dimensions = dict(capacity)
            if total_units is not None and mirror in dimensions:
                supplied = _to_decimal_nonneg(
                    dimensions[mirror], label=f"capacity[{mirror}]"
                )
                if supplied != Decimal(int(total_units)):
                    raise ValueError(
                        f"capacity[{mirror!r}]={supplied} disagrees with "
                        f"total_units={total_units}; pass one consistent value"
                    )
        elif total_units is not None:
            dimensions = {mirror: int(total_units)}
        else:
            raise ValueError(
                "a capacity declaration must name at least one dimension"
            )
        return self.register_declaration_in_session(
            db,
            CapacityDeclaration(
                resource_id=resource_id,
                pool_id=pool_id,
                resource_type=resource_type,
                resource_subtype=resource_subtype,
                host_id=host_id,
                capacity=dimensions,
                attributes=dict(attributes or {}),
                enabled=enabled,
            ),
        )

    def register_declaration_in_session(
        self, db: Session, declaration: CapacityDeclaration
    ) -> dict[str, Any]:
        """Insert or replace one whole declaration inside the caller's transaction.

        The declaration is already valid in itself; what is refused here is
        what only stored state can decide: a pool the site does not have
        (``UnknownPoolError``), a host another resource already names, and a
        pool move while the resource holds a live obligation. Every refusal
        happens before anything is written. See
        :meth:`register_resource_in_session` for the event it emits.
        """
        self._require_serialized("register_declaration_in_session")
        if db.get(ResourcePool, declaration.pool_id) is None:
            raise UnknownPoolError(
                f"resource pool {declaration.pool_id!r} does not exist"
            )
        resource_id = declaration.resource_id
        bucket = self._bucket_by_backing_resource(db, resource_id)
        old_capacity = (
            _resource_capacity(bucket, self._mirror_dimension)
            if bucket is not None else {}
        )
        old_enabled = bool(bucket.enabled) if bucket is not None else None
        if declaration.host_id is not None:
            holder = (
                db.query(CapacityBucket)
                .filter(CapacityBucket.host_id == declaration.host_id)
                .one_or_none()
            )
            if holder is not None and holder.backing_resource_id != resource_id:
                raise CapacityConflictError(
                    f"host {declaration.host_id!r} already carries resource "
                    f"{holder.backing_resource_id!r}"
                )
        if (
            bucket is not None
            and (bucket.pool_id or DEFAULT_POOL_ID) != declaration.pool_id
        ):
            self._refuse_reassignment_under_obligation(db, bucket, declaration.pool_id)
        is_new = bucket is None
        if bucket is None:
            bucket = CapacityBucket(
                capacity_bucket_id=str(uuid.uuid4()),
                backing_resource_id=resource_id,
            )
            db.add(bucket)
        self._write_declaration(bucket, declaration)
        new_capacity = dict(declaration.capacity)
        delta = {
            key: new_capacity.get(key, Decimal(0))
            - old_capacity.get(key, Decimal(0))
            for key in set(new_capacity) | set(old_capacity)
        }
        kind = (
            "released"
            if is_new
            else _capacity_change_kind(
                delta,
                old_enabled=old_enabled,
                new_enabled=declaration.enabled,
            )
        )
        db.add(
            CapacityEvent(
                kind=kind,
                resource_id=resource_id,
                dimensions=_serialize_dimensions(delta),
            )
        )
        db.flush()
        return self._resource_payload(db, bucket)

    def _write_declaration(
        self, bucket: CapacityBucket, declaration: CapacityDeclaration
    ) -> None:
        """Store a declaration on its row, replacing every declared field.

        ``total_units`` is the service-maintained mirror of the composition's
        mirror dimension, absent when the declaration does not name it.
        """
        mirror = self._mirror_dimension
        bucket.pool_id = declaration.pool_id
        bucket.resource_type = declaration.resource_type
        bucket.resource_subtype = declaration.resource_subtype
        bucket.host_id = declaration.host_id
        bucket.capacity = _serialize_dimensions(declaration.capacity)
        bucket.total_units = (
            int(declaration.capacity[mirror]) if mirror in declaration.capacity else None
        )
        bucket.attributes = dict(declaration.attributes)
        bucket.enabled = declaration.enabled

    def _stored_declaration(self, bucket: CapacityBucket) -> CapacityDeclaration:
        """A row read back as the declaration it stores, without revalidating:
        stored state is compared as it is, including a row written before a
        rule it would now fail."""
        return CapacityDeclaration.model_construct(
            resource_id=bucket.backing_resource_id,
            pool_id=bucket.pool_id or DEFAULT_POOL_ID,
            resource_type=bucket.resource_type,
            resource_subtype=bucket.resource_subtype,
            host_id=bucket.host_id,
            capacity=_resource_capacity(bucket, self._mirror_dimension),
            attributes=dict(bucket.attributes or {}),
            enabled=bool(bucket.enabled),
        )

    def declaration_change_in_session(
        self, db: Session, declaration: CapacityDeclaration
    ) -> str:
        """Classify a whole declaration against the stored one.

        Returns ``"created"`` when nothing is stored under its resource id,
        ``"unchanged"`` when registering it would store exactly what is
        stored, and ``"updated"`` otherwise. Registration appends a capacity
        event even when it changes nothing, so a caller reconciling many
        declarations registers only those this does not call unchanged.
        Capacity compares as stored, so ``8`` and ``8.0`` are equal.
        """
        bucket = self._bucket_by_backing_resource(db, declaration.resource_id)
        if bucket is None:
            return "created"
        if self._stored_declaration(bucket) == declaration:
            return "unchanged"
        return "updated"

    def _refuse_reassignment_under_obligation(
        self, db: Session, bucket: CapacityBucket, new_pool_id: str
    ) -> None:
        """Refuse to move a resource between pools while it holds a live obligation.

        A reservation's pool is not recorded on the reservation; it is
        resolved through the resource's current ``pool_id``
        (``backing_pool_id_in_session``). Moving the resource would therefore
        change which pool governs an existing reservation without the
        reservation changing. A live obligation is a reservation in a
        capacity-holding state that is debited against this resource or
        assigned to it for settlement; every running workload holds one, so
        the rule needs no knowledge of fulfillment state.
        """
        debited = (
            db.query(CapacityReservation.capacity_reservation_id)
            .join(
                CapacityReservationDebit,
                CapacityReservationDebit.capacity_reservation_id
                == CapacityReservation.capacity_reservation_id,
            )
            .filter(
                CapacityReservationDebit.capacity_bucket_id
                == bucket.capacity_bucket_id,
                CapacityReservation.state.in_(HELD_RESERVATION_STATES),
            )
            .first()
        )
        assigned = (
            db.query(CapacityReservation.capacity_reservation_id)
            .filter(
                CapacityReservation.settlement_resource_id
                == bucket.backing_resource_id,
                CapacityReservation.state.in_(HELD_RESERVATION_STATES),
            )
            .first()
        )
        live = debited or assigned
        if live is not None:
            raise CapacityConflictError(
                f"resource {bucket.backing_resource_id!r} cannot move from pool "
                f"{bucket.pool_id or DEFAULT_POOL_ID!r} to {new_pool_id!r} while "
                f"reservation {live[0]!r} holds it"
            )

    def list_resources(self) -> list[dict[str, Any]]:
        with self.serialized(), self._session_factory() as db:
            self._expire_stale_holds(db)
            rows = (
                db.query(CapacityBucket).order_by(CapacityBucket.updated_at.asc()).all()
            )
            return [self._resource_payload(db, row) for row in rows]

    # ------------------------------------------------------------------
    # SiteCapacityAuthority verbs
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
        _requested_offering_mode(claim, required=True)
        requested = _requested_dimensions(
            claim,
            unit_claim_keys=self._unit_claim_keys,
            mirror_dimension=self._mirror_dimension,
        )
        window_start, window_end = _lease_window(
            lease_start_utc=lease_start_utc,
            lease_duration_seconds=lease_duration_seconds,
        )
        with self.serialized(), self._session_factory() as db:
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
        """Atomically check-and-reserve capacity matching ``claim``.

        Idempotent by ``deal_ref["escrow_uid"]`` when present: a repeat
        call for the same escrow_uid returns the existing held reservation
        (``reserved``/``provisioning``/``leased``/etc. -- anything in
        ``HELD_RESERVATION_STATES``) rather than minting a second one. This
        closes the gap a caller retrying ``reserve()`` after a crash would
        otherwise hit -- without it, a retry before the first reservation's
        identity was durably recorded elsewhere would reserve a second,
        orphaned unit of capacity for the same deal. An escrow_uid whose
        prior reservation already expired or was released is not found
        here (``_expire_stale_holds`` above already moved it out of
        ``HELD_RESERVATION_STATES``), so a genuinely new attempt after
        expiry still reserves fresh, correctly.
        """
        requested = _requested_dimensions(
            claim,
            unit_claim_keys=self._unit_claim_keys,
            mirror_dimension=self._mirror_dimension,
        )
        requested_mode = _requested_offering_mode(claim, required=True)
        # The same split `_find_candidate` matches on, recorded rather than
        # left to be recomputed. Admission already evaluates these; scheduling
        # later needs the same constraints and has no way to re-derive them,
        # because the claim is gone by then and the reservation kept only its
        # `dimensions`.
        #
        # A resource-pinned claim comes along for free: `resource_feasibility_view`
        # normalizes `resource_id` into the matched attribute mapping, so a
        # listing that named one resource is carried here as an ordinary
        # categorical constraint rather than needing a second mechanism.
        _, claim_attributes = _split_claim_requirement(
            claim, unit_claim_keys=self._unit_claim_keys
        )
        deal = dict(deal_ref or {})
        escrow_uid = deal.get("escrow_uid")
        window_start, window_end = _lease_window(
            lease_start_utc=lease_start_utc,
            lease_duration_seconds=lease_duration_seconds,
        )
        with self.serialized(), self._session_factory() as db:
            self._expire_stale_holds(db)
            if escrow_uid:
                existing = self._find_reservation(db, escrow_uid=escrow_uid)
                if existing is not None:
                    if existing.offering_mode != requested_mode:
                        raise CapacityConflictError(
                            "offering_mode does not match the existing reservation"
                        )
                    return self._reservation_payload_for_reserve(db, existing)
            match = self._find_candidate(db, claim, requested, window_start, window_end)
            if match is None:
                return None
            resource, available = match
            hold_expires_at = None
            if ttl_seconds is not None:
                hold_expires_at = (
                    datetime.now(timezone.utc) + timedelta(seconds=float(ttl_seconds))
                ).isoformat()
            mirrored_units = int(requested.get(self._mirror_dimension, Decimal(0)))
            reservation = CapacityReservation(
                capacity_reservation_id=str(uuid.uuid4()),
                units=mirrored_units,
                dimensions=_serialize_dimensions(requested),
                claim_attributes=dict(claim_attributes),
                state=ReservationState.reserved.value,
                deal_ref=deal,
                escrow_uid=deal.get("escrow_uid"),
                hold_expires_at=hold_expires_at,
                executor_ref=_executor_ref_for_resource(resource),
                offering_mode=requested_mode,
                lease_start_utc=window_start.isoformat() if window_start else None,
                lease_end_utc=window_end.isoformat() if window_end else None,
            )
            db.add(reservation)
            db.flush()
            db.add(
                CapacityReservationDebit(
                    capacity_reservation_id=reservation.capacity_reservation_id,
                    capacity_bucket_id=resource.capacity_bucket_id,
                    dimensions=_serialize_dimensions(requested),
                )
            )
            db.add(
                CapacityEvent(
                    kind="reserved",
                    resource_id=resource.backing_resource_id,
                    dimensions=_serialize_dimensions(
                        {k: -v for k, v in requested.items()}
                    ),
                )
            )
            db.commit()
            available_after = {
                key: available.get(key, Decimal(0)) - requested.get(key, Decimal(0))
                for key in set(available) | set(requested)
            }
            payload = self._match_payload(resource, available_after, requested)
            payload["capacity_reservation_id"] = reservation.capacity_reservation_id
            payload["settlement_resource_id"] = reservation.settlement_resource_id
            payload["hold_expires_at"] = hold_expires_at
            payload["offering_mode"] = requested_mode
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
        with self.serialized(), self._session_factory() as db:
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
        own writes in the same session, and holds :meth:`serialized` around
        it through the commit, because an assignment creates the live
        obligation a concurrent pool move checks for. Availability accounting is
        unchanged by this method: it still keys off ``resource_id``, which
        this method still moves on an actual reassignment, exactly as
        before ``settlement_resource_id`` existed. ``settlement_resource_id``
        is a scheduling-state marker, not a second accounting key. After
        assignment it identifies the concrete resource selected for
        fulfillment. Repeating the same assignment is idempotent.
        """
        self._require_serialized("assign_settlement_resource_in_session")
        reservation = self._find_reservation(
            db, capacity_reservation_id=capacity_reservation_id
        )
        if reservation is None:
            return None
        if reservation.state not in HELD_RESERVATION_STATES:
            raise CapacityConflictError(
                f"reservation {capacity_reservation_id} is {reservation.state}; cannot assign settlement resource"
            )
        destination = self._bucket_by_backing_resource(db, settlement_resource_id)
        if destination is None or not destination.enabled:
            raise CapacityConflictError(
                f"settlement resource {settlement_resource_id!r} is unavailable"
            )
        requested_mode = reservation.offering_mode
        if not requested_mode:
            raise CapacityConflictError(
                f"reservation {capacity_reservation_id} has no executor identity"
            )
        if not self._pool_declares_mode(db, destination, requested_mode):
            raise UndeclaredOfferingModeError(
                f"offering mode {requested_mode!r} is not declared by pool "
                f"{destination.pool_id or DEFAULT_POOL_ID!r}"
            )
        if (
            self._backing_resource_id(db, reservation.capacity_reservation_id)
            == settlement_resource_id
        ):
            if reservation.settlement_resource_id != settlement_resource_id:
                reservation.settlement_resource_id = settlement_resource_id
            return self._reservation_payload(reservation)
        reservation_dims = _reservation_dimensions(reservation, self._mirror_dimension)
        held = self._held_dimensions(db, settlement_resource_id)
        capacity = _resource_capacity(destination, self._mirror_dimension)
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
            raise CapacityConflictError(
                f"reservation {capacity_reservation_id} has no capacity debit"
            )
        debit.capacity_bucket_id = destination.capacity_bucket_id
        reservation.settlement_resource_id = settlement_resource_id
        reservation.executor_ref = _executor_ref_for_resource(destination)
        serialized_dims = _serialize_dimensions(reservation_dims)
        db.add(
            CapacityEvent(
                kind="capacity_released_for_reassignment",
                resource_id=source_id,
                dimensions=serialized_dims,
            )
        )
        db.add(
            CapacityEvent(
                kind="capacity_assigned_for_settlement",
                resource_id=settlement_resource_id,
                dimensions=_serialize_dimensions(
                    {k: -v for k, v in reservation_dims.items()}
                ),
            )
        )
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
        return db.get(
            CapacityReservation, capacity_reservation_id, with_for_update=True
        )

    def backing_resource_id_in_session(
        self, db: Session, capacity_reservation_id: str
    ) -> str | None:
        """Public, session-scoped exposure of the private backing-resource lookup.

        Lets a caller already holding ``db`` open (for example, while
        evaluating scheduling eligibility inside one atomic transaction)
        read this without opening a second session.
        """
        return self._backing_resource_id(db, capacity_reservation_id)

    def backing_pool_id_in_session(
        self,
        db: Session,
        capacity_reservation_id: str,
    ) -> str | None:
        """Return the current reservation debit pool inside ``db``."""
        resource_id = self._backing_resource_id(db, capacity_reservation_id)
        if resource_id is None:
            return None
        resource = self._bucket_by_backing_resource(db, resource_id)
        if resource is None:
            return None
        return resource.pool_id or DEFAULT_POOL_ID

    def reservation_payload_in_session(
        self, reservation: CapacityReservation
    ) -> dict[str, Any]:
        """Public exposure of the private reservation-payload builder.

        Lets a caller holding a row obtained through ``lock_reservation``
        (for example, while validating a reservation inside an atomic
        scheduling transaction) build the same dict shape
        ``get_reservation``/``reserve`` already return, without needing to
        know the payload's internal field construction.
        """
        return self._reservation_payload(reservation)

    def iter_scheduling_candidates_in_session(
        self, db: Session, *, resource_kind: str, exclude_reservation_id: str
    ) -> list[ResourceFeasibilityView]:
        """Every enabled, ``resource_kind``-matching bucket as a canonical view.

        Session-scoped generalization of ``_find_candidate`` for scheduling:
        ``_find_candidate`` returns the first bucket that satisfies a claim,
        which is right for ``reserve()`` but not for round-robin selection,
        which must choose among every eligible candidate. Availability is
        computed the same way ``_resource_payload``/``_find_candidate``
        already do (instantaneous held-dimension snapshot, blocked by an
        exclusive physical-host conflict), so scheduling-time eligibility
        cannot silently diverge from admission-time or listing-time
        availability.

        ``exclude_reservation_id``'s own currently-debited dimensions are
        credited back into its backing resource's ``available`` map: that
        resource is still eligible for this reservation to be (re)assigned
        to, even though it is the reservation's own hold that would
        otherwise make it look full. Callers computing eligibility for a
        reservation that does not yet have a debit (there is always one by
        the time scheduling runs, since ``reserve()`` always creates it)
        would simply credit back nothing.
        """
        now = datetime.now(timezone.utc)
        instant_end = now + timedelta(microseconds=1)
        own_backing_resource_id = self._backing_resource_id(db, exclude_reservation_id)
        own_reservation = db.get(CapacityReservation, exclude_reservation_id)
        own_dimensions = (
            _reservation_dimensions(own_reservation, self._mirror_dimension)
            if own_reservation is not None
            else {}
        )
        rows = (
            db.query(CapacityBucket)
            .filter(
                CapacityBucket.enabled.is_(True),
                CapacityBucket.resource_type == resource_kind,
            )
            .order_by(CapacityBucket.backing_resource_id.asc())
            .all()
        )
        views: list[ResourceFeasibilityView] = []
        for resource in rows:
            if self._has_physical_host_conflict(
                db,
                resource,
                now,
                instant_end,
                exclude_reservation_id=exclude_reservation_id,
            ):
                continue
            capacity = _resource_capacity(resource, self._mirror_dimension)
            held = self._held_dimensions(
                db, resource.backing_resource_id, now, instant_end
            )
            available = {
                key: capacity.get(key, Decimal(0)) - held.get(key, Decimal(0))
                for key in capacity
            }
            if resource.backing_resource_id == own_backing_resource_id:
                for key, amount in own_dimensions.items():
                    available[key] = available.get(key, Decimal(0)) + amount
            views.append(_resource_feasibility_view(resource, available, self._mirror_dimension))
        return views

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

        ``resource_id`` is used only when ``capacity_reservation_id`` is
        omitted — it selects which currently-held reservation to commit by
        looking up the resource's backing bucket instead (see
        ``_find_reservation``). No current caller does this: every real
        caller already has and supplies ``capacity_reservation_id``, so
        ``resource_id`` is ignored. This is deliberate future-facing surface
        for a caller that knows a physical resource but not the reservation
        holding it (e.g. a direct-resource-reservation admin/recovery path),
        not dead code to remove — but it is not what backs ordinary
        pool-scoped or resource-pinned-claim reservations, both of which
        always carry ``capacity_reservation_id`` by the time they commit.
        """
        window_start, window_end = _lease_window(
            lease_start_utc=lease_start_utc,
            lease_end_utc=lease_end_utc,
        )
        with self.serialized(), self._session_factory() as db:
            reservation = self._find_reservation(
                db,
                capacity_reservation_id=capacity_reservation_id,
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
            db.add(
                CapacityEvent(
                    kind="committed",
                    resource_id=self._backing_resource_id(
                        db, reservation.capacity_reservation_id
                    ),
                )
            )
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
        with self.serialized(), self._session_factory() as db:
            reservation = self._find_reservation(
                db,
                capacity_reservation_id=capacity_reservation_id,
                escrow_uid=None if capacity_reservation_id else escrow_uid,
            )
            if reservation is None:
                return None
            # Capacity reclamation always offers fulfillment a chance to
            # reconcile an assigned settlement, including idempotent retries
            # after the reservation is already terminal. The hook owns the
            # fulfillment-state decision and never commits this session.
            if self._settlement_abandonment_hook is not None:
                self._settlement_abandonment_hook(
                    db, reservation.capacity_reservation_id
                )
            if reservation.state in {
                ReservationState.released.value,
                ReservationState.force_released.value,
            }:
                db.commit()
                return self._reservation_payload(reservation)
            if reservation.state not in HELD_RESERVATION_STATES:
                return None
            reservation.state = state
            reservation.released_at = datetime.now(timezone.utc).isoformat()
            reservation.failure_reason = failure_reason
            reservation.failure_message = failure_message
            db.add(
                CapacityEvent(
                    kind="released",
                    resource_id=self._backing_resource_id(
                        db, reservation.capacity_reservation_id
                    ),
                    dimensions=_serialize_dimensions(
                        _reservation_dimensions(reservation, self._mirror_dimension)
                    ),
                )
            )
            db.commit()
            return self._reservation_payload(reservation)

    def resize_reservation(
        self,
        *,
        old_capacity_reservation_id: str,
        new_claim: Mapping[str, Any] | None = None,
        deal_ref: Mapping[str, Any] | None = None,
        ttl_seconds: float | None = None,
        lease_start_utc: str | None = None,
        lease_duration_seconds: int | None = None,
    ) -> dict[str, Any] | None:
        """Atomically supersede a held reservation with a changed claim shape.

        A negotiated shape change never mutates
        ``old_capacity_reservation_id``'s reservation, or any settlement
        assignment already bound to it, in place: it always produces a new
        ``capacity_reservation_id``. This method releases the old
        reservation and reserves the new shape inside one transaction that
        commits or rolls back together, never as two independently
        committed ``release()``/``reserve()`` calls in either order.

        Releasing first, inside the same open transaction, before checking
        the new shape's candidacy is what makes the new shape's
        availability evaluated as if the old hold had already cleared --
        a resource the old hold was consuming becomes visible to
        ``_find_candidate`` immediately, without a separate, already
        -committed release step. If the new shape then has no eligible
        candidate, the whole transaction rolls back and
        ``old_capacity_reservation_id`` is left exactly as it was: still
        held, never actually released. This is a single-database-
        transaction guarantee, not two independently-reversible steps.

        Returns ``None`` without changing anything if
        ``old_capacity_reservation_id`` does not name a currently
        held/leased reservation, or if the new shape has no eligible
        candidate.

        No caller uses this method yet. When one is added: resize before
        ``schedule_resource()`` runs for the affected reservation, not
        after. VM fulfillment-request shape derivation
        (``AnsibleFulfillmentProvider.prepare_create``) trusts the
        reservation's committed ``dimensions`` as authoritative precisely
        because nothing currently changes them once a hold exists
        (``compute_capacity_claim_from_order`` computes the claim from the
        terminal, post-negotiation order at acceptance time, so the initial
        reservation and any later shape-derivation always agree by
        construction). A caller that resizes *after* scheduling would
        silently break that invariant: the already-scheduled
        ``SettlementResource.dimensions`` would keep reflecting the old
        shape.
        """
        requested = _requested_dimensions(
            new_claim,
            unit_claim_keys=self._unit_claim_keys,
            mirror_dimension=self._mirror_dimension,
        )
        requested_mode = _requested_offering_mode(new_claim, required=True)
        deal = dict(deal_ref or {})
        window_start, window_end = _lease_window(
            lease_start_utc=lease_start_utc,
            lease_duration_seconds=lease_duration_seconds,
        )
        with self.serialized(), self._session_factory() as db:
            self._expire_stale_holds(db)
            old_reservation = db.get(
                CapacityReservation, old_capacity_reservation_id, with_for_update=True
            )
            if (
                old_reservation is None
                or old_reservation.state not in HELD_RESERVATION_STATES
            ):
                return None
            old_backing_resource_id = self._backing_resource_id(
                db, old_capacity_reservation_id
            )
            old_dimensions = _reservation_dimensions(old_reservation, self._mirror_dimension)
            old_reservation.state = ReservationState.released.value
            old_reservation.released_at = datetime.now(timezone.utc).isoformat()
            old_reservation.failure_reason = "superseded"
            db.add(
                CapacityEvent(
                    kind="released",
                    resource_id=old_backing_resource_id,
                    dimensions=_serialize_dimensions(old_dimensions),
                )
            )
            db.flush()

            match = self._find_candidate(
                db, new_claim, requested, window_start, window_end
            )
            if match is None:
                db.rollback()
                return None
            resource, available = match

            hold_expires_at = None
            if ttl_seconds is not None:
                hold_expires_at = (
                    datetime.now(timezone.utc) + timedelta(seconds=float(ttl_seconds))
                ).isoformat()
            mirrored_units = int(requested.get(self._mirror_dimension, Decimal(0)))
            new_reservation = CapacityReservation(
                capacity_reservation_id=str(uuid.uuid4()),
                units=mirrored_units,
                dimensions=_serialize_dimensions(requested),
                # Carried from the reservation being superseded, not re-split
                # from this call's claim. A resize changes how much was
                # committed; what kind of resource was sold was settled at
                # admission, and a resize is not an occasion to renegotiate it.
                claim_attributes=(
                    dict(old_reservation.claim_attributes)
                    if old_reservation.claim_attributes is not None
                    else None
                ),
                state=ReservationState.reserved.value,
                deal_ref=deal,
                escrow_uid=deal.get("escrow_uid"),
                hold_expires_at=hold_expires_at,
                executor_ref=_executor_ref_for_resource(resource),
                offering_mode=requested_mode,
                lease_start_utc=window_start.isoformat() if window_start else None,
                lease_end_utc=window_end.isoformat() if window_end else None,
            )
            db.add(new_reservation)
            db.flush()
            db.add(
                CapacityReservationDebit(
                    capacity_reservation_id=new_reservation.capacity_reservation_id,
                    capacity_bucket_id=resource.capacity_bucket_id,
                    dimensions=_serialize_dimensions(requested),
                )
            )
            db.add(
                CapacityEvent(
                    kind="reserved",
                    resource_id=resource.backing_resource_id,
                    dimensions=_serialize_dimensions(
                        {k: -v for k, v in requested.items()}
                    ),
                )
            )
            if self._settlement_abandonment_hook is not None:
                # Same transaction as the release/reserve above: an old
                # settlement assignment is marked abandoned synchronously
                # here rather than waiting for the lease-lifecycle
                # watchdog's next sweep to notice the old reservation is
                # gone.
                self._settlement_abandonment_hook(db, old_capacity_reservation_id)
            db.commit()
            available_after = {
                key: available.get(key, Decimal(0)) - requested.get(key, Decimal(0))
                for key in set(available) | set(requested)
            }
            payload = self._match_payload(resource, available_after, requested)
            payload["capacity_reservation_id"] = new_reservation.capacity_reservation_id
            payload["settlement_resource_id"] = new_reservation.settlement_resource_id
            payload["hold_expires_at"] = hold_expires_at
            payload["superseded_capacity_reservation_id"] = old_capacity_reservation_id
            return payload

    def truncate_lease(
        self,
        *,
        capacity_reservation_id: str,
        lease_end_utc: str,
    ) -> dict[str, Any] | None:
        """End a lease early; injected compute lifecycle observes the new expiry."""
        with self.serialized(), self._session_factory() as db:
            reservation = self._find_reservation(
                db, capacity_reservation_id=capacity_reservation_id
            )
            if reservation is None or reservation.state not in HELD_RESERVATION_STATES:
                return None
            reservation.state = ReservationState.leased.value
            reservation.lease_end_utc = str(lease_end_utc)
            db.add(
                CapacityEvent(
                    kind="lease_truncated",
                    resource_id=self._backing_resource_id(
                        db, reservation.capacity_reservation_id
                    ),
                )
            )
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
        offering_mode: str | None = None,
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
        with self.serialized(), self._session_factory() as db:
            reservation = self._find_reservation(
                db,
                capacity_reservation_id=capacity_reservation_id,
                escrow_uid=None if capacity_reservation_id else escrow_uid,
            )
            if reservation is None or reservation.state not in HELD_RESERVATION_STATES:
                return None
            self._sync_executor_fields(
                reservation,
                offering_mode=offering_mode,
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
        with self.serialized(), self._session_factory() as db:
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
        with self.serialized(), self._session_factory() as db:
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
        offering_mode: str | None = None,
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

        Opens and commits its own transaction. A caller that must land this
        write inside a transaction it already holds open should use
        ``update_lease_fields_in_session`` against that session, not this
        method: on SQLite a second session cannot take the writer slot the
        caller itself is holding, so this form would wait out the busy
        timeout and then fail with ``database is locked``.
        """
        with self.serialized(), self._session_factory() as db:
            result = self.update_lease_fields_in_session(
                db,
                capacity_reservation_id,
                offering_mode=offering_mode,
                executor_target=executor_target,
                executor_ref=executor_ref,
                lease_start_utc=lease_start_utc,
                lease_end_utc=lease_end_utc,
                vm_remove_job_id=vm_remove_job_id,
                release_job_id=release_job_id,
                create_job_id=create_job_id,
            )
            db.commit()
            return result

    def update_lease_fields_in_session(
        self,
        db: Session,
        capacity_reservation_id: str,
        *,
        offering_mode: str | None = None,
        executor_target: str | None = None,
        executor_ref: Mapping[str, Any] | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        vm_remove_job_id: str | None = None,
        release_job_id: str | None = None,
        create_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Session-scoped core of ``update_lease_fields``.

        Does not commit and does not take the ledger lock: the caller owns the
        transaction boundary and decides when this write lands relative to its
        own. Exists so a caller that has already written on another
        repository's behalf -- and therefore holds SQLite's single writer slot
        -- can record lease-tail fields inside that same transaction instead of
        contending with itself from a second session.

        Validation precedes every mutation for all argument combinations:
        ``_sync_executor_fields`` performs both of its raising checks before
        either of its assignments, and nothing after it raises. A raise
        therefore leaves ``db`` exactly as it was found, so a best-effort
        caller may swallow the exception without rolling back its own writes
        and without wrapping this in a savepoint.
        """
        reservation = db.get(CapacityReservation, capacity_reservation_id)
        terminal = {
            ReservationState.released.value,
            ReservationState.force_released.value,
            ReservationState.provisioning_failed.value,
        }
        if reservation is None or reservation.state in terminal:
            return None
        self._sync_executor_fields(
            reservation,
            offering_mode=offering_mode,
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
        return self._reservation_payload(reservation)

    def find_active_lease_by_vm_target(
        self, host_id: str, vm_target: str
    ) -> dict[str, Any] | None:
        """Return the first active (held) lease reservation for a VM, or None.

        Used by the ``POST /vms/{vm_name}/remove`` endpoint to cancel any
        watchdog-managed lease before submitting the explicit removal job,
        avoiding a double-fire when the lease would otherwise expire later.

        ``host_id`` is matched via ``executor_ref``'s JSON payload and
        ``vm_target`` via ``executor_target`` — neither
        ``CapacityReservation`` column exists anymore (see
        ``docs/development/ARCHITECTURE.md``, "Shared vocabulary and
        identities"); the `executor_ref` lookup is the first ORM-level
        use of SQLite's JSON1 extension in this module, though the
        extension itself is already relied on at the migration layer
        (``compute_provisioning_service/db/migrations.py``'s ``pool_id``
        backfill).
        """
        with self.serialized(), self._session_factory() as db:
            reservation = (
                db.query(CapacityReservation)
                .filter(
                    func.json_extract(CapacityReservation.executor_ref, "$.host_id")
                    == host_id,
                    CapacityReservation.executor_target == vm_target,
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
        with self.serialized(), self._session_factory() as db:
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
        with self.serialized(), self._session_factory() as db:
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
        with self.serialized(), self._session_factory() as db:
            reservation = db.get(CapacityReservation, capacity_reservation_id)
            return self._reservation_payload(reservation) if reservation else None

    def get_reservation_by_escrow(self, escrow_uid: str) -> dict[str, Any] | None:
        with self.serialized(), self._session_factory() as db:
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
        with self.serialized(), self._session_factory() as db:
            return self._backing_resource_id(db, capacity_reservation_id)

    def list_reservations(self, *, state: str | None = None) -> list[dict[str, Any]]:
        with self.serialized(), self._session_factory() as db:
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
        return (
            db.get(CapacityBucket, debit.capacity_bucket_id)
            if debit is not None
            else None
        )

    def _backing_resource_id(
        self, db: Session, capacity_reservation_id: str
    ) -> str | None:
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
        with self.serialized(), self._session_factory() as db:
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
            db.add(
                CapacityEvent(
                    kind="released",
                    resource_id=self._backing_resource_id(
                        db, reservation.capacity_reservation_id
                    ),
                )
            )
            if self._settlement_abandonment_hook is not None:
                self._settlement_abandonment_hook(
                    db, reservation.capacity_reservation_id
                )
            lapsed = True
            logger.info(
                "[CAPACITY] TTL hold expired for reservation %s (resource=%s)",
                reservation.capacity_reservation_id,
                self._backing_resource_id(db, reservation.capacity_reservation_id),
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
                CapacityReservationDebit.capacity_bucket_id
                == bucket.capacity_bucket_id,
                CapacityReservation.state.in_(HELD_RESERVATION_STATES),
            )
            .all()
        )
        totals: dict[str, Decimal] = {}

        def _accumulate(row: CapacityReservation) -> None:
            for key, amount in _reservation_dimensions(row, self._mirror_dimension).items():
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
        return int(held.get(self._mirror_dimension, Decimal(0)))
    @staticmethod
    def _pool_declares_mode(
        db: Session,
        resource: CapacityBucket,
        requested_mode: str,
    ) -> bool:
        pool = db.get(ResourcePool, resource.pool_id or DEFAULT_POOL_ID)
        return (
            pool is not None
            and pool.enabled
            and pool_delivers_offering_mode(
                pool.policy_tags or {},
                requested_mode,
            )
        )


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
        requested_mode = _requested_offering_mode(claim, required=False)
        undeclared_pools: set[str] = set()
        pool_mode_decisions: dict[str, bool] = {}
        for resource in rows:
            attrs = resource.attributes or {}
            if any(
                not isinstance(attrs.get(key), str) or not attrs[key].strip()
                for key in self._required_attributes
            ):
                continue
            capacity = _resource_capacity(resource, self._mirror_dimension)
            if not resource_satisfies_requirement(
                resource=_resource_feasibility_view(
                    resource, capacity, self._mirror_dimension
                ),
                required_resource_kind=required_resource_kind,
                required_dimensions=requested,
                required_attributes=required_attributes,
            ):
                continue
            pool_id = resource.pool_id or DEFAULT_POOL_ID
            if requested_mode is not None:
                if pool_id not in pool_mode_decisions:
                    pool_mode_decisions[pool_id] = self._pool_declares_mode(
                        db,
                        resource,
                        requested_mode,
                    )
                if not pool_mode_decisions[pool_id]:
                    undeclared_pools.add(pool_id)
                    continue
            held = self._held_dimensions(
                db, resource.backing_resource_id, lease_start, lease_end
            )
            available = {
                key: capacity.get(key, Decimal(0)) - held.get(key, Decimal(0))
                for key in capacity
            }
            if not resource_satisfies_requirement(
                resource=_resource_feasibility_view(
                    resource, available, self._mirror_dimension
                ),
                required_resource_kind=required_resource_kind,
                required_dimensions=requested,
                required_attributes=required_attributes,
            ):
                continue
            if self._has_physical_host_conflict(
                db,
                resource,
                lease_start,
                lease_end,
            ):
                continue
            return resource, available
        if requested_mode is not None and undeclared_pools:
            pools = ", ".join(sorted(undeclared_pools))
            raise UndeclaredOfferingModeError(
                f"offering mode {requested_mode!r} is not declared by matching pool(s): {pools}"
            )
        return None

    def _find_reservation(
        self,
        db: Session,
        *,
        capacity_reservation_id: str | None = None,
        escrow_uid: str | None = None,
        resource_id: str | None = None,
    ) -> CapacityReservation | None:
        """Look up a held/leased reservation.

        ``resource_id`` (used only when both ``capacity_reservation_id`` and
        ``escrow_uid`` are absent) finds the most recently created held
        reservation currently debited against the named resource's bucket —
        "which reservation currently holds this physical resource" rather
        than "the reservation with this ID". No current caller reaches this
        branch: it exists for a future caller that has a resource identity
        but not a reservation identity (e.g. admin/recovery tooling, or a
        not-yet-built direct-resource-reservation path). Ordinary
        reservations, pool-scoped or resource-pinned, always carry their
        own ``capacity_reservation_id`` by commit time and use that branch
        instead.
        """
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
            ).filter(
                CapacityReservationDebit.capacity_bucket_id == bucket.capacity_bucket_id
            )
        else:
            return None
        return q.order_by(CapacityReservation.created_at.desc()).first()

    def _resource_payload(self, db: Session, row: CapacityBucket) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        capacity = _resource_capacity(row, self._mirror_dimension)
        held = self._held_dimensions(
            db,
            row.backing_resource_id,
            now,
            now + timedelta(microseconds=1),
        )
        mirror = self._mirror_dimension
        # The scalar fields report the mirror dimension only when the
        # declaration names it; a declaration without it has no scalar total,
        # and reporting zero would read as a declared empty resource.
        mirrored = mirror in capacity
        blocked = self._has_physical_host_conflict(
            db,
            row,
            now,
            now + timedelta(microseconds=1),
        )
        if blocked:
            available_map = {key: Decimal(0) for key in capacity}
        else:
            available_map = {
                key: max(
                    capacity.get(key, Decimal(0)) - held.get(key, Decimal(0)),
                    Decimal(0),
                )
                for key in capacity
            }
        nothing_held = not any(amount > 0 for amount in held.values())
        if blocked:
            state = "leased"
        elif mirrored:
            state = (
                "available"
                if available_map[mirror] > 0 or nothing_held
                else "leased"
            )
        else:
            state = (
                "available"
                if nothing_held or any(amount > 0 for amount in available_map.values())
                else "leased"
            )
        return {
            "resource_id": row.backing_resource_id,
            "pool_id": row.pool_id,
            "resource_type": row.resource_type,
            "resource_subtype": row.resource_subtype,
            "host_id": row.host_id,
            "unit": "count",
            "value": int(capacity[mirror]) if mirrored else None,
            "state": state,
            "available_units": int(available_map[mirror]) if mirrored else None,
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
        *,
        exclude_reservation_id: str | None = None,
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
            if reservation.capacity_reservation_id == exclude_reservation_id:
                continue
            held_resource = self._bucket_for_reservation(
                db, reservation.capacity_reservation_id
            )
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

    def _match_payload(
        self,
        resource: CapacityBucket,
        available: Mapping[str, Decimal],
        requested: Mapping[str, Decimal],
    ) -> dict[str, Any]:
        """Shape a probe/reserve result like the embedded adapter's.

        pool/member are storefront (aggregator) concepts the site does not
        know; they are present-and-None for payload compatibility.
        ``requested``/``available`` are full per-dimension maps;
        ``allocated_units``/``available_units`` and the
        ``allocated_<mirror>``/``available_<mirror>`` aliases carry the mirror
        dimension, so a composition whose mirror is ``gpu_count`` keeps the
        ``allocated_gpu_count``/``available_gpu_count`` fields its callers read.
        """
        attrs = dict(resource.attributes or {})
        mirror = self._mirror_dimension
        allocated_primary = int(requested.get(mirror, Decimal(0)))
        available_primary = int(available.get(mirror, Decimal(0)))
        return {
            "resource_id": resource.backing_resource_id,
            "pool_id": None,
            "member_id": None,
            "host_id": resource.host_id,
            "resource_subtype": resource.resource_subtype,
            "unit": "count",
            "state": "available",
            "value": resource.total_units,
            "allocated_units": allocated_primary,
            "available_units": available_primary,
            f"allocated_{mirror}": allocated_primary,
            f"available_{mirror}": available_primary,
            "dimensions": _serialize_dimensions(requested),
            "available": _serialize_dimensions(available),
            "capacity": _serialize_dimensions(_resource_capacity(resource, self._mirror_dimension)),
            "attributes": attrs,
        }

    def _reservation_payload(self, reservation: CapacityReservation) -> dict[str, Any]:
        return {
            "capacity_reservation_id": reservation.capacity_reservation_id,
            "settlement_resource_id": reservation.settlement_resource_id,
            "pool_id": None,
            "units": int(reservation.units or 0),
            f"allocated_{self._mirror_dimension}": int(reservation.units or 0),
            "dimensions": _serialize_dimensions(_reservation_dimensions(reservation, self._mirror_dimension)),
            "state": reservation.state,
            "deal_ref": dict(reservation.deal_ref or {}),
            "escrow_uid": reservation.escrow_uid,
            "hold_expires_at": reservation.hold_expires_at,
            "offering_mode": reservation.offering_mode,
            "executor_target": reservation.executor_target,
            "release_job_id": reservation.release_job_id,
            "executor_ref": dict(reservation.executor_ref or {}),
            "host_id": (reservation.executor_ref or {}).get("host_id"),
            "vm_target": (
                reservation.executor_target
                if reservation.offering_mode == VM_OFFERING_MODE
                else None
            ),
            "lease_start_utc": reservation.lease_start_utc,
            "lease_end_utc": reservation.lease_end_utc,
            "create_job_id": reservation.create_job_id,
            "vm_remove_job_id": reservation.vm_remove_job_id,
            "claim_attributes": (
                dict(reservation.claim_attributes)
                if reservation.claim_attributes is not None
                else None
            ),
            "failure_reason": reservation.failure_reason,
            "failure_message": reservation.failure_message,
            "released_at": reservation.released_at,
        }

    def _reservation_payload_for_reserve(
        self,
        db: Session,
        reservation: CapacityReservation,
    ) -> dict[str, Any]:
        """``_reservation_payload`` plus ``resource_id``, matching the shape
        ``reserve()``'s fresh-reservation path returns (via
        ``_match_payload``), so an idempotent-hit return is byte-compatible
        with a fresh one for callers that read ``resource_id`` (for
        example ``vm_fulfillment_service.py``'s
        ``reserved.get("resource_id")``). ``resource_id`` is resolved via
        the same backing-resource lookup ``get_reservation_backing_resource_id``
        already exposes, not duplicated here.
        """
        payload = self._reservation_payload(reservation)
        payload["resource_id"] = self._backing_resource_id(
            db,
            reservation.capacity_reservation_id,
        )
        payload.setdefault("member_id", None)
        return payload

    @staticmethod
    def _sync_executor_fields(
        reservation: CapacityReservation,
        *,
        offering_mode: str | None = None,
        executor_target: str | None = None,
        executor_ref: Mapping[str, Any] | None = None,
    ) -> None:
        if reservation.offering_mode is None:
            raise CapacityConflictError(
                "reservation has no explicit requested executor identity"
            )
        if (
            offering_mode is not None
            and reservation.offering_mode != offering_mode
        ):
            raise CapacityConflictError(
                f"reservation offering_mode is {reservation.offering_mode!r}, "
                f"not {offering_mode!r}"
            )
        if executor_target is not None:
            reservation.executor_target = executor_target
        if executor_ref is not None:
            reservation.executor_ref = dict(executor_ref)

    @staticmethod
    def _sync_release_job_fields(
        reservation: CapacityReservation,
        *,
        release_job_id: str | None,
    ) -> None:
        if release_job_id is None:
            return
        reservation.release_job_id = release_job_id
        if reservation.offering_mode == VM_OFFERING_MODE:
            reservation.vm_remove_job_id = release_job_id
