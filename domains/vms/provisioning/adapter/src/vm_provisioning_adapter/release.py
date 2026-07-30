"""VM release adapter for leased site reservations.

Submission and completion polling are split across two different owners.
This module only submits: it resolves the durable fulfillment aggregate for
a reservation and asks it to begin teardown. `FulfillmentConvergenceWatchdog`
(``compute_provisioning_service.services.fulfillment_convergence``) owns
everything from there -- dispatch, retry, and status convergence through to
``torn_down``/``teardown_failed``. Completion is read back through
``VmFulfillmentReleaseJobPort`` (``release_job_port.py``), not by polling a provider job directly.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from market_fulfillment import SettlementEntityNotFoundError, SettlementRecordState

logger = logging.getLogger(__name__)


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


VM_EXECUTOR_KIND = "vm"


class VmReleaseExecutor:
    """Initiates durable fulfillment teardown for a leased VM reservation.

    Resolution only: this class does not perform provider I/O itself and
    does not wait for teardown to finish. ``LeaseLifecycleService`` treats
    its return value as a job id to poll later through a
    ``ReleaseJobPort`` -- here, that id is the durable ``fulfillment_id``,
    resolved by ``VmFulfillmentReleaseJobPort.get_job`` against the
    fulfillment aggregate's own teardown state, not against a job queue.
    """

    def __init__(
        self,
        *,
        settlement_repository,
        session_factory: Callable[[], Any],
        teardown_port: FulfillmentTeardownPort,
    ) -> None:
        self._settlement_repository = settlement_repository
        self._session_factory = session_factory
        self._teardown_port = teardown_port

    async def submit_release(self, reservation: dict[str, Any]) -> str | None:
        capacity_reservation_id = reservation.get("capacity_reservation_id")
        if not capacity_reservation_id:
            logger.warning(
                "[LEASE_LIFECYCLE] Reservation has no capacity_reservation_id; "
                "cannot resolve a fulfillment to tear down"
            )
            return None

        fulfillment_id = self._resolve_fulfillment_id(capacity_reservation_id)
        if fulfillment_id is None:
            logger.warning(
                "[LEASE_LIFECYCLE] No fulfillment aggregate found for reservation "
                "%s; cannot begin teardown",
                capacity_reservation_id,
            )
            return None

        return await self._teardown_port.begin_teardown(fulfillment_id)

    def _resolve_fulfillment_id(self, capacity_reservation_id: str) -> str | None:
        with self._session_factory() as db:
            record = self._settlement_repository.get(db, capacity_reservation_id)
            return record.fulfillment_id if record is not None else None


@dataclass(frozen=True)
class _FulfillmentReleaseJob:
    """The subset of job-status shape ``LeaseLifecycleService`` reads.

    Matches the informal ``status``/``error`` interface the shared job
    queue's own job objects already expose (``ReleaseJobPort``), so
    ``LeaseLifecycleService``'s polling loop needs no VM-specific branch.
    """

    status: str
    error: str | None = None


class VmFulfillmentReleaseJobPort:
    """Answers release-job status reads from the fulfillment aggregate's
    own teardown state, not a polled Ansible job.

    ``job_id`` here is a durable ``fulfillment_id``, the value
    ``VmReleaseExecutor.submit_release`` returns. Terminal
    ``torn_down``/``teardown_failed`` map to ``succeeded``/``failed``;
    every other state (including the aggregate not existing yet, which
    cannot happen for a job id this port itself produced, but is handled
    rather than assumed impossible) is reported as still running so the
    caller keeps polling.
    """

    def __init__(self, teardown_port: FulfillmentTeardownPort) -> None:
        self._teardown_port = teardown_port

    def get_job(self, job_id: str) -> Any:
        try:
            status = self._teardown_port.get_status(job_id)
        except SettlementEntityNotFoundError:
            return _FulfillmentReleaseJob(
                status="failed", error=f"no fulfillment {job_id!r}"
            )

        if status.state == SettlementRecordState.torn_down.value:
            return _FulfillmentReleaseJob(status="succeeded")
        if status.state == SettlementRecordState.teardown_failed.value:
            return _FulfillmentReleaseJob(
                status="failed",
                error=status.failure_message or status.failure_reason or "teardown failed",
            )
        return _FulfillmentReleaseJob(status="running")
