"""Release by what a reservation's fulfillment proves, for every offering mode.

A lease delivers nothing; fulfillment does. So whether a lease's capacity can
return, and how, follows the state of the reservation's fulfillment aggregate,
whatever the offering mode, and the aggregate already knows its provider:

- ``active``, or a teardown already begun (``teardown_dispatch_pending``,
  ``tearing_down``, ``teardown_failed``): begin or adopt the aggregate's
  teardown; capacity returns once it reaches ``torn_down``.
- ``torn_down``: teardown is proven, and the capacity is freed directly.
- absent, ``assigned``, or ``abandoned``, with nothing dispatched for the
  reservation: there is nothing to tear down, and the capacity is freed
  directly, abandoning an ``assigned`` aggregate on the way.
- ``dispatch_pending`` or ``dispatching``: a create is in flight; the release
  waits for it to settle, then tears down what it made.
- ``failed``: a create may have left a workload, and ``failed`` has no teardown,
  so the lease is left for an operator to verify and force-release.

"Nothing dispatched" is proven by provenance: no create handle on the
reservation and no job bound to it. The proof is checked by
``FulfillmentReleaseGuard`` inside the transaction that frees the capacity, so
every caller of the site's release is held to it, not only the lease lifecycle.

Submission and completion are separate: ``FulfillmentReleaseExecutor`` decides
what to do and begins or adopts teardown, but never frees capacity itself; the
lease lifecycle does that through the guarded site release, and reads progress
through ``FulfillmentReleaseStatusPort``. Fulfillment convergence owns teardown
dispatch, retry, and recovery.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from market_fulfillment import SettlementEntityNotFoundError, SettlementRecordState
from market_site.db import CapacityReservation
from sqlalchemy.orm import Session

from compute_provisioning.jobs.db import job_bound_to_reservation

logger = logging.getLogger(__name__)

_State = SettlementRecordState

# Aggregates with nothing delivered against them, when provenance agrees.
_UNDELIVERED_STATES = frozenset(
    {_State.assigned.value, _State.abandoned.value}
)
# Aggregates whose teardown can begin, or has begun and is adopted.
_TEARDOWN_STATES = frozenset(
    {
        _State.active.value,
        _State.teardown_dispatch_pending.value,
        _State.tearing_down.value,
        _State.teardown_failed.value,
    }
)
_CREATE_IN_FLIGHT_STATES = frozenset(
    {_State.dispatch_pending.value, _State.dispatching.value}
)


class FulfillmentTeardownPort(Protocol):
    async def begin_teardown(self, fulfillment_id: str) -> str: ...

    def get_status(self, fulfillment_id: str) -> Any: ...


class FulfillmentServiceTeardownPort:
    """Adapt a fulfillment-service provider to the narrow teardown port."""

    def __init__(self, service_provider: Callable[[], Any]) -> None:
        self._service_provider = service_provider

    async def begin_teardown(self, fulfillment_id: str) -> str:
        accepted = await self._service_provider().begin_fulfillment_teardown(fulfillment_id)
        return accepted.fulfillment_id

    def get_status(self, fulfillment_id: str) -> Any:
        return self._service_provider().get_fulfillment_status(fulfillment_id)


class FulfillmentReleaseGuard:
    """The site's release guard: free capacity only on fulfillment's proof.

    Called with the site ledger's session inside the transaction that frees the
    capacity, so the proof and the release cannot be separated by a concurrent
    dispatch. It permits a ``torn_down`` aggregate, and an absent, ``assigned``,
    or ``abandoned`` one when no create handle is recorded on the reservation and
    no job is bound to it. An ``assigned`` aggregate is abandoned by a
    compare-and-set after that check; if a concurrent ``begin`` moved it on, the
    guard refuses. A job or a create handle exists only after an aggregate has
    left ``assigned``, so checking before the compare-and-set loses nothing, and
    a refusal writes nothing.
    """

    def __init__(self, settlement_repository: Any) -> None:
        self._settlement_repository = settlement_repository

    def __call__(self, db: Session, capacity_reservation_id: str) -> bool:
        record = self._settlement_repository.get(db, capacity_reservation_id)
        state = None if record is None else record.state
        if state == _State.torn_down.value:
            return True
        if state is not None and state not in _UNDELIVERED_STATES:
            return False
        if _dispatched(db, capacity_reservation_id):
            return False
        if state == _State.assigned.value:
            return self._settlement_repository.abandon_if_assigned(
                db, capacity_reservation_id
            )
        return True


def _dispatched(db: Session, capacity_reservation_id: str) -> bool:
    reservation = db.get(CapacityReservation, capacity_reservation_id)
    if reservation is not None and reservation.create_job_id:
        return True
    return job_bound_to_reservation(db, capacity_reservation_id)


class ReleaseAction(str, enum.Enum):
    """What the lease lifecycle does with a release request."""

    #: Teardown has begun or was adopted; the lease is releasing under it.
    TEARDOWN = "teardown"
    #: Nothing remains delivered by the aggregate's own account; free the
    #: capacity through the guarded release, which checks provenance.
    FREE = "free"
    #: A create is in flight; the lease is releasing and waits for it.
    CREATE_IN_FLIGHT = "create_in_flight"
    #: Nothing can prove the capacity free; an operator must verify.
    UNRELEASABLE = "unreleasable"


@dataclass(frozen=True)
class ReleaseDecision:
    action: ReleaseAction
    fulfillment_id: str | None = None
    reason: str | None = None
    message: str | None = None


class FulfillmentReleaseExecutor:
    """Decide a reservation's release from its fulfillment aggregate's state.

    Begins or adopts teardown where there is something to tear down, and
    otherwise reports what the lease lifecycle should do. Never frees capacity
    and never submits provider work: the lifecycle frees capacity through the
    guarded site release, and fulfillment convergence dispatches teardown.
    """

    def __init__(
        self,
        *,
        settlement_repository: Any,
        session_factory: Callable[[], Any],
        teardown_port: FulfillmentTeardownPort,
    ) -> None:
        self._settlement_repository = settlement_repository
        self._session_factory = session_factory
        self._teardown_port = teardown_port

    async def submit_release(self, reservation: dict[str, Any]) -> ReleaseDecision:
        capacity_reservation_id = str(reservation["capacity_reservation_id"])
        with self._session_factory() as db:
            record = self._settlement_repository.get(db, capacity_reservation_id)
            state = None if record is None else str(record.state)
            # Assigned before ``begin`` gives it one, so it may be absent.
            fulfillment_id = (
                str(record.fulfillment_id)
                if record is not None and record.fulfillment_id
                else None
            )
            failure = None if record is None else (
                record.failure_message or record.failure_reason
            )

        if state is None or state in _UNDELIVERED_STATES or state == _State.torn_down.value:
            return ReleaseDecision(ReleaseAction.FREE, fulfillment_id=fulfillment_id)
        if state in _TEARDOWN_STATES:
            begun = await self._teardown_port.begin_teardown(fulfillment_id)
            return ReleaseDecision(ReleaseAction.TEARDOWN, fulfillment_id=begun)
        if state in _CREATE_IN_FLIGHT_STATES:
            return ReleaseDecision(
                ReleaseAction.CREATE_IN_FLIGHT, fulfillment_id=fulfillment_id
            )
        return ReleaseDecision(
            ReleaseAction.UNRELEASABLE,
            fulfillment_id=fulfillment_id,
            reason="fulfillment_failed",
            message=failure or f"fulfillment {fulfillment_id} is {state}",
        )

    async def begin_teardown(self, fulfillment_id: str) -> str:
        """Begin teardown once a create in flight has settled as ``active``."""
        return await self._teardown_port.begin_teardown(fulfillment_id)


class ReleaseProgress(str, enum.Enum):
    """How far a releasing lease's fulfillment has come."""

    TORN_DOWN = "torn_down"
    FAILED = "failed"
    #: The create settled; teardown can begin now.
    READY_FOR_TEARDOWN = "ready_for_teardown"
    CREATE_IN_FLIGHT = "create_in_flight"
    TEARING_DOWN = "tearing_down"


