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
- ``failed``, when ``compensable``: the provider reported a dispatched create
  failed, and the job-backed metadata names the create to undo, so the domain's
  ordinary teardown is begun as a compensating teardown; capacity returns once
  it reaches ``torn_down``.
- any other ``failed``: nothing durable says what the create left behind, so
  the lease is left for an operator to verify and force-release.

"Nothing dispatched" is proven by provenance: no create handle on the
reservation and no job bound to it. The proof is checked by
``FulfillmentReleaseGuard`` inside the transaction that frees the capacity, so
every caller of the site's release is held to it, not only the lease lifecycle.

Deciding and acting are separate: ``FulfillmentReleaseExecutor`` decides what a
release does and writes nothing. The lease lifecycle records the release
durably (``releasing``, with the fulfillment as its handle) before it begins
teardown, so a crash between the two leaves a release the next cycle resumes
rather than a teardown the lease does not know about. The lifecycle frees
capacity through the guarded site release and reads progress through
``FulfillmentReleaseStatusPort``. Fulfillment convergence owns teardown
dispatch, retry, and recovery.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from market_fulfillment import (
    CompensationCandidate,
    CompensationRefusedError,
    SettlementRecordState,
)
from market_site.db import CapacityReservation
from pydantic import ValidationError
from sqlalchemy.orm import Session

from compute_provisioning.job_fulfillment import JobFulfillmentMetadata
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


#: The reason convergence records when a provider reports a dispatched
#: operation failed. Only a create that reached the provider can carry it into
#: ``failed``, which is what makes such a create worth compensating.
PROVIDER_REPORTED_FAILURE = "provider_reported_failure"


def compensable(
    state: str | None, failure_reason: str | None, provider_metadata: Any
) -> bool:
    """Whether a fulfillment's failed create is undone by its domain's teardown.

    True only for a ``failed`` aggregate whose provider reported its dispatched
    create failed and whose durable metadata is the job-backed provider's for
    that create, naming its job, host, and target: the teardown is prepared
    from exactly those. A quarantined row, a row failed for metadata that
    cannot name its output, a create never acknowledged, and another provider's
    metadata are not, and are left for an operator. Pure, so the release
    decision, the release status, and the teardown's begin judge alike.
    """
    if state != _State.failed.value or failure_reason != PROVIDER_REPORTED_FAILURE:
        return False
    if not isinstance(provider_metadata, Mapping):
        return False
    try:
        metadata = JobFulfillmentMetadata.model_validate(dict(provider_metadata))
    except ValidationError:
        return False
    return metadata.operation == "create"


def _authorize_compensation(candidate: CompensationCandidate) -> bool:
    return compensable(
        candidate.state, candidate.failure_reason, candidate.provider_metadata
    )


class TeardownRefused(Exception):
    """A teardown that cannot begin for the aggregate as it stands.

    Permanent until something changes the aggregate, unlike a failure to reach
    the fulfillment service: the lease is recorded ``release_failed`` with
    ``reason``, its capacity held, for an operator.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


class FulfillmentTeardownPort(Protocol):
    async def begin_teardown(self, fulfillment_id: str) -> str: ...

    def get_status(self, fulfillment_id: str) -> Any: ...


class FulfillmentServiceTeardownPort:
    """Adapt a fulfillment-service provider to the narrow teardown port.

    ``begin_teardown`` decides from the aggregate's state when it is called,
    never from a decision taken earlier. A ``failed`` aggregate is compensated,
    its eligibility judged again inside the kit's write transaction; any other
    begins, or adopts, its ordinary teardown. A state that changes between this
    read and the kit's transaction is caught there: the compensating operation
    answers only from ``failed`` or a begun teardown, and the ordinary one
    refuses ``failed``.
    """

    def __init__(self, service_provider: Callable[[], Any]) -> None:
        self._service_provider = service_provider

    async def begin_teardown(self, fulfillment_id: str) -> str:
        service = self._service_provider()
        status = service.get_fulfillment_status(fulfillment_id)
        if str(status.state) != _State.failed.value:
            accepted = await service.begin_fulfillment_teardown(fulfillment_id)
            return accepted.fulfillment_id
        try:
            accepted = await service.begin_compensating_teardown(
                fulfillment_id, authorize=_authorize_compensation
            )
        except CompensationRefusedError as exc:
            raise TeardownRefused("compensation_refused", str(exc)) from exc
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

    #: There is something to tear down, or a teardown to adopt; the lease
    #: releases under the fulfillment, and teardown begins once that is recorded.
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

    ``submit_release`` only reads: it reports what the lease lifecycle should
    do, and the lifecycle acts once the release is durably recorded.
    ``begin_teardown`` begins, or adopts, the aggregate's teardown and is
    idempotent. Neither frees capacity or submits provider work: the lifecycle
    frees capacity through the guarded site release, and fulfillment
    convergence dispatches teardown.
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
            compensate = record is not None and compensable(
                state, record.failure_reason, record.provider_metadata
            )

        if state is None or state in _UNDELIVERED_STATES or state == _State.torn_down.value:
            return ReleaseDecision(ReleaseAction.FREE, fulfillment_id=fulfillment_id)
        if state in _TEARDOWN_STATES or compensate:
            return ReleaseDecision(ReleaseAction.TEARDOWN, fulfillment_id=fulfillment_id)
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
        """Begin the aggregate's teardown, or adopt one already begun.

        Raises ``TeardownRefused`` when a failed create's compensation cannot
        begin; any other error is transient.
        """
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

    The release handle is the durable ``fulfillment_id``, and the record is read
    directly, so the provider metadata ``compensable`` judges never leaves this
    package. ``torn_down`` is success. ``teardown_failed`` is reported as failed
    even though convergence requeues it: the lease then waits in
    ``release_failed``, and an operator's retry-release adopts the aggregate's
    teardown again. A compensable ``failed`` aggregate is ready for its
    compensating teardown; any other ``failed`` one has no teardown.
    """

    def __init__(
        self,
        *,
        settlement_repository: Any,
        session_factory: Callable[[], Any],
    ) -> None:
        self._settlement_repository = settlement_repository
        self._session_factory = session_factory

    def get_status(self, fulfillment_id: str) -> ReleaseStatus:
        with self._session_factory() as db:
            record = self._settlement_repository.get_by_fulfillment_id(
                db, fulfillment_id
            )
            if record is None:
                return ReleaseStatus(
                    ReleaseProgress.FAILED,
                    reason="teardown_failed",
                    error=f"no fulfillment {fulfillment_id!r}",
                )
            state = str(record.state)
            detail = record.failure_message or record.failure_reason
            compensate = compensable(
                state, record.failure_reason, record.provider_metadata
            )
        if state == _State.torn_down.value:
            return ReleaseStatus(ReleaseProgress.TORN_DOWN)
        if state == _State.teardown_failed.value:
            return ReleaseStatus(
                ReleaseProgress.FAILED,
                reason="teardown_failed",
                error=detail or "teardown failed",
            )
        if state == _State.failed.value:
            if compensate:
                return ReleaseStatus(ReleaseProgress.READY_FOR_TEARDOWN)
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
    "PROVIDER_REPORTED_FAILURE",
    "FulfillmentReleaseExecutor",
    "FulfillmentReleaseGuard",
    "FulfillmentReleaseStatusPort",
    "FulfillmentServiceTeardownPort",
    "FulfillmentTeardownPort",
    "ReleaseAction",
    "ReleaseDecision",
    "ReleaseProgress",
    "ReleaseStatus",
    "TeardownRefused",
    "compensable",
]