@dataclass(frozen=True)
class ReleaseStatus:
    progress: ReleaseProgress
    reason: str | None = None
    error: str | None = None


class FulfillmentReleaseStatusPort:
    """Read a releasing lease's progress from its fulfillment aggregate.

    The release handle is the durable ``fulfillment_id``. ``torn_down`` is
    success. ``teardown_failed`` is reported as failed even though convergence
    keeps retrying it: the lease then waits in ``release_failed``, and an
    operator's retry-release adopts the aggregate's teardown again. ``failed``
    has no teardown at all.
    """

    def __init__(self, teardown_port: FulfillmentTeardownPort) -> None:
        self._teardown_port = teardown_port

    def get_status(self, fulfillment_id: str) -> ReleaseStatus:
        try:
            status = self._teardown_port.get_status(fulfillment_id)
        except SettlementEntityNotFoundError:
            return ReleaseStatus(
                ReleaseProgress.FAILED,
                reason="teardown_failed",
                error=f"no fulfillment {fulfillment_id!r}",
            )
        state = str(status.state)
        detail = status.failure_message or status.failure_reason
        if state == _State.torn_down.value:
            return ReleaseStatus(ReleaseProgress.TORN_DOWN)
        if state == _State.teardown_failed.value:
            return ReleaseStatus(
                ReleaseProgress.FAILED,
                reason="teardown_failed",
                error=detail or "teardown failed",
            )
        if state == _State.failed.value:
            return ReleaseStatus(
                ReleaseProgress.FAILED,
                reason="fulfillment_failed",
                error=detail or "fulfillment failed",
            )
        if state == _State.active.value:
            return ReleaseStatus(ReleaseProgress.READY_FOR_TEARDOWN)
        if state in _CREATE_IN_FLIGHT_STATES:
            return ReleaseStatus(ReleaseProgress.CREATE_IN_FLIGHT)
        return ReleaseStatus(ReleaseProgress.TEARING_DOWN)


__all__ = [
    "FulfillmentReleaseExecutor",
    "FulfillmentReleaseGuard",
    "FulfillmentReleaseStatusPort",
    "FulfillmentServiceTeardownPort",
    "FulfillmentTeardownPort",
    "ReleaseAction",
    "ReleaseDecision",
    "ReleaseProgress",
    "ReleaseStatus",
]
